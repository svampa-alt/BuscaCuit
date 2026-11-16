"""Catálogo de fuentes públicas y descarga a data/raw/<fuente>/.

Las URL se resuelven contra la API CKAN de cada portal en el momento de la
descarga (así se toma el recurso vigente); si la API no responde se usa la
URL fija verificada el 13/11/2026.
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .db import DIR_CRUDOS

AGENTE = "Mozilla/5.0 (cuit-finder; datos abiertos)"
_GCBA_BASE = (
    "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/"
    "agencia-gubernamental-de-control/habilitaciones-aprobadas/"
)


@dataclass(frozen=True)
class Fuente:
    id: str
    descripcion: str
    pagina: str
    licencia: str
    ckan: str | None            # URL de package_show, si el portal tiene API
    fijas: tuple[str, ...]      # URLs de respaldo


FUENTES = {
    "arca": Fuente(
        "arca",
        "ARCA (ex AFIP) - padrón de condición tributaria con denominación",
        "https://www.afip.gob.ar/genericos/cInscripcion/archivoCompleto.asp",
        "Archivo público de ARCA, sin licencia explícita",
        None,
        ("https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip",),
    ),
    "rns": Fuente(
        "rns",
        "Registro Nacional de Sociedades (Ministerio de Justicia)",
        "https://datos.jus.gob.ar/dataset/registro-nacional-de-sociedades",
        "CC BY 4.0",
        "https://datos.jus.gob.ar/api/3/action/package_show?id=registro-nacional-de-sociedades",
        ("https://datos.jus.gob.ar/dataset/ee83de85-4305-4c53-9a9f-fd3d15e42c36/resource/"
         "13a1a66f-9f49-4d2d-9582-7b4540ef1b83/download/registro-nacional-sociedades-2026.zip",),
    ),
    "gcba": Fuente(
        "gcba",
        "GCBA - Habilitaciones aprobadas (Agencia Gubernamental de Control)",
        "https://data.buenosaires.gob.ar/dataset/habilitaciones-aprobadas",
        "CC BY 2.5 AR",
        "https://data.buenosaires.gob.ar/api/3/action/package_show?id=habilitaciones-aprobadas",
        tuple(_GCBA_BASE + f for f in (
            "habilitaciones-2015-a-2018.csv", "habilitaciones-2019.csv",
            "habilitaciones-aprobadas2020.csv", "habilitaciones-aprobadas2021.csv",
            "habilitaciones-aprobadas2022.csv", "habilitaciones-aprobadas2023.csv",
            "habilitaciones-aprobadas2024.csv", "habilitaciones-aprobadas2026.csv",
        )),
    ),
    "energia": Fuente(
        "energia",
        "Secretaría de Energía - Precios en surtidor (Res. 314/2016)",
        "http://datos.energia.gob.ar/dataset/precios-en-surtidor",
        "CC BY 4.0",
        "http://datos.energia.gob.ar/api/3/action/package_show?id=precios-en-surtidor",
        ("http://datos.energia.gob.ar/dataset/1c181390-5045-475e-94dc-410429be4b17/resource/"
         "80ac25de-a44a-4445-9215-090cf55cfda5/download/precios-en-surtidor-resolucin-3142016.csv",),
    ),
    "sepa": Fuente(
        "sepa",
        "Precios Claros - Base SEPA (comercios y sucursales)",
        "https://datos.gob.ar/dataset/produccion-precios-claros---base-sepa",
        "CC BY 4.0",
        "https://datos.gob.ar/api/3/action/package_show?id=precios-claros-base-sepa",
        ("https://datos.produccion.gob.ar/dataset/6f47ec76-d1ce-4e34-a7e1-621fe9b1d0b5/resource/"
         "91bc072a-4726-44a1-85ec-4a8467aad27e/download/sepa_viernes.zip",),
    ),
}


def _abrir(url: str, timeout: int = 120):
    # Algunos portales publican URLs con caracteres sin escapar.
    url = urllib.parse.quote(url, safe=":/?&=%")
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENTE}), timeout=timeout)


def _fecha_servidor(url: str) -> str:
    try:
        url = urllib.parse.quote(url, safe=":/?&=%")
        pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE}, method="HEAD")
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.headers.get("Last-Modified", "")
    except Exception:
        return ""


def _recursos_ckan(fuente: Fuente) -> list[dict]:
    with _abrir(fuente.ckan, 60) as r:
        return json.load(r)["result"]["resources"]


def resolver_urls(fuente: Fuente) -> list[str]:
    """Elige qué archivos bajar de cada portal. Ante cualquier falla, las URL fijas."""
    if not fuente.ckan:
        return list(fuente.fijas)
    try:
        rec = _recursos_ckan(fuente)
        urls = [r["url"] for r in rec if r.get("url")]
        if fuente.id == "rns":
            # El zip anual más nuevo (no bimestres, no "sin fines de lucro").
            anuales = [u for u in urls if re.search(r"registro-nacional-sociedades-\d{4}\.zip$", u)]
            elegidas = [max(anuales)] if anuales else []
        elif fuente.id == "gcba":
            csvs = [u for u in urls if u.lower().endswith(".csv")]
            # 2025 y 2026 son el mismo padrón acumulado: alcanza con el último.
            acumulados = sorted(u for u in csvs if re.search(r"aprobadas202[5-9]\.csv$", u))
            elegidas = [u for u in csvs if u not in acumulados] + acumulados[-1:]
        elif fuente.id == "energia":
            elegidas = [u for u in urls if "precios-en-surtidor" in u and u.endswith(".csv")][:1]
        elif fuente.id == "sepa":
            elegidas = [u for u in urls if u.endswith("sepa_viernes.zip")]
        else:
            elegidas = []
        return elegidas or list(fuente.fijas)
    except Exception as e:  # red caída, portal cambiado: seguimos con lo verificado
        print(f"  aviso: no se pudo consultar el catálogo de {fuente.id} ({e}); uso URL fija")
        return list(fuente.fijas)


def descargar(ids: list[str] | None = None, forzar: bool = False) -> None:
    """Baja las fuentes a data/raw/<id>/ y anota url y fecha en _descarga.json."""
    for fid in ids or list(FUENTES):
        fuente = FUENTES[fid]
        carpeta = DIR_CRUDOS / fid
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_meta = carpeta / "_descarga.json"
        meta = json.loads(ruta_meta.read_text("utf-8")) if ruta_meta.exists() else {}
        print(f"[{fid}] {fuente.descripcion}")
        for url in resolver_urls(fuente):
            nombre = url.rsplit("/", 1)[-1]
            destino = carpeta / nombre
            if destino.exists() and destino.stat().st_size > 0 and not forzar:
                print(f"  ya está: {nombre} (usar --forzar para bajar de nuevo)")
                if nombre not in meta:   # archivo puesto a mano: se anota la fecha del servidor
                    meta[nombre] = {"url": url, "descargado": "", "fecha_servidor": _fecha_servidor(url)}
                continue
            print(f"  bajando {nombre} ...", end="", flush=True)
            parcial = destino.with_suffix(destino.suffix + ".part")
            with _abrir(url) as r, open(parcial, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
                modificado = r.headers.get("Last-Modified", "")
            parcial.replace(destino)
            meta[nombre] = {
                "url": url,
                "descargado": datetime.now().isoformat(timespec="seconds"),
                "fecha_servidor": modificado,
            }
            print(f" {destino.stat().st_size / 1e6:.1f} MB")
        ruta_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")


def metadatos(fid: str) -> dict:
    ruta = DIR_CRUDOS / fid / "_descarga.json"
    return json.loads(ruta.read_text("utf-8")) if ruta.exists() else {}

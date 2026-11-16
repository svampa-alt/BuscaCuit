"""Fuentes publicas que vinculan un local con el CUIT de su titular.

Se bajan solas en `python -m motor construir` y se guardan en `domicilios` como
tipo "local" (la busqueda las trata como evidencia de mayor peso):

- gcba_hab: habilitaciones aprobadas del GCBA (solo CABA, con CUIT del titular).
- energia: estaciones de servicio de todo el pais (Secretaria de Energia).
- sepa: sucursales de cadenas que informan a Precios Claros (todo el pais).

Solo archivos de descarga masiva publicados por cada organismo; no se hace
scraping ni se saltean controles de acceso.
"""
import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .texto import cuit_valido, norm, partir_direccion, provincia_canonica, solo_digitos

csv.field_size_limit(10 ** 8)
AGENTE = {"User-Agent": "BuscaCuit/2.0 (datos publicos)"}
_GCBA = ("https://cdn.buenosaires.gob.ar/datosabiertos/datasets/"
         "agencia-gubernamental-de-control/habilitaciones-aprobadas/")

# id -> (organismo, API CKAN para ubicar el archivo vigente, URL fijas de respaldo)
CATALOGO = {
    "gcba_hab": (
        "GCBA - Agencia Gubernamental de Control (habilitaciones aprobadas)",
        "https://data.buenosaires.gob.ar/api/3/action/package_show?id=habilitaciones-aprobadas",
        tuple(_GCBA + f for f in (
            "habilitaciones-2015-a-2018.csv", "habilitaciones-2019.csv",
            "habilitaciones-aprobadas2020.csv", "habilitaciones-aprobadas2021.csv",
            "habilitaciones-aprobadas2022.csv", "habilitaciones-aprobadas2023.csv",
            "habilitaciones-aprobadas2024.csv"))),
    "energia": (
        "Secretaria de Energia (precios en surtidor, Res. 314/2016)",
        "http://datos.energia.gob.ar/api/3/action/package_show?id=precios-en-surtidor",
        ("http://datos.energia.gob.ar/dataset/1c181390-5045-475e-94dc-410429be4b17/resource/"
         "80ac25de-a44a-4445-9215-090cf55cfda5/download/precios-en-surtidor-resolucin-3142016.csv",)),
    "sepa": (
        "Secretaria de Comercio (Precios Claros, base SEPA)",
        "https://datos.gob.ar/api/3/action/package_show?id=precios-claros-base-sepa",
        ("https://datos.produccion.gob.ar/dataset/6f47ec76-d1ce-4e34-a7e1-621fe9b1d0b5/resource/"
         "91bc072a-4726-44a1-85ec-4a8467aad27e/download/sepa_viernes.zip",)),
}

_PROV_ISO = {
    "C": "CABA", "B": "BUENOS AIRES", "K": "CATAMARCA", "H": "CHACO", "U": "CHUBUT",
    "X": "CORDOBA", "W": "CORRIENTES", "E": "ENTRE RIOS", "P": "FORMOSA", "Y": "JUJUY",
    "L": "LA PAMPA", "F": "LA RIOJA", "M": "MENDOZA", "N": "MISIONES", "Q": "NEUQUEN",
    "R": "RIO NEGRO", "A": "SALTA", "J": "SAN JUAN", "D": "SAN LUIS", "Z": "SANTA CRUZ",
    "S": "SANTA FE", "G": "SANTIAGO DEL ESTERO", "V": "TIERRA DEL FUEGO", "T": "TUCUMAN",
}


# ---------------------------------------------------------------- descarga

def _abrir(url, timeout=300):
    url = urllib.parse.quote(url, safe=":/?&=%")  # algunos portales publican URL sin escapar
    return urllib.request.urlopen(urllib.request.Request(url, headers=AGENTE), timeout=timeout)


def elegir_urls(fuente, urls):
    """De los recursos que ofrece el catalogo, los archivos que sirven."""
    if fuente == "gcba_hab":
        # Los padrones acumulados 2025+ no traen CUIT: no sirven para vincular.
        return [u for u in urls if u.lower().endswith(".csv")
                and not re.search(r"aprobadas202[5-9]\.csv$", u.lower())]
    if fuente == "energia":
        return [u for u in urls if "precios-en-surtidor" in u and u.lower().endswith(".csv")][:1]
    if fuente == "sepa":
        return [u for u in urls if u.endswith("sepa_viernes.zip")][:1]
    return []


def resolver_urls(fuente):
    """Archivo vigente segun el catalogo del portal; si no responde, las URL fijas."""
    _, ckan, fijas = CATALOGO[fuente]
    try:
        with _abrir(ckan, 60) as r:
            recursos = json.load(r)["result"]["resources"]
        return elegir_urls(fuente, [x["url"] for x in recursos if x.get("url")]) or list(fijas)
    except Exception as e:
        print(f"  aviso: catalogo de {fuente} no disponible ({e}); uso URL fija")
        return list(fijas)


def descargar(fuente, carpeta):
    """Baja los archivos de la fuente a `carpeta`. Devuelve [(ruta, url)]."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    bajados = []
    for url in resolver_urls(fuente):
        destino = carpeta / url.rsplit("/", 1)[-1]
        with _abrir(url) as r, open(destino, "wb") as f:
            while bloque := r.read(1 << 20):
                f.write(bloque)
        bajados.append((destino, url))
    return bajados


# ------------------------------------------------------------------ lectura

def _texto(datos):
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def _cuit(valor):
    d = solo_digitos(valor)
    return d if cuit_valido(d) else ""


_RE_DOM = re.compile(r"^[^;]*[A-Za-zÁ-ú][^;]*\s\d{1,5}(\s*;[^;]*\s\d{1,5})*\s*$")


def _filas_gcba(ruta):
    """Genera (calles, titulares, cuits, rubro, expediente) de un CSV de habilitaciones."""
    lector = csv.reader(io.StringIO(_texto(Path(ruta).read_bytes())), delimiter=";")
    cab = [h.strip().lower().replace("_", "") for h in next(lector, [])]
    pos = {h: i for i, h in enumerate(cab)}
    roto = any(h.startswith("unnamed") for h in cab)  # el CSV 2021 viene desalineado
    if not roto and not {"calles", "titulares", "cuits"} <= set(pos):
        print(f"  aviso: {Path(ruta).name} no trae calles, titulares y cuits; se saltea")
        return
    i_exp = pos.get("numeroexp", pos.get("numeroexpediente"))
    i_rubro = pos.get("descripcionrubro")
    for fila in lector:
        if not roto:
            if len(fila) < len(cab):
                continue
            yield (fila[pos["calles"]], fila[pos["titulares"]], fila[pos["cuits"]],
                   fila[i_rubro] if i_rubro is not None else "",
                   fila[i_exp] if i_exp is not None else "")
            continue
        # Formato roto: se ubica la celda de CUIT y se retrocede hasta el domicilio.
        i_cuit = next((i for i in range(len(fila) - 1, 8, -1)
                       if fila[i] and all(_cuit(x) for x in fila[i].split(";"))), None)
        if i_cuit is None:
            continue
        j = i_cuit - 1
        while j > i_cuit - 4 and j > 9 and not _RE_DOM.match(fila[j]):
            j -= 1
        if not _RE_DOM.match(fila[j]):
            continue
        yield (fila[j], ",".join(fila[j + 1:i_cuit]), fila[i_cuit],
               fila[9] if len(fila) > 9 else "", fila[7] if len(fila) > 7 else "")


def leer_gcba(rutas):
    """Una fila por (CUIT, domicilio). Cada habilitacion puede traer varios de ambos."""
    for ruta in rutas:
        for calles, titulares, cuits, _rubro, exp in _filas_gcba(ruta):
            lista_c = [x.strip() for x in cuits.split(";") if x.strip()]
            lista_t = [x.strip() for x in titulares.split(";")]
            for i, crudo in enumerate(lista_c):
                cuit = _cuit(crudo)
                if not cuit:
                    continue
                titular = lista_t[i] if len(lista_t) == len(lista_c) else titulares.strip()
                for domicilio in calles.split(";"):
                    calle, numero = partir_direccion(domicilio)
                    if calle:
                        yield {"cuit": cuit, "titular": " ".join(titular.split()), "nombre_local": "",
                               "calle": calle, "numero": numero, "localidad": "", "provincia": "CABA",
                               "referencia": " ".join(exp.split())}


def leer_energia(rutas):
    """Una fila por estacion (el archivo trae una por producto y horario)."""
    vistas = set()
    for ruta in rutas:
        for r in csv.DictReader(io.StringIO(_texto(Path(ruta).read_bytes()))):
            ident = r.get("idempresa") or ""
            if not ident or ident in vistas:
                continue
            vistas.add(ident)
            cuit = _cuit(r.get("cuit"))
            calle, numero = partir_direccion(r.get("direccion"))
            if cuit and calle:
                yield {"cuit": cuit, "titular": (r.get("empresa") or "").strip(),
                       "nombre_local": (r.get("empresabandera") or "").strip(),
                       "calle": calle, "numero": numero, "localidad": norm(r.get("localidad")),
                       "provincia": provincia_canonica(r.get("provincia")), "referencia": ident}


def _csv_sepa(z, nombre):
    try:
        datos = z.read(nombre)
    except KeyError:
        return []
    # Los archivos cierran con una linea "Ultima actualizacion: ..." que no es un registro.
    return [r for r in csv.DictReader(io.StringIO(_texto(datos)), delimiter="|") if r.get("id_bandera")]


def leer_sepa(rutas):
    """ZIP de ZIP: de cada comercio se leen comercio.csv y sucursales.csv."""
    for ruta in rutas:
        with zipfile.ZipFile(ruta) as z:
            for info in z.infolist():
                if not info.filename.lower().endswith(".zip") or info.file_size == 0:
                    continue
                try:
                    zi = zipfile.ZipFile(io.BytesIO(z.read(info)))
                except zipfile.BadZipFile:
                    continue
                banderas = {}
                for r in _csv_sepa(zi, "comercio.csv"):
                    cuit = _cuit(r.get("comercio_cuit"))
                    if cuit:
                        banderas[(r.get("id_comercio"), r["id_bandera"])] = (
                            cuit, (r.get("comercio_razon_social") or "").strip(),
                            (r.get("comercio_bandera_nombre") or "").strip())
                for r in _csv_sepa(zi, "sucursales.csv"):
                    dato = banderas.get((r.get("id_comercio"), r["id_bandera"]))
                    if not dato:
                        continue
                    calle = norm(r.get("sucursales_calle"))
                    numero = solo_digitos(r.get("sucursales_numero")).lstrip("0")
                    if not numero:  # algunas cadenas ponen "AV SAN MARTIN 5688" todo en la calle
                        calle, numero = partir_direccion(calle)
                    if not calle:
                        continue
                    yield {"cuit": dato[0], "titular": dato[1], "nombre_local": dato[2],
                           "calle": calle, "numero": numero,
                           "localidad": norm(r.get("sucursales_localidad")),
                           "provincia": _PROV_ISO.get((r.get("sucursales_provincia") or "")[-1:].upper(), ""),
                           "referencia": "-".join(str(r.get(k) or "") for k in
                                                  ("id_comercio", "id_bandera", "id_sucursal"))}


LECTORES = {"gcba_hab": leer_gcba, "energia": leer_energia, "sepa": leer_sepa}


# ------------------------------------------------------------------ importar

def importar(db, fuente, rutas, urls=()):
    """Carga una fuente en `domicilios` y `nombres`. Devuelve cuantos locales guardo."""
    rutas = [Path(r) for r in rutas]
    if not rutas:
        raise ValueError(f"{fuente}: sin archivos para importar")
    db.execute("DELETE FROM domicilios WHERE fuente=?", (fuente,))
    db.execute("DELETE FROM nombres WHERE fuente=?", (fuente,))
    locales, nombres, guardados = [], set(), 0
    for f in LECTORES[fuente](rutas):
        locales.append((f["cuit"], "local", f["provincia"], f["localidad"], f["calle"], f["numero"],
                        "", "", "", "", fuente, f["nombre_local"], f["referencia"]))
        nombres.add((f["titular"], f["cuit"]))
        if fuente == "sepa":  # la bandera identifica a la cadena; en estaciones es de la petrolera
            nombres.add((f["nombre_local"], f["cuit"]))
        if len(locales) >= 50000:
            guardados += _volcar(db, locales)
    guardados += _volcar(db, locales)
    db.executemany("INSERT INTO nombres(nombre, cuit, fuente) VALUES (?,?,?)",
                   [(n, c, fuente) for n, c in sorted(nombres) if n])
    huella = hashlib.sha256()
    for ruta in rutas:
        with open(ruta, "rb") as f:
            while bloque := f.read(1 << 20):
                huella.update(bloque)
    db.execute("INSERT OR REPLACE INTO fuentes VALUES (?,?,?,?,?,?,?)",
               (fuente, CATALOGO[fuente][0], " ".join(urls), " ".join(r.name for r in rutas),
                huella.hexdigest(), datetime.now(timezone.utc).isoformat(timespec="seconds"), guardados))
    db.commit()
    return guardados


def _volcar(db, locales):
    antes = db.total_changes
    db.executemany("INSERT OR IGNORE INTO domicilios VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", locales)
    locales.clear()
    return db.total_changes - antes

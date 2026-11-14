"""Uso:
  python -m motor construir [--padron ZIP] [--sociedades ZIP] [--locales fuente=archivo.csv ...]
  python -m motor buscar --nombre "El Nido Bar" --direccion "Costa Rica 5709" --provincia CABA
  python -m motor lote entrada.csv salida.csv     (columnas: nombre,direccion,localidad,provincia)
  python -m motor resumen
"""
import argparse
import csv
import json
import tempfile
import urllib.request
from pathlib import Path

from . import base
from .buscar import buscar

PADRON_URLS = ("https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip",
               "https://www.arca.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip")
RNS_API = "https://datos.jus.gob.ar/api/3/action/package_show?id=registro-nacional-de-sociedades"
AGENTE = {"User-Agent": "BuscaCuit/2.0 (datos publicos)"}


def bajar(url, destino):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENTE), timeout=300) as r, \
            open(destino, "wb") as salida:
        while bloque := r.read(1 << 20):
            salida.write(bloque)
    return destino


def url_sociedades():
    """ZIP anual mas reciente del registro (excluye asociaciones y cortes parciales)."""
    with urllib.request.urlopen(urllib.request.Request(RNS_API, headers=AGENTE), timeout=120) as r:
        recursos = json.load(r)["result"]["resources"]
    anuales = []
    for rec in recursos:
        partes = [p.strip() for p in rec.get("name", "").lower().split(" - ")]
        if (len(partes) == 2 and partes[0] == "registro nacional de sociedades" and partes[1].isdigit()
                and rec.get("format", "").lower() == "zip" and rec.get("url", "").startswith("https://")):
            anuales.append((int(partes[1]), rec["url"]))
    if not anuales:
        raise RuntimeError("El catalogo no ofrece un ZIP anual de sociedades")
    return max(anuales)[1]


def construir(args):
    args.db.parent.mkdir(parents=True, exist_ok=True)
    db = base.conectar(args.db)
    with tempfile.TemporaryDirectory() as tmp:
        if args.padron != "omitir":
            ruta, url = args.padron, ""
            if not ruta:
                errores = []
                for url in PADRON_URLS:
                    try:
                        ruta = bajar(url, Path(tmp) / "padron.zip")
                        break
                    except Exception as e:  # se prueba el dominio alternativo
                        errores.append(f"{url}: {e}")
                else:
                    raise RuntimeError("No se pudo bajar el padron: " + "; ".join(errores))
            print("padron ARCA:", base.importar_padron(db, ruta, url), "contribuyentes")
        if args.sociedades != "omitir":
            ruta, url = args.sociedades, ""
            if not ruta:
                url = url_sociedades()
                ruta = bajar(url, Path(tmp) / "sociedades.zip")
            print("sociedades:", base.importar_sociedades(db, ruta, url), "CUIT")
    for spec in args.locales:
        fuente, archivo = spec.split("=", 1)
        print(fuente + ":", base.importar_locales(db, archivo, fuente, fuente), "locales con CUIT")
    db.commit()
    print(json.dumps(base.resumen(db), ensure_ascii=False, indent=2))


def lote(args):
    db = base.conectar(args.db, solo_lectura=True)
    with open(args.entrada, encoding="utf-8-sig", newline="") as f, \
            open(args.salida, "w", encoding="utf-8", newline="") as g:
        salida = csv.writer(g)
        salida.writerow(["nombre", "direccion", "localidad", "provincia", "estado", "cuit",
                         "razon_social", "puntaje", "candidatos_totales", "evidencias"])
        for fila in csv.DictReader(f):
            q = {k: (fila.get(k) or "").strip() for k in ("nombre", "direccion", "localidad", "provincia")}
            if not (q["nombre"] or q["direccion"]):
                continue
            r = buscar(db, **q, limite=1)
            m = r["candidatos"][0] if r["candidatos"] else {}
            salida.writerow([*q.values(), r["estado"], m.get("cuit", ""), m.get("razon_social", ""),
                             m.get("puntaje", ""), r["candidatos_totales"],
                             "; ".join(e["tipo"] + ":" + e.get("fuente", "") for e in m.get("evidencias", []))])


def main():
    p = argparse.ArgumentParser(prog="motor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=Path("output/buscacuit.sqlite"))
    sub = p.add_subparsers(dest="orden", required=True)
    c = sub.add_parser("construir")
    c.add_argument("--padron", default="", help="ZIP local; vacio descarga; 'omitir' lo saltea")
    c.add_argument("--sociedades", default="", help="ZIP/CSV local; vacio descarga; 'omitir' lo saltea")
    c.add_argument("--locales", action="append", default=[], help="fuente=archivo.csv (habilitaciones con CUIT)")
    b = sub.add_parser("buscar")
    for campo in ("nombre", "direccion", "localidad", "provincia", "cuit"):
        b.add_argument("--" + campo, default="")
    b.add_argument("--limite", type=int, default=15)
    lo = sub.add_parser("lote")
    lo.add_argument("entrada", type=Path)
    lo.add_argument("salida", type=Path)
    sub.add_parser("resumen")
    args = p.parse_args()
    if args.orden == "construir":
        construir(args)
    elif args.orden == "lote":
        lote(args)
    elif args.orden == "resumen":
        print(json.dumps(base.resumen(base.conectar(args.db, True)), ensure_ascii=False, indent=2))
    else:
        r = buscar(base.conectar(args.db, True), args.nombre, args.direccion, args.localidad,
                   args.provincia, args.cuit, args.limite)
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

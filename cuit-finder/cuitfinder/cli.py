"""Interfaz de línea de comandos: python -m cuitfinder <comando>."""
from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__, db
from .cuit import digito_verificador, es_valido, formatear, limpiar


def _cmd_buscar(a) -> int:
    from .buscar import buscar
    con = db.conectar()
    res = buscar(con, a.nombre, a.direccion, a.max, a.todos)
    if a.json:
        print(json.dumps([c.como_dict() for c in res], ensure_ascii=False, indent=2))
        return 0
    print(f'Consulta: "{a.nombre}" / "{a.direccion}"')
    if not res:
        print("Sin candidatos por encima del umbral. Probá con --todos o revisá la dirección.")
        return 1
    for i, c in enumerate(res, 1):
        cuit = formatear(c.cuit) if c.cuit else "(sin CUIT)"
        print(f"\n{i}. {cuit}  {c.razon_social}")
        print(f"   puntaje {c.puntaje:.0f}/100  confianza {c.nivel}"
              f"  [dirección D={c.sim_direccion:.2f}, nombre N={c.sim_nombre:.2f}"
              f"{' (no cuenta: bajo 0.60)' if 0 < c.sim_nombre < 0.6 else ''}]")
        for e in (c.evidencias if a.detalle else c.evidencias[:4]):
            print(f"   - [{e.fuente}] {e.regla}: {e.detalle}")
    return 0


def _cmd_validar(a) -> int:
    c = limpiar(a.cuit)
    if es_valido(c):
        print(f"{formatear(c)}: válido")
        return 0
    if len(c) != 11:
        print(f"{a.cuit}: inválido, tiene {len(c)} dígitos y deben ser 11")
    else:
        dv = digito_verificador(c[:10])
        esperado = "ninguno (combinación inexistente)" if dv is None else dv
        print(f"{formatear(c)}: inválido, dígito verificador {c[10]} y debería ser {esperado}")
    return 1


def _cmd_descargar(a) -> int:
    from .fuentes import descargar
    descargar(a.fuente or None, a.forzar)
    return 0


def _cmd_construir(a) -> int:
    from .ingesta import construir
    construir(a.fuente or None)
    return 0


def _cmd_actualizar(a) -> int:
    from .fuentes import descargar
    from .ingesta import construir
    descargar(None, forzar=not a.sin_descargar_de_nuevo)
    construir()
    return 0


def _cmd_fuentes(a) -> int:
    con = db.conectar()
    for f in con.execute("SELECT * FROM fuente"):
        print(f"{f['id']}: {f['descripcion']}\n   {f['url']}\n   licencia: {f['licencia']}"
              f"\n   datos al: {f['fecha_datos'] or 's/d'} | ingesta: {f['fecha_ingesta']}"
              f" | filas: {f['filas']}\n   {f['notas']}")
    return 0


def _cmd_alias(a) -> int:
    from .buscar import agregar_alias, leer_alias
    if a.accion == "agregar":
        if not a.fantasia or not a.cuit:
            print("uso: alias agregar \"nombre de fantasía\" CUIT [\"dirección\"] [--nota texto]")
            return 2
        try:
            agregar_alias(a.fantasia, a.cuit, a.direccion or "", a.nota or "")
        except ValueError as e:
            print(e)
            return 1
        print(f"alias guardado en {db.RUTA_ALIAS}")
    else:
        for x in leer_alias():
            print(f"{x['fantasia']} | {formatear(x['cuit'])} | {x['direccion']} | {x['nota']} | {x['fecha']}")
    return 0


def _cmd_evaluar(a) -> int:
    from .evaluar import evaluar, imprimir, muestra_por_direccion
    con = db.conectar()
    if a.muestra_direcciones:
        m = muestra_por_direccion(con, a.muestra_direcciones)
        print(f"{m['casos']} habilitaciones GCBA consultadas solo por dirección | "
              f"CUIT correcto primero: {m['primero']} ({100 * m['primero'] / m['casos']:.0f}%) | "
              f"entre los 5 primeros: {m['entre5']} ({100 * m['entre5'] / m['casos']:.0f}%)")
        return 0
    with open(a.archivo, encoding="utf-8", newline="") as f:
        casos = list(csv.DictReader(f))
    return imprimir(evaluar(con, casos))


def main(argv=None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(
        prog="cuitfinder",
        description="Busca el CUIT de un comercio argentino por nombre de fantasía y dirección.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("buscar", help="buscar candidatos de CUIT")
    b.add_argument("nombre", help="nombre de fantasía o razón social")
    b.add_argument("direccion", nargs="?", default="", help='ej. "Costa Rica 5709, Palermo, CABA"')
    b.add_argument("--max", type=int, default=5, help="cantidad de candidatos (5)")
    b.add_argument("--json", action="store_true", help="salida en JSON")
    b.add_argument("--detalle", action="store_true", help="mostrar todas las evidencias")
    b.add_argument("--todos", action="store_true", help="incluir candidatos bajo el umbral")
    b.set_defaults(f=_cmd_buscar)

    v = sub.add_parser("validar", help="validar el dígito verificador de un CUIT")
    v.add_argument("cuit")
    v.set_defaults(f=_cmd_validar)

    d = sub.add_parser("descargar", help="bajar las fuentes a data/raw")
    d.add_argument("--fuente", action="append", choices=["arca", "rns", "gcba", "energia", "sepa"])
    d.add_argument("--forzar", action="store_true", help="bajar aunque el archivo ya exista")
    d.set_defaults(f=_cmd_descargar)

    c = sub.add_parser("construir", help="armar la base SQLite desde data/raw")
    c.add_argument("--fuente", action="append", choices=["arca", "rns", "gcba", "energia", "sepa"])
    c.set_defaults(f=_cmd_construir)

    u = sub.add_parser("actualizar", help="descargar todo de nuevo y reconstruir la base")
    u.add_argument("--sin-descargar-de-nuevo", action="store_true",
                   help="usar los archivos que ya están en data/raw")
    u.set_defaults(f=_cmd_actualizar)

    sub.add_parser("fuentes", help="mostrar las fuentes cargadas y sus fechas").set_defaults(f=_cmd_fuentes)

    al = sub.add_parser("alias", help="alias fantasía -> CUIT confirmados por vos")
    al.add_argument("accion", choices=["agregar", "listar"])
    al.add_argument("fantasia", nargs="?")
    al.add_argument("cuit", nargs="?")
    al.add_argument("direccion", nargs="?")
    al.add_argument("--nota")
    al.set_defaults(f=_cmd_alias)

    e = sub.add_parser("evaluar", help="medir aciertos sobre un CSV de casos")
    e.add_argument("archivo", nargs="?", default=str(db.RAIZ / "casos" / "casos_reales.csv"))
    e.add_argument("--muestra-direcciones", type=int, metavar="N",
                   help="en vez del CSV, probar N habilitaciones GCBA solo por dirección")
    e.set_defaults(f=_cmd_evaluar)

    a = p.parse_args(argv)
    try:
        return a.f(a)
    except FileNotFoundError as err:
        print(err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

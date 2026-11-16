"""Medición de aciertos sobre un conjunto de casos con CUIT conocido.

CSV de casos: nombre, direccion, cuit_esperado, origen, nota.
"""
from __future__ import annotations

from .buscar import buscar
from .cuit import formatear, limpiar


def evaluar(con, casos: list[dict]) -> list[dict]:
    filas = []
    for caso in casos:
        esperado = limpiar(caso["cuit_esperado"])
        res = buscar(con, caso["nombre"], caso["direccion"], max_resultados=5, alias=[])
        cuits = [str(c.cuit) for c in res]
        pos = cuits.index(esperado) + 1 if esperado in cuits else 0
        filas.append({
            "grupo": caso.get("grupo", ""),
            "nombre": caso["nombre"], "direccion": caso["direccion"], "esperado": esperado,
            "posicion": pos,
            "puntaje": res[pos - 1].puntaje if pos else 0.0,
            "nivel": res[pos - 1].nivel if pos else "-",
            "primero": cuits[0] if cuits else "",
            "puntaje_primero": res[0].puntaje if res else 0.0,
        })
    return filas


def muestra_por_direccion(con, n: int = 300) -> dict:
    """Mide la vía de dirección sola sobre una muestra fija de habilitaciones GCBA.

    Se consulta únicamente con la dirección (sin nombre) y se mira si el CUIT
    habilitado sale primero. No mide el matcheo de nombres: mide cuán ambigua
    es una dirección (varios titulares en el mismo domicilio).
    """
    filas = con.execute(
        "SELECT cuit, calle, altura FROM domicilio WHERE fuente = 'gcba_hab' AND altura IS NOT NULL "
        "ORDER BY (id * 2654435761) % 1000003 LIMIT ?", (n,)).fetchall()
    primero = entre5 = 0
    for f in filas:
        res = buscar(con, "", f"{f['calle']} {f['altura']}, CABA", max_resultados=5, alias=[])
        cuits = [c.cuit for c in res]
        primero += bool(cuits) and cuits[0] == f["cuit"]
        entre5 += f["cuit"] in cuits
    return {"casos": len(filas), "primero": primero, "entre5": entre5}


def imprimir(filas: list[dict]) -> int:
    n = len(filas)
    for f in filas:
        marca = {0: "NO", 1: "OK"}.get(f["posicion"], f"#{f['posicion']}")
        print(f"[{marca:>2}] {f['nombre'][:28]:28} | {f['direccion'][:34]:34} | "
              f"esperado {formatear(f['esperado'])} | puntaje {f['puntaje']:.0f} {f['nivel']}")
    print()
    for g in sorted({f["grupo"] for f in filas}):
        del_grupo = [f for f in filas if f["grupo"] == g]
        ok = sum(1 for f in del_grupo if f["posicion"] == 1)
        alta = sum(1 for f in del_grupo if f["posicion"] == 1 and f["nivel"] == "ALTA")
        print(f"  {g or '(sin grupo)':24} primero correcto {ok}/{len(del_grupo)}, de ellos con confianza ALTA {alta}")
    top1 = sum(1 for f in filas if f["posicion"] == 1)
    top5 = sum(1 for f in filas if f["posicion"] >= 1)
    alta_mal = sum(1 for f in filas if f["posicion"] != 1 and f["puntaje_primero"] >= 80)
    print(f"\n{n} casos | primero correcto: {top1} ({100 * top1 / n:.0f}%) | "
          f"entre los 5 primeros: {top5} ({100 * top5 / n:.0f}%) | "
          f"primer puesto equivocado con confianza ALTA: {alta_mal}")
    return 0

"""Busqueda unica: de nombre de fantasia + direccion a candidatos de CUIT con evidencia.

Estados (AGENTS.md): CONFIRMADO, ALTA_CONFIANZA, POSIBLE, NO_VERIFICADO.
La cercania ordena; nunca excluye. Nada se afirma sin una fila de origen.
"""
import difflib

from .texto import (RUBROS, cuit_valido, misma_calle, misma_provincia, norm, partir_direccion,
                    solo_digitos, tokens_nombre)

ORDEN = {"CONFIRMADO": 3, "ALTA_CONFIANZA": 2, "POSIBLE": 1, "NO_VERIFICADO": 0}
GASTRONOMIA = {"BAR", "CAFE", "RESTAURANTE", "RESTO", "PARRILLA", "PIZZERIA", "CERVECERIA",
               "HELADERIA", "BODEGON"}
COLS_DOM = ("cuit", "tipo", "provincia", "localidad", "calle", "numero", "piso", "depto", "cp",
            "estado", "fuente", "nombre_local", "referencia", "titular", "rubro", "fecha")


def _fts(db, consulta, limite):
    try:
        return db.execute("SELECT nombre, cuit, fuente FROM nombres WHERE nombres MATCH ? "
                          "ORDER BY rank LIMIT ?", (consulta, limite)).fetchall()
    except Exception:
        return []


def _puntaje_nombre(buscado, encontrado):
    q, r = set(buscado), set(tokens_nombre(encontrado, quitar_rubro=True))
    if not q or not r:
        return 0.0
    comunes = sum(1 for t in q if t in r or difflib.get_close_matches(t, r, 1, 0.84))
    cobertura, precision = comunes / len(q), comunes / len(r)
    return round(cobertura * (0.5 + 0.5 * precision), 3)


def _por_nombre(db, nombre, limite=300):
    toks = tokens_nombre(nombre, quitar_rubro=True)
    if not toks:
        return [], toks
    filas = _fts(db, " ".join(f'"{t}"' for t in toks), limite)
    if not filas and len(toks) > 1:
        filas = _fts(db, " OR ".join(f'"{t}"' for t in toks), limite)
    if not filas:  # tolerancia a errores de tipeo: mismo comienzo, parecido alto
        filas = _fts(db, " OR ".join(f'"{t[:4]}"*' for t in toks if len(t) >= 4), limite * 3)
    return filas, toks


def _por_direccion(db, direccion, provincia):
    calle, numero = partir_direccion(direccion)
    if not calle or not numero:
        return []
    filas = db.execute(f"SELECT {','.join(COLS_DOM)} FROM domicilios WHERE numero=?", (numero,))
    return [dict(zip(COLS_DOM, f)) for f in filas
            if misma_calle(calle, f[4]) and misma_provincia(provincia, f[2]) is not False]


def buscar(db, nombre="", direccion="", localidad="", provincia="", cuit="", limite=15):
    if not (nombre or direccion or cuit):
        raise ValueError("Se requiere nombre, direccion o CUIT")
    cand = {}

    def c(numero):
        return cand.setdefault(numero, {"cuit": numero, "puntaje": 0.0, "evidencias": [],
                                        "_nombre": 0.0, "_dom": None, "_fecha": "", "_titular": ""})

    digitos = solo_digitos(cuit)
    if len(digitos) == 11:
        c(digitos)["puntaje"] += 100
        c(digitos)["evidencias"].append({"tipo": "cuit_consultado", "valido": cuit_valido(digitos)})

    for d in _por_direccion(db, direccion, provincia):
        item = c(d["cuit"])
        if item["_dom"] is None or d["tipo"] == "local":
            item["_dom"] = d["tipo"]
        item["evidencias"].append({
            "tipo": "domicilio_coincide", "clase_domicilio": d["tipo"], "fuente": d["fuente"],
            "domicilio": f'{d["calle"]} {d["numero"]}, {d["localidad"]}, {d["provincia"]}',
            "nombre_local": d["nombre_local"], "referencia": d["referencia"],
            "titular": d["titular"], "rubro": d["rubro"], "fecha": d["fecha"]})
        if d["tipo"] == "local":
            item["_titular"] = item["_titular"] or d["titular"] or ""
            item["_fecha"] = max(item["_fecha"], d["fecha"] or "")

    filas, toks = _por_nombre(db, nombre) if nombre else ([], [])
    for texto, numero, fuente in filas:
        p = _puntaje_nombre(toks, texto)
        if p <= 0:
            continue
        item = c(numero)
        if p > item["_nombre"]:
            item["_nombre"] = p
            item["evidencias"] = [e for e in item["evidencias"] if e["tipo"] != "nombre_coincide"]
            item["evidencias"].append({"tipo": "nombre_coincide", "fuente": fuente,
                                       "nombre": texto, "similitud": p})

    # Varios titulares habilitados en la misma direccion: el mas reciente es el mas probable hoy.
    fechas = sorted({i["_fecha"] for i in cand.values() if i["_dom"] == "local" and i["_fecha"]})
    rubro_gastro = bool(set(norm(nombre).split()) & GASTRONOMIA)
    for numero, item in cand.items():
        _enriquecer(db, item)
        if len(fechas) > 1 and item["_dom"] == "local" and item["_fecha"]:
            if item["_fecha"] == fechas[-1]:
                item["puntaje"] += 5
                item["evidencias"].append({"tipo": "habilitacion_mas_reciente", "fecha": item["_fecha"],
                                           "nota": "hay otros titulares habilitados antes en esta direccion"})
            else:
                item["evidencias"].append({"tipo": "habilitacion_anterior", "fecha": item["_fecha"],
                                           "nota": f"hay una habilitacion posterior ({fechas[-1]}) en esta direccion"})
        puntos = 60 * item["_nombre"]
        if item["_dom"]:
            puntos += 100 if item["_dom"] == "local" else 80
        else:  # sin domicilio coincidente, la zona solo ordena
            zonas = [misma_provincia(provincia, d["provincia"]) for d in item["domicilios"]]
            if True in zonas:
                puntos += 10
                if localidad and any(norm(localidad) == d["localidad"] for d in item["domicilios"]):
                    puntos += 5
            elif False in zonas:
                puntos -= 20
                item["evidencias"].append({"tipo": "jurisdiccion_distinta",
                                           "nota": "penaliza el orden, no descarta"})
        if rubro_gastro and any(a["codigo"].startswith(("561", "563")) for a in item["actividades"]):
            puntos += 15
            item["evidencias"].append({"tipo": "actividad_compatible", "fuente": "rns",
                                       "nota": "actividad gastronomica declarada"})
        item["puntaje"] = round(item["puntaje"] + puntos, 2)
        item["estado"] = _estado(item)

    orden = sorted(cand.values(), key=lambda i: (ORDEN[i["estado"]], i["puntaje"]), reverse=True)[:limite]
    for item in cand.values():
        for clave in ("_nombre", "_dom", "_fecha", "_titular"):
            item.pop(clave)
    mejor = orden[0]["estado"] if orden else "NO_VERIFICADO"
    return {
        "consulta": {"nombre": nombre, "direccion": direccion, "localidad": localidad,
                     "provincia": provincia, "cuit": cuit},
        "estado": mejor, "candidatos_totales": len(cand), "candidatos": orden,
        "fuentes": [dict(zip(("id", "url", "fecha_consulta", "sha256"), f)) for f in
                    db.execute("SELECT id, url, fecha_consulta, sha256 FROM fuentes")],
        "advertencia": "Solo CONFIRMADO acredita titularidad; el resto son candidatos a verificar.",
    }


def _estado(item):
    nombre, dom = item["_nombre"], item["_dom"]
    if dom == "local":
        return "CONFIRMADO"  # habilitacion oficial que vincula CUIT y local en esa direccion
    if dom and nombre >= 0.5:
        return "ALTA_CONFIANZA"
    if dom:
        return "POSIBLE"
    conflicto = any(e["tipo"] == "jurisdiccion_distinta" for e in item["evidencias"])
    if nombre >= 0.75 and not conflicto:
        return "POSIBLE"
    return "NO_VERIFICADO"


def _enriquecer(db, item):
    numero = item["cuit"]
    fila = db.execute("SELECT denominacion, ganancias, iva, monotributo, integrante_soc, empleador "
                      "FROM contribuyentes WHERE cuit=?", (numero,)).fetchone()
    soc = db.execute("SELECT razon_social, tipo, fecha_contrato FROM sociedades WHERE cuit=?",
                     (numero,)).fetchone()
    item["cuit_valido"] = cuit_valido(numero)
    item["razon_social"] = (soc[0] if soc else None) or (fila[0] if fila else None) or item["_titular"] or None
    item["en_padron_arca"] = bool(fila)
    if not fila:
        item["evidencias"].append({"tipo": "ausente_en_padron_arca",
                                   "nota": "no figura en el padron ARCA descargado; verificar vigencia"})
    if fila:
        item["arca"] = dict(zip(("ganancias", "iva", "monotributo", "integrante_soc", "empleador"), fila[1:]))
    if soc:
        item["sociedad"] = {"tipo": soc[1], "fecha_contrato": soc[2]}
    item["domicilios"] = [dict(zip(COLS_DOM[1:], f)) for f in db.execute(
        f"SELECT {','.join(COLS_DOM[1:])} FROM domicilios WHERE cuit=?", (numero,))]
    item["actividades"] = [{"codigo": a, "descripcion": b} for a, b in db.execute(
        "SELECT codigo, descripcion FROM actividades WHERE cuit=? LIMIT 8", (numero,))]

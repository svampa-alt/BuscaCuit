"""Método de búsqueda: candidatos por dirección y por nombre, y puntaje combinado.

Resumen del método (ver README para la explicación larga):

1. Se normalizan el nombre y la dirección de la consulta.
2. Candidatos por DIRECCIÓN: domicilios de la base en la misma calle y a
   +-20 números de la altura pedida.
3. Candidatos por NOMBRE: búsqueda de texto completo (FTS5) y similitud difusa.
4. Las habilitaciones sin CUIT se resuelven buscando la razón social exacta.
5. Por cada CUIT se toma la mejor evidencia de dirección (D) y de nombre (N),
   ambas entre 0 y 1, y se calcula  puntaje = 55*D + 45*N  más ajustes.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import db
from .cuit import es_valido, formatear, limpiar
from .normalizar import (
    CABA, PALABRAS_GENERICAS, Direccion, cobertura_consulta, menciona_barrio_caba,
    normalizar_nombre, normalizar_texto, parsear_direccion, provincias_mencionadas,
    similitud_calle, similitud_nombre, tokens_nombre,
)

# ---- Parámetros del método (todos explicados en el README) ----------------
PESO_DIRECCION = 55
PESO_NOMBRE = 45
RANGO_ALTURA = 20            # "misma cuadra": hasta 20 números de diferencia
FACTOR_ALTURA_CERCANA = 0.55
FACTOR_OTRA_ALTURA = 0.25
D_SOLO_LOCALIDAD = 0.10
PESO_TIPO = {"local": 1.0, "sucursal": 1.0, "fiscal": 0.9, "legal": 0.85}
UMBRAL_CALLE = 0.8
UMBRAL_NOMBRE = 0.6          # por debajo, el parecido de nombre no cuenta
BONO_UNICO_EN_DIRECCION = 10
BONO_NOMBRE_UNICO = 10
BONO_MAS_RECIENTE = 3
BONO_RUBRO = 5               # "bar", "farmacia"... de la consulta figura en el rubro
PISO_COINCIDENCIA_DOBLE = 90  # nombre y dirección coinciden
PUNTAJE_ALIAS = 97
FACTOR_RESUELTO_POR_NOMBRE = 0.9   # habilitación sin CUIT, razón social única
FACTOR_HOMONIMOS = 0.5             # habilitación sin CUIT, varios CUIT posibles
FACTOR_NOMBRE_REPARTIDO = 0.9      # consulta cubierta entre varias banderas
NIVEL_ALTA, NIVEL_MEDIA, NIVEL_BAJA = 80, 55, 35
ORDEN_FUENTE_RAZON = {"rns": 0, "arca": 1, "gcba_hab": 2, "sepa": 3, "energia": 4}


@dataclass
class Evidencia:
    fuente: str
    regla: str
    detalle: str


@dataclass
class Candidato:
    cuit: int | None
    razon_social: str = ""
    puntaje: float = 0.0
    nivel: str = ""
    sim_nombre: float = 0.0       # N
    sim_direccion: float = 0.0    # D
    evidencias: list[Evidencia] = field(default_factory=list)
    # auxiliares internos
    _exacta_local: bool = False
    _fecha: str = ""
    _alias: bool = False

    def como_dict(self) -> dict:
        return {
            "cuit": formatear(self.cuit) if self.cuit else None,
            "cuit_valido": es_valido(self.cuit) if self.cuit else None,
            "razon_social": self.razon_social,
            "puntaje": round(self.puntaje, 1),
            "nivel": self.nivel,
            "similitud_nombre": round(self.sim_nombre, 2),
            "similitud_direccion": round(self.sim_direccion, 2),
            "evidencias": [e.__dict__ for e in self.evidencias],
        }


def nivel_de(puntaje: float) -> str:
    if puntaje >= NIVEL_ALTA:
        return "ALTA"
    if puntaje >= NIVEL_MEDIA:
        return "MEDIA"
    if puntaje >= NIVEL_BAJA:
        return "BAJA"
    return "DESCARTADO"


def puntuar(d: float, n: float, unico_en_direccion: bool = False, nombre_unico: bool = False,
            mas_reciente: bool = False, rubro_coincide: bool = False) -> tuple[float, list[str]]:
    """Puntaje 0-100 a partir de D (dirección) y N (nombre), con sus reglas."""
    n = n if n >= UMBRAL_NOMBRE else 0.0
    p = PESO_DIRECCION * d + PESO_NOMBRE * n
    reglas = [f"base = {PESO_DIRECCION}*D({d:.2f}) + {PESO_NOMBRE}*N({n:.2f}) = {p:.1f}"]
    if d >= 0.85 and n >= 0.75 and p < PISO_COINCIDENCIA_DOBLE:
        p = PISO_COINCIDENCIA_DOBLE
        reglas.append(f"nombre y dirección coinciden: piso {PISO_COINCIDENCIA_DOBLE}")
    if unico_en_direccion:
        p += BONO_UNICO_EN_DIRECCION
        reglas.append(f"único titular con local en esa dirección: +{BONO_UNICO_EN_DIRECCION}")
    elif mas_reciente:
        p += BONO_MAS_RECIENTE
        reglas.append(f"habilitación más reciente de esa dirección: +{BONO_MAS_RECIENTE}")
    if rubro_coincide and d >= 0.5:
        p += BONO_RUBRO
        reglas.append(f"el rubro del domicilio coincide con la consulta: +{BONO_RUBRO}")
    if nombre_unico and d < 0.5:
        p += BONO_NOMBRE_UNICO
        reglas.append(f"único CUIT con ese nombre en las bases: +{BONO_NOMBRE_UNICO}")
    return min(100.0, p), reglas


# --------------------------------------------------------------------------
# Dirección
# --------------------------------------------------------------------------

def factor_localidad(q: Direccion, provincia: str, localidad: str) -> float:
    """Cuánto confiar en una coincidencia de calle según la jurisdicción."""
    ql = " ".join(t for t in q.localidad.split() if t not in ("ARGENTINA", "REPUBLICA", "PROVINCIA"))
    ql = ql.replace("BS AS", "BUENOS AIRES").replace("BSAS", "BUENOS AIRES")
    if not ql:
        return 0.9                      # la consulta no dice dónde
    if q.es_caba:
        return 1.0 if provincia == CABA else 0.35
    relleno = f" {ql} "
    mencionadas = provincias_mencionadas(ql)
    if provincia == CABA:
        # "Buenos Aires" a secas, o "<barrio porteño>, Buenos Aires", pueden ser CABA.
        ambigua = mencionadas == {"BUENOS AIRES"} and (ql == "BUENOS AIRES" or menciona_barrio_caba(ql))
        return 0.9 if ambigua else 0.35
    if localidad and f" {localidad} " in relleno:
        return 1.0
    if provincia and provincia in mencionadas:
        return 0.7 if localidad and ql != provincia else 0.9
    if mencionadas:
        return 0.35                     # la consulta nombra otra provincia
    return 0.6


def evaluar_domicilio(q: Direccion, calle_clave: str, altura, provincia: str,
                      localidad: str, tipo: str) -> tuple[float, str, bool]:
    """Devuelve (D, regla, exacta) para un domicilio de la base frente a la consulta."""
    f_loc = factor_localidad(q, provincia or "", localidad or "")
    s = similitud_calle(q.calle_clave, calle_clave or "") if q.calle_clave else 0.0
    peso = PESO_TIPO.get(tipo, 0.85)
    if s >= UMBRAL_CALLE:
        if q.altura and altura:
            delta = abs(q.altura - altura)
            if delta == 0:
                return s * f_loc * peso, "calle y altura exactas", True
            if delta <= RANGO_ALTURA:
                return (s * FACTOR_ALTURA_CERCANA * f_loc * peso,
                        f"misma calle, altura cercana (a {delta} números)", False)
        if f_loc >= 0.7:
            return s * FACTOR_OTRA_ALTURA * f_loc * peso, "misma calle, otra altura", False
        return 0.0, "", False
    if f_loc == 1.0 and q.localidad:
        return D_SOLO_LOCALIDAD, "misma localidad, otra calle", False
    return 0.0, "", False


def _claves_parecidas(con, q: Direccion) -> list[str]:
    filas = con.execute(
        "SELECT DISTINCT calle_clave FROM domicilio WHERE altura BETWEEN ? AND ?",
        (q.altura - RANGO_ALTURA, q.altura + RANGO_ALTURA),
    ).fetchall()
    toks = q.tokens_calle
    largo = len(q.calle_clave)
    salida = []
    for (clave,) in filas:
        # Prefiltro barato antes de la comparación difusa.
        if not (toks & set(clave.split())) and not (
            clave[:1] == q.calle_clave[:1] and abs(len(clave) - largo) <= 2
        ):
            continue
        if similitud_calle(q.calle_clave, clave) >= UMBRAL_CALLE:
            salida.append(clave)
    return salida


# Palabras de la consulta que describen un rubro y pueden aparecer en el rubro
# de una habilitación o en la actividad declarada de una sociedad.
PALABRAS_DE_RUBRO = {
    "BAR", "CAFE", "CAFETERIA", "RESTAURANT", "RESTAURANTE", "PIZZERIA", "PARRILLA",
    "HELADERIA", "PANADERIA", "CONFITERIA", "KIOSCO", "FARMACIA", "SUPERMERCADO",
    "CARNICERIA", "VERDULERIA", "FERRETERIA", "LIBRERIA", "HOTEL", "GIMNASIO",
    "PELUQUERIA", "LAVADERO", "GARAGE", "CERVECERIA", "ROTISERIA", "OPTICA",
    "VETERINARIA", "HOSPITAL", "CLINICA", "SANATORIO", "TEATRO", "CINE",
}
# Raíces que se buscan en el texto del rubro para cada palabra de la consulta.
_RUBRO_EQUIVALE = {
    "PIZZERIA": ("PIZZ", "COMIDAS", "FAST FOOD"),
    "PARRILLA": ("PARRILLA", "RESTAURANT", "COMIDAS"),
    "RESTAURANT": ("RESTAURANT", "COMIDAS"), "RESTAURANTE": ("RESTAURANT", "COMIDAS"),
    "BAR": (" BAR", "BEBIDAS", "GASTRONOMIA"), "CAFE": ("CAFE", " BAR", "GASTRONOMIA"),
    "CAFETERIA": ("CAFE", " BAR"), "KIOSCO": ("KIOSCO", "GOLOSINAS"),
    "HOTEL": ("HOTEL", "ALOJAMIENTO"),
    "HOSPITAL": ("HOSPITAL", "SALUD", "SANATORIO", "INTERNACION"),
    "CLINICA": ("CLINICA", "SALUD", "INTERNACION"),
    "SANATORIO": ("SANATORIO", "SALUD", "INTERNACION"),
    "HELADERIA": ("HELAD",), "PANADERIA": ("PANAD",), "CERVECERIA": ("CERVEC", "BEBIDAS"),
    "GARAGE": ("GARAGE", "ESTACIONAMIENTO"),
}


def _rubro_coincide(palabras: list[str], rubro) -> bool:
    if not palabras or not rubro:
        return False
    texto = f" {normalizar_texto(rubro)} "
    return any(raiz in texto for p in palabras for raiz in _RUBRO_EQUIVALE.get(p, (p[:6],)))


def _domicilios_en_direccion(con, q: Direccion) -> list[sqlite3.Row]:
    if not (q.altura and q.calle_clave):
        return []
    claves = _claves_parecidas(con, q)[:200]
    if not claves:
        return []
    marcas = ",".join("?" * len(claves))
    return con.execute(
        f"SELECT * FROM domicilio WHERE altura BETWEEN ? AND ? AND calle_clave IN ({marcas})",
        (q.altura - RANGO_ALTURA, q.altura + RANGO_ALTURA, *claves),
    ).fetchall()


# --------------------------------------------------------------------------
# Nombre
# --------------------------------------------------------------------------

def _candidatos_por_nombre(con, q_norm: str) -> dict[int, tuple[float, sqlite3.Row]]:
    """CUIT -> (similitud, fila de `nombre`) para los mejores parecidos."""
    toks = tokens_nombre(q_norm)
    distintivos = [t for t in toks if t not in PALABRAS_GENERICAS] or toks
    if not distintivos:
        return {}
    sql = ("SELECT n.* FROM nombre_fts f JOIN nombre n ON n.id = f.rowid "
           "WHERE nombre_fts MATCH ? ORDER BY rank LIMIT 400")
    filas = con.execute(sql, (" ".join(f'"{t}"' for t in distintivos),)).fetchall()
    if len(distintivos) > 1 and len(filas) < 30:
        filas += con.execute(sql, (" OR ".join(f'"{t}"' for t in distintivos),)).fetchall()
    mejores: dict[int, tuple[float, sqlite3.Row]] = {}
    for f in filas:
        truncado = f["fuente"] == "arca" and len(f["nombre"]) >= 29
        s = similitud_nombre(q_norm, f["norm"], truncado)
        if s >= UMBRAL_NOMBRE and s > mejores.get(f["cuit"], (0, None))[0]:
            mejores[f["cuit"]] = (s, f)
    top = sorted(mejores.items(), key=lambda kv: -kv[1][0])[:60]
    return dict(top)


def _razon_social(con, cuit: int) -> str:
    filas = con.execute(
        "SELECT nombre, fuente FROM nombre WHERE cuit = ? AND clase = 'razon_social'", (cuit,)
    ).fetchall()
    if not filas:
        return ""
    return min(filas, key=lambda f: ORDEN_FUENTE_RAZON.get(f["fuente"], 9))["nombre"]


# --------------------------------------------------------------------------
# Alias confirmados por el usuario (alias.csv)
# --------------------------------------------------------------------------

CAMPOS_ALIAS = ["fantasia", "cuit", "direccion", "nota", "fecha"]


def leer_alias(ruta=None) -> list[dict]:
    ruta = ruta or db.RUTA_ALIAS
    try:
        with open(ruta, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def agregar_alias(fantasia: str, cuit: str, direccion: str = "", nota: str = "", ruta=None) -> None:
    if not es_valido(cuit):
        raise ValueError(f"CUIT inválido (dígito verificador): {cuit}")
    ruta = ruta or db.RUTA_ALIAS
    filas = leer_alias(ruta)
    filas.append({"fantasia": fantasia, "cuit": limpiar(cuit), "direccion": direccion,
                  "nota": nota, "fecha": date.today().isoformat()})
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_ALIAS)
        w.writeheader()
        w.writerows(filas)


def _alias_que_aplican(q_norm: str, q_dir: Direccion, alias: list[dict]) -> list[dict]:
    salida = []
    for a in alias:
        if similitud_nombre(q_norm, normalizar_nombre(a.get("fantasia"))) < 0.9:
            continue
        if a.get("direccion") and q_dir.calle_clave:
            ad = parsear_direccion(a["direccion"])
            if similitud_calle(q_dir.calle_clave, ad.calle_clave) < UMBRAL_CALLE or (
                q_dir.altura and ad.altura and abs(q_dir.altura - ad.altura) > RANGO_ALTURA
            ):
                continue  # mismo nombre pero otro local (otra sucursal u homónimo)
        salida.append(a)
    return salida


# --------------------------------------------------------------------------
# Búsqueda
# --------------------------------------------------------------------------

def _texto_dom(f) -> str:
    partes = [f"{f['calle']} {f['altura'] or 's/n'}"]
    if f["localidad"] or f["provincia"]:
        partes.append(", ".join(x for x in (f["localidad"], f["provincia"]) if x))
    extra = [x for x in (f["rubro"], f["fecha"], f["ref"]) if x]
    if f["fantasia"]:
        extra.insert(0, f"bandera {f['fantasia']}")
    return f"{' - '.join(partes)} [{f['tipo']}]" + (f" ({'; '.join(extra)})" if extra else "")


def buscar(con, nombre: str, direccion: str = "", max_resultados: int = 10,
           incluir_descartados: bool = False, alias: list[dict] | None = None) -> list[Candidato]:
    q_norm = normalizar_nombre(nombre)
    q_dir = parsear_direccion(direccion)
    cands: dict[object, Candidato] = {}
    mejor_dom: dict[object, tuple[float, list]] = {}   # clave -> (D, [(D, fila, regla)])

    def cand(clave, cuit) -> Candidato:
        if clave not in cands:
            cands[clave] = Candidato(cuit=cuit)
        return cands[clave]

    def anotar_dom(clave, cuit, d, fila, regla, exacta, prefijo=""):
        c = cand(clave, cuit)
        mejor_dom.setdefault(clave, []).append((d, fila, prefijo + regla))
        if d > c.sim_direccion:
            c.sim_direccion = d
        if exacta and fila["tipo"] in ("local", "sucursal"):
            c._exacta_local = True
            c._fecha = max(c._fecha, fila["fecha"] or "")
        for texto in (fila["titular"], fila["fantasia"]):
            if texto and q_norm:
                c.sim_nombre = max(c.sim_nombre, similitud_nombre(q_norm, normalizar_nombre(texto)))
        if not c.razon_social and fila["titular"]:
            c.razon_social = fila["titular"]

    # --- 1. Candidatos por dirección -------------------------------------
    for f in _domicilios_en_direccion(con, q_dir):
        d, regla, exacta = evaluar_domicilio(q_dir, f["calle_clave"], f["altura"],
                                             f["provincia"], f["localidad"], f["tipo"])
        if d <= 0:
            continue
        if f["cuit"] is not None:
            anotar_dom(f["cuit"], f["cuit"], d, f, regla, exacta)
            continue
        # Habilitación sin CUIT: se resuelve por razón social exacta.
        norm = normalizar_nombre(f["titular"])
        posibles = [r[0] for r in con.execute(
            "SELECT DISTINCT cuit FROM nombre WHERE norm = ? LIMIT 6", (norm,))]
        if len(posibles) == 1:
            anotar_dom(posibles[0], posibles[0], d * FACTOR_RESUELTO_POR_NOMBRE, f, regla, exacta,
                       "titular sin CUIT en la fuente, resuelto por razón social exacta (única); ")
        elif 1 < len(posibles) <= 5:
            for p in posibles:
                anotar_dom(p, p, d * FACTOR_HOMONIMOS, f, regla, False,
                           f"titular sin CUIT en la fuente; {len(posibles)} CUIT con esa razón social; ")
        else:
            anotar_dom(("sin_cuit", norm), None, d, f, regla, exacta,
                       "titular habilitado sin CUIT identificable; ")

    # --- 2. Candidatos por nombre ----------------------------------------
    por_nombre = _candidatos_por_nombre(con, q_norm) if q_norm else {}
    casi_exactos = sum(1 for s, _ in por_nombre.values() if s >= 0.95)
    for cuit, (s, fila) in por_nombre.items():
        c = cand(cuit, cuit)
        c.sim_nombre = max(c.sim_nombre, s)
        clase = "nombre de fantasía/bandera" if fila["clase"] == "fantasia" else "razón social"
        c.evidencias.append(Evidencia(fila["fuente"], f"{clase} parecida (similitud {s:.2f})", fila["nombre"]))
        if cuit not in mejor_dom and (q_dir.calle_clave or q_dir.localidad):
            for f in con.execute("SELECT * FROM domicilio WHERE cuit = ? LIMIT 60", (cuit,)):
                d, regla, exacta = evaluar_domicilio(q_dir, f["calle_clave"], f["altura"],
                                                     f["provincia"], f["localidad"], f["tipo"])
                if d > 0:
                    anotar_dom(cuit, cuit, d, f, regla, exacta)

    # --- 2b. Cadenas con bandera -----------------------------------------
    # El nombre buscado puede repartirse entre la bandera del comercio y la de
    # la sucursal. Solo se aplica si hay una bandera en la dirección encontrada.
    if q_norm:
        for clave, doms in mejor_dom.items():
            banderas = [normalizar_nombre(f["fantasia"]) for _, f, _ in doms if f["fantasia"]]
            c = cands[clave]
            if not banderas or c.cuit is None or c.sim_nombre >= 0.9:
                continue
            otros = [r[0] for r in con.execute(
                "SELECT norm FROM nombre WHERE cuit = ? LIMIT 20", (c.cuit,))]
            cob = FACTOR_NOMBRE_REPARTIDO * cobertura_consulta(q_norm, banderas + otros)
            if cob > c.sim_nombre:
                c.sim_nombre = cob
                c.evidencias.append(Evidencia(
                    doms[0][1]["fuente"], f"nombre repartido entre razón social y banderas (similitud {cob:.2f})",
                    ", ".join(sorted(set(banderas + otros)))))

    # --- 3. Puntaje -------------------------------------------------------
    palabras_rubro = [t for t in q_norm.split() if t in PALABRAS_DE_RUBRO]
    con_local = [c for c in cands.values() if c._exacta_local]
    fecha_max = max((c._fecha for c in con_local), default="")
    for clave, c in cands.items():
        unico = c._exacta_local and len(con_local) == 1
        reciente = c._exacta_local and len(con_local) > 1 and c._fecha and c._fecha == fecha_max \
            and sum(1 for x in con_local if x._fecha == fecha_max) == 1
        nombre_unico = c.sim_nombre >= 0.95 and casi_exactos == 1 and clave in por_nombre
        doms = sorted(mejor_dom.get(clave, []), key=lambda x: (-x[0], x[1]["fecha"] or ""))
        rubro_ok = any(_rubro_coincide(palabras_rubro, f["rubro"]) for d, f, _ in doms if d >= 0.5)
        c.puntaje, reglas = puntuar(c.sim_direccion, c.sim_nombre, unico, nombre_unico, reciente, rubro_ok)
        for d, f, regla in doms[:3]:
            c.evidencias.insert(0, Evidencia(f["fuente"], f"{regla} (D={d:.2f})", _texto_dom(f)))
        c.evidencias.append(Evidencia("método", "cálculo del puntaje", "; ".join(reglas)))

    # --- 4. Alias confirmados --------------------------------------------
    for a in _alias_que_aplican(q_norm, q_dir, leer_alias() if alias is None else alias):
        cuit = int(limpiar(a["cuit"]))
        c = cand(cuit, cuit)
        c._alias = True
        c.puntaje = max(c.puntaje, PUNTAJE_ALIAS)
        c.evidencias.insert(0, Evidencia(
            "alias.csv", f"alias confirmado por el usuario: puntaje {PUNTAJE_ALIAS}",
            f"{a['fantasia']} -> {formatear(cuit)}" + (f" ({a['nota']})" if a.get("nota") else "")))

    # --- 5. Orden y presentación -----------------------------------------
    resultado = sorted(cands.values(), key=lambda c: (-c.puntaje, -(c.sim_direccion + c.sim_nombre)))
    if not incluir_descartados:
        resultado = [c for c in resultado if c.puntaje >= NIVEL_BAJA]
    resultado = resultado[:max_resultados]
    for c in resultado:
        c.nivel = nivel_de(c.puntaje)
        if c.cuit:
            oficial = _razon_social(con, c.cuit)
            c.razon_social = oficial or c.razon_social
        else:
            c.nivel = "SIN CUIT"
    return resultado

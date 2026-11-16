"""Normalización de nombres y direcciones argentinas, y medidas de similitud.

Todo es determinístico: mismas entradas, mismas salidas. Las listas de
palabras están a la vista para poder ajustarlas.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# --------------------------------------------------------------------------
# Texto base
# --------------------------------------------------------------------------


def normalizar_texto(texto) -> str:
    """Mayúsculas, sin acentos ni signos, espacios colapsados. Ñ se conserva como N."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto).upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return t.strip()


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------

# Sufijos societarios ya "pegados" (S.A. -> SA). Se quitan del final o del
# principio del nombre, nunca del medio.
SUFIJOS_SOCIETARIOS = {
    "SA", "SRL", "SAS", "SAU", "SCA", "SCS", "SH", "SC", "SE", "SAC", "SACI",
    "SAIC", "SACIF", "SAICF", "SACIFI", "SACIFIA", "SAICFA", "SACIA", "SAIYC",
    "SACEI", "SACIFYA", "SAFI", "SAA", "SAI", "SAF", "SAE", "SAT", "SAG",
    "SACIFIYA", "SCC", "SGR", "SAPEM", "LTDA", "LTD", "SDH", "SCI", "UTE",
    "LIMITADA",
}
_FRASES_SOCIETARIAS = [
    "SOCIEDAD DE RESPONSABILIDAD LIMITADA",
    "SOCIEDAD POR ACCIONES SIMPLIFICADA",
    "SOCIEDAD ANONIMA SIMPLIFICADA",
    "SOCIEDAD ANONIMA UNIPERSONAL",
    "SOCIEDAD EN COMANDITA POR ACCIONES",
    "SOCIEDAD EN COMANDITA SIMPLE",
    "SOCIEDAD ANONIMA",
    "SOCIEDAD DE HECHO",
    "SOCIEDAD COLECTIVA",
    "SOCIEDAD SIMPLE",
    "SOCIEDAD CIVIL",
    "SOC DE HECHO",
    "EN FORMACION",
    "EN LIQUIDACION",
]
_RE_FRASES = re.compile(r"\b(?:" + "|".join(_FRASES_SOCIETARIAS) + r")\b")

_RE_SIGLA_PARTIDA = re.compile(r"\b(?:S RL|SR L)\b")

PALABRAS_VACIAS = {
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "E", "EN", "A", "AL", "CON",
    "POR", "PARA", "THE", "AND", "OF",
}

# Palabras de rubro: aparecen en miles de nombres, así que pesan poco.
PALABRAS_GENERICAS = {
    "BAR", "CAFE", "CAFETERIA", "RESTAURANT", "RESTAURANTE", "RESTO", "PIZZERIA",
    "PARRILLA", "HELADERIA", "PANADERIA", "CONFITERIA", "KIOSCO", "MAXIKIOSCO",
    "FARMACIA", "SUPERMERCADO", "AUTOSERVICIO", "ALMACEN", "CARNICERIA",
    "VERDULERIA", "FERRETERIA", "LIBRERIA", "HOTEL", "HOSTEL", "GIMNASIO",
    "PELUQUERIA", "LAVADERO", "GARAGE", "ESTACIONAMIENTO", "CERVECERIA",
    "ROTISERIA", "COMIDAS", "CASA", "TIENDA", "LOCAL", "COMERCIAL", "SERVICIOS",
    "COMPANIA", "CIA", "EMPRESA", "GRUPO", "ARGENTINA", "HNOS", "HERMANOS",
    "HIJOS", "ESTACION", "SERVICIO", "DISTRIBUIDORA", "INDUSTRIAS",
    "ESTABLECIMIENTO", "CENTRO", "INSTITUTO", "CLINICA", "OPTICA", "VETERINARIA",
    "GRAN", "NUEVO", "NUEVA", "SUPER", "SUPERMERCADOS", "HIPERMERCADO", "DIARIO",
}
PESO_GENERICA = 0.3


def _pegar_iniciales(tokens: list[str]) -> list[tuple[str, bool]]:
    """Une corridas de letras sueltas: S A -> SA, S R L -> SRL.

    Devuelve (token, pegado) para saber cuáles vinieron de siglas.
    """
    salida: list[tuple[str, bool]] = []
    corrida: list[str] = []
    for tok in tokens + [""]:
        if len(tok) == 1 and tok.isalpha():
            corrida.append(tok)
            continue
        if corrida:
            if len(corrida) == 1:
                salida.append((corrida[0], False))
            else:
                salida.append(("".join(corrida), True))
            corrida = []
        if tok:
            salida.append((tok, False))
    return salida


def _es_sufijo(token: str, pegado: bool) -> bool:
    if token in SUFIJOS_SOCIETARIOS:
        return True
    # Siglas del tipo S.A.C.I.F.I.A. en cualquier combinación.
    return pegado and re.fullmatch(r"S[AC][ACEFGIMY]{0,7}", token) is not None


def normalizar_nombre(nombre) -> str:
    """Nombre comparable: sin acentos, sin tipo societario (S.A., SRL, ...)."""
    t = _RE_FRASES.sub(" ", normalizar_texto(nombre))
    t = _RE_SIGLA_PARTIDA.sub("SRL", t)     # "S RL", "SR L"
    pares = _pegar_iniciales(t.split())
    while len(pares) > 1 and _es_sufijo(*pares[-1]):
        pares.pop()
    while len(pares) > 1 and pares[0][1] and _es_sufijo(*pares[0]):
        pares.pop(0)
    return " ".join(tok for tok, _ in pares)


def tokens_nombre(nombre_norm: str) -> list[str]:
    """Tokens significativos (sin palabras vacías). Si no queda nada, todos."""
    todos = nombre_norm.split()
    utiles = [t for t in todos if t not in PALABRAS_VACIAS]
    return utiles or todos


def _peso(token: str) -> float:
    return PESO_GENERICA if token in PALABRAS_GENERICAS else 1.0


def _parecido_token(a: str, b: str, truncado: bool = False) -> float:
    if a == b:
        return 1.0
    if len(a) < 4 or len(b) < 4:
        return 0.0
    if truncado and (a.startswith(b) or b.startswith(a)):
        return 0.9
    r = SequenceMatcher(None, a, b).ratio()
    return r if r >= 0.84 else 0.0


def similitud_nombre(consulta_norm: str, candidato_norm: str, truncado: bool = False) -> float:
    """Similitud 0..1 entre dos nombres ya normalizados.

    Es el máximo de dos medidas:
    - cobertura de tokens: qué parte (ponderada) de la consulta aparece en el
      candidato, castigada si al candidato le sobran palabras;
    - parecido de cadena completa (difflib), que tolera errores de tipeo.
    `truncado` acepta prefijos (el padrón de ARCA corta en 30 caracteres).
    """
    if not consulta_norm or not candidato_norm:
        return 0.0
    if consulta_norm == candidato_norm:
        return 1.0
    tq, tc = tokens_nombre(consulta_norm), tokens_nombre(candidato_norm)
    peso_q = sum(_peso(t) for t in tq)
    peso_c = sum(_peso(t) for t in tc)
    hallado_q = 0.0
    usados: set[int] = set()
    for t in tq:
        mejor, idx = 0.0, -1
        for i, c in enumerate(tc):
            if i in usados:
                continue
            p = _parecido_token(t, c, truncado)
            if p > mejor:
                mejor, idx = p, i
        if idx >= 0:
            usados.add(idx)
            hallado_q += _peso(t) * mejor
    cob_q = hallado_q / peso_q if peso_q else 0.0
    hallado_c = sum(_peso(tc[i]) for i in usados)
    cob_c = hallado_c / peso_c if peso_c else 0.0
    por_tokens = cob_q * (0.6 + 0.4 * cob_c)
    # Si lo único que coincide son palabras de rubro ("BAR"), no alcanza.
    if all(tc[i] in PALABRAS_GENERICAS for i in usados):
        por_tokens *= 0.4
    # El candidato empieza con la consulta completa ("SANCOR" -> "SANCOR COOPERATIVAS
    # UNIDAS"): suele ser la entidad principal y no una derivada ("FUNDACION SANCOR").
    if cob_q >= 0.99 and len(tc) > len(tq) and tc[:len(tq)] == tq:
        por_tokens = max(por_tokens, 0.85)
    # La cadena completa solo sirve para errores de tipeo: bajo 0.88 no cuenta
    # ("GALERIAS PACIFICO" y "CAFETERIA PACIFICO" se parecen como cadenas, no como nombres).
    por_cadena = SequenceMatcher(None, consulta_norm, candidato_norm).ratio()
    if por_cadena < 0.88:
        por_cadena = 0.0
    return round(min(1.0, max(por_tokens, por_cadena)), 4)


def cobertura_consulta(consulta_norm: str, nombres_norm: list[str]) -> float:
    """Parte (ponderada) de la consulta que aparece en ALGUNO de los nombres.

    Sirve para cadenas: "CARREFOUR EXPRESS" se reparte entre la bandera del
    comercio ("HIPERMERCADO CARREFOUR") y la de la sucursal ("EXPRESS").
    """
    tq = tokens_nombre(consulta_norm)
    union = {t for n in nombres_norm for t in tokens_nombre(n)}
    peso = sum(_peso(t) for t in tq)
    if not peso or not union:
        return 0.0
    hallado = sum(_peso(t) * max(_parecido_token(t, u) for u in union) for t in tq)
    return round(hallado / peso, 4)


# --------------------------------------------------------------------------
# Direcciones
# --------------------------------------------------------------------------

ABREVIATURAS_CALLE = {
    "AV": "AVENIDA", "AVDA": "AVENIDA", "AVE": "AVENIDA", "BV": "BOULEVARD",
    "BVD": "BOULEVARD", "BLVD": "BOULEVARD", "BOULEVAR": "BOULEVARD",
    "PJE": "PASAJE", "PSJE": "PASAJE", "DIAG": "DIAGONAL",
    "GRAL": "GENERAL", "GAL": "GENERAL", "TTE": "TENIENTE", "CNEL": "CORONEL",
    "CORL": "CORONEL", "CMTE": "COMANDANTE", "CTE": "COMANDANTE",
    "CAP": "CAPITAN", "SGTO": "SARGENTO", "ALTE": "ALMIRANTE",
    "ALMTE": "ALMIRANTE", "BRIG": "BRIGADIER", "DR": "DOCTOR", "DRA": "DOCTORA",
    "ING": "INGENIERO", "PTE": "PRESIDENTE", "PRES": "PRESIDENTE",
    "INT": "INTENDENTE", "GDOR": "GOBERNADOR", "GOB": "GOBERNADOR",
    "PROF": "PROFESOR", "MTRO": "MAESTRO", "PBRO": "PRESBITERO",
    "MONS": "MONSENOR", "OB": "OBISPO", "CGO": "CANONIGO", "FRAY": "FRAY",
    "STA": "SANTA", "STO": "SANTO", "SGO": "SANTIAGO", "FCO": "FRANCISCO",
    "HNO": "HERMANO", "CDRO": "COMODORO", "SUBTE": "SUBTENIENTE",
    "MCAL": "MARISCAL", "VTE": "VICENTE",
}
# Tipo de vía y títulos: no distinguen una calle de otra, se descartan de la clave.
TIPOS_Y_TITULOS = {
    "AVENIDA", "CALLE", "PASAJE", "BOULEVARD", "DIAGONAL", "CAMINO",
    "GENERAL", "TENIENTE", "CORONEL", "COMANDANTE", "CAPITAN", "SARGENTO",
    "ALMIRANTE", "BRIGADIER", "DOCTOR", "DOCTORA", "INGENIERO", "PRESIDENTE",
    "INTENDENTE", "GOBERNADOR", "PROFESOR", "MAESTRO", "PRESBITERO",
    "MONSENOR", "OBISPO", "CANONIGO", "FRAY", "COMODORO", "SUBTENIENTE",
    "MARISCAL", "PADRE", "DON", "SENADOR", "DIPUTADO",
}
_MARCAS_UNIDAD = {
    "PISO", "DTO", "DPTO", "DEPTO", "DEPARTAMENTO", "LOCAL", "LOC", "OF",
    "OFICINA", "UF", "PB", "TORRE", "ESQ", "ESQUINA", "ENTRE", "KM", "MANZANA",
    "MZA", "LOTE", "CP", "TEL", "PLANTA",
}
_MARCAS_NUMERO = {"N", "NRO", "NUM", "NUMERO", "NO", "AL"}

_SINONIMOS_CABA = [
    "CIUDAD AUTONOMA DE BUENOS AIRES", "CIUDAD AUTONOMA BUENOS AIRES",
    "CIUDAD DE BUENOS AIRES", "CAPITAL FEDERAL", "CABA", "C A B A", "CAP FED",
]
BARRIOS_CABA = {
    "AGRONOMIA", "ALMAGRO", "BALVANERA", "BARRACAS", "BELGRANO", "BOEDO",
    "CABALLITO", "CHACARITA", "COGHLAN", "COLEGIALES", "CONSTITUCION",
    "FLORES", "FLORESTA", "LA BOCA", "LA PATERNAL", "LINIERS", "MATADEROS",
    "MONTE CASTRO", "MONSERRAT", "NUEVA POMPEYA", "NUNEZ", "PALERMO",
    "PARQUE AVELLANEDA", "PARQUE CHACABUCO", "PARQUE CHAS", "PARQUE PATRICIOS",
    "PUERTO MADERO", "RECOLETA", "RETIRO", "SAAVEDRA", "SAN CRISTOBAL",
    "SAN NICOLAS", "SAN TELMO", "VELEZ SARSFIELD", "VERSALLES",
    "VILLA CRESPO", "VILLA DEL PARQUE", "VILLA DEVOTO", "VILLA GENERAL MITRE",
    "VILLA LUGANO", "VILLA LURO", "VILLA ORTUZAR", "VILLA PUEYRREDON",
    "VILLA REAL", "VILLA RIACHUELO", "VILLA SANTA RITA", "VILLA SOLDATI",
    "VILLA URQUIZA", "BARRIO NORTE", "ONCE", "ABASTO", "MICROCENTRO",
    "PALERMO SOHO", "PALERMO HOLLYWOOD", "CONGRESO", "TRIBUNALES",
}
CABA = "CABA"


@dataclass
class Direccion:
    original: str = ""
    calle: str = ""            # texto de la calle normalizado (con abreviaturas expandidas)
    calle_clave: str = ""      # tokens distintivos ordenados: "JUAN PERON"
    altura: int | None = None
    localidad: str = ""        # resto normalizado (barrio, ciudad, provincia)
    es_caba: bool = False
    tokens_calle: frozenset = field(default_factory=frozenset)


def clave_calle(calle) -> str:
    """Clave canónica de una calle, independiente del orden y de los títulos.

    "PERON, JUAN TTE.GRAL." y "Tte. Gral. Juan D. Perón" -> "JUAN PERON".
    """
    toks = []
    for t in normalizar_texto(calle).split():
        t = ABREVIATURAS_CALLE.get(t, t)
        if t in TIPOS_Y_TITULOS or t in PALABRAS_VACIAS:
            continue
        if len(t) == 1 and t.isalpha():
            continue  # iniciales
        toks.append(t)
    if not toks:  # "AVENIDA GENERAL PAZ" no puede quedar vacía
        toks = [ABREVIATURAS_CALLE.get(t, t) for t in normalizar_texto(calle).split()]
    return " ".join(sorted(set(toks)))


PROVINCIAS = {
    "BUENOS AIRES", "CATAMARCA", "CHACO", "CHUBUT", "CORDOBA", "CORRIENTES",
    "ENTRE RIOS", "FORMOSA", "JUJUY", "LA PAMPA", "LA RIOJA", "MENDOZA", "MISIONES",
    "NEUQUEN", "RIO NEGRO", "SALTA", "SAN JUAN", "SAN LUIS", "SANTA CRUZ", "SANTA FE",
    "SANTIAGO DEL ESTERO", "TIERRA DEL FUEGO", "TUCUMAN",
}


def menciona_barrio_caba(texto_norm: str) -> bool:
    relleno = f" {texto_norm} "
    return any(f" {b} " in relleno for b in BARRIOS_CABA)


def provincias_mencionadas(texto_norm: str) -> set[str]:
    relleno = f" {texto_norm} "
    return {p for p in PROVINCIAS if f" {p} " in relleno}


def detectar_caba(texto_norm: str) -> bool:
    """True si el texto dice CABA sin ambigüedad.

    "Palermo" o "Capital Federal" sí; "San Nicolás, Buenos Aires" no: San
    Nicolás es un barrio porteño y también una ciudad de la provincia.
    """
    if not texto_norm:
        return False
    relleno = f" {texto_norm} "
    if any(f" {s} " in relleno for s in _SINONIMOS_CABA):
        return True
    return (menciona_barrio_caba(texto_norm) and not provincias_mencionadas(texto_norm)
            and "PROVINCIA" not in relleno)


def parsear_direccion(texto) -> Direccion:
    """Separa calle, altura y localidad de una dirección escrita libremente.

    Reglas para ubicar la altura (en orden):
    1. el número que sigue a N°, Nro o "al";
    2. el primer número que no es parte del nombre de la calle: no está
       seguido de "DE" (9 de Julio, 25 de Mayo) ni de otro número (Calle 7 1234).
    Lo que queda a la derecha es piso/depto (se descarta) y localidad.
    """
    d = Direccion(original=str(texto or ""))
    crudo = re.sub(r"[°ºª]", " ", str(texto or ""))
    toks = normalizar_texto(crudo).split()
    if not toks:
        return d

    def es_num(t: str) -> bool:
        return t.isdigit() and len(t) <= 6

    i_alt = None
    for i in range(1, len(toks) - 1):
        if toks[i] in _MARCAS_NUMERO and es_num(toks[i + 1]) and toks[i] != "AL":
            i_alt = i + 1
            break
    if i_alt is None:
        for i in range(1, len(toks)):
            if not es_num(toks[i]):
                continue
            sig = toks[i + 1] if i + 1 < len(toks) else ""
            if sig == "DE":
                continue
            j = i + 1
            while j < len(toks) and toks[j] in _MARCAS_NUMERO:
                j += 1
            if j < len(toks) and es_num(toks[j]) and toks[i - 1] not in _MARCAS_UNIDAD:
                continue
            if toks[i - 1] in _MARCAS_UNIDAD:
                continue
            i_alt = i
            break

    if i_alt is None:
        parte_calle, resto = toks, []
    else:
        d.altura = int(toks[i_alt])
        parte_calle, resto = toks[:i_alt], toks[i_alt + 1:]
        while parte_calle and parte_calle[-1] in _MARCAS_NUMERO:
            parte_calle.pop()

    # Del resto se quita piso/depto/local y su valor.
    limpio, saltar = [], False
    for t in resto:
        if saltar:
            saltar = False
            if es_num(t) or len(t) <= 2:
                continue
        if t in _MARCAS_UNIDAD:
            saltar = True
            continue
        limpio.append(t)
    d.calle = " ".join(ABREVIATURAS_CALLE.get(t, t) for t in parte_calle)
    d.calle_clave = clave_calle(d.calle)
    d.tokens_calle = frozenset(d.calle_clave.split())
    d.localidad = " ".join(limpio)
    d.es_caba = detectar_caba(d.localidad)
    return d


def similitud_calle(clave_a: str, clave_b: str) -> float:
    """Similitud 0..1 entre dos claves de calle.

    1.0 claves iguales; 0.9 si una contiene a la otra ("PERON" vs "JUAN PERON");
    si no, parecido de cadena (tolera "CORIENTES"), descartado bajo 0.8.
    """
    if not clave_a or not clave_b:
        return 0.0
    if clave_a == clave_b:
        return 1.0
    a, b = set(clave_a.split()), set(clave_b.split())
    if a <= b or b <= a:
        chico = a if len(a) <= len(b) else b
        # Un único token numérico o muy corto no alcanza ("7" vs "7 MAYO").
        if all(t.isdigit() or len(t) < 3 for t in chico):
            return 0.0
        return 0.9
    comunes = a & b
    if comunes and len(comunes) >= max(len(a), len(b)) - 1 and any(len(t) > 3 for t in comunes):
        return 0.8
    r = SequenceMatcher(None, clave_a, clave_b).ratio()
    return round(r, 4) if r >= 0.85 else 0.0


def normalizar_provincia(provincia, localidad="") -> str:
    """Unifica la provincia; cualquier forma de Capital Federal -> "CABA"."""
    p = normalizar_texto(provincia)
    l = normalizar_texto(localidad)
    if detectar_caba(p) or p in ("CAPITAL", "CIUDAD AUTONOMA") or l in ("CAPITAL FEDERAL", "CABA", "CIUDAD AUTONOMA BUENOS AIRES"):
        return CABA
    return p

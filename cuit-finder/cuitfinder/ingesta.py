"""Carga de los archivos crudos (data/raw) en la base SQLite.

Cada función `cargar_*` lee una fuente y devuelve cuántas filas aportó. La
base se arma en un archivo temporal y recién al final reemplaza a la anterior.
"""
from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import db
from .cuit import es_valido, limpiar
from .fuentes import FUENTES, metadatos
from .normalizar import (
    CABA, clave_calle, normalizar_nombre, normalizar_provincia, normalizar_texto,
    parsear_direccion,
)

csv.field_size_limit(10**8)
LOTE = 50_000

SQL_NOMBRE = "INSERT INTO nombre(cuit, nombre, norm, clase, fuente) VALUES (?,?,?,?,?)"
SQL_DOM = (
    "INSERT INTO domicilio(fuente, cuit, titular, fantasia, tipo, calle, calle_clave, altura,"
    " localidad, provincia, rubro, fecha, ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


class Cargador:
    """Acumula filas y las inserta por lotes."""

    def __init__(self, con):
        self.con = con
        self.nombres: list[tuple] = []
        self.doms: list[tuple] = []
        self.n_nombres = 0
        self.n_doms = 0

    def nombre(self, cuit: int, nombre: str, clase: str, fuente: str) -> None:
        nombre = " ".join(str(nombre).split())
        norm = normalizar_nombre(nombre)
        if not norm:
            return
        self.nombres.append((cuit, nombre, norm, clase, fuente))
        if len(self.nombres) >= LOTE:
            self.volcar()

    def domicilio(self, fuente, cuit, titular, fantasia, tipo, calle, altura,
                  localidad, provincia, rubro="", fecha="", ref="") -> None:
        clave = clave_calle(calle)
        if not clave:
            return
        self.doms.append((fuente, cuit, titular, fantasia or None, tipo, calle, clave, altura,
                          normalizar_texto(localidad), provincia, rubro or None, fecha or None,
                          ref or None))
        if len(self.doms) >= LOTE:
            self.volcar()

    def volcar(self) -> None:
        if self.nombres:
            self.con.executemany(SQL_NOMBRE, self.nombres)
            self.n_nombres += len(self.nombres)
            self.nombres.clear()
        if self.doms:
            self.con.executemany(SQL_DOM, self.doms)
            self.n_doms += len(self.doms)
            self.doms.clear()


def _leer_texto(ruta: Path) -> str:
    datos = ruta.read_bytes()
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("cp1252", errors="replace")


def _cuit_valido(valor) -> int | None:
    c = limpiar(valor)
    return int(c) if es_valido(c) else None


def _fecha_iso(valor: str) -> str:
    valor = (valor or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", valor)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", valor)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def _fecha_mas_nueva(fechas_http: list[str]) -> str:
    """De varias fechas Last-Modified, la más reciente en formato AAAA-MM-DD."""
    from email.utils import parsedate_to_datetime
    validas = []
    for f in fechas_http:
        try:
            validas.append(parsedate_to_datetime(f))
        except (TypeError, ValueError):
            pass
    return max(validas).date().isoformat() if validas else ""


def _altura(valor) -> int | None:
    v = limpiar(valor)
    return int(v) if v and 0 < int(v) < 1_000_000 else None


# --------------------------------------------------------------------------
# ARCA: padrón de ancho fijo. CUIT(11) + denominación(30) + condiciones.
# --------------------------------------------------------------------------

def cargar_arca(c: Cargador, carpeta: Path) -> str:
    zips = sorted(carpeta.glob("*.zip"))
    if not zips:
        return "sin archivo"
    malos = 0
    with zipfile.ZipFile(zips[-1]) as z:
        with z.open(z.infolist()[0]) as f:
            for linea in io.TextIOWrapper(f, encoding="latin-1"):
                cuit = _cuit_valido(linea[:11])
                if cuit is None:
                    malos += 1
                    continue
                c.nombre(cuit, linea[11:41], "razon_social", "arca")
    return f"{malos} líneas con CUIT inválido descartadas; denominación truncada a 30 caracteres"


# --------------------------------------------------------------------------
# Registro Nacional de Sociedades: una fila por (sociedad, actividad).
# --------------------------------------------------------------------------

def cargar_rns(c: Cargador, carpeta: Path) -> str:
    zips = sorted(carpeta.glob("*.zip"))
    if not zips:
        return "sin archivo"
    vistos: set[int] = set()
    rubros: dict[int, str] = {}
    pendientes: dict[int, list[tuple]] = {}
    with zipfile.ZipFile(zips[-1]) as z:
        interno = [i for i in z.infolist() if i.filename.lower().endswith(".csv")][0]
        with z.open(interno) as f:
            texto = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace", newline="")
            for r in csv.DictReader(texto):
                cuit = _cuit_valido(r["cuit"])
                if cuit is None:
                    continue
                if r.get("actividad_orden") == "1" and r.get("actividad_descripcion"):
                    rubros[cuit] = r["actividad_descripcion"][:120]
                if cuit in vistos:
                    continue
                vistos.add(cuit)
                c.nombre(cuit, r["razon_social"], "razon_social", "rns")
                doms, claves = [], set()
                for tipo in ("fiscal", "legal"):
                    calle = (r.get(f"dom_{tipo}_calle") or "").strip()
                    if not calle:
                        continue
                    altura = _altura(r.get(f"dom_{tipo}_numero"))
                    k = (clave_calle(calle), altura)
                    if k in claves:      # legal igual al fiscal: una sola fila
                        continue
                    claves.add(k)
                    loc = r.get(f"dom_{tipo}_localidad") or ""
                    prov = normalizar_provincia(r.get(f"dom_{tipo}_provincia"), loc)
                    doms.append((tipo, calle, altura, loc, prov, r.get("fecha_hora_actualizacion", "")[:10]))
                pendientes[cuit] = [(r["razon_social"],) + d for d in doms]
    # El rubro principal puede venir en una fila posterior: se escribe al final.
    for cuit, filas in pendientes.items():
        for (razon, tipo, calle, altura, loc, prov, fecha) in filas:
            c.domicilio("rns", cuit, razon, None, tipo, calle, altura, loc, prov,
                        rubros.get(cuit, ""), fecha, "")
    return f"{len(vistos)} sociedades"


# --------------------------------------------------------------------------
# GCBA habilitaciones. Tres formatos según el año.
# --------------------------------------------------------------------------

_RE_DOM = re.compile(r"^[^;]*[A-Za-zÁ-ú][^;]*\s\d{1,5}(\s*;[^;]*\s\d{1,5})*\s*$")


def _gcba_filas_con_cuit(ruta: Path):
    """Genera (calles, titulares, cuits, fecha, rubro, expediente)."""
    lector = csv.reader(io.StringIO(_leer_texto(ruta)), delimiter=";")
    cab = [h.strip().lower().replace("_", "") for h in next(lector)]
    roto = any(h.startswith("unnamed") for h in cab)   # el CSV 2021 está desalineado
    pos = {h: i for i, h in enumerate(cab)}
    i_exp = pos.get("numeroexp", pos.get("numeroexpediente"))
    for fila in lector:
        if not roto:
            if len(fila) < len(cab):
                continue
            yield (fila[pos["calles"]], fila[pos["titulares"]], fila[pos["cuits"]],
                   fila[pos["fechahabilitacion"]], fila[pos["descripcionrubro"]],
                   fila[i_exp] if i_exp is not None else "")
            continue
        # Formato roto: se ubica la celda de CUIT y se retrocede hasta el domicilio.
        i_cuit = next((i for i in range(len(fila) - 1, 8, -1)
                       if fila[i] and all(es_valido(x) for x in fila[i].split(";"))), None)
        if i_cuit is None:
            continue
        j = i_cuit - 1
        while j > i_cuit - 4 and j > 9 and not _RE_DOM.match(fila[j]):
            j -= 1
        if not _RE_DOM.match(fila[j]):
            continue
        yield (fila[j], ",".join(fila[j + 1:i_cuit]), fila[i_cuit],
               fila[5] if len(fila) > 5 else "", fila[9] if len(fila) > 9 else "",
               fila[7] if len(fila) > 7 else "")


def cargar_gcba(c: Cargador, carpeta: Path) -> str:
    archivos = sorted(carpeta.glob("*.csv"))
    acumulados = [a for a in archivos if re.search(r"aprobadas202[5-9]\.csv$", a.name)]
    con_cuit = [a for a in archivos if a not in acumulados]
    notas = []

    # (cuit, calle) -> [titular, rubros, fecha, expediente]
    agregados: dict[tuple, list] = {}
    invalidos = total = 0
    for ruta in con_cuit:
        for calles, titulares, cuits, fecha, rubro, exp in _gcba_filas_con_cuit(ruta):
            total += 1
            lista_c = [x.strip() for x in cuits.split(";") if x.strip()]
            lista_t = [x.strip() for x in titulares.split(";")]
            for i, crudo in enumerate(lista_c):
                cuit = _cuit_valido(crudo)
                if cuit is None:
                    invalidos += 1
                    continue
                titular = lista_t[i] if len(lista_t) == len(lista_c) else titulares.strip()
                for calle in calles.split(";"):
                    calle = " ".join(calle.split())
                    if not calle:
                        continue
                    ag = agregados.setdefault((cuit, calle), [titular, [], "", ""])
                    rubro = " ".join(rubro.split())
                    if rubro and rubro not in ag[1] and len(ag[1]) < 3:
                        ag[1].append(rubro)
                    f = _fecha_iso(fecha)
                    if f >= ag[2]:
                        ag[2], ag[3] = f, " ".join(exp.split())
    nombres_vistos = set()
    for (cuit, calle), (titular, rubros, fecha, exp) in agregados.items():
        d = parsear_direccion(calle)
        c.domicilio("gcba_hab", cuit, titular, None, "local", d.calle or calle, d.altura,
                    "", CABA, " / ".join(rubros), fecha, exp)
        if (cuit, titular) not in nombres_vistos:
            nombres_vistos.add((cuit, titular))
            c.nombre(cuit, titular, "razon_social", "gcba_hab")
    notas.append(f"{total} filas con CUIT de {len(con_cuit)} archivos, {invalidos} CUIT inválidos descartados")

    # Padrón acumulado 2025+: razón social y domicilio, SIN CUIT. No se guarda
    # el teléfono ni los comentarios.
    if acumulados:
        texto = _leer_texto(acumulados[-1])
        delim = ";" if texto[:200].count(";") > texto[:200].count(",") else ","
        sin: dict[tuple, list] = {}
        for r in csv.DictReader(io.StringIO(texto), delimiter=delim):
            titular = " ".join((r.get("razon_social") or "").split())
            calle = " ".join((r.get("domicilio") or "").split())
            if not titular or not calle:
                continue
            ag = sin.setdefault((titular.upper(), calle), [titular, [], ""])
            rubro = " ".join((r.get("rubro") or "").split())
            if rubro and rubro not in ag[1] and len(ag[1]) < 3:
                ag[1].append(rubro)
            ag[2] = ag[2] or (r.get("disposicion") or "").strip()
        for (_, calle), (titular, rubros, disp) in sin.items():
            d = parsear_direccion(calle)
            m = re.search(r"-(20\d{2})-", disp)
            c.domicilio("gcba_hab_sin_cuit", None, titular, None, "local", d.calle or calle,
                        d.altura, "", CABA, " / ".join(rubros), m.group(1) if m else "", disp)
        notas.append(f"{len(sin)} habilitaciones sin CUIT de {acumulados[-1].name}")
    return "; ".join(notas)


# --------------------------------------------------------------------------
# Energía: estaciones de servicio (una fila por producto y horario).
# --------------------------------------------------------------------------

def cargar_energia(c: Cargador, carpeta: Path) -> str:
    archivos = sorted(carpeta.glob("*.csv"))
    if not archivos:
        return "sin archivo"
    vistas: set[str] = set()
    nombres: set[tuple] = set()
    for r in csv.DictReader(io.StringIO(_leer_texto(archivos[-1]))):
        if r["idempresa"] in vistas:
            continue
        vistas.add(r["idempresa"])
        cuit = _cuit_valido(r["cuit"])
        if cuit is None:
            continue
        d = parsear_direccion(r["direccion"])
        c.domicilio("energia", cuit, r["empresa"], r.get("empresabandera"), "local",
                    d.calle or r["direccion"], d.altura, r["localidad"],
                    normalizar_provincia(r["provincia"], r["localidad"]),
                    "ESTACION DE SERVICIO", (r.get("fecha_vigencia") or "")[:10], r["idempresa"])
        if (cuit, r["empresa"]) not in nombres:
            nombres.add((cuit, r["empresa"]))
            c.nombre(cuit, r["empresa"], "razon_social", "energia")
    return f"{len(vistas)} estaciones"


# --------------------------------------------------------------------------
# SEPA: zip de zips; de cada comercio se leen comercio.csv y sucursales.csv.
# --------------------------------------------------------------------------

_PROV_ISO = {
    "C": CABA, "B": "BUENOS AIRES", "K": "CATAMARCA", "H": "CHACO", "U": "CHUBUT",
    "X": "CORDOBA", "W": "CORRIENTES", "E": "ENTRE RIOS", "P": "FORMOSA", "Y": "JUJUY",
    "L": "LA PAMPA", "F": "LA RIOJA", "M": "MENDOZA", "N": "MISIONES", "Q": "NEUQUEN",
    "R": "RIO NEGRO", "A": "SALTA", "J": "SAN JUAN", "D": "SAN LUIS", "Z": "SANTA CRUZ",
    "S": "SANTA FE", "G": "SANTIAGO DEL ESTERO", "V": "TIERRA DEL FUEGO", "T": "TUCUMAN",
}


def _csv_sepa(z: zipfile.ZipFile, nombre: str):
    try:
        datos = z.read(nombre)
    except KeyError:
        return []
    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = datos.decode("cp1252", errors="replace")
    # Los archivos terminan con una línea "Última actualización: ..." que se ignora.
    return [r for r in csv.DictReader(io.StringIO(texto), delimiter="|") if r.get("id_bandera")]


def cargar_sepa(c: Cargador, carpeta: Path) -> str:
    zips = sorted(carpeta.glob("*.zip"))
    if not zips:
        return "sin archivo"
    comercios = sucursales = 0
    nombres: set[tuple] = set()
    with zipfile.ZipFile(zips[-1]) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".zip") or info.file_size == 0:
                continue
            try:
                zi = zipfile.ZipFile(io.BytesIO(z.read(info)))
            except zipfile.BadZipFile:
                continue
            banderas = {}
            for r in _csv_sepa(zi, "comercio.csv"):
                cuit = _cuit_valido(r.get("comercio_cuit"))
                if cuit is None:
                    continue
                razon = r.get("comercio_razon_social", "")
                bandera = r.get("comercio_bandera_nombre", "")
                banderas[(r["id_comercio"], r["id_bandera"])] = (cuit, razon, bandera)
                for nombre, clase in ((razon, "razon_social"), (bandera, "fantasia")):
                    if nombre and (cuit, nombre) not in nombres:
                        nombres.add((cuit, nombre))
                        c.nombre(cuit, nombre, clase, "sepa")
                comercios += 1
            for r in _csv_sepa(zi, "sucursales.csv"):
                dato = banderas.get((r["id_comercio"], r["id_bandera"]))
                if not dato:
                    continue
                cuit, razon, bandera = dato
                prov = _PROV_ISO.get((r.get("sucursales_provincia") or "")[-1:].upper(), "")
                calle, altura = r.get("sucursales_calle", ""), _altura(r.get("sucursales_numero"))
                if altura is None:   # algunas cadenas ponen "AV SAN MARTIN 5688" todo en la calle
                    d = parsear_direccion(calle)
                    calle, altura = d.calle or calle, d.altura
                c.domicilio("sepa", cuit, razon, bandera, "sucursal", calle,
                            altura, r.get("sucursales_localidad", ""),
                            prov, (r.get("sucursales_tipo") or "").upper(), "",
                            f"{r['id_comercio']}-{r['id_bandera']}-{r.get('id_sucursal', '')}")
                sucursales += 1
    return f"{comercios} banderas, {sucursales} sucursales"


CARGADORES = {
    "gcba": cargar_gcba, "energia": cargar_energia, "sepa": cargar_sepa,
    "rns": cargar_rns, "arca": cargar_arca,
}


def construir(ids: list[str] | None = None) -> Path:
    """Arma la base completa desde data/raw. Devuelve la ruta final."""
    db.DIR_DATOS.mkdir(parents=True, exist_ok=True)
    temporal = db.RUTA_DB.with_suffix(".db.nuevo")
    if temporal.exists():
        temporal.unlink()
    con = db.crear(temporal)
    for fid in ids or list(CARGADORES):
        carpeta = db.DIR_CRUDOS / fid
        if not carpeta.exists():
            print(f"[{fid}] sin datos crudos, se omite (corré 'descargar')")
            continue
        t0 = time.time()
        print(f"[{fid}] cargando ...", flush=True)
        c = Cargador(con)
        notas = CARGADORES[fid](c, carpeta)
        c.volcar()
        meta = metadatos(fid)
        f = FUENTES[fid]
        con.execute(
            "INSERT INTO fuente VALUES (?,?,?,?,?,?,?,?)",
            (fid, f.descripcion, f.pagina, f.licencia,
             _fecha_mas_nueva([m.get("fecha_servidor", "") for m in meta.values()]),
             datetime.now().isoformat(timespec="seconds"), c.n_nombres + c.n_doms, notas),
        )
        con.commit()
        print(f"[{fid}] {c.n_nombres} nombres, {c.n_doms} domicilios en {time.time() - t0:.0f}s. {notas}")
    print("creando índices y búsqueda de texto ...", flush=True)
    t0 = time.time()
    con.executescript(db.INDICES)
    con.execute("ANALYZE")
    con.commit()
    con.close()
    temporal.replace(db.RUTA_DB)
    print(f"listo en {time.time() - t0:.0f}s: {db.RUTA_DB} ({db.RUTA_DB.stat().st_size / 1e6:.0f} MB)")
    return db.RUTA_DB

"""Construye la base SQLite unica (padron ARCA + Registro Nacional de Sociedades).

La base es local y privada: no se versiona ni se publica.
"""
import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .texto import norm, partir_direccion, provincia_canonica, solo_digitos

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fuentes(
  id TEXT PRIMARY KEY, organismo TEXT, url TEXT, archivo TEXT, sha256 TEXT,
  fecha_consulta TEXT, filas INTEGER);
CREATE TABLE IF NOT EXISTS contribuyentes(
  cuit TEXT PRIMARY KEY, denominacion TEXT NOT NULL, ganancias TEXT, iva TEXT,
  monotributo TEXT, integrante_soc TEXT, empleador TEXT, act_monotributo TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sociedades(
  cuit TEXT PRIMARY KEY, razon_social TEXT NOT NULL, tipo TEXT, fecha_contrato TEXT,
  fecha_actualizacion TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS domicilios(
  cuit TEXT NOT NULL, tipo TEXT NOT NULL, provincia TEXT, localidad TEXT, calle TEXT,
  numero TEXT, piso TEXT, depto TEXT, cp TEXT, estado TEXT, fuente TEXT NOT NULL,
  nombre_local TEXT, referencia TEXT,
  PRIMARY KEY(cuit, tipo, fuente, calle, numero)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS domicilios_numero ON domicilios(numero, provincia);
CREATE TABLE IF NOT EXISTS actividades(
  cuit TEXT NOT NULL, codigo TEXT NOT NULL, descripcion TEXT, fuente TEXT NOT NULL,
  PRIMARY KEY(cuit, codigo)) WITHOUT ROWID;
CREATE VIRTUAL TABLE IF NOT EXISTS nombres USING fts5(
  nombre, cuit UNINDEXED, fuente UNINDEXED, tokenize="unicode61 remove_diacritics 2");
"""


def conectar(ruta, solo_lectura=False):
    if solo_lectura:
        return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    db = sqlite3.connect(ruta)
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + ESQUEMA)
    return db


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while bloque := f.read(1 << 20):
            h.update(bloque)
    return h.hexdigest()


def registrar_fuente(db, ident, organismo, url, ruta, filas):
    db.execute("INSERT OR REPLACE INTO fuentes VALUES (?,?,?,?,?,?,?)",
               (ident, organismo, url, Path(ruta).name, sha256(ruta),
                datetime.now(timezone.utc).isoformat(timespec="seconds"), filas))
    db.commit()


def _miembros(ruta, sufijos=None):
    with zipfile.ZipFile(ruta) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            if sufijos and not info.filename.lower().endswith(sufijos):
                continue
            with z.open(info) as f:
                yield f


def linea_padron(linea):
    """Ancho fijo ARCA: CUIT(11) denominacion(30) ganancias(2) IVA(2) monotributo(2)
    integrante de sociedad(1) empleador(1) actividad monotributo(2)."""
    linea = linea.rstrip(b"\r\n")
    if len(linea) < 41 or not linea[:11].isdigit():
        return None
    nombre = linea[11:41].decode("latin-1").strip()
    if not nombre:
        return None
    cola = linea[41:51].decode("latin-1").ljust(10)
    return (linea[:11].decode(), nombre, cola[0:2].strip(), cola[2:4].strip(), cola[4:6].strip(),
            cola[6:7].strip(), cola[7:8].strip(), cola[8:10].strip())


def importar_padron(db, ruta_zip, url=""):
    db.execute("DELETE FROM contribuyentes")
    db.execute("DELETE FROM nombres WHERE fuente='arca_padron'")
    total = 0
    for f in _miembros(ruta_zip):
        lote = []
        for linea in f:
            fila = linea_padron(linea)
            if fila:
                lote.append(fila)
            if len(lote) >= 50000:
                total += _volcar_padron(db, lote)
        total += _volcar_padron(db, lote)
    if total < 100000 and url:
        raise ValueError(f"Padron sospechosamente chico: {total} filas")
    registrar_fuente(db, "arca_padron", "ARCA", url, ruta_zip, total)
    return total


def _volcar_padron(db, lote):
    db.executemany("INSERT OR REPLACE INTO contribuyentes VALUES (?,?,?,?,?,?,?,?)", lote)
    db.executemany("INSERT INTO nombres(nombre, cuit, fuente) VALUES (?,?,'arca_padron')",
                   [(f[1], f[0]) for f in lote])
    n = len(lote)
    lote.clear()
    return n


def _domicilio(fila, prefijo):
    calle = norm(fila.get(prefijo + "calle"))
    numero = solo_digitos(fila.get(prefijo + "numero")).lstrip("0")
    if not numero and calle:  # a veces la altura viene dentro de la calle
        calle, numero = partir_direccion(calle)
    return (provincia_canonica(fila.get(prefijo + "provincia")), norm(fila.get(prefijo + "localidad")),
            calle, numero, norm(fila.get(prefijo + "piso")), norm(fila.get(prefijo + "departamento")),
            solo_digitos(fila.get(prefijo + "cp")), norm(fila.get(prefijo + "estado_domicilio")))


def importar_sociedades(db, ruta, url=""):
    """Acepta el ZIP oficial o un CSV suelto. Una fila por actividad: se deduplica por CUIT."""
    for tabla in ("sociedades", "actividades"):
        db.execute(f"DELETE FROM {tabla}")
    db.execute("DELETE FROM domicilios WHERE fuente='rns'")
    db.execute("DELETE FROM nombres WHERE fuente='rns'")
    vistos, filas = set(), 0
    flujos = _miembros(ruta, (".csv",)) if zipfile.is_zipfile(ruta) else [open(ruta, "rb")]
    for binario in flujos:
        lector = csv.DictReader(io.TextIOWrapper(binario, encoding="utf-8-sig", newline=""))
        if not {"cuit", "razon_social"} <= set(lector.fieldnames or []):
            raise ValueError("El archivo de sociedades no trae cuit y razon_social")
        soc, dom, act, nom = [], [], [], []
        for fila in lector:
            filas += 1
            cuit = solo_digitos(fila["cuit"])
            nombre = (fila["razon_social"] or "").strip()
            if len(cuit) != 11 or not nombre:
                continue
            if fila.get("actividad_codigo"):
                act.append((cuit, fila["actividad_codigo"].strip(),
                            (fila.get("actividad_descripcion") or "").strip(), "rns"))
            if cuit not in vistos:
                vistos.add(cuit)
                soc.append((cuit, nombre, fila.get("tipo_societario", ""),
                            fila.get("fecha_hora_contrato_social", ""),
                            fila.get("fecha_hora_actualizacion", "")))
                nom.append((nombre, cuit))
                for tipo, prefijo in (("fiscal", "dom_fiscal_"), ("legal", "dom_legal_")):
                    d = _domicilio(fila, prefijo)
                    if d[2]:
                        dom.append((cuit, tipo, *d, "rns", None, None))
            if len(act) >= 50000:
                _volcar_sociedades(db, soc, dom, act, nom)
        _volcar_sociedades(db, soc, dom, act, nom)
    registrar_fuente(db, "rns", "Registro Nacional de Sociedades (Min. Justicia)", url, ruta, filas)
    return len(vistos)


def _volcar_sociedades(db, soc, dom, act, nom):
    db.executemany("INSERT OR REPLACE INTO sociedades VALUES (?,?,?,?,?)", soc)
    db.executemany("INSERT OR IGNORE INTO domicilios VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", dom)
    db.executemany("INSERT OR IGNORE INTO actividades VALUES (?,?,?,?)", act)
    db.executemany("INSERT INTO nombres(nombre, cuit, fuente) VALUES (?,?,'rns')", nom)
    for lista in (soc, dom, act, nom):
        lista.clear()


ALIAS_LOCALES = {
    "cuit": ("cuit", "cuit_titular", "cuit_contribuyente", "nro_cuit"),
    "titular": ("razon_social", "titular", "denominacion", "nombre_titular"),
    "nombre_local": ("nombre_comercial", "nombre_fantasia", "fantasia", "establecimiento", "comercio"),
    "direccion": ("domicilio", "direccion", "domicilio_comercial", "ubicacion"),
    "calle": ("calle", "calle_nombre"), "numero": ("numero", "altura", "calle_altura"),
    "localidad": ("localidad", "barrio", "ciudad", "municipio", "partido"),
    "provincia": ("provincia", "jurisdiccion"),
    "referencia": ("expediente", "numero_expediente", "resolucion", "referencia", "url"),
}


def importar_locales(db, ruta_csv, fuente, organismo, provincia="", localidad="", url=""):
    """Padrones de habilitaciones o locales (municipios, GCBA, etc.) en CSV con CUIT.

    Las filas sin CUIT valido se descartan: sin CUIT no hay vinculo que guardar.
    """
    db.execute("DELETE FROM domicilios WHERE fuente=?", (fuente,))
    db.execute("DELETE FROM nombres WHERE fuente=?", (fuente,))
    filas = guardadas = 0
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        muestra = f.read(4096)
        f.seek(0)
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|") if muestra.strip() else csv.excel
        for cruda in csv.DictReader(f, dialect=dialecto):
            filas += 1
            col = {norm(k).lower().replace(" ", "_"): (v or "").strip() for k, v in cruda.items() if k}
            dato = {campo: next((col[a] for a in alias if col.get(a)), "")
                    for campo, alias in ALIAS_LOCALES.items()}
            cuit = solo_digitos(dato["cuit"])
            if len(cuit) != 11:
                continue
            calle, numero = norm(dato["calle"]), solo_digitos(dato["numero"]).lstrip("0")
            if not calle:
                calle, numero = partir_direccion(dato["direccion"])
            if not calle:
                continue
            db.execute("INSERT OR IGNORE INTO domicilios VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (cuit, "local", provincia_canonica(dato["provincia"] or provincia),
                        norm(dato["localidad"] or localidad), calle, numero, "", "", "", "",
                        fuente, dato["nombre_local"], dato["referencia"]))
            for nombre in {dato["nombre_local"], dato["titular"]} - {""}:
                db.execute("INSERT INTO nombres(nombre, cuit, fuente) VALUES (?,?,?)", (nombre, cuit, fuente))
            guardadas += 1
    registrar_fuente(db, fuente, organismo, url, ruta_csv, filas)
    return guardadas


def resumen(db):
    datos = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
             for t in ("contribuyentes", "sociedades", "domicilios", "actividades")}
    datos["fuentes"] = [dict(zip(("id", "organismo", "url", "archivo", "sha256", "fecha_consulta", "filas"), r))
                        for r in db.execute("SELECT * FROM fuentes")]
    return datos



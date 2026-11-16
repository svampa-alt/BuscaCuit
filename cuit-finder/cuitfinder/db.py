"""Esquema y conexión de la base local SQLite."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

RAIZ = Path(os.environ.get("CUITFINDER_HOME", Path(__file__).resolve().parent.parent))
DIR_DATOS = RAIZ / "data"
DIR_CRUDOS = DIR_DATOS / "raw"
RUTA_DB = DIR_DATOS / "cuitfinder.db"
RUTA_ALIAS = RAIZ / "alias.csv"

ESQUEMA = """
-- Una fila por archivo ingerido: de dónde salió cada dato y de cuándo es.
CREATE TABLE fuente (
    id            TEXT PRIMARY KEY,   -- arca_padron, rns, gcba_hab, ...
    descripcion   TEXT,
    url           TEXT,
    licencia      TEXT,
    fecha_datos   TEXT,               -- fecha del archivo según el servidor
    fecha_ingesta TEXT,
    filas         INTEGER,
    notas         TEXT
);

-- Todos los nombres conocidos de cada CUIT.
CREATE TABLE nombre (
    id     INTEGER PRIMARY KEY,
    cuit   INTEGER NOT NULL,
    nombre TEXT NOT NULL,             -- tal como figura en la fuente
    norm   TEXT NOT NULL,             -- normalizar_nombre(nombre)
    clase  TEXT NOT NULL,             -- razon_social | fantasia
    fuente TEXT NOT NULL
);

-- Domicilios vinculados a un titular. cuit puede ser NULL (GCBA 2025+ publica
-- la razón social del habilitado pero no su CUIT).
CREATE TABLE domicilio (
    id          INTEGER PRIMARY KEY,
    fuente      TEXT NOT NULL,
    cuit        INTEGER,
    titular     TEXT,                 -- razón social / titular según la fuente
    fantasia    TEXT,                 -- bandera o nombre comercial, si existe
    tipo        TEXT NOT NULL,        -- local | sucursal | fiscal | legal
    calle       TEXT,                 -- texto original
    calle_clave TEXT,                 -- clave_calle(calle)
    altura      INTEGER,
    localidad   TEXT,
    provincia   TEXT,                 -- normalizada; Capital Federal = CABA
    rubro       TEXT,
    fecha       TEXT,
    ref         TEXT                  -- expediente, disposición o id de origen
);
"""

INDICES = """
CREATE INDEX ix_nombre_norm ON nombre(norm);
CREATE INDEX ix_nombre_cuit ON nombre(cuit);
CREATE INDEX ix_dom_altura ON domicilio(altura, calle_clave);
CREATE INDEX ix_dom_cuit ON domicilio(cuit);
CREATE VIRTUAL TABLE nombre_fts USING fts5(norm, content='nombre', content_rowid='id');
INSERT INTO nombre_fts(nombre_fts) VALUES('rebuild');
"""


def conectar(ruta: Path | str | None = None) -> sqlite3.Connection:
    ruta = Path(ruta or RUTA_DB)
    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe la base {ruta}. Construila con: python -m cuitfinder actualizar"
        )
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def crear(ruta: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(str(ruta))
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-200000;")
    con.executescript(ESQUEMA)
    return con

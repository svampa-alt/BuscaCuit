"""Descarga el padrón público ARCA y construye un SQLite consultable como artefacto privado."""
import csv
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

URLS = [
    "https://www.afip.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip",
    "https://www.arca.gob.ar/genericos/cInscripcion/archivos/apellidoNombreDenominacion.zip",
]
OUTPUT = Path("output")
# Formato de ancho fijo documentado por PyAfipWs: CUIT(11), denominación(30)
def parse(line):
    line = line.rstrip(b"\r\n")
    if len(line) < 41:
        return None
    cuit = line[:11].decode("ascii", "ignore")
    if not re.fullmatch(r"\d{11}", cuit):
        return None
    name = line[11:41].decode("latin-1", "replace").strip()
    return (cuit, name) if name else None

def main():
    OUTPUT.mkdir(exist_ok=True)
    errors = []
    archive = None
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "padron.zip"
        for url in URLS:
            try:
                req = urllib.request.Request(url, headers={"User-Agent":"BuscaCuit/0.1 (padron publico)"})
                with urllib.request.urlopen(req, timeout=120) as response, target.open("wb") as out:
                    import shutil
                    shutil.copyfileobj(response, out)
                if not zipfile.is_zipfile(target):
                    raise ValueError("La respuesta no es ZIP")
                archive = url
                break
            except Exception as e:
                errors.append(f"{url}: {e}")
        if not archive:
            raise RuntimeError("No se pudo descargar el padrón: "+"; ".join(errors))
        dbpath = OUTPUT / "padron.sqlite"
        conn = sqlite3.connect(dbpath)
        conn.execute("CREATE TABLE IF NOT EXISTS contribuyentes(cuit TEXT PRIMARY KEY, denominacion TEXT NOT NULL)")
        count = 0
        with zipfile.ZipFile(target) as z:
            members = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")]
            if not members:
                raise ValueError("ZIP sin archivos de datos")
            for member in members:
                with z.open(member) as f:
                    batch = []
                    for line in f:
                        record = parse(line)
                        if record:
                            batch.append(record)
                        if len(batch) >= 10000:
                            conn.executemany("INSERT OR REPLACE INTO contribuyentes VALUES (?,?)",batch)
                            count += len(batch)
                            batch.clear()
                    if batch:
                        conn.executemany("INSERT OR REPLACE INTO contribuyentes VALUES (?,?)",batch)
                        count += len(batch)
        conn.commit()
        distinct = conn.execute("SELECT count(*) FROM contribuyentes").fetchone()[0]
        conn.close()
        if distinct < 100000:
            raise ValueError(f"Cantidad sospechosa de registros: {distinct}; revisar formato antes de usar")
        metadata = {"fuente":archive,"fecha_utc":datetime.now(timezone.utc).isoformat(),"registros_leidos":count,"cuit_distintos":distinct,"archivo":"padron.sqlite"}
        (OUTPUT/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(metadata,ensure_ascii=False))
if __name__ == "__main__":
    main()

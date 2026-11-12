"""Descarga el padrón público ARCA y construye un SQLite consultable como artefacto privado."""
import argparse
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

def main(argv=None):
    parser = argparse.ArgumentParser(description='Importar padrón ARCA mensual, local o remoto')
    parser.add_argument('--archivo', type=Path, help='ZIP oficial descargado manualmente')
    parser.add_argument('--salida', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    args.salida.mkdir(parents=True, exist_ok=True)
    errors = []
    archive = None
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "padron.zip"
        urls = [] if args.archivo else URLS
        if args.archivo:
            if not args.archivo.is_file():
                raise FileNotFoundError(args.archivo)
            import shutil
            shutil.copyfile(args.archivo, target)
            if not zipfile.is_zipfile(target):
                raise ValueError('El archivo manual debe ser un ZIP válido')
            archive = 'ARCA:archivo-manual'
        for url in urls:
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
        dbpath = args.salida / "padron.sqlite"
        conn = sqlite3.connect(dbpath)
        conn.execute("DROP TABLE IF EXISTS contribuyentes")
        conn.execute("CREATE TABLE contribuyentes(cuit TEXT PRIMARY KEY, denominacion TEXT NOT NULL)")
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
        metadata = {"fuente":archive,"fecha_utc":datetime.now(timezone.utc).isoformat(),"registros_leidos":count,"cuit_distintos":distinct,"archivo":"padron.sqlite","modo":"manual" if args.archivo else "automatico"}
        (args.salida/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(metadata,ensure_ascii=False))
if __name__ == "__main__":
    main()

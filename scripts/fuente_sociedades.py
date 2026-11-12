"""Valida muestra o registro completo de sociedades sin publicar datos personales."""
import argparse
import csv
import hashlib
import io
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

API = "https://datos.gob.ar/api/3/action/package_show?id=justicia-registro-nacional-sociedades"
DATASET = "https://datos.gob.ar/dataset/justicia-registro-nacional-sociedades"
MAX_DOWNLOAD = 1_500_000_000
MAX_UNCOMPRESSED = 4_000_000_000
REQUIRED = {"cuit", "razon_social"}


def request_with_retry(req, read, attempts=4):
    """Reintenta errores temporales HTTP y conexiones fallidas, sin ocultar errores definitivos."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return read(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == attempts - 1:
                raise
            time.sleep(min(2 ** attempt, 8))


def get_bytes(url, max_bytes=15_000_000):
    if not url.startswith("https://"):
        raise ValueError("Se exige HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": "BuscaCuit/1.0 (investigacion datos publicos)"})
    data = request_with_retry(req, lambda response: response.read(max_bytes + 1))
    if len(data) > max_bytes:
        raise ValueError("Recurso supera el limite")
    return data


def choose_sample(resources):
    candidates = [r for r in resources if r.get("url", "").startswith("https://")
                  and r.get("format", "").lower() == "csv"
                  and "muestreo" in (r.get("name", "") + " " + r.get("description", "")).lower()]
    if len(candidates) != 1:
        raise ValueError(f"Se esperaba un unico CSV de muestreo, encontrados: {len(candidates)}")
    return candidates[0]


def choose_full(resources):
    """Selecciona la version anual mas reciente; no mezcla historicos ni asociaciones."""
    candidates = []
    for r in resources:
        name = r.get("name", "")
        label = name.lower()
        match = re.fullmatch(r"registro nacional de sociedades\s*-\s*(20\d{2})(?:\s*-\s*semestre\s*([12]))?", label.strip())
        if (match and r.get("url", "").startswith("https://")
                and r.get("format", "").lower() in ("csv", "zip")):
            year = int(match.group(1))
            semester = int(match.group(2) or 2)
            candidates.append(((year, semester), r))
    if not candidates:
        raise ValueError("No se encontro registro societario anual oficial compatible")
    latest = max(key for key, _ in candidates)
    winners = [r for key, r in candidates if key == latest]
    if len(winners) != 1:
        raise ValueError(f"Hay {len(winners)} recursos para el periodo {latest}")
    return winners[0]


def download(url, destination):
    if not url.startswith("https://"):
        raise ValueError("Se exige HTTPS")
    h = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": "BuscaCuit/1.0 (investigacion datos publicos)"})
    def transfer(response):
        nonlocal size, h
        size = 0
        h = hashlib.sha256()
        with destination.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("Descarga supera el limite")
                out.write(chunk)
                h.update(chunk)
    request_with_retry(req, transfer)
    return size, h.hexdigest()


def inspect_csv(stream):
    wrapper = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    try:
        reader = csv.DictReader(wrapper)
        columns = reader.fieldnames or []
        if not REQUIRED.issubset(set(columns)):
            raise ValueError(f"Faltan columnas obligatorias: {sorted(REQUIRED - set(columns))}")
        rows = sum(1 for row in reader if row.get("cuit") and row.get("razon_social"))
        if rows == 0:
            raise ValueError("CSV sin registros validos")
        return {"columns": columns, "rows_with_cuit_and_name": rows}
    finally:
        wrapper.detach()


def inspect_file(path, fmt):
    if fmt == "csv":
        with path.open("rb") as f:
            data = inspect_csv(f)
        return {"files": [{"name": path.name, **data}], "rows": data["rows_with_cuit_and_name"]}
    if fmt != "zip":
        raise ValueError(f"Formato no soportado: {fmt}")
    with zipfile.ZipFile(path) as archive:
        entries = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".csv")]
        if not entries or sum(i.file_size for i in entries) > MAX_UNCOMPRESSED:
            raise ValueError("ZIP sin CSV o supera limite descomprimido")
        files = []
        for entry in entries:
            with archive.open(entry) as stream:
                data = inspect_csv(stream)
            files.append({"name": entry.filename, **data})
        return {"files": files, "rows": sum(f["rows_with_cuit_and_name"] for f in files)}


def run(output, full=False):
    meta = json.loads(get_bytes(API))
    if not meta.get("success"):
        raise ValueError("API CKAN no devolvio success")
    resource = choose_full(meta["result"].get("resources", [])) if full else choose_sample(meta["result"].get("resources", []))
    fmt = resource.get("format", "").lower()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ("recurso." + fmt)
        size, digest = download(resource["url"], path)
        result = inspect_file(path, fmt)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "dataset": DATASET, "api": API, "mode": "full" if full else "sample",
        "resource_url": resource["url"], "resource_id": resource.get("id"),
        "resource_name": resource.get("name"), "accessed_utc": datetime.now(timezone.utc).isoformat(),
        "format": fmt, "sha256": digest, "bytes": size, "row_count": result["rows"],
        "files": result["files"], "ownership_verified": False,
        "note": "Registros societarios no acreditan titularidad comercial; no se conserva CSV ni ZIP."
    }
    name = "registro_sociedades_completo_metadata.json" if full else "registro_sociedades_muestreo_metadata.json"
    (output / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("output/fuentes"))
    p.add_argument("--full", action="store_true")
    args = p.parse_args()
    run(args.output, full=args.full)

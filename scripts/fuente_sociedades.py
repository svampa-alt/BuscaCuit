"""Descarga controlada de una muestra oficial del Registro Nacional de Sociedades.

No deduce titularidad comercial a partir de una coincidencia societaria.
"""
import argparse
import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://datos.gob.ar/api/3/action/package_show?id=justicia-registro-nacional-sociedades"
DATASET = "https://datos.gob.ar/dataset/justicia-registro-nacional-sociedades"
MAX_BYTES = 15_000_000


def get_bytes(url, max_bytes=MAX_BYTES):
    if not url.startswith("https://"):
        raise ValueError("Se exige HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": "BuscaCuit/1.0 (investigacion datos publicos)"})
    with urllib.request.urlopen(req, timeout=35) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Recurso supera el limite de descarga")
    return data


def choose_sample(resources):
    candidates = [r for r in resources
                  if r.get("url", "").startswith("https://")
                  and r.get("format", "").lower() == "csv"
                  and "muestreo" in (r.get("name", "") + " " + r.get("description", "")).lower()]
    if len(candidates) != 1:
        raise ValueError(f"Se esperaba un unico CSV de muestreo, encontrados: {len(candidates)}")
    return candidates[0]


def run(output):
    meta = json.loads(get_bytes(API))
    if not meta.get("success"):
        raise ValueError("API CKAN no devolvio success")
    resource = choose_sample(meta["result"].get("resources", []))
    url = resource["url"]
    data = get_bytes(url)
    decoded = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ValueError("CSV sin encabezados")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV sin filas")
    output.mkdir(parents=True, exist_ok=True)
    # No persistir ni publicar el CSV con registros de terceros: solo metadatos y esquema.
    report = {
        "dataset": DATASET,
        "api": API,
        "resource_url": url,
        "resource_id": resource.get("id"),
        "resource_name": resource.get("name"),
        "accessed_utc": datetime.now(timezone.utc).isoformat(),
        "format": "csv",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "row_count": len(rows),
        "columns": reader.fieldnames,
        "ownership_verified": False,
        "note": "Datos societarios: no acreditan titularidad de establecimientos comerciales."
    }
    (output / "registro_sociedades_muestreo_metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("output/fuentes"))
    args = p.parse_args()
    run(args.output)

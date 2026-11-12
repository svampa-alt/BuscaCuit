"""Cruce reproducible de sociedades con indicios comerciales; no identifica titulares."""
import argparse
import csv
import io
import json
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from fuente_sociedades import API, ALTERNATE_API, choose_full, download, get_bytes

ALIASES = {
    "cuit": ("cuit", "cuit_sociedad"),
    "name": ("razon_social", "denominacion", "nombre", "nombre_comercial"),
    "address": ("domicilio", "direccion", "domicilio_fiscal", "calle"),
    "city": ("localidad", "ciudad", "municipio"),
    "province": ("provincia", "jurisdiccion"),
    "postal": ("codigo_postal", "cp"),
}
STOP = {"SA", "SRL", "SAS", "SOCIEDAD", "ANONIMA", "RESPONSABILIDAD", "LIMITADA", "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y"}
MAX_CANDIDATES = 30


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").upper())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", value).strip()


def fields(row):
    keys = {norm(k).lower().replace(" ", "_"): v for k, v in row.items() if k}
    return {field: next((keys[alias] for alias in aliases if alias in keys), "")
            for field, aliases in ALIASES.items()}


def tokens(value):
    return {w for w in norm(value).split() if w not in STOP and len(w) > 1}


def match(record, query):
    name = tokens(record["name"])
    wanted = tokens(query.get("name", ""))
    overlap = len(name & wanted) / max(len(wanted), 1)
    exact_cuit = bool(query.get("cuit") and re.sub(r"\D", "", record["cuit"]) == re.sub(r"\D", "", query["cuit"]))
    address = bool(query.get("address") and norm(query["address"]) in norm(record["address"]))
    city = bool(query.get("city") and norm(query["city"]) == norm(record["city"]))
    province = bool(query.get("province") and norm(query["province"]) == norm(record["province"]))
    postal = bool(query.get("postal") and norm(query["postal"]) == norm(record["postal"]))
    if not (exact_cuit or overlap > 0 or address):
        return None
    score = round(100 * overlap + 70 * exact_cuit + 35 * address + 15 * city + 12 * province + 15 * postal, 2)
    return {"score": score, "signals": {"cuit_exact": exact_cuit, "name_overlap": round(overlap, 3),
            "address": address, "city": city, "province": province, "postal": postal}}


def records(path, fmt):
    if fmt == "csv":
        with path.open("rb") as stream:
            yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
    elif fmt == "zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".csv") and not name.endswith("/"):
                    with archive.open(name) as stream:
                        yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
    else:
        raise ValueError("Formato no admitido")


def rank(source, fmt, query, limit=MAX_CANDIDATES):
    if not query.get("name") and not query.get("cuit"):
        raise ValueError("Se requiere nombre o CUIT para evitar barridos indiscriminados")
    results = []
    seen = set()
    scanned = 0
    for raw in records(source, fmt):
        scanned += 1
        row = fields(raw)
        matched = match(row, query)
        if matched is None:
            continue
        key = (row["cuit"], norm(row["name"]))
        if key in seen:
            continue
        seen.add(key)
        results.append({"cuit": row["cuit"], "razon_social": row["name"],
                        "domicilio": row["address"], "localidad": row["city"],
                        "provincia": row["province"], "codigo_postal": row["postal"],
                        **matched, "estado": "CANDIDATO_NO_VERIFICADO"})
        results.sort(key=lambda r: r["score"], reverse=True)
        if len(results) > limit:
            results.pop()
    return {"scanned": scanned, "candidates": results, "ownership_verified": False,
            "warning": "Coincidencia societaria no acredita titularidad del comercio."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="")
    p.add_argument("--cuit", default="")
    p.add_argument("--address", default="")
    p.add_argument("--city", default="")
    p.add_argument("--province", default="")
    p.add_argument("--postal", default="")
    p.add_argument("--source", type=Path, help="CSV o ZIP local; si se omite, descarga fuente oficial")
    p.add_argument("--output", type=Path, default=Path("output/cruce_sociedades.json"))
    args = p.parse_args()
    query = {k: getattr(args, k) for k in ("name", "cuit", "address", "city", "province", "postal")}
    if not args.name and not args.cuit:
        p.error("Se requiere --name o --cuit")
    with tempfile.TemporaryDirectory() as tmp:
        if args.source:
            path = args.source
            fmt = path.suffix.lower().lstrip(".")
            origin = str(path)
        else:
            errors = []
            for endpoint in (API, ALTERNATE_API):
                try:
                    payload = json.loads(get_bytes(endpoint))
                    if not payload.get("success"):
                        raise ValueError("Respuesta CKAN invalida")
                    resource = choose_full(payload["result"]["resources"])
                    break
                except Exception as exc:
                    errors.append(f"{endpoint}: {exc}")
            else:
                raise RuntimeError("Catalogos oficiales inaccesibles: " + " | ".join(errors))
            fmt = resource["format"].lower()
            path = Path(tmp) / ("sociedades." + fmt)
            download(resource["url"], path)
            origin = resource["url"]
        report = rank(path, fmt, query)
        report["source"] = origin
        report["query"] = query
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"scanned": report["scanned"], "candidates": len(report["candidates"]),
                          "output": str(args.output), "ownership_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

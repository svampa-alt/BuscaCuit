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
from fuentes_evidencia import FUENTES, importar_csv

GCBA_API = "https://data.buenosaires.gob.ar/api/3/action/package_show?id=habilitaciones-aprobadas"

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
    """Ranking contextual: la jurisdiccion contradictoria penaliza, no elimina."""
    name = tokens(record["name"])
    wanted = tokens(query.get("name", ""))
    overlap = len(name & wanted) / max(len(wanted), 1)
    raw_cuit = re.sub(r"\D", "", str(query.get("cuit", "")))
    record_cuit = re.sub(r"\D", "", str(record["cuit"]))
    exact_cuit = bool(len(raw_cuit) == 11 and raw_cuit == record_cuit)
    query_address = norm(query.get("address", ""))
    record_address = norm(record["address"])
    address = bool(query_address and record_address and
                   (query_address == record_address or
                    query_address.split() == record_address.split()[:len(query_address.split())]))
    city = bool(query.get("city") and norm(query["city"]) == norm(record["city"]))
    province = bool(query.get("province") and norm(query["province"]) == norm(record["province"]))
    postal = bool(query.get("postal") and norm(query["postal"]) == norm(record["postal"]))
    # Palermo es un barrio de CABA, no una ciudad de otra jurisdiccion.
    # No otorgar puntos por coincidencia exacta, pero evitar falso conflicto.
    caba_barrios = {"PALERMO", "RECOLETA", "BELGRANO", "CABALLITO", "FLORES",
                   "ALMAGRO", "BALVANERA", "RETIRO", "SAN TELMO", "BOEDO",
                   "VILLA CRESPO", "COLEGIALES", "NUNEZ", "BARRACAS", "LA BOCA"}
    qcity = norm(query.get("city", ""))
    rcity = norm(record["city"])
    qprov = norm(query.get("province", ""))
    rprov = norm(record["province"])
    caba_alias = {"CABA", "CIUDAD AUTONOMA DE BUENOS AIRES", "CAPITAL FEDERAL"}
    same_caba_area = bool(qprov in caba_alias and rprov in caba_alias and
                          ((qcity in caba_barrios and rcity in caba_alias) or
                           (rcity in caba_barrios and qcity in caba_alias)))
    city_conflict = bool(query.get("city") and record["city"] and not city and not same_caba_area)
    province_conflict = bool(query.get("province") and record["province"] and not province)
    postal_conflict = bool(query.get("postal") and record["postal"] and not postal)
    if not (exact_cuit or overlap > 0 or address):
        return None
    score = round(100 * overlap + 70 * exact_cuit + 35 * address +
                  15 * city + 12 * province + 15 * postal -
                  30 * city_conflict - 60 * province_conflict - 25 * postal_conflict, 2)
    return {"score": score, "signals": {
        "cuit_exact": exact_cuit, "name_overlap": round(overlap, 3),
        "address": address, "city": city, "province": province, "postal": postal,
        "city_conflict": city_conflict, "province_conflict": province_conflict,
        "postal_conflict": postal_conflict}}


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



def load_evidence(paths):
    """Lee exportaciones oficiales locales; cada archivo conserva su procedencia."""
    evidence = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".csv":
            raise ValueError(f"Se requiere CSV de evidencia: {path}")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for raw in reader:
                row = fields(raw)
                if row["cuit"] or row["name"]:
                    evidence.append({"source_file": path.name, "record": row})
    return evidence


def load_catalog_evidence(specs):
    """Fuente=archivo.csv; cada evidencia conserva organismo, catalogo y fila."""
    items = []
    for spec in specs:
        if "=" not in spec:
            raise ValueError("Usar --evidence-catalog fuente=archivo.csv")
        fuente, archivo = spec.split("=", 1)
        for entry in importar_csv(Path(archivo), fuente):
            d = entry["datos"]
            items.append({"source_file": entry["archivo_origen"], "source_id": fuente,
                          "source_catalog": entry["catalogo"], "source_record_id": entry["id"],
                          "record": {"cuit": d["cuit"], "name": d["razon_social"] or d["nombre_comercial"],
                                     "address": d["domicilio"], "city": d["localidad"],
                                     "province": d["provincia"], "postal": ""}})
    return items


def cross_evidence(report, evidence):
    """Corrobora coincidencias por CUIT; coincidencias textuales no prueban titularidad."""
    for candidate in report["candidates"]:
        linked = []
        for item in evidence:
            row = item["record"]
            cuit_a = re.sub(r"\D", "", candidate["cuit"])
            cuit_b = re.sub(r"\D", "", row["cuit"])
            exact = bool(len(cuit_a) == 11 and cuit_a == cuit_b)
            textual = bool(norm(candidate["razon_social"]) and norm(candidate["razon_social"]) == norm(row["name"]))
            candidate_address = norm(candidate.get("domicilio", ""))
            source_address = norm(row["address"])
            same_address = bool(candidate_address and source_address and candidate_address == source_address)
            # El nombre aislado no identifica una sociedad: exigir CUIT o
            # nombre y domicilio simultaneamente para vincular evidencia.
            if exact or (textual and same_address):
                linked.append({"fuente": item.get("source_id", item["source_file"]),
                               "archivo": item["source_file"],
                               "catalogo": item.get("source_catalog", ""),
                               "id_evidencia": item.get("source_record_id", ""),
                               "cuit_coincide": exact,
                               "razon_social_coincide": textual,
                               "domicilio_coincide": same_address,
                               "domicilio_fuente": row["address"],
                               "estado": "COINCIDENCIA_DOCUMENTAL_NO_TITULARIDAD"})
        candidate["evidencias"] = linked
        candidate["fuentes_coincidentes"] = len({e["fuente"] for e in linked})
        candidate["score"] += 25 * sum(e["cuit_coincide"] for e in linked)
    report["candidates"].sort(key=lambda item: item["score"], reverse=True)
    report["evidence_records"] = len(evidence)
    return report


def download_gcba(destination):
    """Descarga el CSV anual mas reciente del catalogo oficial de habilitaciones."""
    catalog = json.loads(get_bytes(GCBA_API))
    if not catalog.get("success"):
        raise ValueError("Catalogo GCBA sin respuesta valida")
    resources = catalog["result"].get("resources", [])
    matches = []
    for resource in resources:
        label = norm(resource.get("name", ""))
        year = re.search(r"HABILITACIONES (20[0-9]{2})", label)
        if year and resource.get("format", "").lower() == "csv" and resource.get("url", "").startswith("https://"):
            matches.append((int(year.group(1)), resource))
    if not matches:
        raise ValueError("No hay CSV anual de habilitaciones GCBA")
    resource = max(matches, key=lambda item: item[0])[1]
    download(resource["url"], destination)
    return resource["url"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="")
    p.add_argument("--cuit", default="")
    p.add_argument("--address", default="")
    p.add_argument("--city", default="")
    p.add_argument("--province", default="")
    p.add_argument("--postal", default="")
    p.add_argument("--source", type=Path, help="CSV o ZIP local; si se omite, descarga fuente oficial")
    p.add_argument("--evidence", type=Path, action="append", default=[], help="CSV oficial externo, repetible; ej. exportaciones ARCA o GCBA")
    p.add_argument("--evidence-catalog", action="append", default=[],
                   help="Fuente registrada=archivo.csv; ej. bora_sociedades=avisos.csv")
    p.add_argument("--gcba", action="store_true", help="Descargar automaticamente habilitaciones oficiales GCBA")
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
        evidence_paths = list(args.evidence)
        if args.gcba:
            gcba_file = Path(tmp) / "gcba_habilitaciones.csv"
            gcba_url = download_gcba(gcba_file)
            evidence_paths.append(gcba_file)
            report["gcba_source"] = gcba_url
        if evidence_paths or args.evidence_catalog:
            report = cross_evidence(report, load_evidence(evidence_paths) +
                                    load_catalog_evidence(args.evidence_catalog))
        report["source"] = origin
        report["query"] = query
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"scanned": report["scanned"], "candidates": len(report["candidates"]),
                          "output": str(args.output), "ownership_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

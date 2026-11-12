"""BuscaCuit: consulta local de padrones CSV con trazabilidad."""
import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

ALIASES = {
    "cuit": ("cuit", "cuit_contribuyente", "id_persona", "id"),
    "razon_social": ("razon_social", "denominacion", "apellido_nombre", "nombre"),
    "domicilio": ("domicilio", "direccion", "domicilio_fiscal"),
    "nombre_comercial": ("nombre_comercial", "fantasia", "nombre_fantasia"),
}

def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text.lower() if not unicodedata.combining(c)))

def valid_cuit(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 11:
        return False
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    check = (11 - sum(int(x) * w for x, w in zip(digits[:10], weights)) % 11) % 11
    return check == int(digits[-1])

def pick(row, field):
    keys = {normalize(k): v for k, v in row.items() if k}
    return next((keys[normalize(alias)] for alias in ALIASES[field] if keys.get(normalize(alias))), "")

def search(paths, query, limit=30):
    needle = normalize(query)
    if len(needle) < 3:
        raise ValueError("La consulta debe contener al menos tres caracteres")
    found = []
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as file:
            sample = file.read(4096)
            file.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
            for row in csv.DictReader(file, dialect=dialect):
                data = {key: pick(row, key) for key in ALIASES}
                if not any(needle in normalize(value) for value in data.values()):
                    continue
                cuit = data["cuit"]
                data.update(fuente=str(path), cuit_valido=valid_cuit(cuit),
                            evidencia="coincidencia en padrón; titularidad comercial no confirmada")
                found.append(data)
                if len(found) >= limit:
                    return found
    return found

def main():
    parser = argparse.ArgumentParser(description="Buscar CUIT por nombre, domicilio o CUIT en CSV")
    parser.add_argument("consulta")
    parser.add_argument("archivos", nargs="+", type=Path)
    parser.add_argument("--limite", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(search(args.archivos, args.consulta, args.limite), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

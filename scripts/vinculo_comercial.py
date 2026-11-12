"""Vincula locales con CUIT únicamente cuando un documento contiene ambos datos."""
import argparse
import csv
import json
import re
from pathlib import Path
try:
    from scripts.cruce_sociedades import norm, tokens
except ModuleNotFoundError:
    from cruce_sociedades import norm, tokens

CUIT = re.compile(r"(?<!\\d)\\d{2}[- ]?\\d{8}[- ]?\\d(?!\\d)")
ALIASES = {
    "cuit": ("cuit", "cuit_titular", "cuit_contribuyente"),
    "comercio": ("nombre_comercial", "nombre_fantasia", "nombre_del_local", "establecimiento", "comercio"),
    "direccion": ("domicilio_comercial", "direccion_comercial", "direccion", "domicilio", "ubicacion"),
    "razon_social": ("razon_social", "titular", "denominacion"),
    "expediente": ("expediente", "numero_expediente", "resolucion", "documento"),
}
def extract(row):
    normalized = {norm(k).lower().replace(" ", "_"): str(v or "").strip() for k,v in row.items() if k}
    return {field: next((normalized[k] for k in keys if k in normalized), "") for field,keys in ALIASES.items()}

def analyze(rows, name, address, source):
    """Sin CUIT explícito, ningún candidato se identifica como titular."""
    matches = []
    for raw in rows:
        r = extract(raw)
        target = tokens(name)
        commercial = tokens(r["comercio"])
        name_ok = bool(target and commercial and (target <= commercial or commercial <= target))
        address_ok = bool(address and norm(address) and norm(address) == norm(r["direccion"]))
        if not (name_ok and address_ok):
            continue
        digits = re.sub(r"\\D", "", r["cuit"])
        valid_cuit = bool(CUIT.fullmatch(r["cuit"]) and len(digits) == 11)
        matches.append({
            "fuente": source, "comercio": r["comercio"], "direccion": r["direccion"],
            "razon_social_documentada": r["razon_social"],
            "cuit": digits if valid_cuit else None, "documento": r["expediente"],
            "estado": "VINCULO_DOCUMENTAL_CUIT_COMERCIO" if valid_cuit else "LOCAL_COINCIDENTE_SIN_CUIT",
            "titularidad_confirmada": False,
        })
    return {"consulta": {"nombre":name,"direccion":address}, "coincidencias":matches,
            "advertencia":"La coincidencia documental no confirma titularidad fiscal ni vigencia. Revisar documento y fecha."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--evidencia",type=Path,required=True)
    p.add_argument("--nombre",required=True)
    p.add_argument("--direccion",required=True)
    p.add_argument("--salida",type=Path,default=Path("output/vinculo_comercial.json"))
    a=p.parse_args()
    with a.evidencia.open(encoding="utf-8-sig",newline="") as f:
        result=analyze(csv.DictReader(f),a.nombre,a.direccion,a.evidencia.name)
    a.salida.parent.mkdir(parents=True,exist_ok=True)
    a.salida.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"coincidencias":len(result["coincidencias"]),"con_cuit":sum(bool(x["cuit"]) for x in result["coincidencias"])},ensure_ascii=False))

if __name__=="__main__":
    main()

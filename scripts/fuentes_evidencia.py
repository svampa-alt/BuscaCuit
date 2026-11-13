"""Registro y normalizacion reproducible de evidencias de distintas fuentes.
No afirma titularidad por coincidencias de nombres o domicilios.
"""
import argparse
import csv
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

FUENTES = {
    "sociedades": {"organismo": "Registro Nacional de Sociedades", "tipo": "registro_societario",
        "catalogo": "https://datos.gob.ar/dataset/justicia-registro-nacional-sociedades"},
    "gcba_habilitaciones": {"organismo": "GCBA / AGC", "tipo": "habilitacion",
        "catalogo": "https://data.buenosaires.gob.ar/dataset/habilitaciones-aprobadas"},
    "bora_sociedades": {"organismo": "Boletin Oficial de la Republica Argentina", "tipo": "aviso_societario",
        "catalogo": "https://www.boletinoficial.gob.ar/"},
    "arca_padron": {"organismo": "ARCA", "tipo": "padron_tributario",
        "catalogo": "https://www.arca.gob.ar/"},
}
ALIASES = {
    "cuit": ("cuit", "cuit_sociedad", "cuit_contribuyente", "nro_cuit"),
    "razon_social": ("razon_social", "denominacion", "denominacion_social", "nombre", "contribuyente"),
    "nombre_comercial": ("nombre_comercial", "nombre_fantasia", "fantasia"),
    "domicilio": ("domicilio", "direccion", "domicilio_fiscal", "domicilio_comercial"),
    "localidad": ("localidad", "ciudad", "municipio"),
    "provincia": ("provincia", "jurisdiccion"),
    "fecha": ("fecha", "fecha_publicacion", "fecha_habilitacion", "fechahabilitacion"),
    "referencia": ("referencia", "expediente", "numero_aviso", "url", "enlace"),
}

def normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", "_", texto).strip("_").lower()

def extraer(fila):
    columnas = {normalizar(k): v for k, v in fila.items() if k}
    return {campo: next((str(columnas[a]).strip() for a in alias if a in columnas and columnas[a] is not None), "")
            for campo, alias in ALIASES.items()}

def importar_csv(ruta, fuente, *, fecha_consulta=None):
    if fuente not in FUENTES:
        raise ValueError("Fuente no registrada: " + fuente)
    fecha_consulta = fecha_consulta or datetime.now(timezone.utc).date().isoformat()
    evidencias = []
    with Path(ruta).open(encoding="utf-8-sig", newline="") as archivo:
        for numero, fila in enumerate(csv.DictReader(archivo), start=2):
            datos = extraer(fila)
            cuit = re.sub(r"\\D", "", datos["cuit"])
            if cuit and len(cuit) != 11:
                cuit = ""  # No inventar ni propagar identificadores incompletos.
            if not (cuit or datos["razon_social"] or datos["nombre_comercial"]):
                continue
            datos["cuit"] = cuit
            identificador = hashlib.sha256(
                (fuente + "|" + str(numero) + "|" + json.dumps(datos, sort_keys=True, ensure_ascii=False)).encode()
            ).hexdigest()[:20]
            evidencias.append({
                "id": identificador, "fuente": fuente,
                "organismo": FUENTES[fuente]["organismo"],
                "tipo_documento": FUENTES[fuente]["tipo"],
                "catalogo": FUENTES[fuente]["catalogo"],
                "archivo_origen": Path(ruta).name, "fila_origen": numero,
                "fecha_consulta": fecha_consulta,
                "datos": datos, "titularidad_confirmada": False,
            })
    return evidencias

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuente", choices=sorted(FUENTES), required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    registros = importar_csv(args.csv, args.fuente)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({"registros": registros, "total": len(registros),
        "titularidad_confirmada": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"fuente": args.fuente, "registros": len(registros),
                      "salida": str(args.salida)}, ensure_ascii=False))

if __name__ == "__main__":
    main()

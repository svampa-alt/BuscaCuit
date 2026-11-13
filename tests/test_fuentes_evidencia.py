import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fuentes_evidencia import FUENTES, importar_csv
from cruce_sociedades import load_catalog_evidence, cross_evidence

class FuentesTests(unittest.TestCase):
    def crear_csv(self, carpeta, nombre, rows):
        ruta = Path(carpeta) / nombre
        with ruta.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return ruta

    def test_registro_incluye_cuatro_fuentes(self):
        self.assertEqual(set(FUENTES), {"sociedades", "gcba_habilitaciones", "bora_sociedades", "arca_padron"})

    def test_importacion_preserva_trazabilidad(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self.crear_csv(tmp, "avisos.csv", [{"razon_social": "El Nido SRL",
                "cuit": "30-12345678-9", "domicilio": "Costa Rica 5709", "fecha_publicacion": "2026-11-01"}])
            registros = importar_csv(ruta, "bora_sociedades", fecha_consulta="2026-11-12")
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["datos"]["cuit"], "30123456789")
            self.assertEqual(registros[0]["datos"]["fecha"], "2026-11-01")
            self.assertEqual(registros[0]["fila_origen"], 2)
            self.assertFalse(registros[0]["titularidad_confirmada"])

    def test_cuit_incompleto_no_se_propaga(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self.crear_csv(tmp, "arca.csv", [{"razon_social": "Prueba", "cuit": "123"}])
            self.assertEqual(importar_csv(ruta, "arca_padron")[0]["datos"]["cuit"], "")

    def test_cruce_multifuente_no_confirma_titularidad(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self.crear_csv(tmp, "arca.csv", [{"razon_social": "El Nido SRL",
                "cuit": "30-12345678-9", "domicilio": "Costa Rica 5709"}])
            evidencias = load_catalog_evidence(["arca_padron=" + str(ruta)])
            report = {"candidates": [{"cuit": "30123456789", "razon_social": "El Nido SRL", "score": 100}],
                      "ownership_verified": False}
            result = cross_evidence(report, evidencias)
            self.assertEqual(result["candidates"][0]["fuentes_coincidentes"], 1)
            self.assertEqual(result["candidates"][0]["evidencias"][0]["fuente"], "arca_padron")
            self.assertFalse(result["ownership_verified"])

    def test_fuente_desconocida_rechazada(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self.crear_csv(tmp, "otro.csv", [{"razon_social": "Prueba"}])
            with self.assertRaises(ValueError):
                importar_csv(ruta, "fuente_desconocida")

if __name__ == "__main__":
    unittest.main()

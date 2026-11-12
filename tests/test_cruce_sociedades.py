"""Pruebas de cruce de fuentes societarias."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cruce_sociedades import fields, match, rank


class CruceSociedadesTests(unittest.TestCase):
    def test_normaliza_encabezados(self):
        row = fields({"CUIT": "30-123", "Razón Social": "El Nido SRL", "Provincia": "CABA"})
        self.assertEqual(row["cuit"], "30-123")
        self.assertEqual(row["name"], "El Nido SRL")

    def test_proximidad_suma_sin_excluir(self):
        near = fields({"cuit": "301", "razon_social": "El Nido SRL", "localidad": "Palermo", "provincia": "CABA"})
        far = fields({"cuit": "302", "razon_social": "El Nido SRL", "localidad": "Rawson", "provincia": "Chubut"})
        query = {"name": "El Nido", "city": "Palermo", "province": "CABA"}
        self.assertGreater(match(near, query)["score"], match(far, query)["score"])
        self.assertIsNotNone(match(far, query))

    def test_sin_coincidencia_no_inventa(self):
        row = fields({"cuit": "301", "razon_social": "Otra Empresa"})
        self.assertIsNone(match(row, {"name": "El Nido"}))

    def test_lectura_real_csv_y_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registro.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["cuit", "razon_social", "localidad", "provincia"])
                writer.writeheader()
                writer.writerow({"cuit": "301", "razon_social": "El Nido SRL", "localidad": "Palermo", "provincia": "CABA"})
                writer.writerow({"cuit": "302", "razon_social": "El Nido SRL", "localidad": "Rawson", "provincia": "Chubut"})
            result = rank(path, "csv", {"name": "El Nido", "city": "Palermo", "province": "CABA"})
            self.assertEqual(result["scanned"], 2)
            self.assertEqual(len(result["candidates"]), 2)
            self.assertEqual(result["candidates"][0]["cuit"], "301")
            self.assertFalse(result["ownership_verified"])
            self.assertEqual(result["candidates"][0]["estado"], "CANDIDATO_NO_VERIFICADO")


if __name__ == "__main__":
    unittest.main()

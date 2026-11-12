import io
import unittest
from scripts.fuente_sociedades import choose_sample, choose_full, inspect_csv, get_bytes


class SociedadesTests(unittest.TestCase):
    def test_muestreo_unico(self):
        resources = [
            {"name": "Registro Nacional de Sociedades", "format": "zip", "url": "https://example.org/full.zip"},
            {"name": "Registro Nacional de Sociedades - Muestreo", "format": "CSV", "url": "https://example.org/sample.csv"},
        ]
        self.assertEqual(choose_sample(resources)["url"], "https://example.org/sample.csv")
        self.assertEqual(choose_full(resources)["url"], "https://example.org/full.zip")

    def test_no_acepta_csv_ambiguo(self):
        with self.assertRaises(ValueError):
            choose_sample([
                {"name": "Muestreo A", "format": "csv", "url": "https://example.org/a.csv"},
                {"name": "Muestreo B", "format": "csv", "url": "https://example.org/b.csv"},
            ])

    def test_no_acepta_http(self):
        with self.assertRaises(ValueError):
            get_bytes("http://example.org/sample.csv")

    def test_no_confunde_muestra_con_completo(self):
        with self.assertRaises(ValueError):
            choose_full([{"name": "Registro Sociedades Muestreo", "format": "csv",
                          "url": "https://example.org/sample.csv"}])

    def test_lee_csv_y_valida_campos(self):
        data = inspect_csv(io.BytesIO(b"cuit,razon_social\n20123456789,Empresa A\n,Sin CUIT\n"))
        self.assertEqual(data["rows_with_cuit_and_name"], 1)

    def test_rechaza_esquema_incorrecto(self):
        with self.assertRaises(ValueError):
            inspect_csv(io.BytesIO(b"nombre,provincia\nA,B\n"))


if __name__ == "__main__":
    unittest.main()

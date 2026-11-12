import unittest
from scripts.fuente_sociedades import choose_sample, get_bytes


class SociedadesTests(unittest.TestCase):
    def test_muestreo_unico(self):
        resources = [
            {"name": "Registro Nacional de Sociedades - 2026", "format": "zip", "url": "https://example.org/full.zip"},
            {"name": "Registro Nacional de Sociedades - Muestreo", "format": "CSV", "url": "https://example.org/sample.csv"},
        ]
        self.assertEqual(choose_sample(resources)["url"], "https://example.org/sample.csv")

    def test_no_acepta_csv_ambiguo(self):
        with self.assertRaises(ValueError):
            choose_sample([
                {"name": "Muestreo A", "format": "csv", "url": "https://example.org/a.csv"},
                {"name": "Muestreo B", "format": "csv", "url": "https://example.org/b.csv"},
            ])

    def test_no_acepta_http(self):
        with self.assertRaises(ValueError):
            get_bytes("http://example.org/sample.csv")


if __name__ == "__main__":
    unittest.main()

import csv
import tempfile
import unittest
from pathlib import Path
from buscacuit import normalize, search, valid_cuit

class BuscaCuitTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize("Razón Social S.A."), "razonsocialsa")

    def test_check_digit(self):
        self.assertTrue(valid_cuit("20-12345678-6"))
        self.assertFalse(valid_cuit("20-12345678-7"))

    def test_search_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "padron.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["CUIT", "Denominacion", "Domicilio"], delimiter=";")
                writer.writeheader()
                writer.writerow({"CUIT":"20123456786", "Denominacion":"Comercio Ejemplo", "Domicilio":"Calle Ficticia 123"})
            rows = search([path], "comercio")
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["cuit_valido"])
            self.assertEqual(rows[0]["fuente"], str(path))
            self.assertEqual(len(search([path], "inexistente")), 0)

if __name__ == "__main__":
    unittest.main()

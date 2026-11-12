import unittest
from scripts.descargar_padron import parse

class PadronTests(unittest.TestCase):
    def test_fixed_width(self):
        row=b"20123456786"+b"COMERCIO DE PRUEBA".ljust(30,b" ")+b"ACAC"
        self.assertEqual(parse(row),("20123456786","COMERCIO DE PRUEBA"))
    def test_invalid_rows(self):
        self.assertIsNone(parse(b"texto"))
        self.assertIsNone(parse(b"abcdefghijk"+b"NOMBRE".ljust(30,b" ")))

if __name__=="__main__":
    unittest.main()

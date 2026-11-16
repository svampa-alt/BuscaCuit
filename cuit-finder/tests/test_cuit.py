import unittest

from cuitfinder.cuit import digito_verificador, es_juridica, es_valido, formatear, limpiar


class TestCuit(unittest.TestCase):
    def test_validos_reales(self):
        # CUIT públicos de organismos y empresas conocidas.
        for c in ("30-50000012-7", "30687310434", "33-64337382-9", "30506730038", "20268445642"):
            self.assertTrue(es_valido(c), c)

    def test_digito_incorrecto(self):
        self.assertFalse(es_valido("30-50000012-8"))
        self.assertFalse(es_valido("30687310435"))

    def test_largo_incorrecto(self):
        for c in ("", "123", "3050000012", "305000001277", None):
            self.assertFalse(es_valido(c), c)

    def test_resto_diez_no_existe(self):
        # 20-00000001: la suma da resto 10, no hay dígito posible.
        base = next(f"20{n:08d}" for n in range(1, 500) if digito_verificador(f"20{n:08d}") is None)
        for d in range(10):
            self.assertFalse(es_valido(base + str(d)))

    def test_resto_once_es_cero(self):
        base = next(f"30{n:08d}" for n in range(1, 500) if digito_verificador(f"30{n:08d}") == 0)
        self.assertTrue(es_valido(base + "0"))

    def test_formato(self):
        self.assertEqual(formatear("30687310434"), "30-68731043-4")
        self.assertEqual(limpiar(" 30-68731043-4 "), "30687310434")
        self.assertTrue(es_juridica("30687310434"))
        self.assertFalse(es_juridica("20268445642"))

    def test_digito_requiere_diez(self):
        with self.assertRaises(ValueError):
            digito_verificador("123")


if __name__ == "__main__":
    unittest.main()

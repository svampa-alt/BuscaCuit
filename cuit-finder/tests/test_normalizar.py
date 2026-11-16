import unittest

from cuitfinder.normalizar import (
    clave_calle, normalizar_nombre, normalizar_provincia, normalizar_texto,
    parsear_direccion, similitud_calle, similitud_nombre,
)


class TestNombres(unittest.TestCase):
    def test_texto(self):
        self.assertEqual(normalizar_texto("  Café  Ñandú, S.A. "), "CAFE NANDU S A")
        self.assertEqual(normalizar_texto(None), "")

    def test_sufijos_societarios(self):
        casos = {
            "SEGUROS SURA S.A": "SEGUROS SURA",
            "Faramir  S R L": "FARAMIR",
            "Salud y Deportes S.R.L.": "SALUD Y DEPORTES",
            "ALCHEMY VALORES SOCIEDAD ANONIMA": "ALCHEMY VALORES",
            "La Serenísima S.A.C.I.F.I.A.": "LA SERENISIMA",
            "Pepe SAS": "PEPE",
            "S A BANCO DE ITALIA Y RIO DE LA PLATA": "BANCO DE ITALIA Y RIO DE LA PLATA",
            "Acme Sociedad de Responsabilidad Limitada": "ACME",
            "INC S.A.": "INC",
            "GRAN CAFE TORTONI S RL": "GRAN CAFE TORTONI",
            "SANCOR COOPERATIVAS UNIDAS LIMITADA": "SANCOR COOPERATIVAS UNIDAS",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(normalizar_nombre(entrada), esperado, entrada)

    def test_no_rompe_palabras(self):
        # SA / SE dentro del nombre no son sufijos.
        self.assertEqual(normalizar_nombre("SA PEREIRA Y CIA"), "SA PEREIRA Y CIA")
        self.assertEqual(normalizar_nombre("SASTRERIA SAGA"), "SASTRERIA SAGA")
        # Un nombre que es solo la sigla no queda vacío.
        self.assertEqual(normalizar_nombre("S.A."), "SA")

    def test_similitud_nombre(self):
        s = similitud_nombre
        self.assertEqual(s("EL NIDO", "EL NIDO"), 1.0)
        self.assertGreaterEqual(s("NIDO", "EL NIDO"), 0.95)          # palabras vacías no cuentan
        self.assertGreater(s("FARMACIA AZUL", "AZUL"), 0.75)          # el rubro pesa poco
        self.assertLess(s("FARMACIA AZUL", "FARMACIA ROJA"), 0.6)     # coincidir solo en el rubro no alcanza
        self.assertGreater(s("CARREFOUR", "CARREFUR"), 0.8)           # error de tipeo
        self.assertLess(s("EL NIDO", "ORLANDO BRENNAN MARIA LUZ"), 0.4)
        self.assertEqual(s("", "ALGO"), 0.0)
        # Parecerse como cadena no alcanza si las palabras distintivas difieren.
        self.assertLess(s("GALERIAS PACIFICO", "CAFETERIA PACIFICO"), 0.6)
        # La entidad cuyo nombre empieza con la consulta gana a la derivada.
        self.assertGreater(s("SANCOR", "SANCOR COOPERATIVAS UNIDAS"), s("SANCOR", "FUNDACION SANCOR"))
        self.assertGreater(s("CAFE TORTONI", "GRAN CAFE TORTONI"), 0.9)

    def test_similitud_truncada(self):
        # El padrón de ARCA corta en 30 caracteres.
        completo = "DISTRIBUIDORA METROPOLITANA DEL SUR"
        cortado = completo[:30].strip()
        self.assertGreater(similitud_nombre(completo, cortado, truncado=True), 0.85)


class TestDirecciones(unittest.TestCase):
    def test_parseo_basico(self):
        d = parsear_direccion("Costa Rica 5709, Palermo, CABA")
        self.assertEqual((d.calle_clave, d.altura, d.es_caba), ("COSTA RICA", 5709, True))
        d = parsear_direccion("Av. Corrientes 1234 piso 3 dto B, Capital Federal")
        self.assertEqual((d.calle_clave, d.altura, d.es_caba), ("CORRIENTES", 1234, True))
        self.assertNotIn("3", d.localidad.split())

    def test_calles_con_numero(self):
        self.assertEqual(parsear_direccion("Av. 9 de Julio 1200").altura, 1200)
        self.assertEqual(parsear_direccion("25 de Mayo 350, Rosario").altura, 350)
        d = parsear_direccion("Calle 7 N° 1234, La Plata")
        self.assertEqual((d.altura, d.calle_clave), (1234, "7"))
        self.assertEqual(parsear_direccion("Calle 50 1020 La Plata").altura, 1020)

    def test_formato_gcba(self):
        d = parsear_direccion("FERNANDEZ DE LA CRUZ, F., GRAL. AV. 4602")
        self.assertEqual((d.calle_clave, d.altura), ("CRUZ FERNANDEZ", 4602))
        d = parsear_direccion("ALVEAR, MARCELO T. De 1658")
        self.assertEqual((d.calle_clave, d.altura), ("ALVEAR MARCELO", 1658))

    def test_sin_altura(self):
        d = parsear_direccion("Florida y Lavalle")
        self.assertIsNone(d.altura)
        self.assertEqual(parsear_direccion("").calle_clave, "")

    def test_clave_calle_equivalencias(self):
        self.assertEqual(clave_calle("PERON, JUAN TTE.GRAL."), "JUAN PERON")
        self.assertEqual(clave_calle("Tte. Gral. Juan D. Perón"), "JUAN PERON")
        self.assertEqual(clave_calle("AV. SANTA FE"), clave_calle("Avda Sta Fe"))
        self.assertEqual(clave_calle("Av. General Paz"), "PAZ")

    def test_similitud_calle(self):
        self.assertEqual(similitud_calle("JUAN PERON", "JUAN PERON"), 1.0)
        self.assertEqual(similitud_calle("PERON", "JUAN PERON"), 0.9)       # una contiene a la otra
        self.assertGreater(similitud_calle("CORIENTES", "CORRIENTES"), 0.85)  # tipeo
        self.assertEqual(similitud_calle("COSTA RICA", "NICARAGUA"), 0.0)
        self.assertEqual(similitud_calle("7", "7 MAYO"), 0.0)                # solo un número no alcanza

    def test_caba(self):
        self.assertTrue(parsear_direccion("Gorriti 4015, Palermo").es_caba)
        self.assertTrue(parsear_direccion("Gorriti 4015, Ciudad Autónoma de Buenos Aires").es_caba)
        self.assertFalse(parsear_direccion("Gorriti 4015, Rosario, Santa Fe").es_caba)
        self.assertEqual(normalizar_provincia("CIUDAD AUTONOMA BUENOS AIRES"), "CABA")
        self.assertEqual(normalizar_provincia("Córdoba"), "CORDOBA")


if __name__ == "__main__":
    unittest.main()

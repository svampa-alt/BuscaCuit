"""Tests del método de matcheo sobre una base chica armada en memoria."""
import sqlite3
import unittest

from cuitfinder import db
from cuitfinder.buscar import buscar, evaluar_domicilio, factor_localidad, nivel_de, puntuar
from cuitfinder.cuit import digito_verificador
from cuitfinder.ingesta import Cargador
from cuitfinder.normalizar import CABA, parsear_direccion


def cuit_de(prefijo: int, numero: int) -> int:
    """Arma un CUIT sintético con dígito verificador correcto."""
    while True:
        base = f"{prefijo}{numero:08d}"
        dv = digito_verificador(base)
        if dv is not None:
            return int(base + str(dv))
        numero += 1


BAR = cuit_de(30, 71564413)
SEGUROS = cuit_de(30, 50000012)
SAIGON = cuit_de(30, 71000001)
NIDO_ROSARIO = cuit_de(30, 70000002)
NIDO_PALERMO = cuit_de(30, 70000003)
VIEJO = cuit_de(20, 11111111)
GARCIA_1 = cuit_de(20, 22222222)
GARCIA_2 = cuit_de(27, 33333333)
SUPER = cuit_de(30, 68731043)


def base_de_prueba() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.ESQUEMA)
    c = Cargador(con)
    # Local habilitado cuyo titular no se parece al nombre de fantasía.
    c.domicilio("gcba_hab", BAR, "ORLANDO BRENNAN MARIA LUZ", None, "local", "NICARAGUA", 6048,
                "", CABA, "CAFE BAR", "2024-11-14", "EX-2017-1")
    c.nombre(BAR, "ORLANDO BRENNAN MARIA LUZ", "razon_social", "gcba_hab")
    # Sociedad con domicilio fiscal en formato invertido.
    c.domicilio("rns", SEGUROS, "SEGUROS SURA S.A", None, "fiscal", "PERON, JUAN TTE.GRAL.", 430,
                "CAPITAL FEDERAL", CABA)
    c.nombre(SEGUROS, "SEGUROS SURA S.A", "razon_social", "rns")
    # Habilitación sin CUIT cuya razón social existe una sola vez en el padrón.
    c.domicilio("gcba_hab_sin_cuit", None, "Saigon Buenos Aires S.A.", None, "local", "BONPLAND",
                2362, "", CABA, "RESTAURANTE", "2015", "DI-2015-1")
    c.nombre(SAIGON, "SAIGON BUENOS AIRES SA", "razon_social", "arca")
    # Habilitación sin CUIT con homónimos.
    c.domicilio("gcba_hab_sin_cuit", None, "Garcia, Juan", None, "local", "THAMES", 1500, "", CABA)
    c.nombre(GARCIA_1, "GARCIA JUAN", "razon_social", "arca")
    c.nombre(GARCIA_2, "GARCIA JUAN", "razon_social", "arca")
    # Dos sociedades homónimas en distintas ciudades.
    c.nombre(NIDO_ROSARIO, "EL NIDO SRL", "razon_social", "rns")
    c.domicilio("rns", NIDO_ROSARIO, "EL NIDO SRL", None, "fiscal", "COSTA RICA", 5709, "ROSARIO", "SANTA FE")
    c.nombre(NIDO_PALERMO, "EL NIDO SA", "razon_social", "rns")
    c.domicilio("rns", NIDO_PALERMO, "EL NIDO SA", None, "fiscal", "COSTA RICA", 5709, "CAPITAL FEDERAL", CABA)
    # Dos habilitaciones sucesivas en la misma dirección.
    c.domicilio("gcba_hab", VIEJO, "PEREZ, ANA", None, "local", "GORRITI", 4015, "", CABA, "KIOSCO", "2015-04-23")
    c.domicilio("gcba_hab", BAR, "ORLANDO BRENNAN MARIA LUZ", None, "local", "GORRITI", 4015, "", CABA, "BAR", "2022-01-10")
    # Cadena con bandera.
    c.nombre(SUPER, "INC S.A.", "razon_social", "sepa")
    c.nombre(SUPER, "Hipermercado Carrefour", "fantasia", "sepa")
    c.domicilio("sepa", SUPER, "INC S.A.", "Express", "sucursal", "Nazca", 1944,
                "CIUDAD AUTONOMA DE BUENOS AIRES", CABA)
    c.volcar()
    con.executescript(db.INDICES)
    return con


class TestPuntaje(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(puntuar(1.0, 1.0)[0], 100)
        self.assertEqual(puntuar(1.0, 0.0)[0], 55)
        self.assertEqual(puntuar(0.0, 1.0)[0], 45)
        self.assertEqual(puntuar(1.0, 0.0, unico_en_direccion=True)[0], 65)
        self.assertEqual(puntuar(0.0, 1.0, nombre_unico=True)[0], 55)
        self.assertEqual(puntuar(0.9, 0.8)[0], 90)            # piso por coincidencia doble
        self.assertEqual(puntuar(0.0, 0.5)[0], 0)             # nombre bajo el umbral no suma
        self.assertEqual(puntuar(1.0, 0.0, rubro_coincide=True)[0], 60)
        self.assertEqual(puntuar(0.1, 1.0, rubro_coincide=True)[0], 50.5)   # el rubro solo cuenta con dirección

    def test_niveles(self):
        self.assertEqual([nivel_de(p) for p in (95, 80, 79, 55, 54, 35, 34)],
                         ["ALTA", "ALTA", "MEDIA", "MEDIA", "BAJA", "BAJA", "DESCARTADO"])

    def test_evaluar_domicilio(self):
        q = parsear_direccion("Nicaragua 6048, Palermo, CABA")
        self.assertEqual(evaluar_domicilio(q, "NICARAGUA", 6048, CABA, "", "local")[0], 1.0)
        cercana = evaluar_domicilio(q, "NICARAGUA", 6052, CABA, "", "local")
        self.assertAlmostEqual(cercana[0], 0.55)
        self.assertFalse(cercana[2])
        otra_ciudad = evaluar_domicilio(q, "NICARAGUA", 6048, "SANTA FE", "ROSARIO", "local")[0]
        self.assertLess(otra_ciudad, 0.4)
        self.assertEqual(evaluar_domicilio(q, "HONDURAS", 6048, "CORDOBA", "", "local")[0], 0.0)

    def test_factor_localidad(self):
        self.assertEqual(factor_localidad(parsear_direccion("Mitre 100"), CABA, ""), 0.9)
        q = parsear_direccion("Mitre 100, Rosario, Santa Fe")
        self.assertEqual(factor_localidad(q, "SANTA FE", "ROSARIO"), 1.0)
        self.assertEqual(factor_localidad(q, CABA, ""), 0.35)
        ambigua = parsear_direccion("Mitre 100, Buenos Aires")
        self.assertEqual(factor_localidad(ambigua, CABA, ""), 0.9)
        # San Nicolás es barrio porteño y ciudad bonaerense: no se asume CABA.
        q = parsear_direccion("Presidente Perón 2130, San Nicolás, Buenos Aires")
        self.assertFalse(q.es_caba)
        self.assertEqual(factor_localidad(q, "BUENOS AIRES", "SAN NICOLAS"), 1.0)
        self.assertEqual(factor_localidad(q, CABA, ""), 0.9)
        # La consulta nombra otra provincia.
        q = parsear_direccion("Mitre 100, Salta")
        self.assertEqual(factor_localidad(q, "MENDOZA", "GODOY CRUZ"), 0.35)


class TestBuscar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = base_de_prueba()

    def b(self, nombre, direccion, **kw):
        return buscar(self.con, nombre, direccion, alias=kw.pop("alias", []), **kw)

    def test_direccion_exacta_sin_parecido_de_nombre(self):
        r = self.b("El Bar de la Esquina", "Nicaragua 6048, Palermo, CABA")
        self.assertEqual(r[0].cuit, BAR)
        self.assertEqual(r[0].nivel, "MEDIA")
        self.assertEqual(r[0].puntaje, 70)             # 55 + 10 único en la dirección + 5 rubro (bar)
        sin_rubro = self.b("La Esquina", "Nicaragua 6048, Palermo, CABA")
        self.assertEqual(sin_rubro[0].puntaje, 65)
        self.assertEqual(r[0].evidencias[0].fuente, "gcba_hab")

    def test_nombre_y_direccion(self):
        r = self.b("Seguros Sura", "Tte. Gral. Perón 430, CABA")
        self.assertEqual((r[0].cuit, r[0].nivel), (SEGUROS, "ALTA"))

    def test_error_de_tipeo_en_calle(self):
        r = self.b("Seguros Sura", "Peron 430, Capital Federal")
        self.assertEqual(r[0].cuit, SEGUROS)

    def test_habilitacion_sin_cuit_se_resuelve_por_razon_social(self):
        r = self.b("Saigon", "Bonpland 2362, CABA")
        self.assertEqual(r[0].cuit, SAIGON)
        self.assertIn("resuelto por razón social exacta", r[0].evidencias[0].regla)

    def test_homonimos_no_dan_confianza_alta(self):
        r = self.b("Kiosco Juancito", "Thames 1500, CABA", incluir_descartados=True)
        self.assertEqual({c.cuit for c in r[:2]}, {GARCIA_1, GARCIA_2})
        self.assertTrue(all(c.nivel != "ALTA" for c in r))

    def test_la_localidad_desempata_homonimos(self):
        r = self.b("El Nido", "Costa Rica 5709, Palermo, CABA")
        self.assertEqual(r[0].cuit, NIDO_PALERMO)
        self.assertEqual(r[0].nivel, "ALTA")
        otro = next(c for c in r if c.cuit == NIDO_ROSARIO)
        self.assertLess(otro.puntaje, r[0].puntaje - 15)

    def test_habilitacion_mas_reciente_gana(self):
        r = self.b("Algo", "Gorriti 4015, CABA")
        self.assertEqual([c.cuit for c in r[:2]], [BAR, VIEJO])

    def test_bandera_como_nombre_de_fantasia(self):
        r = self.b("Carrefour Express", "Nazca 1944, CABA")
        self.assertEqual((r[0].cuit, r[0].nivel), (SUPER, "ALTA"))

    def test_solo_nombre(self):
        r = self.b("Hipermercado Carrefour", "")
        self.assertEqual(r[0].cuit, SUPER)
        self.assertNotEqual(r[0].nivel, "ALTA")        # sin dirección nunca es ALTA

    def test_sin_resultados(self):
        self.assertEqual(self.b("Xyzzy Inexistente", "Calle Falsa 123, Springfield"), [])

    def test_alias_confirmado(self):
        alias = [{"fantasia": "El Bar de la Esquina", "cuit": str(VIEJO),
                  "direccion": "Nicaragua 6048", "nota": "factura", "fecha": "2026-11-13"}]
        r = self.b("el bar de la esquina", "Nicaragua 6048, CABA", alias=alias)
        self.assertEqual((r[0].cuit, r[0].nivel), (VIEJO, "ALTA"))
        self.assertEqual(r[0].evidencias[0].fuente, "alias.csv")
        # El mismo nombre en otra dirección no usa el alias.
        r = self.b("el bar de la esquina", "Bonpland 2362, CABA", alias=alias)
        self.assertNotEqual(r[0].cuit, VIEJO)

    def test_salida_serializable(self):
        d = self.b("Seguros Sura", "Peron 430, CABA")[0].como_dict()
        self.assertTrue(d["cuit_valido"])
        self.assertRegex(d["cuit"], r"^\d{2}-\d{8}-\d$")
        self.assertTrue(d["evidencias"])


if __name__ == "__main__":
    unittest.main()

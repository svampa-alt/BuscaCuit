"""Motor unificado: base unica + busqueda con estados de evidencia (datos sinteticos)."""
import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from motor import base
from motor.buscar import buscar
from motor.texto import cuit_valido, misma_calle, partir_direccion, tokens_nombre

CAMPOS = ("cuit,razon_social,fecha_hora_contrato_social,tipo_societario,fecha_hora_actualizacion,"
          "numero_inscripcion,dom_fiscal_provincia,dom_fiscal_localidad,dom_fiscal_calle,dom_fiscal_numero,"
          "dom_fiscal_piso,dom_fiscal_departamento,dom_fiscal_cp,dom_fiscal_estado_domicilio,"
          "dom_legal_provincia,dom_legal_localidad,dom_legal_calle,dom_legal_numero,dom_legal_piso,"
          "dom_legal_departamento,dom_legal_cp,dom_legal_estado_domicilio,actividad_codigo,"
          "actividad_descripcion,actividad_orden,actividad_estado,actividad_vigencia").split(",")


def sociedad(cuit, nombre, prov, loc, calle, num, act="", desc=""):
    fila = dict.fromkeys(CAMPOS, "")
    fila.update(cuit=cuit, razon_social=nombre, tipo_societario="SOCIEDAD ANONIMA",
                dom_fiscal_provincia=prov, dom_fiscal_localidad=loc, dom_fiscal_calle=calle,
                dom_fiscal_numero=num, actividad_codigo=act, actividad_descripcion=desc)
    return fila


class MotorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        with zipfile.ZipFile(d / "padron.zip", "w") as z:
            lineas = [b"30111111118" + b"EL NIDO SA".ljust(30) + b"ACACNINS00",
                      b"30222222229" + b"GASTRONOMIA PALERMO SRL".ljust(30) + b"ACACNINS00",
                      b"20333333334" + b"PEREZ JUAN".ljust(30) + b"NINIB NN12"]
            z.writestr("padron.txt", b"\n".join(lineas) + b"\n")
        with open(d / "rns.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS)
            w.writeheader()
            w.writerow(sociedad("30111111118", "EL NIDO SA", "CHUBUT", "RAWSON", "SAN MARTIN", "100", "011119", "Cultivo"))
            w.writerow(sociedad("30222222229", "GASTRONOMIA PALERMO SRL", "CIUDAD AUTONOMA BUENOS AIRES",
                                "CAPITAL FEDERAL", "COSTA RICA", "5709", "561019", "Expendio de comidas"))
            w.writerow(sociedad("30222222229", "GASTRONOMIA PALERMO SRL", "CIUDAD AUTONOMA BUENOS AIRES",
                                "CAPITAL FEDERAL", "COSTA RICA", "5709", "563000", "Bares"))
            w.writerow(sociedad("30444444440", "OTRA COSA SA", "CIUDAD AUTONOMA BUENOS AIRES",
                                "CAPITAL FEDERAL", "COSTA RICA", "57090"))
        with open(d / "hab.csv", "w", encoding="utf-8", newline="") as f:
            f.write("cuit;nombre_fantasia;domicilio;expediente\n"
                    "30-55555555-1;Cafe Lavalle;Lavalle 1234;EX-1\n;Sin Cuit;Lavalle 1;EX-2\n")
        cls.db = base.conectar(d / "b.sqlite")
        base.importar_padron(cls.db, d / "padron.zip")
        base.importar_sociedades(cls.db, d / "rns.csv")
        base.importar_locales(cls.db, d / "hab.csv", "hab_prueba", "Municipio X", provincia="CABA")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_texto(self):
        self.assertEqual(partir_direccion("Av. Costa Rica 5709 PB"), ("AV COSTA RICA", "5709"))
        self.assertEqual(partir_direccion("9 de Julio 1234"), ("9 DE JULIO", "1234"))
        self.assertTrue(misma_calle("Av. Peron", "PERON, JUAN TTE.GRAL."))
        self.assertFalse(misma_calle("Costa Rica", "Costa Azul"))
        self.assertEqual(tokens_nombre("El Nido Bar", quitar_rubro=True), ["NIDO"])
        self.assertTrue(cuit_valido("20-12345678-6"))

    def test_importa_columnas_reales_y_deduplica(self):
        r = base.resumen(self.db)
        self.assertEqual(r["contribuyentes"], 3)
        self.assertEqual(r["sociedades"], 3)
        self.assertEqual(r["actividades"], 3)
        mono = self.db.execute("SELECT monotributo, act_monotributo FROM contribuyentes WHERE cuit='20333333334'").fetchone()
        self.assertEqual(mono, ("B", "12"))

    def test_domicilio_supera_homonimo_lejano(self):
        r = buscar(self.db, "El Nido Bar", "Costa Rica 5709", "Palermo", "CABA")
        primero = r["candidatos"][0]
        self.assertEqual(primero["cuit"], "30222222229")
        self.assertEqual(primero["estado"], "POSIBLE")
        tipos = {e["tipo"] for e in primero["evidencias"]}
        self.assertIn("domicilio_coincide", tipos)
        self.assertIn("actividad_compatible", tipos)
        homonimo = next(c for c in r["candidatos"] if c["cuit"] == "30111111118")
        self.assertEqual(homonimo["estado"], "NO_VERIFICADO")  # otra provincia: queda, pero abajo

    def test_altura_distinta_no_coincide(self):
        r = buscar(self.db, direccion="Costa Rica 5709", provincia="CABA")
        self.assertNotIn("30444444440", [c["cuit"] for c in r["candidatos"]])

    def test_nombre_y_domicilio_es_alta_confianza(self):
        r = buscar(self.db, "Gastronomia Palermo", "Costa Rica 5709", provincia="CABA")
        self.assertEqual(r["estado"], "ALTA_CONFIANZA")

    def test_habilitacion_con_cuit_confirma(self):
        r = buscar(self.db, "Cafe Lavalle", "Lavalle 1234", provincia="CABA")
        self.assertEqual(r["estado"], "CONFIRMADO")
        self.assertEqual(r["candidatos"][0]["cuit"], "30555555551")

    def test_error_de_tipeo(self):
        r = buscar(self.db, "Gastronomia Palermmo")
        self.assertEqual(r["candidatos"][0]["cuit"], "30222222229")

    def test_sin_datos_no_inventa(self):
        r = buscar(self.db, "Inexistente Total", "Calle Falsa 999")
        self.assertEqual((r["estado"], r["candidatos"]), ("NO_VERIFICADO", []))


if __name__ == "__main__":
    unittest.main()

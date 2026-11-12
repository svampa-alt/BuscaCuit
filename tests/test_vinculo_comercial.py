import unittest
from scripts.vinculo_comercial import analyze

class VinculoComercialTests(unittest.TestCase):
    def test_documento_con_cuit_y_domicilio(self):
        rows=[{"nombre_comercial":"El Nido Bar","direccion":"Costa Rica 5709","cuit":"30-12345678-9","razon_social":"Ejemplo SRL","expediente":"EXP-1"}]
        result=analyze(rows,"El Nido","Costa Rica 5709","GCBA.csv")
        self.assertEqual(result["coincidencias"][0]["cuit"],"30123456789")
        self.assertFalse(result["coincidencias"][0]["titularidad_confirmada"])
    def test_sin_cuit_no_inventa(self):
        rows=[{"nombre_comercial":"El Nido","direccion":"Costa Rica 5709","razon_social":"Ejemplo SRL"}]
        result=analyze(rows,"El Nido","Costa Rica 5709","GCBA.csv")
        self.assertIsNone(result["coincidencias"][0]["cuit"])
    def test_no_acepta_otro_domicilio(self):
        rows=[{"nombre_comercial":"El Nido","direccion":"Costa Rica 5708","cuit":"30123456789"}]
        self.assertFalse(analyze(rows,"El Nido","Costa Rica 5709","GCBA.csv")["coincidencias"])
if __name__=="__main__":
    unittest.main()

import unittest
from geografia import evaluate,rank,distance_km

class GeografiaTests(unittest.TestCase):
    def test_prioriza_cercania_sin_excluir_chubut(self):
        data=[{"cuit":"1","provincia":"Chubut","localidad":"Rawson"},{"cuit":"2","provincia":"CABA","localidad":"Palermo"},{"cuit":"3"}]
        r=rank(data,localidad="Palermo",provincia="CABA")
        self.assertEqual([x["cuit"] for x in r],["2","1","3"])
        self.assertEqual(r[1]["estado_geografico"],"ubicacion_no_verificada")
    def test_domicilio_exacto_prioritario(self):
        data=[{"cuit":"1","provincia":"CABA","localidad":"Palermo","domicilio":"Costa Rica 5709"},{"cuit":"2","provincia":"CABA","localidad":"Palermo","domicilio":"Otra calle 10"}]
        self.assertEqual(rank(data,localidad="Palermo",provincia="CABA",domicilio="Costa Rica 5709")[0]["cuit"],"1")
    def test_sucursal_cercana_con_domicilio_fiscal_lejano(self):
        data=[{"cuit":"1","provincia":"Chubut","establecimientos":[{"provincia":"CABA","localidad":"Palermo","domicilio":"Costa Rica 5709"}]},{"cuit":"2","provincia":"CABA","localidad":"Palermo"}]
        self.assertEqual(rank(data,localidad="Palermo",provincia="CABA",domicilio="Costa Rica 5709")[0]["cuit"],"1")
    def test_distancia(self):
        self.assertAlmostEqual(distance_km((-34.6,-58.4),(-34.6,-58.4)),0)
    def test_sin_evidencia_no_inventa_provincia(self):
        self.assertEqual(evaluate({"cuit":"30647606039"},provincia="CABA"),(0,"ubicacion_no_verificada"))
if __name__=="__main__":
    unittest.main()

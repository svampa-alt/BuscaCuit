import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cruce_sociedades import match

def record(**kw):
    return dict(cuit="30123456789",name="EL NIDO SRL",address="COSTA RICA 5709",
                city="CABA",province="CABA",postal="1414",**kw)

class ContextoTests(unittest.TestCase):
    def test_proximidad_supera_jurisdiccion_ajena(self):
        q={"name":"El Nido","address":"Costa Rica 5709","city":"CABA","province":"CABA"}
        cercano=match(record(),q)
        lejano=match(dict(record(),city="RAWSON",province="CHUBUT"),q)
        self.assertGreater(cercano["score"],lejano["score"])
        self.assertTrue(lejano["signals"]["province_conflict"])
    def test_domicilio_numero_distinto_no_coincide(self):
        r=dict(record(),address="COSTA RICA 57090")
        self.assertFalse(match(r,{"name":"El Nido","address":"Costa Rica 5709"})["signals"]["address"])
    def test_cuit_exacto_conserva_candidato(self):
        r=dict(record(),city="RAWSON",province="CHUBUT")
        self.assertTrue(match(r,{"cuit":"30-12345678-9","province":"CABA"})["signals"]["cuit_exact"])
    def test_sin_jurisdiccion_no_penaliza(self):
        result=match(record(),{"name":"El Nido"})
        self.assertFalse(result["signals"]["province_conflict"])
if __name__=="__main__":
    unittest.main()

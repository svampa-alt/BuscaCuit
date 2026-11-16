"""Fuentes de locales que el motor baja solo (GCBA, Energia, SEPA), con archivos sinteticos."""
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from motor import base, fuentes
from motor.buscar import buscar

# CUIT con digito verificador correcto
A, B, C, D, E = "30500000127", "30500000224", "30500000321", "30500000429", "30500000526"
F, G = "30717089126", "30500000623"


class FuentesLocalesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        with open(d / "hab2024.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["numero_exp", "fecha_habilitacion", "descripcion_rubro", "calles", "titulares", "cuits"])
            w.writerow(["EX-1", "01/02/2024", "BAR", "COSTA RICA 5709", "NIDO GASTRONOMIA SRL", A])
            w.writerow(["EX-2", "01/03/2024", "KIOSCO", "LAVALLE 100;LAVALLE 102", "UNO SA;DOS SA", f"{B};{C}"])
            w.writerow(["EX-3", "01/03/2024", "KIOSCO", "FLORIDA 1", "SIN CUIT SA", "123"])
            w.writerow(["EX-4", "01/03/2024", "KIOSCO", "0", "SIN DOMICILIO SA", B])
            # caso La Yerra: una habilitacion con dos puertas y una fila por rubro; titular anterior en la misma puerta
            w.writerow(["EX-5", "2022-02-10", "Restaurante, cantina", "HUMBOLDT 1618;HUMBOLDT 1620", "PORTALES DE BARES SRL", F])
            w.writerow(["EX-5", "2022-02-10", "Parrilla", "HUMBOLDT 1618;HUMBOLDT 1620", "PORTALES DE BARES SRL", F])
            w.writerow(["EX-0", "15/03/2016", "Café bar", "HUMBOLDT 1620", "TITULAR VIEJO SA", G])
        (d / "acumulado2026.csv").write_text("razon_social,domicilio,rubro\nX SA,FLORIDA 2,BAR\n", encoding="utf-8")
        (d / "surtidor.csv").write_text(
            "idempresa,cuit,empresa,direccion,localidad,provincia,producto,empresabandera,fecha_vigencia\n"
            f"77,{D[:2]}-{D[2:10]}-{D[10]},COMBUSTIBLES DEL SUR SRL,Av. San Martin 1500,ROSARIO,SANTA FE,Nafta,YPF,2026-11-01\n"
            f"77,{D},COMBUSTIBLES DEL SUR SRL,Av. San Martin 1500,ROSARIO,SANTA FE,Gasoil,YPF,2026-11-01\n",
            encoding="utf-8")
        interno = io.BytesIO()
        with zipfile.ZipFile(interno, "w") as z:
            z.writestr("comercio.csv",
                       "id_comercio|id_bandera|comercio_cuit|comercio_razon_social|comercio_bandera_nombre\n"
                       f"10|3|{E}|INC S.A.|Carrefour\x00 Express\n\nUltima actualizacion: hoy\n")
            z.writestr("sucursales.csv",
                       "id_comercio|id_bandera|id_sucursal|sucursales_tipo|sucursales_calle|sucursales_numero|"
                       "sucursales_localidad|sucursales_provincia\n"
                       "10|3|365|Autoservicio|Nazca|1944|Villa Santa Rita|AR-C\n"
                       "10|3|366|Autoservicio|AV COLON 250||CORDOBA|AR-X\n")
        with zipfile.ZipFile(d / "sepa_viernes.zip", "w") as z:
            z.writestr("sepa_1_comercio-sepa-10.zip", interno.getvalue())
            z.writestr("roto.zip", b"no es un zip")
        cls.db = base.conectar(d / "b.sqlite")
        cls.n_gcba = fuentes.importar(cls.db, "gcba_hab", [d / "acumulado2026.csv", d / "hab2024.csv"])
        cls.n_energia = fuentes.importar(cls.db, "energia", [d / "surtidor.csv"])
        cls.n_sepa = fuentes.importar(cls.db, "sepa", [d / "sepa_viernes.zip"])

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_cantidades(self):
        # GCBA: 1 + (2 CUIT x 2 domicilios) + 2 puertas + 1 titular anterior; la fila con CUIT invalido y el padron sin CUIT no entran
        self.assertEqual((self.n_gcba, self.n_energia, self.n_sepa), (8, 1, 2))

    def test_gcba_confirma_por_direccion_aunque_el_nombre_no_coincida(self):
        r = buscar(self.db, "El Nido Bar", "Costa Rica 5709", provincia="CABA")
        self.assertEqual(r["estado"], "CONFIRMADO")
        self.assertEqual(r["candidatos"][0]["cuit"], A)
        ev = [e for e in r["candidatos"][0]["evidencias"] if e["tipo"] == "domicilio_coincide"][0]
        self.assertEqual((ev["fuente"], ev["referencia"]), ("gcba_hab", "EX-1"))

    def test_local_con_dos_puertas_y_titular_anterior(self):
        r = buscar(self.db, "La Yerra", "Humboldt 1620", provincia="CABA")
        primero, segundo = r["candidatos"][:2]
        self.assertEqual((r["estado"], primero["cuit"], segundo["cuit"]), ("CONFIRMADO", F, G))
        self.assertEqual(primero["razon_social"], "PORTALES DE BARES SRL")  # sin padron: sale del titular
        ev = [e for e in primero["evidencias"] if e["tipo"] == "domicilio_coincide"][0]
        self.assertEqual((ev["referencia"], ev["fecha"], ev["rubro"]),
                         ("EX-5", "2022-02-10", "Restaurante, cantina / Parrilla"))
        self.assertIn("habilitacion_mas_reciente", [e["tipo"] for e in primero["evidencias"]])
        self.assertIn("habilitacion_anterior", [e["tipo"] for e in segundo["evidencias"]])

    def test_base_vieja_se_actualiza_sola(self):
        import sqlite3
        ruta = Path(self.tmp.name) / "vieja.sqlite"
        v = sqlite3.connect(ruta)
        v.execute("CREATE TABLE domicilios(cuit TEXT NOT NULL, tipo TEXT NOT NULL, provincia TEXT, localidad TEXT,"
                  " calle TEXT, numero TEXT, piso TEXT, depto TEXT, cp TEXT, estado TEXT, fuente TEXT NOT NULL,"
                  " nombre_local TEXT, referencia TEXT, PRIMARY KEY(cuit, tipo, fuente, calle, numero)) WITHOUT ROWID")
        v.commit(), v.close()
        db = base.conectar(ruta)
        fuentes.importar(db, "energia", [Path(self.tmp.name) / "surtidor.csv"])
        self.assertEqual(buscar(db, "YPF", "San Martin 1500", "Rosario", "Santa Fe")["candidatos"][0]["cuit"], D)
        db.close()

    def test_gcba_titulares_emparejados_con_su_cuit(self):
        r = buscar(self.db, "Dos", "Lavalle 102", provincia="CABA")
        self.assertEqual(r["candidatos"][0]["cuit"], C)

    def test_energia_fuera_de_caba(self):
        r = buscar(self.db, "YPF", "San Martin 1500", "Rosario", "Santa Fe")
        self.assertEqual((r["estado"], r["candidatos"][0]["cuit"]), ("CONFIRMADO", D))

    def test_sepa_bandera_y_altura_dentro_de_la_calle(self):
        r = buscar(self.db, "Carrefour Express", "Nazca 1944", provincia="CABA")
        self.assertEqual((r["estado"], r["candidatos"][0]["cuit"]), ("CONFIRMADO", E))
        r = buscar(self.db, "Carrefour", "Colon 250", "Cordoba", "Cordoba")
        self.assertEqual((r["estado"], r["candidatos"][0]["cuit"]), ("CONFIRMADO", E))

    def test_reimportar_no_duplica(self):
        antes = self.db.execute("SELECT count(*) FROM nombres WHERE fuente='sepa'").fetchone()[0]
        fuentes.importar(self.db, "sepa", [Path(self.tmp.name) / "sepa_viernes.zip"])
        self.assertEqual(antes, self.db.execute("SELECT count(*) FROM nombres WHERE fuente='sepa'").fetchone()[0])

    def test_eleccion_de_archivos_del_catalogo(self):
        urls = ["https://x/habilitaciones-aprobadas2024.csv", "https://x/habilitaciones-aprobadas2026.csv",
                "https://x/leeme.pdf"]
        self.assertEqual(fuentes.elegir_urls("gcba_hab", urls), urls[:1])
        self.assertEqual(fuentes.elegir_urls("sepa", ["https://x/sepa_lunes.zip", "https://x/sepa_viernes.zip"]),
                         ["https://x/sepa_viernes.zip"])


if __name__ == "__main__":
    unittest.main()

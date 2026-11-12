import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.descargar_padron import main

class ImportacionMensualTests(unittest.TestCase):
    def test_zip_manual_y_reemplazo_seguro(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            archive = base / "arca.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
                with z.open("padron.txt", "w") as f:
                    for i in range(100001):
                        f.write((f"{20000000000+i:011d}" + "SOCIEDAD EJEMPLO".ljust(30) + "\n").encode("ascii"))
            output = base / "salida"
            main(["--archivo", str(archive), "--salida", str(output)])
            with sqlite3.connect(output / "padron.sqlite") as db:
                self.assertEqual(db.execute("SELECT count(*) FROM contribuyentes").fetchone()[0], 100001)
            self.assertEqual(json.loads((output / "metadata.json").read_text())["modo"], "manual")
            invalid = base / "invalido.zip"
            invalid.write_bytes(b"archivo no zip")
            with self.assertRaises(ValueError):
                main(["--archivo", str(invalid), "--salida", str(output)])
            with sqlite3.connect(output / "padron.sqlite") as db:
                self.assertEqual(db.execute("SELECT count(*) FROM contribuyentes").fetchone()[0], 100001)

if __name__ == "__main__":
    unittest.main()

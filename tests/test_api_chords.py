"""Pruebas de la corrección de acordes en la API (requiere fastapi; usa una carpeta temporal).

    python -m unittest tests.test_api_chords -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from fastapi.testclient import TestClient
except ImportError:                                           # pragma: no cover
    TestClient = None

ORIGINAL = [{"start": 0.0, "end": 2.0, "chord": "C"}, {"start": 2.0, "end": 4.0, "chord": "G7"}]


@unittest.skipIf(TestClient is None, "fastapi no está instalado")
class ChordEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.song = root / "cancion"
        cls.song.mkdir()
        (cls.song / "lyrics.json").write_text("[]", encoding="utf-8")
        (cls.song / "chords.json").write_text(json.dumps(ORIGINAL), encoding="utf-8")
        os.environ["SONGS_DIR"] = str(root)
        for var in ("VIEWER_USER", "VIEWER_PASSWORD", "REQUIRE_AUTH", "CHORD_EDITS"):
            os.environ.pop(var, None)
        import importlib
        import web.app
        cls.app_module = importlib.reload(web.app)
        cls.client = TestClient(cls.app_module.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tearDown(self):
        (self.song / "chords.edit.json").unlink(missing_ok=True)
        os.environ.pop("CHORD_EDITS", None)

    def put(self, chords, **kw):
        return self.client.put("/api/songs/cancion/chords", json={"chords": chords}, **kw)

    def test_guardar_leer_y_restaurar(self):
        song = self.client.get("/api/songs/cancion").json()
        self.assertEqual((song["chords"], song["chords_edited"], song["can_edit"]), (ORIGINAL, False, True))
        edited = [{"start": 0, "end": 2, "chord": "Cmaj7"}, {"start": 2, "end": 3, "chord": "C/E"},
                  {"start": 3, "end": 4, "chord": "Dm7/G"}, {"start": 4, "end": 5, "chord": "C6/9"}]
        r = self.put(edited)
        self.assertEqual(r.status_code, 200, r.text)
        song = self.client.get("/api/songs/cancion").json()
        self.assertTrue(song["chords_edited"])
        self.assertEqual([c["chord"] for c in song["chords"]], ["Cmaj7", "C/E", "Dm7/G", "C6/9"])
        self.assertEqual(json.loads((self.song / "chords.json").read_text(encoding="utf-8")), ORIGINAL)  # intacto
        self.assertEqual(self.client.delete("/api/songs/cancion/chords").status_code, 200)
        song = self.client.get("/api/songs/cancion").json()
        self.assertEqual((song["chords"], song["chords_edited"]), (ORIGINAL, False))

    def test_ordena_y_recorta_solapes(self):
        self.put([{"start": 3, "end": 6, "chord": "G"}, {"start": 0, "end": 4, "chord": "C"}])
        saved = json.loads((self.song / "chords.edit.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, [{"start": 0.0, "end": 3.0, "chord": "C"}, {"start": 3.0, "end": 6.0, "chord": "G"}])

    def test_rechaza_datos_no_validos(self):
        bad = {
            "nombre raro": [{"start": 0, "end": 1, "chord": "<script>"}],
            "sin raíz": [{"start": 0, "end": 1, "chord": "m7"}],
            "fin antes del inicio": [{"start": 2, "end": 1, "chord": "C"}],
            "tiempo negativo": [{"start": -1, "end": 1, "chord": "C"}],
            "tiempo de texto": [{"start": "0", "end": 1, "chord": "C"}],
            "booleano": [{"start": True, "end": 2, "chord": "C"}],
            "no es lista": {"start": 0},
            "demasiados": [{"start": i, "end": i + 1, "chord": "C"} for i in range(5001)],
        }
        for name, chords in bad.items():
            with self.subTest(name):
                self.assertEqual(self.put(chords).status_code, 422)
        self.assertFalse((self.song / "chords.edit.json").exists())

    def test_solo_json_y_rutas_seguras(self):
        r = self.client.put("/api/songs/cancion/chords", content=json.dumps({"chords": ORIGINAL}),
                            headers={"content-type": "text/plain"})
        self.assertEqual(r.status_code, 415)
        self.assertIn(self.client.put("/api/songs/..%2f..%2fx/chords", json={"chords": ORIGINAL}).status_code, (404, 405))
        self.assertEqual(self.client.put("/api/songs/noexiste/chords", json={"chords": ORIGINAL}).status_code, 404)

    def test_servidor_de_solo_lectura(self):
        os.environ["CHORD_EDITS"] = "0"
        self.assertFalse(self.client.get("/api/songs/cancion").json()["can_edit"])
        self.assertEqual(self.put(ORIGINAL).status_code, 409)
        self.assertFalse((self.song / "chords.edit.json").exists())


if __name__ == "__main__":
    unittest.main()

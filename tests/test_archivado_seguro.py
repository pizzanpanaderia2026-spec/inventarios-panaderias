import unittest
from types import SimpleNamespace
from datetime import date
from unittest.mock import patch

from google_drive import GoogleDriveConfigurationError
from archivado_service import _limpiar_periodos_verificados


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table_name = table
        self.action = "select"
        self.filters = []

    def select(self, *args, **kwargs): self.action = "select"; return self
    def eq(self, *args): self.filters.append(("eq", args)); return self
    def lt(self, *args): self.filters.append(("lt", args)); return self
    def gte(self, *args): self.filters.append(("gte", args)); return self
    def lte(self, *args): self.filters.append(("lte", args)); return self
    def in_(self, *args): self.filters.append(("in", args)); return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args): return self
    def update(self, payload): self.action = "update"; self.payload = payload; return self
    def delete(self): self.action = "delete"; return self

    def execute(self):
        self.db.calls.append((self.table_name, self.action, self.filters))
        if self.action != "select":
            return SimpleNamespace(data=[])
        if self.table_name == "archivos_archivados":
            return SimpleNamespace(data=[{
                "archive_key": "7|2026-01-01|2026-01-31",
                "periodo_inicio": "2026-01-01",
                "periodo_fin": "2026-01-31",
                "drive_file_id": "drive-file-1",
                "sha256": "expected-hash",
                "estado": "verificado",
            }])
        if self.table_name == "cierres_diarios":
            return SimpleNamespace(data=[{"id": 77}])
        return SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeQuery(self, name)


class ArchivadoSeguroTests(unittest.TestCase):
    def setUp(self):
        self.locales = [{"id": 7, "nombre": "Panadería Pixán"}]

    @patch("archivado_service.obtener_archivo_archivado", return_value={"id": "drive-file-1"})
    @patch("archivado_service._verificar_archivo_existente", side_effect=GoogleDriveConfigurationError("falló"))
    def test_no_elimina_registros_si_drive_no_verifica(self, _verificar, _archivo):
        db = FakeSupabase()
        with self.assertRaises(GoogleDriveConfigurationError):
            _limpiar_periodos_verificados(db, self.locales, date(2026, 3, 5))
        self.assertFalse(any(action in ("update", "delete") for _, action, _ in db.calls))

    @patch("archivado_service.obtener_archivo_archivado", return_value={"id": "drive-file-1"})
    @patch("archivado_service._verificar_archivo_existente", return_value=b"excel-verificado")
    def test_solo_limpia_despues_de_verificar_drive(self, _verificar, _archivo):
        db = FakeSupabase()
        eliminados = _limpiar_periodos_verificados(db, self.locales, date(2026, 3, 5))
        self.assertEqual(eliminados, 1)
        acciones = [(tabla, accion) for tabla, accion, _ in db.calls if accion != "select"]
        self.assertEqual(acciones, [
            ("auditoria_inventario", "update"),
            ("inventario_detalles", "delete"),
            ("cierres_diarios", "delete"),
        ])


if __name__ == "__main__":
    unittest.main()

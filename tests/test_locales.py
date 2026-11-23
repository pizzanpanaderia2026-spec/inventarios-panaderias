import unittest
from types import SimpleNamespace

from locales import _estado_eliminacion_local


class FakeQuery:
    def __init__(self, table, data):
        self.table = table
        self.data = data
        self.filters = {}
        self.excluded = {}
        self.limit_count = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def neq(self, key, value):
        self.excluded[key] = value
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def execute(self):
        if self.table == "panaderias":
            if "id" in self.filters:
                rows = [self.data["local"]] if self.data["local"]["id"] == self.filters["id"] else []
            else:
                rows = self.data.get("other_active", [])
        elif self.table == "accesos_panaderias":
            if "usuario_id" in self.filters:
                rows = self.data.get("other_access", {}).get(self.filters["usuario_id"], [])
            else:
                rows = self.data.get("access", [])
        else:
            rows = self.data.get(self.table, [])
        for key, value in self.filters.items():
            rows = [row for row in rows if row.get(key) == value]
        for key, value in self.excluded.items():
            rows = [row for row in rows if row.get(key) != value]
        return SimpleNamespace(data=rows[:self.limit_count] if self.limit_count is not None else rows)


class FakeSupabase:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return FakeQuery(name, self.data)


class LocalDeletionChecksTests(unittest.TestCase):
    def make_core(self, **overrides):
        data = {
            "local": {"id": 2, "nombre": "Local vacío", "foto_key": None, "activa": True},
            "other_active": [{"id": 1, "activa": True}],
            "access": [],
            "other_access": {},
            "productos": [],
            "cierres_diarios": [],
            "produccion_registros": [],
            "archivos_archivados": [],
        }
        data.update(overrides)
        return SimpleNamespace(supabase=FakeSupabase(data))

    def test_empty_location_can_be_removed(self):
        local, blockers = _estado_eliminacion_local(self.make_core(), 2)
        self.assertEqual(local["nombre"], "Local vacío")
        self.assertEqual(blockers, [])

    def test_user_with_another_location_does_not_block_removal(self):
        core = self.make_core(
            access=[{"usuario_id": "user-1"}],
            other_access={"user-1": [{"panaderia_id": 1}]},
        )
        _, blockers = _estado_eliminacion_local(core, 2)
        self.assertEqual(blockers, [])

    def test_user_with_only_this_location_blocks_removal(self):
        core = self.make_core(access=[{"usuario_id": "user-1"}], other_access={"user-1": []})
        _, blockers = _estado_eliminacion_local(core, 2)
        self.assertIn("Hay usuarios que solo tienen asignado este local", blockers)

    def test_products_block_removal(self):
        core = self.make_core(productos=[{"id": 10}])
        _, blockers = _estado_eliminacion_local(core, 2)
        self.assertIn("Productos registrados", blockers)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace

from locales import _estado_eliminacion_local


class FakeQuery:
    def __init__(self, table, data):
        self.table, self.data = table, data
        self.filters, self.excluded = {}, {}
        self.limit_count = None

    def select(self, *_args): return self
    def eq(self, key, value): self.filters[key] = value; return self
    def neq(self, key, value): self.excluded[key] = value; return self
    def in_(self, key, values): self.filters[key] = list(values); return self
    def limit(self, count): self.limit_count = count; return self

    def execute(self):
        if self.table == "panaderias":
            rows = ([self.data["local"]] if self.data["local"]["id"] == self.filters.get("id")
                    else self.data.get("other_active", []))
        elif self.table == "accesos_panaderias":
            rows = (self.data.get("other_access", {}).get(self.filters["usuario_id"], [])
                    if "usuario_id" in self.filters else self.data.get("access", []))
        else:
            rows = self.data.get(self.table, [])
        for key, value in self.filters.items():
            if key == "id" and self.table == "panaderias": continue
            rows = ([row for row in rows if row.get(key) in value] if isinstance(value, list)
                    else [row for row in rows if row.get(key) == value])
        for key, value in self.excluded.items():
            rows = [row for row in rows if row.get(key) != value]
        if self.limit_count is not None: rows = rows[:self.limit_count]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, data): self.data = data
    def table(self, name): return FakeQuery(name, self.data)


class LocalDeletionChecksTests(unittest.TestCase):
    def make_core(self, **overrides):
        data = {
            "local": {"id": 2, "nombre": "G", "foto_key": None, "activa": True},
            "other_active": [{"id": 1, "activa": True}],
            "access": [], "other_access": {},
            "productos": [], "inventario_detalles": [],
            "cierres_diarios": [], "produccion_registros": [], "archivos_archivados": [],
        }
        data.update(overrides)
        return SimpleNamespace(supabase=FakeSupabase(data))

    def test_empty_location_can_be_removed(self):
        self.assertEqual(_estado_eliminacion_local(self.make_core(), 2)[1], [])

    def test_inactive_products_without_inventory_details_do_not_block(self):
        core = self.make_core(productos=[{"id": 10, "panaderia_id": 2, "activo": False}])
        self.assertEqual(_estado_eliminacion_local(core, 2)[1], [])

    def test_active_products_block_removal(self):
        core = self.make_core(productos=[{"id": 10, "panaderia_id": 2, "activo": True}])
        self.assertIn("Productos activos registrados", _estado_eliminacion_local(core, 2)[1])

    def test_inventory_details_block_removal_even_for_inactive_products(self):
        core = self.make_core(
            productos=[{"id": 10, "panaderia_id": 2, "activo": False}],
            inventario_detalles=[{"id": 3, "producto_id": 10}],
        )
        self.assertIn("Los productos conservan detalles de inventario históricos", _estado_eliminacion_local(core, 2)[1])

    def test_user_with_another_location_does_not_block_removal(self):
        core = self.make_core(
            access=[{"usuario_id": "u", "panaderia_id": 2}],
            other_access={"u": [{"usuario_id": "u", "panaderia_id": 1}]},
        )
        self.assertEqual(_estado_eliminacion_local(core, 2)[1], [])

    def test_user_with_only_this_location_blocks_removal(self):
        core = self.make_core(access=[{"usuario_id": "u", "panaderia_id": 2}])
        self.assertIn("Hay usuarios que solo tienen asignado este local", _estado_eliminacion_local(core, 2)[1])


if __name__ == "__main__":
    unittest.main()

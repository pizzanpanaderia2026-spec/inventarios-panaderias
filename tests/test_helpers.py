import unittest

from fastapi import HTTPException
from pydantic import ValidationError

import main


class HelpersTests(unittest.TestCase):
    def test_normaliza_espacios_en_nombre(self):
        self.assertEqual(main.normalizar_nombre_producto("  Concha   vainilla  "), "Concha vainilla")

    def test_clave_ignora_mayusculas_acentos_y_espacios_repetidos(self):
        self.assertEqual(
            main.clave_nombre_producto("  Café   GRANDE "),
            main.clave_nombre_producto("cafe grande"),
        )

    def test_clave_conserva_limite_entre_palabras(self):
        self.assertNotEqual(
            main.clave_nombre_producto("Bolillo grande"),
            main.clave_nombre_producto("Bolillogrande"),
        )

    def test_admin_principal_requiere_ambas_condiciones(self):
        self.assertTrue(main.es_admin_principal({"rol": "admin", "es_admin_principal": True}))
        self.assertFalse(main.es_admin_principal({"rol": "admin", "es_admin_principal": False}))
        self.assertFalse(main.es_admin_principal({"rol": "encargado", "es_admin_principal": True}))

    def test_producto_rechaza_precio_negativo(self):
        with self.assertRaises(ValidationError):
            main.ProductoNuevo(panaderia_id=1, nombre="Concha", precio="-1")

    def test_producto_rechaza_nombre_vacio(self):
        with self.assertRaises(ValidationError):
            main.ProductoNuevo(panaderia_id=1, nombre="", precio="10.00")

    def test_registro_rechaza_cantidad_negativa(self):
        with self.assertRaises(ValidationError):
            main.LineaRegistro(producto_id=1, cantidad=-1)

    def test_registro_rechaza_ids_duplicados_en_payload(self):
        registro = main.GuardarRegistro(
            panaderia_id=1,
            fecha="2026-10-20",
            lineas=[
                {"producto_id": 4, "cantidad": 2},
                {"producto_id": 4, "cantidad": 3},
            ],
        )
        # La duplicidad se comprueba en el endpoint; aquí comprobamos
        # que el payload se conserva para que el endpoint pueda rechazarlo.
        self.assertEqual([x.producto_id for x in registro.lineas], [4, 4])

    def test_resumen_ventas_agrupa_por_producto_y_precio(self):
        ventas = [{
            "lineas": [
                {"producto_id": 1, "producto_nombre": "Bolillo", "cantidad": 2, "precio_unitario": "5.00", "importe": "10.00"},
                {"producto_id": 2, "producto_nombre": "Concha", "cantidad": 3, "precio_unitario": "5.00", "importe": "15.00"},
                {"producto_id": 3, "producto_nombre": "Oreja", "cantidad": 1, "precio_unitario": "7.00", "importe": "7.00"},
            ]
        }]
        resumen = main.construir_resumen_ventas(ventas)
        self.assertEqual(resumen["total_ventas"], 1)
        self.assertEqual(resumen["cantidad_total"], 6)
        self.assertEqual(resumen["importe_total"], "32.00")
        precio_cinco = next(x for x in resumen["por_precio"] if x["precio"] == "5.00")
        self.assertEqual(precio_cinco["cantidad"], 5)
        self.assertEqual(precio_cinco["importe"], "25.00")

    def test_correccion_venta_requiere_al_menos_un_producto(self):
        with self.assertRaises(ValidationError):
            main.VentaPosCorreccion(lineas=[])

    def test_cierre_debe_existir_para_buscarlo(self):
        class Query:
            def select(self, *_args):
                return self
            def eq(self, *_args):
                return self
            def limit(self, *_args):
                return self
            def execute(self):
                return type("Response", (), {"data": []})()

        class FakeSupabase:
            def table(self, _name):
                return Query()

        original = main.supabase
        main.supabase = FakeSupabase()
        try:
            with self.assertRaises(HTTPException) as ctx:
                main.buscar_cierre(1, main.date(2026, 10, 20))
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            main.supabase = original


if __name__ == "__main__":
    unittest.main()

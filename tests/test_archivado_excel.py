import unittest
from datetime import date
from io import BytesIO

from openpyxl import load_workbook

from archivado_excel import crear_excel_periodo


class ExcelArchivadoTests(unittest.TestCase):
    def setUp(self):
        self.dias = [
            {
                "cierre": {"fecha": "2026-06-16", "cerrado_por_nombre": "Betty"},
                "lineas": [
                    {"producto": "Bolillo", "cantidad": 10, "precio_unitario": "5.00", "total": "50.00"},
                    {"producto": "Concha", "cantidad": 3, "precio_unitario": "10.00", "total": "30.00"},
                ],
            },
            {"cierre": {"fecha": "2026-06-17", "cerrado_por_nombre": "Admin"}, "lineas": []},
            {
                "cierre": {"fecha": "2026-06-18", "cerrado_por_nombre": "Betty"},
                "lineas": [
                    {"producto": "Bolillo", "cantidad": 20, "precio_unitario": "5.00", "total": "100.00"},
                ],
            },
        ]

    def libro(self):
        contenido = crear_excel_periodo(
            "Panadería Pixán",
            date(2026, 6, 15),
            date(2026, 7, 14),
            self.dias,
        )
        return load_workbook(BytesIO(contenido), data_only=True)

    def test_resumen_es_primera_hoja_y_acumula_por_pan_y_precio(self):
        libro = self.libro()
        self.assertEqual(libro.sheetnames[0], "Resumen del periodo")
        filas = list(libro["Resumen del periodo"].values)
        self.assertIn(("Bolillo", 30, 150), filas)
        self.assertIn(("Concha", 3, 30), filas)
        self.assertIn(("TOTAL", 33, 180), filas)

    def test_crea_una_hoja_por_dia_con_inventario_y_omite_dias_vacios(self):
        libro = self.libro()
        self.assertEqual(libro.sheetnames, [
            "Resumen del periodo", "16-06-2026", "18-06-2026"
        ])
        filas = list(libro["16-06-2026"].values)
        self.assertEqual(filas[0][0], "Cuenta: Betty")
        self.assertEqual(filas[1][0], "Fecha: 16/06/2026")
        self.assertIn(("Producto", "Cantidad", "Precio unitario", "Importe"), filas)
        self.assertIn(("Precio unitario", "Cantidad total", "Importe", None), filas)

    def test_resumen_por_precio_incluye_cantidad_e_importe(self):
        filas = list(self.libro()["Resumen del periodo"].values)
        self.assertIn((5, 30, 150), filas)
        self.assertIn((10, 3, 30), filas)


if __name__ == "__main__":
    unittest.main()

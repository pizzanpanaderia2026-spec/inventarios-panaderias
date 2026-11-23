from datetime import date
from io import BytesIO
import unittest

from openpyxl import load_workbook

from historial_archivos import _normalizar_dia
from historial_reportes import _agregar, _crear_excel


class HistorialReportesTests(unittest.TestCase):
    def setUp(self):
        self.inv = _normalizar_dia(
            {"fecha": "2026-03-01", "cerrado_por_nombre": "Encargada"},
            [
                {"producto": "Bolillo", "cantidad": 10, "precio_unitario": "2.00"},
                {"producto": "Concha", "cantidad": 4, "precio_unitario": "12.50"},
            ],
        )
        self.prod = [{
            "fecha": "2026-03-01",
            "registros": [{"pan": "Bolillo", "cantidad": 20}],
            "por_pan": [{"pan": "Bolillo", "cantidad": 20}],
            "total": 20,
        }]

    def test_summary_aggregates_inventory_and_production(self):
        data = _agregar([self.inv], self.prod, date(2026, 3, 1), date(2026, 3, 1))
        self.assertEqual(data["inventario"]["total_piezas"], 14)
        self.assertEqual(data["produccion"]["total"], 20)
        self.assertEqual(data["analisis"]["por_pan"][0]["porcentaje_sobrante"], 50.0)

    def test_day_excel_has_native_charts(self):
        data = _agregar([self.inv], self.prod, date(2026, 3, 1), date(2026, 3, 1))
        output = _crear_excel("analisis", "dia", date(2026, 3, 1), date(2026, 3, 1), data, False)
        book = load_workbook(BytesIO(output.getvalue()))
        self.assertEqual(book.sheetnames, ["Resumen"])
        self.assertGreaterEqual(len(book["Resumen"]._charts), 3)

    def test_month_excel_adds_only_days_with_records(self):
        end = date(2026, 3, 31)
        data = _agregar([self.inv], self.prod, date(2026, 3, 1), end)
        output = _crear_excel("analisis", "mes", date(2026, 3, 1), end, data, False)
        book = load_workbook(BytesIO(output.getvalue()))
        self.assertEqual(book.sheetnames, ["Resumen", "01-mar-2026"])

    def test_year_excel_has_monthly_sheets(self):
        start, end = date(2025, 1, 1), date(2025, 12, 31)
        data = _agregar([self.inv], self.prod, start, end)
        output = _crear_excel("produccion", "anio", start, end, data, False)
        book = load_workbook(BytesIO(output.getvalue()))
        self.assertEqual(len(book.sheetnames), 13)
        self.assertEqual(book.sheetnames[1:], [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ])
        self.assertGreaterEqual(len(book["Resumen"]._charts), 1)

    def test_long_period_exports_summary_only(self):
        start, end = date(2024, 1, 1), date(2025, 1, 1)
        data = _agregar([self.inv], self.prod, start, end)
        data["resumen_mensual"] = [{"mes": "2024-01", "inventario_cantidad": 14,
            "inventario_importe": "70.00", "produccion_cantidad": 20}]
        output = _crear_excel("analisis", "periodo", start, end, data, True)
        book = load_workbook(BytesIO(output.getvalue()))
        self.assertEqual(book.sheetnames, ["Resumen"])


if __name__ == "__main__":
    unittest.main()

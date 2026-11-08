from datetime import date
from decimal import Decimal
from io import BytesIO
import unittest

from fastapi import HTTPException
from openpyxl import load_workbook

from historial_archivos import _crear_libro, _leer_hoja_diaria, _normalizar_dia, _validar_rango


class HistorialArchivosTests(unittest.TestCase):
    def sample_day(self):
        return _normalizar_dia(
            {"fecha": "2026-07-30", "cerrado_por_nombre": "Encargada"},
            [
                {"producto": "Concha", "cantidad": 4, "precio_unitario": "12.50"},
                {"producto": "Bolillo", "cantidad": 10, "precio_unitario": "2.00"},
            ],
        )

    def test_period_limit_counts_both_dates(self):
        _validar_rango(date(2026, 3, 30), date(2026, 4, 29))
        with self.assertRaises(HTTPException):
            _validar_rango(date(2026, 3, 30), date(2026, 4, 30))

    def test_excel_has_summary_first_and_one_daily_sheet(self):
        output = _crear_libro([self.sample_day()])
        workbook = load_workbook(BytesIO(output.getvalue()), data_only=True)
        self.assertEqual(workbook.sheetnames, ["Resumen del periodo", "2026-07-30"])
        summary = workbook[workbook.sheetnames[0]]
        self.assertEqual(summary["A3"].value, "POR TIPO DE PAN")
        self.assertEqual(summary["A4"].value, "Producto")
        self.assertEqual(summary["A5"].value, "Bolillo")
        self.assertEqual(summary["A6"].value, "Concha")
        daily = workbook["2026-07-30"]
        self.assertEqual(daily["B1"].value, "Encargada")
        self.assertEqual(daily["B2"].value, "2026-07-30")
        parsed = _leer_hoja_diaria(daily)
        self.assertEqual(parsed["cierre"]["fecha"], "2026-07-30")
        self.assertEqual(len(parsed["lineas"]), 2)
        self.assertEqual(Decimal(parsed["total_importe"]), Decimal("70.00"))


if __name__ == "__main__":
    unittest.main()

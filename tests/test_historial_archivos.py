from datetime import date
from io import BytesIO
from decimal import Decimal

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from historial_archivos import _crear_libro, _leer_hoja_diaria, _normalizar_dia, _validar_rango


def sample_day():
    return _normalizar_dia(
        {"fecha": "2026-07-30", "cerrado_por_nombre": "Encargada"},
        [
            {"producto": "Concha", "cantidad": 4, "precio_unitario": "12.50"},
            {"producto": "Bolillo", "cantidad": 10, "precio_unitario": "2.00"},
        ],
    )


def test_period_limit_counts_both_dates():
    _validar_rango(date(2026, 3, 30), date(2026, 4, 29))
    with pytest.raises(HTTPException):
        _validar_rango(date(2026, 3, 30), date(2026, 4, 30))


def test_excel_has_summary_first_and_one_daily_sheet():
    output = _crear_libro([sample_day()])
    workbook = load_workbook(BytesIO(output.getvalue()), data_only=True)
    assert workbook.sheetnames == ["Resumen del periodo", "2026-07-30"]
    summary = workbook[workbook.sheetnames[0]]
    assert summary["A3"].value == "POR TIPO DE PAN"
    assert summary["A4"].value == "Producto"
    assert summary["A5"].value == "Bolillo"
    assert summary["A6"].value == "Concha"
    daily = workbook["2026-07-30"]
    assert daily["B1"].value == "Encargada"
    assert daily["B2"].value == "2026-07-30"
    parsed = _leer_hoja_diaria(daily)
    assert parsed["cierre"]["fecha"] == "2026-07-30"
    assert len(parsed["lineas"]) == 2
    assert Decimal(parsed["total_importe"]) == Decimal("70.00")

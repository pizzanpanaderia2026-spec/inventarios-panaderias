"""Generación compacta de los libros Excel de archivo por periodo y panadería."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


def _dinero(valor) -> Decimal:
    return Decimal(str(valor if valor is not None else "0")).quantize(Decimal("0.01"))


def _importe(linea: dict) -> Decimal:
    if linea.get("total") is not None:
        return _dinero(linea["total"])
    return _dinero(linea.get("precio_unitario")) * int(linea.get("cantidad") or 0)


def _fecha_cierre(cierre: dict) -> date:
    valor = cierre["fecha"]
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def crear_excel_periodo(
    nombre_panaderia: str,
    desde: date,
    hasta: date,
    dias: list[dict],
) -> bytes:
    """Crea resumen como primera hoja y una hoja por cada cierre con inventario.

    Cada hoja diaria contiene únicamente el nombre de la cuenta, la fecha y
    las dos tablas existentes en la página Tablas de la aplicación.
    """
    dias_ordenados = sorted(\n        (dia for dia in dias if dia.get("lineas")),\n        key=lambda item: _fecha_cierre(item["cierre"]),\n    )
    productos = {}
    precios = {}
    total_piezas = 0
    total_importe = Decimal("0")

    for dia in dias_ordenados:
        for linea in dia.get("lineas", []):
            nombre = str(linea.get("producto") or "Producto").strip() or "Producto"
            cantidad = int(linea.get("cantidad") or 0)
            precio = _dinero(linea.get("precio_unitario"))
            importe = _importe(linea)
            clave_producto = nombre.casefold()

            productos.setdefault(
                clave_producto,
                {"nombre": nombre, "cantidad": 0, "importe": Decimal("0")},
            )
            productos[clave_producto]["cantidad"] += cantidad
            productos[clave_producto]["importe"] += importe

            precios.setdefault(
                precio,
                {"cantidad": 0, "importe": Decimal("0")},
            )
            precios[precio]["cantidad"] += cantidad
            precios[precio]["importe"] += importe

            total_piezas += cantidad
            total_importe += importe

    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen del periodo"
    resumen.append(["Panadería", nombre_panaderia])
    resumen.append(["Periodo", f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"])
    resumen.append([])
    resumen.append(["RESUMEN POR PAN"])
    resumen.append(["Producto", "Cantidad", "Importe"])

    for item in sorted(productos.values(), key=lambda valor: valor["nombre"].casefold()):
        resumen.append([item["nombre"], item["cantidad"], float(item["importe"])])

    fila_total_pan = 6 + len(productos)
    resumen.append(["TOTAL", total_piezas, float(total_importe)])
    resumen.append([])
    fila_seccion_precio = resumen.max_row + 1
    resumen.append(["RESUMEN POR PRECIO"])
    fila_encabezado_precio = resumen.max_row + 1
    resumen.append(["Precio unitario", "Cantidad total", "Importe"])

    for precio, item in sorted(precios.items()):
        resumen.append([float(precio), item["cantidad"], float(item["importe"])])

    fila_total_precio = resumen.max_row + 1
    resumen.append(["TOTAL", total_piezas, float(total_importe)])

    for fila in (4, 5, fila_total_pan, fila_seccion_precio, fila_encabezado_precio, fila_total_precio):
        for celda in resumen[fila]:
            celda.font = Font(bold=True)
    for fila in resumen.iter_rows():
        for celda in fila:
            if celda.value is not None:
                celda.alignment = Alignment(vertical="center")
    for fila in range(6, fila_total_pan + 1):
        resumen.cell(fila, 3).number_format = '"$"#,##0.00'
    for fila in range(fila_encabezado_precio + 1, fila_total_precio + 1):
        resumen.cell(fila, 1).number_format = '"$"#,##0.00'
        resumen.cell(fila, 3).number_format = '"$"#,##0.00'
    resumen.column_dimensions["A"].width = 34
    resumen.column_dimensions["B"].width = 18
    resumen.column_dimensions["C"].width = 18
    resumen.freeze_panes = "A5"

    for dia in dias_ordenados:
        cierre = dia["cierre"]
        fecha = _fecha_cierre(cierre)
        lineas = dia.get("lineas", [])
        hoja = libro.create_sheet(fecha.strftime("%d-%m-%Y"))
        cuenta = str(cierre.get("cerrado_por_nombre") or "Usuario").strip() or "Usuario"
        hoja.append([f"Cuenta: {cuenta}"])
        hoja.append([f"Fecha: {fecha:%d/%m/%Y}"])
        hoja.append([])
        hoja.append(["Producto", "Cantidad", "Precio unitario", "Importe"])

        cantidad_dia = 0
        importe_dia = Decimal("0")
        resumen_precios_dia = {}

        for linea in lineas:
            cantidad = int(linea.get("cantidad") or 0)
            precio = _dinero(linea.get("precio_unitario"))
            importe = _importe(linea)
            hoja.append([
                linea.get("producto") or "Producto",
                cantidad,
                float(precio),
                float(importe),
            ])
            cantidad_dia += cantidad
            importe_dia += importe
            resumen_precios_dia.setdefault(
                precio,
                {"cantidad": 0, "importe": Decimal("0")},
            )
            resumen_precios_dia[precio]["cantidad"] += cantidad
            resumen_precios_dia[precio]["importe"] += importe

        fila_total_detalle = hoja.max_row + 1
        hoja.append(["TOTAL GENERAL", cantidad_dia, None, float(importe_dia)])
        hoja.append([])
        fila_encabezado_resumen = hoja.max_row + 1
        hoja.append(["Precio unitario", "Cantidad total", "Importe"])

        for precio, item in sorted(resumen_precios_dia.items()):
            hoja.append([float(precio), item["cantidad"], float(item["importe"])])

        fila_total_resumen = hoja.max_row + 1
        hoja.append(["TOTAL GENERAL", cantidad_dia, float(importe_dia)])

        for fila in (4, fila_total_detalle, fila_encabezado_resumen, fila_total_resumen):
            for celda in hoja[fila]:
                celda.font = Font(bold=True)
        for fila in hoja.iter_rows():
            for celda in fila:
                if celda.value is not None:
                    celda.alignment = Alignment(vertical="center")
        for fila in range(5, fila_total_detalle + 1):
            hoja.cell(fila, 3).number_format = '"$"#,##0.00'
            hoja.cell(fila, 4).number_format = '"$"#,##0.00'
        for fila in range(fila_encabezado_resumen + 1, fila_total_resumen + 1):
            hoja.cell(fila, 1).number_format = '"$"#,##0.00'
            hoja.cell(fila, 3).number_format = '"$"#,##0.00'
        for columna, ancho in {"A": 34, "B": 16, "C": 18, "D": 18}.items():
            hoja.column_dimensions[columna].width = ancho
        hoja.freeze_panes = "A5"

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()

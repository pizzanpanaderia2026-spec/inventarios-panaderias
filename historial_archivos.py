"""Consulta unificada del historial en Supabase y archivos privados de Cloudflare R2.

Formato de los Excel archivados:
- Primera hoja: Resumen del periodo.
- Una hoja por fecha con inventario, con nombre ISO YYYY-MM-DD.
- Cada hoja diaria conserva cuenta, fecha, detalle por producto y resumen por precio.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook

router = APIRouter()
MAX_DIAS = 31
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _validar_rango(desde: date, hasta: date) -> None:
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la fecha final.")
    if (hasta - desde).days + 1 > MAX_DIAS:
        raise HTTPException(status_code=422, detail="El periodo máximo es de 31 días contando ambas fechas.")
    if hasta > date.today():
        raise HTTPException(status_code=422, detail="No puedes consultar fechas futuras.")


def _normalizar_dia(cierre: dict, lineas: list[dict]) -> dict:
    resumen_precio: dict[Decimal, dict[str, Any]] = {}
    total_piezas = 0
    total_importe = Decimal("0")
    normalizadas = []
    for linea in lineas:
        cantidad = int(linea.get("cantidad") or 0)
        precio = Decimal(str(linea.get("precio_unitario") or "0")).quantize(Decimal("0.01"))
        importe = (precio * cantidad).quantize(Decimal("0.01"))
        nombre = str(linea.get("producto") or linea.get("producto_nombre") or "Producto")
        normalizadas.append({
            "producto": nombre,
            "cantidad": cantidad,
            "precio_unitario": str(precio),
            "total": str(importe),
        })
        grupo = resumen_precio.setdefault(precio, {"cantidad": 0, "total": Decimal("0")})
        grupo["cantidad"] += cantidad
        grupo["total"] += importe
        total_piezas += cantidad
        total_importe += importe
    resumen = [
        {"precio": str(precio), "cantidad": valores["cantidad"], "total": str(valores["total"])}
        for precio, valores in sorted(resumen_precio.items())
    ]
    return {
        "cierre": {
            "fecha": str(cierre.get("fecha") or ""),
            "cerrado_por_nombre": str(cierre.get("cerrado_por_nombre") or "Usuario"),
        },
        "lineas": normalizadas,
        "resumen": resumen,
        "total_piezas": total_piezas,
        "total_importe": str(total_importe),
    }


def _leer_hoja_diaria(hoja) -> dict | None:
    fecha_valor = hoja["B2"].value
    if not fecha_valor:
        return None
    fecha_texto = fecha_valor.isoformat() if hasattr(fecha_valor, "isoformat") else str(fecha_valor)[:10]
    cuenta = str(hoja["B1"].value or "Usuario")
    lineas = []
    resumen_precio = {}
    modo = ""
    for row in hoja.iter_rows(values_only=True):
        valores = list(row or [])
        primero = str(valores[0] or "").strip() if valores else ""
        if "TABLA A" in primero.upper():
            modo = "detalle"
            continue
        if "TABLA B" in primero.upper():
            modo = "resumen"
            continue
        if primero.upper() == "TOTAL GENERAL":
            modo = ""
            continue
        if not primero or primero.upper() in ("PRODUCTO", "PRECIO UNITARIO"):
            continue
        if modo == "detalle" and len(valores) >= 4:
            try:
                nombre = str(valores[0])
                cantidad = int(valores[1] or 0)
                precio = Decimal(str(valores[2] or 0))
                importe = Decimal(str(valores[3] if valores[3] is not None else precio * cantidad))
                lineas.append({"producto": nombre, "cantidad": cantidad, "precio_unitario": str(precio), "total": str(importe)})
            except (ValueError, TypeError, ArithmeticError):
                continue
        elif modo == "resumen" and len(valores) >= 3:
            try:
                precio = Decimal(str(valores[0] or 0)).quantize(Decimal("0.01"))
                resumen_precio[precio] = {"cantidad": int(valores[1] or 0), "total": Decimal(str(valores[2] or 0))}
            except (ValueError, TypeError, ArithmeticError):
                continue
    dia = _normalizar_dia({"fecha": fecha_texto, "cerrado_por_nombre": cuenta}, lineas)
    # El resumen se vuelve a calcular a partir del detalle para validar consistencia.
    return dia if dia["lineas"] else None


def _leer_archivos_r2(panaderia_id: int, desde: date, hasta: date) -> dict[str, dict]:
    from main import supabase
    from r2_storage import crear_cliente_r2

    if supabase is None:
        raise RuntimeError("Supabase no está disponible.")
    filas = (
        supabase.table("archivos_archivados")
        .select("periodo_inicio,periodo_fin,archive_key,estado")
        .eq("panaderia_id", panaderia_id)
        .lte("periodo_inicio", hasta.isoformat())
        .gte("periodo_fin", desde.isoformat())
        .eq("estado", "verificado")
        .execute()
    ).data or []
    if not filas:
        return {}
    cliente = crear_cliente_r2()
    bucket = __import__("os").environ["R2_BUCKET_NAME"]
    encontrados: dict[str, dict] = {}
    for archivo in filas:
        key = archivo.get("archive_key")
        if not key:
            continue
        respuesta = cliente.get_object(Bucket=bucket, Key=key)
        contenido = respuesta["Body"].read()
        libro = load_workbook(BytesIO(contenido), read_only=True, data_only=True)
        try:
            for nombre_hoja in libro.sheetnames[1:]:
                try:
                    fecha_hoja = date.fromisoformat(nombre_hoja)
                except ValueError:
                    continue
                if desde <= fecha_hoja <= hasta:
                    dia = _leer_hoja_diaria(libro[nombre_hoja])
                    if dia:
                        encontrados[fecha_hoja.isoformat()] = dia
        finally:
            libro.close()
    return encontrados


def _leer_supabase(panaderia_id: int, desde: date, hasta: date) -> dict[str, dict]:
    from main import supabase

    if supabase is None:
        raise RuntimeError("Supabase no está disponible.")
    cierres = (
        supabase.table("cierres_diarios")
        .select("id,fecha,estado,cerrado_por_nombre,cerrado_por")
        .eq("panaderia_id", panaderia_id)
        .eq("estado", "cerrado")
        .gte("fecha", desde.isoformat())
        .lte("fecha", hasta.isoformat())
        .order("fecha")
        .execute()
    ).data or []
    ids = [int(c["id"]) for c in cierres]
    if not ids:
        return {}
    detalles = (
        supabase.table("inventario_detalles")
        .select("cierre_id,producto_id,cantidad,precio_unitario,producto_nombre")
        .in_("cierre_id", ids)
        .execute()
    ).data or []
    ids_productos = list({int(d["producto_id"]) for d in detalles if d.get("producto_id") is not None})
    nombres = {}
    if ids_productos:
        productos = (
            supabase.table("productos").select("id,nombre")
            .in_("id", ids_productos).execute()
        ).data or []
        nombres = {int(p["id"]): p["nombre"] for p in productos}
    por_cierre: dict[int, list[dict]] = {}
    for d in detalles:
        pid = int(d["producto_id"])
        por_cierre.setdefault(int(d["cierre_id"]), []).append({
            "producto": d.get("producto_nombre") or nombres.get(pid) or f"Producto {pid}",
            "cantidad": d.get("cantidad") or 0,
            "precio_unitario": d.get("precio_unitario") or 0,
        })
    salida = {}
    for cierre in cierres:
        lineas = por_cierre.get(int(cierre["id"]), [])
        if not lineas:
            continue
        fecha_texto = str(cierre["fecha"])[:10]
        dia = _normalizar_dia(cierre, lineas)
        salida[fecha_texto] = dia
    return salida


def _consultar(panaderia_id: int, desde: date, hasta: date, authorization: str | None) -> list[dict]:
    from main import obtener_usuario_autenticado, obtener_perfil, comprobar_acceso_panaderia

    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    _validar_rango(desde, hasta)
    try:
        datos_db = _leer_supabase(panaderia_id, desde, hasta)
        datos_r2 = _leer_archivos_r2(panaderia_id, desde, hasta)
        # Un archivo verificado prevalece sobre la copia activa para evitar duplicados.
        datos_db.update(datos_r2)
        return [datos_db[k] for k in sorted(datos_db)]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo recuperar el historial. Comprueba la conexión con Supabase y el archivo histórico.")


def _crear_libro(historial: list[dict]) -> BytesIO:
    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen del periodo"
    resumen.append(["RESUMEN DEL PERIODO"])
    resumen.append([])
    resumen.append(["POR TIPO DE PAN"])
    resumen.append(["Producto", "Cantidad total", "Importe"])
    por_producto: dict[str, dict] = {}
    por_precio: dict[Decimal, dict] = {}
    total_piezas = 0
    total_importe = Decimal("0")
    for dia in historial:
        for linea in dia["lineas"]:
            nombre = str(linea["producto"])
            cantidad = int(linea["cantidad"])
            precio = Decimal(str(linea["precio_unitario"]))
            importe = Decimal(str(linea["total"]))
            producto = por_producto.setdefault(nombre, {"cantidad": 0, "importe": Decimal("0")})
            producto["cantidad"] += cantidad
            producto["importe"] += importe
            precio_grupo = por_precio.setdefault(precio, {"cantidad": 0, "importe": Decimal("0")})
            precio_grupo["cantidad"] += cantidad
            precio_grupo["importe"] += importe
            total_piezas += cantidad
            total_importe += importe
    for nombre, valores in sorted(por_producto.items(), key=lambda x: x[0].casefold()):
        resumen.append([nombre, valores["cantidad"], float(valores["importe"])])
    resumen.append(["TOTAL GENERAL", total_piezas, float(total_importe)])
    resumen.append([])
    resumen.append(["POR PRECIO"])
    resumen.append(["Precio unitario", "Cantidad total", "Importe"])
    for precio, valores in sorted(por_precio.items()):
        resumen.append([float(precio), valores["cantidad"], float(valores["importe"])])
    resumen.append(["TOTAL GENERAL", total_piezas, float(total_importe)])
    for row in resumen.iter_rows():
        for cell in row:
            if cell.value is not None and (cell.row in (1, 3, 4, resumen.max_row - len(por_precio) - 1, resumen.max_row - len(por_precio)) or str(cell.value).upper() == "TOTAL GENERAL"):
                cell.font = cell.font.copy(bold=True)
    for col, width in {"A": 34, "B": 18, "C": 20}.items():
        resumen.column_dimensions[col].width = width
    for row in range(5, resumen.max_row + 1):
        resumen.cell(row, 3).number_format = '"$"#,##0.00'
    resumen.freeze_panes = "A5"

    for dia in sorted(historial, key=lambda x: x["cierre"]["fecha"]):
        fecha_texto = dia["cierre"]["fecha"]
        hoja = libro.create_sheet(fecha_texto)
        hoja.append(["Cuenta", dia["cierre"].get("cerrado_por_nombre") or "Usuario"])
        hoja.append(["Fecha", fecha_texto])
        hoja.append([])
        hoja.append(["TABLA A · DETALLE POR PRODUCTO"])
        hoja.append(["Producto", "Cantidad", "Precio unitario", "Importe"])
        for linea in dia["lineas"]:
            hoja.append([linea["producto"], int(linea["cantidad"]), float(Decimal(str(linea["precio_unitario"]))), float(Decimal(str(linea["total"])))])
        hoja.append(["TOTAL GENERAL", dia["total_piezas"], "", float(Decimal(str(dia["total_importe"])))])
        hoja.append([])
        hoja.append(["TABLA B · RESUMEN POR PRECIO"])
        hoja.append(["Precio unitario", "Cantidad total", "Importe"])
        for linea in dia["resumen"]:
            hoja.append([float(Decimal(str(linea["precio"]))), int(linea["cantidad"]), float(Decimal(str(linea["total"])))])
        hoja.append(["TOTAL GENERAL", dia["total_piezas"], float(Decimal(str(dia["total_importe"])))])
        for row in hoja.iter_rows():
            for cell in row:
                if cell.value is not None and (cell.row in (1, 2, 4, 5, 8 + len(dia["lineas"]), 9 + len(dia["lineas"])) or str(cell.value).upper() == "TOTAL GENERAL"):
                    cell.font = cell.font.copy(bold=True)
        for col, width in {"A": 36, "B": 16, "C": 19, "D": 19}.items():
            hoja.column_dimensions[col].width = width
        for row in range(6, hoja.max_row + 1):
            hoja.cell(row, 3).number_format = '"$"#,##0.00'
            hoja.cell(row, 4).number_format = '"$"#,##0.00'
        hoja.freeze_panes = "A6"
    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida


@router.get("/api/historial/consulta")
def historial_consulta(
    panaderia_id: int,
    desde: date,
    hasta: date,
    authorization: str | None = Header(default=None),
):
    historial = _consultar(panaderia_id, desde, hasta, authorization)
    return {"historial": historial, "fechas_con_inventario": [x["cierre"]["fecha"] for x in historial]}


@router.get("/api/historial/periodo/excel")
def historial_periodo_excel(
    panaderia_id: int,
    desde: date,
    hasta: date,
    authorization: str | None = Header(default=None),
):
    historial = _consultar(panaderia_id, desde, hasta, authorization)
    if not historial:
        raise HTTPException(status_code=404, detail="No hay inventarios registrados en las fechas seleccionadas.")
    salida = _crear_libro(historial)
    nombre = f"historial_{panaderia_id}_{desde.isoformat()}_{hasta.isoformat()}.xlsx"
    return StreamingResponse(salida, media_type=XLSX_MIME, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

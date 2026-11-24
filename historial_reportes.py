"""Informes del módulo Historial: consultas agregadas y libros Excel con gráficas nativas."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo
import unicodedata

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList

from historial_archivos import _normalizar_dia, _leer_archivos_r2, XLSX_MIME

router = APIRouter()
MAX_DIAS_DETALLE = 365
MAX_DIAS_CONSULTA = 3650
TZ_LOCAL = ZoneInfo("America/Mexico_City")
MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _paginar(consulta_factory, tamano=1000):
    filas, inicio = [], 0
    while True:
        pagina = consulta_factory().range(inicio, inicio + tamano - 1).execute().data or []
        filas.extend(pagina)
        if len(pagina) < tamano:
            break
        inicio += tamano
    return filas


def _validar(desde: date, hasta: date):
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la fecha final.")
    dias = (hasta - desde).days + 1
    if dias > MAX_DIAS_CONSULTA:
        raise HTTPException(status_code=422, detail="El periodo supera el máximo técnico de consulta de diez años. Divide la consulta en intervalos más pequeños.")
    if hasta > datetime.now(TZ_LOCAL).date():
        raise HTTPException(status_code=422, detail="No puedes consultar fechas futuras.")
    return dias


def _leer_inventario(panaderia_id: int, desde: date, hasta: date):
    from main import supabase
    if supabase is None:
        raise RuntimeError("Supabase no está disponible.")
    cierres = _paginar(lambda: supabase.table("cierres_diarios")
        .select("id,fecha,estado,cerrado_por_nombre,cerrado_por")
        .eq("panaderia_id", panaderia_id).eq("estado", "cerrado")
        .gte("fecha", desde.isoformat()).lte("fecha", hasta.isoformat()).order("fecha"))
    ids = [int(c["id"]) for c in cierres]
    detalles = []
    for i in range(0, len(ids), 300):
        bloque = ids[i:i + 300]
        detalles.extend(_paginar(lambda bloque=bloque: supabase.table("inventario_detalles")
            .select("cierre_id,producto_id,cantidad,precio_unitario,producto_nombre")
            .in_("cierre_id", bloque)))
    ids_productos = list({int(d["producto_id"]) for d in detalles if d.get("producto_id") is not None})
    nombres = {}
    for i in range(0, len(ids_productos), 300):
        bloque = ids_productos[i:i + 300]
        productos = _paginar(lambda bloque=bloque: supabase.table("productos").select("id,nombre").in_("id", bloque))
        nombres.update({int(p["id"]): p["nombre"] for p in productos})
    por_cierre = defaultdict(list)
    for d in detalles:
        pid = int(d["producto_id"])
        por_cierre[int(d["cierre_id"])].append({
            "producto": d.get("producto_nombre") or nombres.get(pid) or f"Producto {pid}",
            "cantidad": d.get("cantidad") or 0,
            "precio_unitario": d.get("precio_unitario") or 0,
        })
    datos = {}
    for cierre in cierres:
        lineas = por_cierre.get(int(cierre["id"]), [])
        if lineas:
            dia = _normalizar_dia(cierre, lineas)
            datos[dia["cierre"]["fecha"]] = dia
    # Los respaldos verificados sustituyen la copia activa del mismo día.
    datos.update(_leer_archivos_r2(panaderia_id, desde, hasta))
    return [datos[k] for k in sorted(datos)]


def _leer_produccion(panaderia_id: int, desde: date, hasta: date):
    from main import supabase
    if supabase is None:
        raise RuntimeError("Supabase no está disponible.")
    filas = _paginar(lambda: supabase.table("produccion_registros")
        .select("id,fecha_produccion,pan_nombre,cantidad,observaciones,usuario_id,registrado_en")
        .eq("panaderia_id", panaderia_id)
        .gte("fecha_produccion", desde.isoformat()).lte("fecha_produccion", hasta.isoformat())
        .order("fecha_produccion"))
    por_fecha = defaultdict(list)
    for fila in filas:
        por_fecha[str(fila["fecha_produccion"])[:10]].append({
            "pan": " ".join(str(fila.get("pan_nombre") or "Pan sin nombre").split()),
            "cantidad": int(fila.get("cantidad") or 0),
            "observaciones": fila.get("observaciones"),
        })
    salida = []
    for fecha, registros in sorted(por_fecha.items()):
        por_pan = defaultdict(int)
        for r in registros:
            por_pan[r["pan"]] += r["cantidad"]
        salida.append({"fecha": fecha, "registros": registros,
            "por_pan": [{"pan": k, "cantidad": v} for k, v in sorted(por_pan.items(), key=lambda x: x[0].casefold())],
            "total": sum(por_pan.values())})
    return salida


def _clave(texto):
    normal = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in normal if unicodedata.category(c) != "Mn").casefold().strip()


def _agregar(inventario, produccion, desde, hasta, resumen_only=False):
    productos, precios, panes = defaultdict(lambda: [0, Decimal("0")]), defaultdict(lambda: [0, Decimal("0")]), defaultdict(int)
    inv_por_fecha = {d["cierre"]["fecha"]: d for d in inventario}
    prod_por_fecha = {d["fecha"]: d for d in produccion}
    for dia in inventario:
        for linea in dia["lineas"]:
            nombre = linea["producto"]
            cantidad = int(linea["cantidad"])
            precio = Decimal(str(linea["precio_unitario"]))
            importe = Decimal(str(linea["total"]))
            productos[nombre][0] += cantidad
            productos[nombre][1] += importe
            precios[precio][0] += cantidad
            precios[precio][1] += importe
    for dia in produccion:
        for item in dia["por_pan"]:
            panes[item["pan"]] += int(item["cantidad"])
    total_inv = sum(v[0] for v in productos.values())
    importe_inv = sum((v[1] for v in productos.values()), Decimal("0"))
    total_prod = sum(panes.values())
    por_producto = [{"producto": k, "cantidad": v[0], "importe": str(v[1])}
        for k, v in sorted(productos.items(), key=lambda x: x[0].casefold())]
    por_precio = [{"precio": str(k), "cantidad": v[0], "importe": str(v[1])}
        for k, v in sorted(precios.items())]
    por_pan = [{"pan": k, "cantidad": v} for k, v in sorted(panes.items(), key=lambda x: x[0].casefold())]
    inventario_normalizado = {}
    for nombre, valores in productos.items():
        clave = _clave(nombre)
        actual = inventario_normalizado.setdefault(clave, {"nombre": nombre, "cantidad": 0})
        actual["cantidad"] += valores[0]
    produccion_normalizada = {}
    for nombre, cantidad in panes.items():
        clave = _clave(nombre)
        actual = produccion_normalizada.setdefault(clave, {"nombre": nombre, "cantidad": 0})
        actual["cantidad"] += cantidad
    comparacion = []
    for clave in sorted(set(inventario_normalizado) | set(produccion_normalizada)):
        inv_item = inventario_normalizado.get(clave, {"nombre": "", "cantidad": 0})
        prod_item = produccion_normalizada.get(clave, {"nombre": "", "cantidad": 0})
        nombre = inv_item["nombre"] or prod_item["nombre"]
        producido = prod_item["cantidad"]
        sobrante = inv_item["cantidad"]
        comparacion.append({"pan": nombre, "producido": producido, "sobrante": sobrante,
            "porcentaje_sobrante": round(sobrante / producido * 100, 2) if producido > 0 else None})
    dias = []
    cursor = desde
    while cursor <= hasta:
        f = cursor.isoformat()
        inv = inv_por_fecha.get(f)
        prod = prod_por_fecha.get(f)
        dias.append({
            "fecha": f,
            "inventario_cantidad": int(inv["total_piezas"]) if inv else 0,
            "inventario_importe": str(inv["total_importe"]) if inv else "0",
            "produccion_cantidad": int(prod["total"]) if prod else 0,
            "tiene_inventario": bool(inv),
            "tiene_produccion": bool(prod),
        })
        cursor += timedelta(days=1)
    return {
        "inventario": {"por_producto": por_producto, "por_precio": por_precio,
            "total_piezas": total_inv, "total_importe": str(importe_inv), "dias": inventario},
        "produccion": {"por_pan": por_pan, "total": total_prod, "dias": produccion},
        "analisis": {"por_pan": comparacion},
        "resumen_diario": dias,
    }


def _reporte(panaderia_id, categoria, tipo, desde, hasta, authorization, incluir_detalle=True):
    from main import (obtener_usuario_autenticado, obtener_perfil,
        comprobar_acceso_panaderia, comprobar_permiso_local, _perfil_con_acceso_produccion,
        obtener_ventas_pos_periodo, construir_resumen_ventas)
    dias = _validar(desde, hasta)
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    if categoria not in ("inventario", "produccion", "ventas", "analisis"):
        raise HTTPException(status_code=422, detail="La categoría de Historial no es válida.")
    if categoria == "ventas":
        comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
        if tipo == "dia" and desde != hasta:
            raise HTTPException(status_code=422, detail="La consulta diaria debe contener una sola fecha.")
        if tipo == "mes" and (desde.year, desde.month) != (hasta.year, hasta.month):
            raise HTTPException(status_code=422, detail="La consulta mensual debe corresponder a un solo mes.")
        if tipo == "anio" and (desde.month != 1 or desde.day != 1 or desde.year != hasta.year or (hasta.month != 12 or hasta.day != 31) and hasta != datetime.now(TZ_LOCAL).date()):
            raise HTTPException(status_code=422, detail="La consulta anual debe abarcar desde el 1 de enero hasta el cierre del año o la fecha actual.")
        if tipo == "semana":
            hoy = datetime.now(TZ_LOCAL).date()
            if desde.weekday() != 0 or hasta != min(desde + timedelta(days=6), hoy):
                raise HTTPException(status_code=422, detail="La consulta semanal debe abarcar de lunes a domingo o hasta hoy si es la semana actual.")
        ventas = obtener_ventas_pos_periodo(panaderia_id, desde, hasta)
        return {"ventas": ventas, **construir_resumen_ventas(ventas)}, False, dias
    if categoria == "analisis":
        from main import es_admin_principal
        if not es_admin_principal(perfil):
            raise HTTPException(status_code=403, detail="El análisis operativo está reservado para la administradora principal.")
        comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    elif categoria == "produccion":
        _perfil_con_acceso_produccion(str(usuario.id), perfil, panaderia_id)
    else:
        comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    if tipo == "dia" and desde != hasta:
        raise HTTPException(status_code=422, detail="La consulta diaria debe contener una sola fecha.")
    if tipo == "mes" and (desde.year, desde.month) != (hasta.year, hasta.month):
        raise HTTPException(status_code=422, detail="La consulta mensual debe corresponder a un solo mes.")
    if tipo == "anio" and (desde.month != 1 or desde.day != 1 or desde.year != hasta.year or (hasta.month != 12 or hasta.day != 31) and hasta != datetime.now(TZ_LOCAL).date()):
        raise HTTPException(status_code=422, detail="La consulta anual debe abarcar desde el 1 de enero hasta el cierre del año o la fecha actual.")
    if tipo == "semana":
        hoy = datetime.now(TZ_LOCAL).date()
        if desde.weekday() != 0 or hasta != min(desde + timedelta(days=6), hoy):
            raise HTTPException(status_code=422, detail="La consulta semanal debe abarcar de lunes a domingo o hasta hoy si es la semana actual.")
    try:
        inventario = _leer_inventario(panaderia_id, desde, hasta) if categoria in ("inventario", "analisis") else []
        produccion = _leer_produccion(panaderia_id, desde, hasta) if categoria in ("produccion", "analisis") else []
        resumen = _agregar(inventario, produccion, desde, hasta)
        resumen_only = tipo == "periodo" and dias > MAX_DIAS_DETALLE
        if resumen_only:
            # Para intervalos largos se conservan los agregados y la serie mensual, no cientos de hojas.
            mensual = defaultdict(lambda: {"inventario_cantidad": 0, "inventario_importe": Decimal("0"), "produccion_cantidad": 0})
            for item in resumen["resumen_diario"]:
                mes = item["fecha"][:7]
                mensual[mes]["inventario_cantidad"] += item["inventario_cantidad"]
                mensual[mes]["inventario_importe"] += Decimal(item["inventario_importe"])
                mensual[mes]["produccion_cantidad"] += item["produccion_cantidad"]
            resumen["resumen_mensual"] = [{"mes": k, "inventario_cantidad": v["inventario_cantidad"],
                "inventario_importe": str(v["inventario_importe"]), "produccion_cantidad": v["produccion_cantidad"]}
                for k, v in sorted(mensual.items())]
            resumen["resumen_diario"] = []
            resumen["inventario"]["dias"] = []
            resumen["produccion"]["dias"] = []
        elif not incluir_detalle:
            # La pantalla necesita agregados y series, no las líneas completas de cada día.
            resumen["inventario"]["dias"] = []
            resumen["produccion"]["dias"] = []
        return resumen, resumen_only, dias
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="No se pudo recuperar el informe histórico. Comprueba la conexión con Supabase y los archivos históricos.") from exc


def _titulo_periodo(tipo, desde, hasta):
    if tipo == "dia":
        return f"{desde.day:02d} de {MESES_ES[desde.month-1]} de {desde.year}"
    if tipo == "mes":
        return f"{MESES_ES[desde.month-1].capitalize()} {desde.year}"
    if tipo == "anio":
        return str(desde.year)
    if tipo == "semana":
        return f"Semana del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
    return f"Periodo {desde.isoformat()} a {hasta.isoformat()}"


def _estilizar(hoja):
    hoja.freeze_panes = "A3"
    hoja.sheet_view.showGridLines = False
    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value is not None:
                celda.alignment = Alignment(vertical="center")
                if celda.row == 1 or (isinstance(celda.value, str) and celda.value.isupper()):
                    celda.font = Font(bold=True, color="713F12")
    for col, width in {"A": 32, "B": 18, "C": 19, "D": 18, "E": 18}.items():
        hoja.column_dimensions[col].width = width


def _tabla(hoja, fila, titulo, encabezados, filas, formatos=None):
    hoja.cell(fila, 1, titulo)
    for c, valor in enumerate(encabezados, 1):
        celda = hoja.cell(fila + 1, c, valor)
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="F3E8D8")
    for r, valores in enumerate(filas, fila + 2):
        for c, valor in enumerate(valores, 1):
            celda = hoja.cell(r, c, valor)
            if formatos and c in formatos:
                celda.number_format = formatos[c]
    return fila + len(filas) + 3


def _grafica(hoja, titulo, fila_inicio, fila_fin, columna, titulo_grafica, ancla, categorias_col=1, tipo="bar", segunda_serie=None):
    if fila_fin < fila_inicio:
        return
    chart = BarChart()
    chart.type = tipo
    chart.style = 10
    chart.title = titulo_grafica
    chart.y_axis.title = "Cantidad"
    chart.x_axis.title = "Concepto"
    chart.height = 8
    chart.width = 14
    chart.add_data(Reference(hoja, min_col=columna, min_row=fila_inicio - 1, max_row=fila_fin), titles_from_data=True)
    if segunda_serie:
        chart.add_data(Reference(hoja, min_col=segunda_serie, min_row=fila_inicio - 1, max_row=fila_fin), titles_from_data=True)
    chart.set_categories(Reference(hoja, min_col=categorias_col, min_row=fila_inicio, max_row=fila_fin))
    if not segunda_serie:
        chart.legend = None
    chart.varyColors = True
    chart.dLbls = DataLabelList()
    chart.dLbls.showVal = True
    hoja.add_chart(chart, ancla)


def _hoja_informe(libro, nombre_hoja, titulo, categoria, inventario, produccion, resumen_diario, resumen_mensual=None, analisis=None, anio=False):
    hoja = libro.create_sheet(nombre_hoja) if nombre_hoja != libro.sheetnames[0] else libro.active
    hoja.title = nombre_hoja
    hoja["A1"] = titulo
    hoja["A1"].font = Font(bold=True, size=15, color="713F12")
    fila = 3
    filas_inv = inventario["por_producto"] if categoria in ("inventario", "analisis") else []
    filas_precio = inventario["por_precio"] if categoria in ("inventario", "analisis") else []
    filas_prod = produccion["por_pan"] if categoria in ("produccion", "analisis") else []
    if categoria in ("inventario", "analisis"):
        inicio_producto = fila + 2
        fila = _tabla(hoja, fila, "INVENTARIO POR TIPO DE PAN", ["Pan", "Cantidad", "Importe"],
            [[x["producto"], x["cantidad"], float(Decimal(x["importe"]))] for x in filas_inv], {3: '"$"#,##0.00'})
        fin_producto = fila - 2
        inicio_precio = fila + 2
        fila = _tabla(hoja, fila, "INVENTARIO POR PRECIO", ["Precio", "Cantidad", "Importe"],
            [[float(Decimal(x["precio"])), x["cantidad"], float(Decimal(x["importe"]))] for x in filas_precio], {1: '"$"#,##0.00', 3: '"$"#,##0.00'})
        fin_precio = fila - 2
    else:
        inicio_producto = fin_producto = inicio_precio = fin_precio = 0
    if categoria in ("produccion", "analisis"):
        inicio_prod = fila + 2
        fila = _tabla(hoja, fila, "PRODUCCIÓN POR TIPO DE PAN", ["Pan", "Cantidad producida"],
            [[x["pan"], x["cantidad"]] for x in filas_prod])
        fin_prod = fila - 2
    else:
        inicio_prod = fin_prod = 0
    if categoria == "analisis":
        inicio_analisis = fila + 2
        filas_analisis = (analisis or {}).get("por_pan", [])
        fila = _tabla(hoja, fila, "PRODUCCIÓN Y SOBRANTES", ["Pan", "Producido", "Sobrante", "% sobrante"],
            [[x["pan"], x["producido"], x["sobrante"], x["porcentaje_sobrante"] if x["porcentaje_sobrante"] is not None else "N/D"] for x in filas_analisis])
        hoja.cell(fila, 1, "El porcentaje compara sobrantes registrados con producción del mismo pan; no representa ventas.")
        hoja.cell(fila, 1).font = Font(italic=True, color="666666")
        fin_analisis = fila - 2
    else:
        inicio_analisis = fin_analisis = 0
    if resumen_diario:
        if categoria == "inventario":
            datos = [[x["fecha"], x["inventario_cantidad"], float(Decimal(x["inventario_importe"]))] for x in resumen_diario]
            fila = _tabla(hoja, fila, "RESUMEN DIARIO", ["Fecha", "Inventario", "Importe"], datos, {3: '"$"#,##0.00'})
        elif categoria == "produccion":
            datos = [[x["fecha"], x["produccion_cantidad"]] for x in resumen_diario]
            fila = _tabla(hoja, fila, "RESUMEN DIARIO", ["Fecha", "Producción"], datos)
        else:
            datos = [[x["fecha"], x["inventario_cantidad"], float(Decimal(x["inventario_importe"])), x["produccion_cantidad"]] for x in resumen_diario]
            fila = _tabla(hoja, fila, "RESUMEN DIARIO", ["Fecha", "Inventario", "Importe inventario", "Producción"], datos, {3: '"$"#,##0.00'})
    inicio_mensual = fin_mensual = 0
    if resumen_mensual:
        inicio_mensual = fila + 2
        if categoria == "inventario":
            datos = [[x["mes"], x["inventario_cantidad"], float(Decimal(x["inventario_importe"]))] for x in resumen_mensual]
            fila = _tabla(hoja, fila, "RESUMEN MENSUAL", ["Mes", "Inventario", "Importe"], datos, {3: '"$"#,##0.00'})
        elif categoria == "produccion":
            datos = [[x["mes"], x["produccion_cantidad"]] for x in resumen_mensual]
            fila = _tabla(hoja, fila, "RESUMEN MENSUAL", ["Mes", "Producción"], datos)
        else:
            datos = [[x["mes"], x["inventario_cantidad"], float(Decimal(x["inventario_importe"])), x["produccion_cantidad"]] for x in resumen_mensual]
            fila = _tabla(hoja, fila, "RESUMEN MENSUAL", ["Mes", "Inventario", "Importe inventario", "Producción"], datos, {3: '"$"#,##0.00'})
        fin_mensual = fila - 2
    if categoria in ("inventario", "analisis") and fin_producto >= inicio_producto:
        _grafica(hoja, "Producto", inicio_producto, fin_producto, 2, "Inventario por tipo de pan", "F3")
        if fin_precio >= inicio_precio:
            _grafica(hoja, "Precio", inicio_precio, fin_precio, 2, "Inventario por precio", "F19")
    if categoria == "produccion" and fin_prod >= inicio_prod:
        _grafica(hoja, "Pan", inicio_prod, fin_prod, 2, "Producción por tipo de pan", "F3")
    if categoria == "analisis" and fin_analisis >= inicio_analisis:
        _grafica(hoja, "Producido", inicio_analisis, fin_analisis, 2, "Producción frente a sobrantes", "F35", segunda_serie=3)
    if anio and categoria in ("produccion", "analisis") and fin_mensual >= inicio_mensual:
        _grafica(hoja, "Mes", inicio_mensual, fin_mensual, 2 if categoria == "produccion" else 4, "Producción por mes", "F51")
    _estilizar(hoja)
    return hoja


def _crear_excel(categoria, tipo, desde, hasta, datos, resumen_only):
    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen"
    if categoria == "ventas":
        resumen.append(["Producto", "Cantidad", "Importe"])
        for fila in datos.get("resumen", []):
            resumen.append([fila["producto"], fila["cantidad"], float(Decimal(str(fila["importe"])))])
        resumen.append(["TOTAL GENERAL", datos.get("cantidad_total", 0), float(Decimal(str(datos.get("importe_total", "0"))))])
        detalle = libro.create_sheet("Ventas")
        detalle.append(["Fecha", "Venta", "Hora", "Registró", "Producto", "Cantidad", "Precio unitario", "Importe"])
        for venta in datos.get("ventas", []):
            hora = ""
            if venta.get("creado_en"):
                marca = datetime.fromisoformat(str(venta["creado_en"]).replace("Z", "+00:00"))
                if marca.tzinfo is not None:
                    marca = marca.astimezone(TZ_LOCAL)
                hora = marca.strftime("%H:%M")
            for linea in venta.get("lineas", []):
                detalle.append([venta.get("fecha"), "Venta #" + str(venta.get("numero_venta")), hora,
                    venta.get("usuario_nombre") or "Usuario", linea.get("producto_nombre"),
                    int(linea.get("cantidad") or 0), float(Decimal(str(linea.get("precio_unitario") or "0"))),
                    float(Decimal(str(linea.get("importe") or "0")))])
        for hoja in (resumen, detalle):
            hoja.freeze_panes = "A2"
            hoja.auto_filter.ref = hoja.dimensions
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        return salida
    inv, prod = datos["inventario"], datos["produccion"]
    resumen_diario = datos.get("resumen_diario", [])
    resumen_mensual = datos.get("resumen_mensual")
    titulo = "Resumen " + _titulo_periodo(tipo, desde, hasta)
    if tipo == "anio":
        mensual = {f"{desde.year}-{mes:02d}": {"inventario_cantidad": 0, "inventario_importe": Decimal("0"), "produccion_cantidad": 0}
            for mes in range(1, 13)}
        for x in resumen_diario:
            mes = x["fecha"][:7]
            mensual[mes]["inventario_cantidad"] += x["inventario_cantidad"]
            mensual[mes]["inventario_importe"] += Decimal(x["inventario_importe"])
            mensual[mes]["produccion_cantidad"] += x["produccion_cantidad"]
        resumen_mensual = [{"mes": k, **{a: (str(v) if isinstance(v, Decimal) else v) for a,v in vals.items()}}
            for k, vals in sorted(mensual.items())]
    _hoja_informe(libro, "Resumen", titulo, categoria, inv, prod, resumen_diario if tipo in ("mes","periodo") else [], resumen_mensual, datos.get("analisis"), anio=(tipo=="anio"))
    if resumen_only:
        resumen["A2"] = "Informe resumido por la extensión del periodo; se omitieron las hojas diarias para proteger el rendimiento."
        resumen["A2"].font = Font(italic=True, color="666666")

    if resumen_only:
        pass
    elif tipo in ("mes", "periodo", "semana"):
        inv_map = {x["cierre"]["fecha"]: x for x in inv["dias"]}
        prod_map = {x["fecha"]: x for x in prod["dias"]}
        fechas = sorted(set(inv_map) | set(prod_map))
        for fecha in fechas:
            inv_dia = inv_map.get(fecha)
            prod_dia = prod_map.get(fecha)
            inv_datos = _agregar([inv_dia] if inv_dia else [], [], date.fromisoformat(fecha), date.fromisoformat(fecha))
            prod_datos = _agregar([], [prod_dia] if prod_dia else [], date.fromisoformat(fecha), date.fromisoformat(fecha))
            combinado = {
                "inventario": inv_datos["inventario"],
                "produccion": prod_datos["produccion"],
                "resumen_diario": inv_datos["resumen_diario"],
            }
            combinado["analisis"] = _agregar([inv_dia] if inv_dia else [], [prod_dia] if prod_dia else [], date.fromisoformat(fecha), date.fromisoformat(fecha))["analisis"]
            fecha_obj = date.fromisoformat(fecha)
            nombre = f"{fecha_obj.day:02d}-{MESES_ES[fecha_obj.month-1][:3]}-{fecha_obj.year}"
            titulo_dia = f"{fecha_obj.day:02d} de {MESES_ES[fecha_obj.month-1]} de {fecha_obj.year}"
            _hoja_informe(libro, nombre[:31], titulo_dia, categoria,
                combinado["inventario"], combinado["produccion"], combinado["resumen_diario"], analisis=combinado["analisis"])
    elif tipo == "anio":
        for mes in range(1, 13):
            inicio = date(desde.year, mes, 1)
            fin_mes = date(desde.year + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1)
            fin_datos = min(fin_mes, hasta)
            inv_mes = [x for x in inv["dias"] if inicio.isoformat() <= x["cierre"]["fecha"] <= fin_datos.isoformat()]
            prod_mes = [x for x in prod["dias"] if inicio.isoformat() <= x["fecha"] <= fin_datos.isoformat()]
            datos_mes = _agregar(inv_mes, prod_mes, inicio, fin_datos if inicio <= hasta else fin_mes)
            resumen_dia_mes = datos_mes["resumen_diario"] if inicio <= hasta else []
            _hoja_informe(libro, MESES_ES[mes-1].capitalize(), MESES_ES[mes-1].capitalize() + " " + str(desde.year),
                categoria, datos_mes["inventario"], datos_mes["produccion"], resumen_dia_mes, analisis=datos_mes["analisis"])
    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida


@router.get("/api/historial/informe")
def consultar_informe_historial(panaderia_id: int, categoria: str, tipo: str, desde: date, hasta: date,
    authorization: str | None = Header(default=None)):
    if categoria not in ("inventario", "produccion", "ventas", "analisis"):
        raise HTTPException(status_code=422, detail="Categoría de historial no válida.")
    if tipo not in ("dia", "mes", "semana", "anio", "periodo"):
        raise HTTPException(status_code=422, detail="Tipo de consulta no válido.")
    datos, resumen_only, dias = _reporte(panaderia_id, categoria, tipo, desde, hasta, authorization, incluir_detalle=False)
    return {"categoria": categoria, "tipo": tipo, "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "dias_consultados": dias, "resumen_only": resumen_only, **datos}


@router.get("/api/historial/informe/excel")
def descargar_informe_historial(panaderia_id: int, categoria: str, tipo: str, desde: date, hasta: date,
    authorization: str | None = Header(default=None)):
    if categoria not in ("inventario", "produccion", "ventas", "analisis") or tipo not in ("dia", "mes", "semana", "anio", "periodo"):
        raise HTTPException(status_code=422, detail="Los filtros del informe no son válidos.")
    datos, resumen_only, dias = _reporte(panaderia_id, categoria, tipo, desde, hasta, authorization)
    hay_datos = bool(datos["inventario"]["por_producto"] or datos["produccion"]["por_pan"])
    if not hay_datos:
        raise HTTPException(status_code=404, detail="No hay registros para la categoría y las fechas seleccionadas.")
    salida = _crear_excel(categoria, tipo, desde, hasta, datos, resumen_only)
    nombre = f"historial_{categoria}_{desde.isoformat()}_{hasta.isoformat()}.xlsx"
    return StreamingResponse(salida, media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

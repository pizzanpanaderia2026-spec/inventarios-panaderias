"""Servicio de archivado mensual con verificación en Drive y limpieza segura."""
from datetime import date, datetime, timedelta
import hashlib
from decimal import Decimal
from zoneinfo import ZoneInfo

from archivado_excel import crear_excel_periodo
from google_drive import (
    GoogleDriveConfigurationError,
    descargar_archivo_drive,
    obtener_archivo_archivado,
    preparar_carpeta_periodo,
    subir_y_verificar_excel,
)
from periodos_archivado import (
    cambiar_fin_periodo,
    periodo_inicial,
    periodo_que_contiene,
    siguiente_periodo,
)


ZONA_HORARIA = ZoneInfo("America/Mexico_City")
DIA_ARCHIVADO_INICIAL = 15
MAX_PERIODOS_POR_EJECUCION = 24


def fecha_local() -> date:
    return datetime.now(ZONA_HORARIA).date()


def _fecha(valor) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _insertar_evento_configuracion(supabase, config: dict, usuario_id: str | None = None):
    payload = {
        "id": 1,
        "dia_mes": int(config["dia_mes"]),
        "periodo_inicio": config["periodo_inicio"],
        "periodo_fin": config["periodo_fin"],
        "desplazamiento_fin": int(config.get("desplazamiento_fin", -1)),
        "ultima_ejecucion": config.get("ultima_ejecucion"),
        "ultimo_error": config.get("ultimo_error"),
        "ultimo_error_en": config.get("ultimo_error_en"),
        "actualizado_en": datetime.now(ZONA_HORARIA).isoformat(),
    }
    if usuario_id:
        payload["actualizado_por"] = usuario_id
    supabase.table("configuracion_archivado").upsert(
        payload, on_conflict="id"
    ).execute()
def obtener_configuracion_archivado(supabase, hoy: date | None = None) -> dict:
    hoy = hoy or fecha_local()
    filas = (
        supabase.table("configuracion_archivado")
        .select("id,dia_mes,periodo_inicio,periodo_fin,desplazamiento_fin,ultima_ejecucion,ultimo_error,ultimo_error_en")
        .eq("id", 1)
        .limit(1)
        .execute()
    ).data

    if filas:
        fila = filas[0]
        return {
            "dia_mes": int(fila["dia_mes"]),
            "periodo_inicio": str(fila["periodo_inicio"]),
            "periodo_fin": str(fila["periodo_fin"]),
            "desplazamiento_fin": int(fila.get("desplazamiento_fin", -1)),
            "ultima_ejecucion": fila.get("ultima_ejecucion"),
            "ultimo_error": fila.get("ultimo_error"),
            "ultimo_error_en": fila.get("ultimo_error_en"),
        }

    inicio, fin = periodo_inicial(hoy, DIA_ARCHIVADO_INICIAL)
    primer_cierre = (
        supabase.table("cierres_diarios")
        .select("fecha")
        .order("fecha")
        .limit(1)
        .execute()
    ).data
    if primer_cierre:
        inicio, fin = periodo_que_contiene(
            _fecha(primer_cierre[0]["fecha"]),
            DIA_ARCHIVADO_INICIAL,
            -1,
        )

    config = {
        "dia_mes": DIA_ARCHIVADO_INICIAL,
        "periodo_inicio": inicio.isoformat(),
        "periodo_fin": fin.isoformat(),
        "desplazamiento_fin": -1,
        "ultima_ejecucion": None,
        "ultimo_error": None,
        "ultimo_error_en": None,
    }
    _insertar_evento_configuracion(supabase, config)
    return config
def guardar_dia_archivado(supabase, nuevo_dia: int, usuario_id: str) -> dict:
    if not isinstance(nuevo_dia, int) or not 1 <= nuevo_dia <= 31:
        raise ValueError("El día mensual debe estar entre 1 y 31.")
    hoy = fecha_local()
    config = obtener_configuracion_archivado(supabase, hoy)
    if int(config["dia_mes"]) == nuevo_dia:
        return config

    nuevo_fin, desplazamiento = cambiar_fin_periodo(
        _fecha(config["periodo_inicio"]),
        _fecha(config["periodo_fin"]),
        hoy,
        nuevo_dia,
    )
    config.update({
        "dia_mes": nuevo_dia,
        "periodo_fin": nuevo_fin.isoformat(),
        "desplazamiento_fin": desplazamiento,
        "ultimo_error": None,
        "ultimo_error_en": None,
    })
    _insertar_evento_configuracion(supabase, config, usuario_id)
    return config


def _registrar_error_configuracion(supabase, config: dict, mensaje: str):
    config = dict(config)
    config["ultimo_error"] = mensaje[:1000]
    config["ultimo_error_en"] = datetime.now(ZONA_HORARIA).isoformat()
    _insertar_evento_configuracion(supabase, config)
def _actualizar_configuracion_ejecucion(supabase, config: dict):
    config = dict(config)
    config["ultima_ejecucion"] = datetime.now(ZONA_HORARIA).isoformat()
    config["ultimo_error"] = None
    config["ultimo_error_en"] = None
    _insertar_evento_configuracion(supabase, config)
def _clave_archivo(panaderia_id: int, inicio: date, fin: date) -> str:
    return f"{panaderia_id}|{inicio.isoformat()}|{fin.isoformat()}"


def _nombre_archivo(inicio: date, fin: date) -> str:
    return (
        f"{inicio.day:02d} del {inicio.month:02d} de {inicio.year} "
        f"al {fin.day:02d} del {fin.month:02d} de {fin.year}.xlsx"
    )


def _verificar_archivo_existente(archivo: dict | None, detalles: dict) -> bytes:
    if not archivo or archivo.get("id") != detalles.get("drive_file_id"):
        raise GoogleDriveConfigurationError(
            "No se encontró el archivo histórico verificado en Google Drive. Se detuvo la limpieza de datos pendientes."
        )
    contenido = descargar_archivo_drive(archivo["id"])
    esperado = detalles.get("sha256")
    if not esperado or hashlib.sha256(contenido).hexdigest() != esperado:
        raise GoogleDriveConfigurationError(
            "El archivo histórico no superó la verificación de integridad. Se detuvo la limpieza de datos pendientes."
        )
    return contenido


def _ultimo_evento_archivo(supabase, panaderia_id: int, clave: str):
    filas = (
        supabase.table("archivos_archivados")
        .select("*")
        .eq("panaderia_id", panaderia_id)
        .eq("archive_key", clave)
        .limit(1)
        .execute()
    ).data
    return filas[0] if filas else None


def _registrar_evento_archivo(
    supabase,
    panaderia_id: int,
    inicio: date,
    fin: date,
    clave: str,
    estado: str,
    archivo: dict | None = None,
    error: str | None = None,
):
    existente = _ultimo_evento_archivo(supabase, panaderia_id, clave)
    payload = {
        "panaderia_id": panaderia_id,
        "periodo_inicio": inicio.isoformat(),
        "periodo_fin": fin.isoformat(),
        "archive_key": clave,
        "estado": estado,
        "intentos": int((existente or {}).get("intentos", 0)) + 1,
        "ultimo_error": error[:1000] if error else None,
        "actualizado_en": datetime.now(ZONA_HORARIA).isoformat(),
    }
    if archivo:
        payload.update({
            "drive_file_id": archivo["id"],
            "drive_file_name": archivo["nombre"],
            "sha256": archivo["sha256"],
            "tamano_bytes": archivo["bytes"],
            "verificado_en": datetime.now(ZONA_HORARIA).isoformat(),
            "ultimo_error": None,
        })
    if existente:
        supabase.table("archivos_archivados").update(payload).eq(
            "id", existente["id"]
        ).execute()
    else:
        supabase.table("archivos_archivados").insert(payload).execute()
def _obtener_dias_periodo(supabase, panaderia_id: int, inicio: date, fin: date) -> list[dict]:
    cierres = (
        supabase.table("cierres_diarios")
        .select("id,fecha,estado,cerrado_por_nombre")
        .eq("panaderia_id", panaderia_id)
        .gte("fecha", inicio.isoformat())
        .lte("fecha", fin.isoformat())
        .order("fecha")
        .execute()
    ).data
    if not cierres:
        return []

    ids = [int(c["id"]) for c in cierres]
    detalles = (
        supabase.table("inventario_detalles")
        .select("cierre_id,producto_id,cantidad,precio_unitario,producto_nombre")
        .in_("cierre_id", ids)
        .execute()
    ).data
    if not detalles:
        return []

    producto_ids = sorted({int(d["producto_id"]) for d in detalles if d.get("producto_id")})
    nombres_producto = {}
    if producto_ids:
        productos = (
            supabase.table("productos")
            .select("id,nombre")
            .in_("id", producto_ids)
            .execute()
        ).data
        nombres_producto = {int(p["id"]): p["nombre"] for p in productos}

    guardados = (
        supabase.table("auditoria_inventario")
        .select("cierre_id,usuario_id,creado_en")
        .eq("accion", "guardar_registro")
        .in_("cierre_id", ids)
        .order("creado_en", desc=True)
        .execute()
    ).data
    usuario_por_cierre = {}
    for evento in guardados:
        cierre_id = int(evento["cierre_id"])
        if cierre_id not in usuario_por_cierre and evento.get("usuario_id"):
            usuario_por_cierre[cierre_id] = str(evento["usuario_id"])

    nombres_usuario = {}
    if usuario_por_cierre:
        perfiles = (
            supabase.table("perfiles")
            .select("id,nombre")
            .in_("id", list(set(usuario_por_cierre.values())))
            .execute()
        ).data
        nombres_usuario = {str(p["id"]): p["nombre"] for p in perfiles}

    por_cierre = {}
    for detalle in detalles:
        cierre_id = int(detalle["cierre_id"])
        precio = Decimal(str(detalle.get("precio_unitario") or "0"))
        cantidad = int(detalle.get("cantidad") or 0)
        nombre = (
            detalle.get("producto_nombre")
            or nombres_producto.get(int(detalle["producto_id"]), "Producto histórico")
        )
        por_cierre.setdefault(cierre_id, []).append({
            "producto": nombre,
            "cantidad": cantidad,
            "precio_unitario": str(precio),
            "total": str(precio * cantidad),
        })

    salida = []
    for cierre in cierres:
        cierre_id = int(cierre["id"])
        lineas = por_cierre.get(cierre_id, [])
        if not lineas:
            continue
        usuario_id = usuario_por_cierre.get(cierre_id)
        nombre_cuenta = (
            nombres_usuario.get(usuario_id)
            or cierre.get("cerrado_por_nombre")
            or "Usuario"
        )
        salida.append({
            "cierre": {
                "fecha": _fecha(cierre["fecha"]).isoformat(),
                "cerrado_por_nombre": nombre_cuenta,
            },
            "lineas": lineas,
        })
    return salida


def _archivar_local(supabase, local: dict, inicio: date, fin: date) -> dict:
    local_id = int(local["id"])
    clave = _clave_archivo(local_id, inicio, fin)
    evento = _ultimo_evento_archivo(supabase, local_id, clave)

    if evento and evento.get("estado") == "verificado":
        archivo_existente = obtener_archivo_archivado(clave)
        _verificar_archivo_existente(archivo_existente, evento)
        return {"panaderia_id": local_id, "estado": "ya_verificado"}

    try:
        dias = _obtener_dias_periodo(supabase, local_id, inicio, fin)
        contenido = crear_excel_periodo(str(local["nombre"]), inicio, fin, dias)
        carpeta_id = preparar_carpeta_periodo(str(local["nombre"]), inicio.year)
        archivo = subir_y_verificar_excel(
            carpeta_id,
            _nombre_archivo(inicio, fin),
            contenido,
            clave,
        )
        _registrar_evento_archivo(
            supabase, local_id, inicio, fin, clave, "verificado", archivo=archivo
        )
        return {"panaderia_id": local_id, "estado": "verificado", "archivo": archivo["nombre"]}
    except Exception as exc:
        mensaje = str(exc) if isinstance(exc, GoogleDriveConfigurationError) else (
            "Ocurrió un error al preparar o verificar el archivo de respaldo."
        )
        _registrar_evento_archivo(
            supabase, local_id, inicio, fin, clave, "error", error=mensaje
        )
        raise RuntimeError(mensaje) from exc


def _limpiar_periodos_verificados(supabase, locales: list[dict], hoy: date) -> int:
    limite = hoy - timedelta(days=30)
    eliminados = 0
    for local in locales:
        local_id = int(local["id"])
        eventos = (
            supabase.table("archivos_archivados")
            .select("*")
            .eq("panaderia_id", local_id)
            .eq("estado", "verificado")
            .order("periodo_inicio", desc=True)
            .limit(1000)
            .execute()
        ).data
        for detalles in eventos:
            inicio = _fecha(detalles["periodo_inicio"])
            fin = _fecha(detalles["periodo_fin"])
            if inicio >= limite:
                continue
            clave = detalles["archive_key"]
            archivo = obtener_archivo_archivado(clave)
            _verificar_archivo_existente(archivo, detalles)

            cierres = (
                supabase.table("cierres_diarios")
                .select("id")
                .eq("panaderia_id", local_id)
                .lt("fecha", limite.isoformat())
                .gte("fecha", inicio.isoformat())
                .lte("fecha", fin.isoformat())
                .execute()
            ).data
            ids = [int(c["id"]) for c in cierres]
            if not ids:
                continue

            # La auditoría se conserva, pero se desvincula del cierre que se retira.
            supabase.table("auditoria_inventario").update(
                {"cierre_id": None}
            ).in_("cierre_id", ids).execute()
            supabase.table("inventario_detalles").delete().in_("cierre_id", ids).execute()
            supabase.table("cierres_diarios").delete().in_("id", ids).execute()
            eliminados += len(ids)
    return eliminados
def ejecutar_archivado(supabase) -> dict:
    """Procesa periodos pendientes en orden; nunca avanza si un local falla."""
    hoy = fecha_local()
    config = obtener_configuracion_archivado(supabase, hoy)
    locales = (
        supabase.table("panaderias")
        .select("id,nombre,activa")
        .order("id")
        .execute()
    ).data
    if not locales:
        raise RuntimeError("No hay locales activos para respaldar.")

    periodos_procesados = 0
    archivos_verificados = 0
    inicio = _fecha(config["periodo_inicio"])
    fin = _fecha(config["periodo_fin"])

    try:
        while fin < hoy and periodos_procesados < MAX_PERIODOS_POR_EJECUCION:
            for local in locales:
                resultado = _archivar_local(supabase, local, inicio, fin)
                if resultado["estado"] == "verificado":
                    archivos_verificados += 1

            periodos_procesados += 1
            inicio, fin = siguiente_periodo(
                fin,
                int(config["dia_mes"]),
                int(config.get("desplazamiento_fin", -1)),
            )
            config.update({
                "periodo_inicio": inicio.isoformat(),
                "periodo_fin": fin.isoformat(),
            })
            _insertar_evento_configuracion(supabase, config)

        eliminados = _limpiar_periodos_verificados(supabase, locales, hoy)
        _actualizar_configuracion_ejecucion(supabase, config)
        return {
            "periodos_procesados": periodos_procesados,
            "archivos_verificados": archivos_verificados,
            "registros_retirados": eliminados,
            "periodo_actual_inicio": config["periodo_inicio"],
            "periodo_actual_fin": config["periodo_fin"],
        }
    except Exception as exc:
        mensaje = str(exc) if isinstance(exc, (GoogleDriveConfigurationError, RuntimeError)) else (
            "Ocurrió un error durante el archivado. Los registros se conservaron para reintentar."
        )
        _registrar_error_configuracion(supabase, config, mensaje)
        raise


def obtener_estado_archivado(supabase) -> dict:
    config = obtener_configuracion_archivado(supabase)
    return {
        "dia_mes": config["dia_mes"],
        "periodo_inicio": config["periodo_inicio"],
        "periodo_fin": config["periodo_fin"],
        "ultima_ejecucion": config.get("ultima_ejecucion"),
        "ultimo_error": config.get("ultimo_error"),
        "ultimo_error_en": config.get("ultimo_error_en"),
    }


def obtener_archivo_para_fecha(supabase, panaderia_id: int, fecha: date) -> dict:
    filas = (
        supabase.table("archivos_archivados")
        .select("*")
        .eq("panaderia_id", panaderia_id)
        .eq("estado", "verificado")
        .lte("periodo_inicio", fecha.isoformat())
        .gte("periodo_fin", fecha.isoformat())
        .order("periodo_inicio", desc=True)
        .limit(1)
        .execute()
    ).data
    if not filas:
        raise LookupError("Todavía no hay un archivo histórico para esa fecha.")
    detalles = filas[0]
    clave = detalles["archive_key"]
    archivo = obtener_archivo_archivado(clave)
    contenido = _verificar_archivo_existente(archivo, detalles)
    return {
        "id": archivo["id"],
        "nombre": detalles.get("drive_file_name") or archivo["name"],
        "bytes": contenido,
        "periodo_inicio": str(detalles["periodo_inicio"]),
        "periodo_fin": str(detalles["periodo_fin"]),
    }


def listar_archivos_historicos(supabase, panaderia_id: int) -> list[dict]:
    eventos = (
        supabase.table("archivos_archivados")
        .select("periodo_inicio,periodo_fin,drive_file_name,verificado_en")
        .eq("panaderia_id", panaderia_id)
        .eq("estado", "verificado")
        .order("periodo_inicio", desc=True)
        .limit(1000)
        .execute()
    ).data
    return [
        {
            "periodo_inicio": str(evento["periodo_inicio"]),
            "periodo_fin": str(evento["periodo_fin"]),
            "nombre": evento.get("drive_file_name") or "Inventario histórico.xlsx",
            "verificado_en": evento.get("verificado_en"),
        }
        for evento in eventos
    ]

"""Configuración y ejecución automática de respaldos privados en Cloudflare R2."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
import hmac
import os
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field

from r2_storage import R2ConfigurationError, comprobar_conexion_r2

router = APIRouter()
TZ_LOCAL = ZoneInfo("America/Mexico_City")


def _admin(authorization: str | None):
    from main import exigir_admin_principal
    return exigir_admin_principal(authorization)


def _tabla(nombre: str):
    from main import supabase
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase no está disponible.")
    return supabase.table(nombre)


def _ancla(anio: int, mes: int, dia: int) -> date:
    return date(anio, mes, min(dia, monthrange(anio, mes)[1]))


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def _periodo_inicial(dia: int, hoy: date) -> tuple[str, str]:
    """Periodo que cierra en la frontera mensual actual, ajustando meses cortos."""
    ancla_actual = _ancla(hoy.year, hoy.month, dia)
    anio_previo, mes_previo = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    inicio = _ancla(anio_previo, mes_previo, dia)
    fin = ancla_actual - timedelta(days=1)
    return inicio.isoformat(), fin.isoformat()


def _siguiente_periodo(fin_actual: date, dia: int) -> tuple[str, str]:
    inicio = fin_actual + timedelta(days=1)
    anio_sig, mes_sig = _mes_siguiente(inicio.year, inicio.month)
    fin = _ancla(anio_sig, mes_sig, dia) - timedelta(days=1)
    return inicio.isoformat(), fin.isoformat()


def _dividir_periodo(inicio: date, fin: date):
    cursor = inicio
    while cursor <= fin:
        cierre = min(fin, cursor + timedelta(days=30))
        yield cursor, cierre
        cursor = cierre + timedelta(days=1)


class ConfiguracionArchivado(BaseModel):
    dia_mes: int = Field(ge=1, le=31)


def _crear_ejecucion(periodo_inicio: str, periodo_fin: str) -> dict:
    return _tabla("archivado_ejecuciones").insert({
        "estado": "preparando",
        "periodo_inicio": periodo_inicio,
        "periodo_fin": periodo_fin,
        "fechas_total": 0,
        "fechas_completadas": 0,
        "etapa": "Localizando inventarios con registros.",
        "detalle": [],
    }).execute().data[0]


def _actualizar_ejecucion(ejecucion_id: str, cambios: dict):
    cambios["actualizado_en"] = datetime.now(timezone.utc).isoformat()
    _tabla("archivado_ejecuciones").update(cambios).eq("id", ejecucion_id).execute()


def _hay_ejecucion_activa() -> bool:
    filas = _tabla("archivado_ejecuciones").select("id,actualizado_en").in_(
        "estado", ["preparando", "subiendo", "verificando"]
    ).limit(10).execute().data or []
    ahora = datetime.now(timezone.utc)
    activa = False
    for fila in filas:
        marca = datetime.fromisoformat(str(fila["actualizado_en"]).replace("Z", "+00:00"))
        if marca < ahora - timedelta(hours=6):
            _actualizar_ejecucion(str(fila["id"]), {
                "estado": "error",
                "error": "El proceso se interrumpió antes de terminar. Se volverá a intentar sin eliminar los inventarios originales.",
                "etapa": "Ejecución interrumpida; pendiente de reintento.",
                "terminado_en": ahora.isoformat(),
            })
        else:
            activa = True
    return activa


def _procesar_respaldo(ejecucion_id: str, periodo_inicio: str, periodo_fin: str):
    """Trabaja fuera de la petición web y persiste cada avance para que la UI lo consulte."""
    from main import supabase
    from historial_archivos import _leer_supabase, _subir_archivo_verificado

    inicio = date.fromisoformat(periodo_inicio)
    fin = date.fromisoformat(periodo_fin)
    detalles = []
    total_fechas = 0
    completadas = 0
    try:
        panaderias = (
            supabase.table("panaderias").select("id,nombre")
            .eq("activa", True).order("id").execute().data or []
        )
        preparados = []
        for panaderia in panaderias:
            pid = int(panaderia["id"])
            datos = _leer_supabase(pid, inicio, fin)
            fechas = sorted(datos.keys())
            total_fechas += len(fechas)
            preparados.append((panaderia, datos, fechas))
            detalles.append({
                "panaderia_id": pid,
                "panaderia": panaderia.get("nombre") or f"Panadería {pid}",
                "estado": "pendiente" if fechas else "sin_registros",
                "fechas": [{"fecha": f, "estado": "pendiente" if fechas else "sin_registros"} for f in fechas],
            })
        _actualizar_ejecucion(ejecucion_id, {
            "estado": "subiendo",
            "fechas_total": total_fechas,
            "fechas_completadas": 0,
            "etapa": "Subiendo los archivos de cada panadería.",
            "detalle": detalles,
        })
        for indice, (panaderia, datos, fechas) in enumerate(preparados):
            if not fechas:
                continue
            pid = int(panaderia["id"])
            for chunk_inicio, chunk_fin in _dividir_periodo(inicio, fin):
                historial = [datos[f] for f in fechas if chunk_inicio.isoformat() <= f <= chunk_fin.isoformat()]
                if not historial:
                    continue
                _actualizar_ejecucion(ejecucion_id, {
                    "estado": "subiendo",
                    "etapa": f"Subiendo respaldo de {panaderia.get('nombre') or 'la panadería'}.",
                    "detalle": detalles,
                })
                def al_subir():
                    _actualizar_ejecucion(ejecucion_id, {
                        "estado": "verificando",
                        "etapa": f"Verificando el archivo de {panaderia.get('nombre') or 'la panadería'}.",
                    })
                _subir_archivo_verificado(pid, chunk_inicio, chunk_fin, historial, on_uploaded=al_subir)
                completadas += len(historial)
                for detalle in detalles:
                    if detalle["panaderia_id"] == pid:
                        for fecha_info in detalle["fechas"]:
                            if chunk_inicio.isoformat() <= fecha_info["fecha"] <= chunk_fin.isoformat():
                                fecha_info["estado"] = "verificado"
                        detalle["estado"] = "verificado" if all(x["estado"] == "verificado" for x in detalle["fechas"]) else "en_proceso"
                _actualizar_ejecucion(ejecucion_id, {
                    "estado": "subiendo",
                    "fechas_completadas": completadas,
                    "etapa": "Archivo guardado y verificado.",
                    "detalle": detalles,
                })
        config = _tabla("configuracion_archivado").select("dia_mes").eq("id", 1).limit(1).execute().data or []
        dia = int(config[0]["dia_mes"]) if config else 15
        siguiente_inicio, siguiente_fin = _siguiente_periodo(fin, dia)
        _tabla("configuracion_archivado").update({
            "periodo_inicio": siguiente_inicio,
            "periodo_fin": siguiente_fin,
            "ultima_ejecucion": datetime.now(timezone.utc).isoformat(),
            "ultimo_error": None,
            "ultimo_error_en": None,
        }).eq("id", 1).execute()
        _actualizar_ejecucion(ejecucion_id, {
            "estado": "completado",
            "fechas_total": total_fechas,
            "fechas_completadas": total_fechas,
            "etapa": "Todos los archivos quedaron guardados y verificados.",
            "detalle": detalles,
            "terminado_en": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })
    except Exception as error:
        mensaje = str(error)[:700]
        try:
            _actualizar_ejecucion(ejecucion_id, {
                "estado": "error",
                "fechas_total": total_fechas,
                "fechas_completadas": completadas,
                "etapa": "El respaldo se detuvo. Los inventarios originales se conservaron.",
                "detalle": detalles,
                "error": mensaje,
                "terminado_en": datetime.now(timezone.utc).isoformat(),
            })
            _tabla("configuracion_archivado").update({
                "ultimo_error": mensaje,
                "ultimo_error_en": datetime.now(timezone.utc).isoformat(),
            }).eq("id", 1).execute()
        except Exception:
            pass


def _iniciar_respaldo(background_tasks: BackgroundTasks) -> dict:
    if _hay_ejecucion_activa():
        return {"iniciado": False, "mensaje": "Ya hay un respaldo en ejecución."}
    config = _tabla("configuracion_archivado").select(
        "periodo_inicio,periodo_fin"
    ).eq("id", 1).limit(1).execute().data or []
    if not config:
        return {"iniciado": False, "mensaje": "Primero guarda la configuración de archivado."}
    inicio = config[0]["periodo_inicio"]
    fin = config[0]["periodo_fin"]
    ejecucion = _crear_ejecucion(inicio, fin)
    background_tasks.add_task(_procesar_respaldo, str(ejecucion["id"]), inicio, fin)
    return {"iniciado": True, "ejecucion_id": str(ejecucion["id"])}


@router.get("/api/admin/archivado/estado-r2")
def admin_estado_r2(authorization: str | None = Header(default=None)):
    _admin(authorization)
    try:
        return comprobar_conexion_r2()
    except R2ConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudo comprobar la conexión con Cloudflare R2. Revisa las variables de entorno y los permisos del token.",
        )


@router.get("/api/admin/archivado/configuracion")
def admin_obtener_configuracion(authorization: str | None = Header(default=None)):
    _admin(authorization)
    try:
        filas = _tabla("configuracion_archivado").select(
            "id,dia_mes,periodo_inicio,periodo_fin,ultima_ejecucion,ultimo_error,ultimo_error_en,actualizado_en"
        ).eq("id", 1).limit(1).execute().data or []
        if not filas:
            return {"dia_mes": 15, "configurada": False}
        return {**filas[0], "configurada": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar la configuración de archivado.")


@router.put("/api/admin/archivado/configuracion")
def admin_guardar_configuracion(
    datos: ConfiguracionArchivado,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    usuario, _perfil = _admin(authorization)
    try:
        tabla = _tabla("configuracion_archivado")
        existente = tabla.select(
            "id,dia_mes,periodo_inicio,periodo_fin,desplazamiento_fin"
        ).eq("id", 1).limit(1).execute().data or []
        hoy = datetime.now(TZ_LOCAL).date()
        ancla = _ancla(hoy.year, hoy.month, datos.dia_mes)
        if existente:
            periodo_inicio = date.fromisoformat(str(existente[0]["periodo_inicio"]))
            periodo_fin = ancla - timedelta(days=1)
            if periodo_fin < periodo_inicio:
                anio_sig, mes_sig = _mes_siguiente(hoy.year, hoy.month)
                periodo_fin = _ancla(anio_sig, mes_sig, datos.dia_mes) - timedelta(days=1)
            periodo_inicio_texto = periodo_inicio.isoformat()
            periodo_fin_texto = periodo_fin.isoformat()
            desplazamiento = existente[0].get("desplazamiento_fin", -1)
        else:
            periodo_inicio_texto, periodo_fin_texto = _periodo_inicial(datos.dia_mes, hoy)
            periodo_fin = date.fromisoformat(periodo_fin_texto)
            desplazamiento = -1
        fila = {
            "id": 1,
            "dia_mes": datos.dia_mes,
            "periodo_inicio": periodo_inicio_texto,
            "periodo_fin": periodo_fin_texto,
            "desplazamiento_fin": desplazamiento,
            "actualizado_por": str(usuario.id),
        }
        tabla.upsert(fila, on_conflict="id").execute()
        iniciado = False
        if periodo_fin < hoy:
            resultado = _iniciar_respaldo(background_tasks)
            iniciado = bool(resultado.get("iniciado"))
        return {
            "guardado": True,
            "dia_mes": datos.dia_mes,
            "respaldo_iniciado": iniciado,
            "mensaje": "Configuración guardada. Los periodos anteriores se conservan.",
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar la configuración de archivado.")


@router.get("/api/admin/archivado/estado")
def admin_estado_archivado(authorization: str | None = Header(default=None)):
    _admin(authorization)
    try:
        ejecuciones = _tabla("archivado_ejecuciones").select(
            "id,estado,periodo_inicio,periodo_fin,fechas_total,fechas_completadas,etapa,error,iniciado_en,actualizado_en,terminado_en,detalle"
        ).order("iniciado_en", desc=True).limit(1).execute().data or []
        if ejecuciones:
            actual = ejecuciones[0]
            total = int(actual.get("fechas_total") or 0)
            hechas = int(actual.get("fechas_completadas") or 0)
            actual["progreso"] = round((hechas / total) * 100) if total else (100 if actual["estado"] == "completado" else 0)
            return actual
        return {"estado": "esperando", "progreso": 0, "fechas_total": 0, "fechas_completadas": 0}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar el estado del respaldo.")


@router.get("/api/admin/archivado/detalles")
def admin_detalles_archivado(authorization: str | None = Header(default=None)):
    _admin(authorization)
    try:
        filas = _tabla("archivos_archivados").select(
            "panaderia_id,periodo_inicio,periodo_fin,estado,drive_file_name,tamano_bytes,sha256,verificado_en,ultimo_error,intentos"
        ).order("periodo_fin", desc=True).limit(50).execute().data or []
        ejecuciones = _tabla("archivado_ejecuciones").select(
            "estado,detalle,periodo_inicio,periodo_fin,terminado_en"
        ).order("iniciado_en", desc=True).limit(1).execute().data or []
        return {
            "archivos": filas,
            "fechas": ejecuciones[0].get("detalle", []) if ejecuciones else [],
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar los detalles de los respaldos.")


@router.post("/api/internal/archivado/ejecutar")
def ejecutar_archivado_programado(
    background_tasks: BackgroundTasks,
    request: Request,
):
    esperado = os.environ.get("ARCHIVADO_CRON_SECRET", "")
    recibido = request.headers.get("x-archivado-secret", "")
    if not esperado or not recibido or not hmac.compare_digest(esperado, recibido):
        raise HTTPException(status_code=401, detail="No autorizado.")
    try:
        config = _tabla("configuracion_archivado").select(
            "dia_mes,periodo_fin"
        ).eq("id", 1).limit(1).execute().data or []
        if not config:
            return {"iniciado": False, "mensaje": "Configuración aún no creada."}
        hoy = datetime.now(TZ_LOCAL).date()
        fin = date.fromisoformat(str(config[0]["periodo_fin"]))
        if hoy <= fin:
            return {"iniciado": False, "mensaje": "Todavía no corresponde respaldar este periodo."}
        return _iniciar_respaldo(background_tasks)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo iniciar el respaldo programado.")

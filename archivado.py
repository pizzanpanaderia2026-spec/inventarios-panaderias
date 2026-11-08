"""Configuración y estado del archivado privado en Cloudflare R2."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from r2_storage import R2ConfigurationError, comprobar_conexion_r2

router = APIRouter()


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
    """Devuelve el periodo mensual vigente, respetando el último día de meses cortos."""
    ancla_mes = _ancla(hoy.year, hoy.month, dia)
    if hoy <= ancla_mes:
        anio_sig, mes_sig = _mes_siguiente(hoy.year, hoy.month)
        inicio = _ancla(*((hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)), dia)
        fin = _ancla(anio_sig, mes_sig, dia) - timedelta(days=1)
    else:
        anio_sig, mes_sig = _mes_siguiente(hoy.year, hoy.month)
        inicio = ancla_mes
        fin = _ancla(anio_sig, mes_sig, dia) - timedelta(days=1)
    return inicio.isoformat(), fin.isoformat()


class ConfiguracionArchivado(BaseModel):
    dia_mes: int = Field(ge=1, le=31)


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
    authorization: str | None = Header(default=None),
):
    usuario, _perfil = _admin(authorization)
    try:
        tabla = _tabla("configuracion_archivado")
        existente = tabla.select(
            "id,dia_mes,periodo_inicio,periodo_fin,desplazamiento_fin"
        ).eq("id", 1).limit(1).execute().data or []
        ahora = date.today()
        if existente:
            # No reescribe periodos ya iniciados: únicamente cambia el día de las
            # siguientes fronteras. El proceso de recuperación resolverá el tramo pendiente.
            periodo_inicio = existente[0]["periodo_inicio"]
            periodo_fin = existente[0]["periodo_fin"]
            desplazamiento = existente[0].get("desplazamiento_fin", -1)
        else:
            periodo_inicio, periodo_fin = _periodo_inicial(datos.dia_mes, ahora)
            desplazamiento = -1
        fila = {
            "id": 1,
            "dia_mes": datos.dia_mes,
            "periodo_inicio": periodo_inicio,
            "periodo_fin": periodo_fin,
            "desplazamiento_fin": desplazamiento,
            "actualizado_por": str(usuario.id),
        }
        tabla.upsert(fila, on_conflict="id").execute()
        return {
            "guardado": True,
            "dia_mes": datos.dia_mes,
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
        return {"archivos": filas}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar los detalles de los respaldos.")

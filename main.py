
from pathlib import Path
import os
import unicodedata

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from fastapi.staticfiles import StaticFiles
from supabase import create_client


app = FastAPI(
    title="Inventarios de Panaderías",
    description="Sistema para administrar inventarios de panaderías",
    version="0.2.0",
)


# Conexión con Supabase desde el servidor
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Configuración de archivos estáticos
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


# Página principal
@app.get("/")
def inicio():
    return FileResponse(STATIC_DIR / "index.html")


# Estado general de la API
@app.get("/api")
def estado_api():
    return {
        "mensaje": "La aplicación de inventarios está funcionando."
    }


# Comprobar que el servidor tiene conexión con Supabase.
# No devuelve nombres de panaderías ni información privada.
@app.get("/api/probar-supabase")
def probar_supabase():
    if supabase is None:
        raise HTTPException(
            status_code=503,
            detail="Faltan las variables de conexión en Render.",
        )

    try:
        supabase.table("panaderias").select("id").limit(1).execute()
        return {
            "conectado": True,
            "mensaje": "La conexión con Supabase funciona.",
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudo consultar Supabase.",
        )


# Verificar el token de acceso de Supabase Auth.
def obtener_usuario_autenticado(authorization: str | None):
    if supabase is None:
        raise HTTPException(
            status_code=503,
            detail="El servidor no tiene conexión con Supabase.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Debes iniciar sesión.",
        )

    token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token de acceso vacío.",
        )

    try:
        respuesta = supabase.auth.get_user(token)
        usuario = respuesta.user

        if usuario is None:
            raise HTTPException(
                status_code=401,
                detail="La sesión no es válida.",
            )

        return usuario

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="La sesión no es válida o ha vencido.",
        )


# Obtener el perfil y comprobar que la cuenta esté registrada
# en nuestra tabla de perfiles.
def obtener_perfil(usuario_id: str):
    try:
        respuesta = (
            supabase.table("perfiles")
            .select("id,nombre,rol,es_admin_principal")
            .eq("id", usuario_id)
            .limit(1)
            .execute()
        )

        if not respuesta.data:
            raise HTTPException(
                status_code=403,
                detail="Tu cuenta no tiene un perfil autorizado.",
            )

        return respuesta.data[0]

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudo comprobar el perfil.",
        )


# Identidad del usuario que inició sesión
@app.get("/api/mi-perfil")
def mi_perfil(
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))

    return {
        "id": perfil["id"],
        "nombre": perfil["nombre"],
        "rol": perfil["rol"],
        "es_admin_principal": perfil["es_admin_principal"],
    }


def _panaderias_con_fotografias(filas):
    from locales import foto_url_para_clave
    salida = []
    for fila in filas or []:
        item = dict(fila)
        clave = item.pop("foto_key", None)
        item["foto_url"] = foto_url_para_clave(clave)
        salida.append(item)
    return salida


# Listar únicamente las panaderías autorizadas para el usuario
@app.get("/api/panaderias")
def listar_panaderias(
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))

    try:
        if perfil["rol"] == "admin" and perfil["es_admin_principal"]:
            resultado = (
                supabase.table("panaderias")
                .select("id,nombre,activa,foto_key")
                .order("id")                .execute()
            )
            return {"panaderias": _panaderias_con_fotografias(resultado.data)}

        accesos = (
            supabase.table("accesos_panaderias")
            .select("panaderia_id")
            .eq("usuario_id", str(usuario.id))
            .execute()
        )

        ids = [
            acceso["panaderia_id"]
            for acceso in accesos.data
        ]

        if not ids:
            return {"panaderias": []}

        resultado = (
            supabase.table("panaderias")
            .select("id,nombre,activa,foto_key")
            .in_("id", ids)
            .order("id")
            .execute()
        )

        return {"panaderias": _panaderias_con_fotografias(resultado.data)}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudieron consultar las panaderías.",
        )


from pydantic import BaseModel, Field
from decimal import Decimal


class ProductoNuevo(BaseModel):
    panaderia_id: int = Field(gt=0)
    nombre: str = Field(min_length=1, max_length=120)
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class ProductoCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    activo: bool


def comprobar_acceso_panaderia(usuario_id: str, perfil: dict, panaderia_id: int, permitir_produccion: bool = False):
    if perfil["rol"] == "produccion" and not permitir_produccion:
        raise HTTPException(status_code=403, detail="Tu cuenta no tiene permiso para esta operación.")
    if perfil["rol"] == "admin" and perfil["es_admin_principal"]:
        return
    try:
        acceso = (
            supabase.table("accesos_panaderias")
            .select("panaderia_id")
            .eq("usuario_id", usuario_id)
            .eq("panaderia_id", panaderia_id)
            .limit(1)
            .execute()
        )
        if not acceso.data:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta panadería.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo verificar el acceso a la panadería.")


def exigir_duena_catalogo(perfil: dict):
    if perfil.get("rol") != "admin" or perfil.get("es_admin_principal") is not True:
        raise HTTPException(status_code=403, detail="Solo la dueña puede agregar, editar o eliminar productos y categorías.")


def normalizar_nombre_producto(nombre: str) -> str:
    """Normaliza espacios sin cambiar la escritura que se muestra al usuario."""
    return " ".join(nombre.strip().split())


def clave_nombre_producto(nombre: str) -> str:
    """Clave de comparación: ignora mayúsculas y diacríticos, no los espacios entre palabras."""
    normalizado = unicodedata.normalize("NFD", normalizar_nombre_producto(nombre))
    sin_diacriticos = "".join(
        caracter for caracter in normalizado
        if unicodedata.category(caracter) != "Mn"
    )
    return sin_diacriticos.casefold()


@app.get("/api/productos")
def listar_productos(
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id, permitir_produccion=True)
    try:
        resultado = (
            supabase.table("productos")
            .select("id,panaderia_id,nombre,precio,activo,creado_en")
            .eq("panaderia_id", panaderia_id)
            .order("nombre")
            .execute()
        )
        return {"productos": resultado.data}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar los productos.")


@app.post("/api/productos", status_code=201)
def crear_producto(
    producto: ProductoNuevo,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    exigir_duena_catalogo(perfil)
    comprobar_acceso_panaderia(str(usuario.id), perfil, producto.panaderia_id)
    nombre = normalizar_nombre_producto(producto.nombre)
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe un nombre de producto.")
    try:
        existentes = (
            supabase.table("productos")
            .select("id,nombre,activo,precio")
            .eq("panaderia_id", producto.panaderia_id)
            .execute()
        )
        duplicado = next(
            (p for p in existentes.data
             if clave_nombre_producto(p["nombre"]) == clave_nombre_producto(nombre)),
            None,
        )
        if duplicado:
            if not duplicado.get("activo", True):
                reactivado = (
                    supabase.table("productos")
                    .update({"activo": True})
                    .eq("id", duplicado["id"])
                    .eq("panaderia_id", producto.panaderia_id)
                    .execute()
                )
                if not reactivado.data:
                    raise HTTPException(status_code=409, detail="No se pudo reactivar el producto existente.")
                # Registra la reactivación para mantener trazabilidad.
                supabase.table("auditoria_inventario").insert({
                    "panaderia_id": producto.panaderia_id,
                    "usuario_id": str(usuario.id),
                    "accion": "reactivar_producto",
                    "detalles": {
                        "producto_id": duplicado["id"],
                        "nombre": reactivado.data[0]["nombre"],
                    },
                }).execute()
                return {"producto": reactivado.data[0], "accion": "reactivado"}
            raise HTTPException(status_code=409, detail="El producto ya existe.")
        resultado = supabase.table("productos").insert({
            "panaderia_id": producto.panaderia_id,
            "nombre": nombre,
            "precio": str(producto.precio),
            "activo": True,
        }).execute()
        return {"producto": resultado.data[0]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar el producto.")


@app.patch("/api/productos/{producto_id}")
def actualizar_producto(
    producto_id: int,
    cambio: ProductoCambio,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    exigir_duena_catalogo(perfil)
    try:
        encontrado = (
            supabase.table("productos")
            .select("id,panaderia_id,nombre")
            .eq("id", producto_id)
            .limit(1)
            .execute()
        )
        if not encontrado.data:
            raise HTTPException(status_code=404, detail="No se encontró el producto.")
        actual = encontrado.data[0]
        comprobar_acceso_panaderia(str(usuario.id), perfil, int(actual["panaderia_id"]))
        nombre = normalizar_nombre_producto(cambio.nombre)
        if not nombre:
            raise HTTPException(status_code=422, detail="Escribe un nombre de producto.")
        existentes = (
            supabase.table("productos")
            .select("id,nombre")
            .eq("panaderia_id", actual["panaderia_id"])
            .execute()
        )
        if any(
            int(p["id"]) != producto_id
            and clave_nombre_producto(p["nombre"]) == clave_nombre_producto(nombre)
            for p in existentes.data
        ):
            raise HTTPException(status_code=409, detail="Ya existe otro producto con ese nombre en esta panadería.")
        actualizado = supabase.table("productos").update({
            "nombre": nombre,
            "precio": str(cambio.precio),
            "activo": cambio.activo,
        }).eq("id", producto_id).execute()
        return {"producto": actualizado.data[0]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar el producto.")


@app.delete("/api/productos/{producto_id}")
def eliminar_o_desactivar_producto(
    producto_id: int,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    exigir_duena_catalogo(perfil)
    try:
        encontrado = (
            supabase.table("productos")
            .select("id,panaderia_id")
            .eq("id", producto_id)
            .limit(1)
            .execute()
        )
        if not encontrado.data:
            raise HTTPException(status_code=404, detail="No se encontró el producto.")
        actual = encontrado.data[0]
        comprobar_acceso_panaderia(str(usuario.id), perfil, int(actual["panaderia_id"]))
        usos = (
            supabase.table("inventario_detalles")
            .select("id")
            .eq("producto_id", producto_id)
            .limit(1)
            .execute()
        )
        if usos.data:
            resultado = supabase.table("productos").update({"activo": False}).eq("id", producto_id).execute()
            return {"accion": "desactivado", "producto": resultado.data[0]}
        supabase.table("productos").delete().eq("id", producto_id).execute()
        return {"accion": "eliminado", "id": producto_id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar o desactivar el producto.")


from datetime import date, datetime, timezone
from pydantic import model_validator


class LineaRegistro(BaseModel):
    producto_id: int = Field(gt=0)
    cantidad: int = Field(ge=0)


class GuardarRegistro(BaseModel):
    panaderia_id: int = Field(gt=0)
    fecha: date
    lineas: list[LineaRegistro] = Field(max_length=500)


def obtener_o_crear_cierre(panaderia_id: int, fecha_registro: date, usuario_id: str):
    encontrado = (
        supabase.table("cierres_diarios")
        .select("*")
        .eq("panaderia_id", panaderia_id)
        .eq("fecha", fecha_registro.isoformat())
        .limit(1)
        .execute()
    )
    if encontrado.data:
        return encontrado.data[0]
    # ON CONFLICT DO NOTHING evita capturar excepciones ajenas a una
    # colisión simultánea y respeta la restricción única panadería/fecha.
    creado = (
        supabase.table("cierres_diarios")
        .upsert(
            {
                "panaderia_id": panaderia_id,
                "fecha": fecha_registro.isoformat(),
                "estado": "abierto",
            },
            on_conflict="panaderia_id,fecha",
            ignore_duplicates=True,
        )
        .execute()
    )
    if creado.data:
        return creado.data[0]

    # Si otra solicitud ganó la carrera, recupera el cierre ya creado.
    reintento = (
        supabase.table("cierres_diarios").select("*")
        .eq("panaderia_id", panaderia_id)
        .eq("fecha", fecha_registro.isoformat()).limit(1).execute()
    )
    if not reintento.data:
        raise HTTPException(status_code=503, detail="No se pudo preparar el registro diario.")
    return reintento.data[0]


@app.get("/api/registro")
def consultar_registro(
    panaderia_id: int,
    fecha_registro: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    try:
        cierre = (
            supabase.table("cierres_diarios").select("*")
            .eq("panaderia_id", panaderia_id)
            .eq("fecha", fecha_registro.isoformat()).limit(1).execute()
        )
        if not cierre.data:
            return {"cierre": None, "lineas": []}
        datos_cierre = cierre.data[0]
        lineas = (
            supabase.table("inventario_detalles")
            .select("id,producto_id,cantidad,precio_unitario,producto_nombre")
            .eq("cierre_id", datos_cierre["id"]).execute()
        )
        return {"cierre": datos_cierre, "lineas": lineas.data}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar el registro diario.")


@app.put("/api/registro")
def guardar_registro(
    registro: GuardarRegistro,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, registro.panaderia_id)
    hoy_local = datetime.now(TZ_PRODUCCION).date()
    if registro.fecha > hoy_local:
        raise HTTPException(status_code=422, detail="No puedes registrar una fecha futura.")
    dias_inventario = obtener_configuracion_edicion()["dias_inventario"]
    dias_transcurridos = (hoy_local - registro.fecha).days
    if dias_transcurridos > dias_inventario and not es_admin_principal(perfil):
        raise HTTPException(status_code=403, detail=f"El plazo para editar inventario es de {dias_inventario} días.")
    ids = [linea.producto_id for linea in registro.lineas]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="No repitas el mismo producto en el registro.")
    try:
        cierre = obtener_o_crear_cierre(registro.panaderia_id, registro.fecha, str(usuario.id))
        if cierre["estado"] == "cerrado":
            dias_inventario = obtener_configuracion_edicion()["dias_inventario"]
            dias_transcurridos = (datetime.now(TZ_PRODUCCION).date() - registro.fecha).days
            es_admin_principal = perfil["rol"] == "admin" and perfil["es_admin_principal"]
            if (dias_transcurridos > dias_inventario or dias_transcurridos < 0) and not es_admin_principal:
                raise HTTPException(status_code=403, detail=f"El plazo para editar inventario es de {dias_inventario} días. Solo la dueña puede reabrirlo fuera de ese plazo.")
            # Todo cierre debe reabrirse por el endpoint específico antes de editar.
            # Así se exige motivo y auditoría en correcciones administrativas tardías.
            raise HTTPException(
                status_code=409,
                detail="El día está cerrado. Usa la opción de reabrir antes de modificarlo.",
            )
        productos = (
            supabase.table("productos")
            .select("id,panaderia_id,nombre,precio,activo")
            .eq("panaderia_id", registro.panaderia_id).execute()
        )
        por_id = {int(p["id"]): p for p in productos.data}
        # Conserva el precio histórico ya guardado para cada producto.
        # Solo los productos nuevos en este registro toman el precio actual.
        anteriores = (
            supabase.table("inventario_detalles")
            .select("producto_id,precio_unitario,producto_nombre")
            .eq("cierre_id", cierre["id"])
            .execute()
        )
        precios_anteriores = {
            int(item["producto_id"]): item.get("precio_unitario")
            for item in anteriores.data
        }
        nombres_anteriores = {
            int(item["producto_id"]): item.get("producto_nombre")
            for item in anteriores.data
        }
        nuevas = []
        for linea in registro.lineas:
            producto = por_id.get(linea.producto_id)
            if not producto or not producto["activo"]:
                raise HTTPException(status_code=422, detail="Uno de los productos no existe o está inactivo.")
            nuevas.append({                "cierre_id": cierre["id"],
                "producto_id": linea.producto_id,
                "cantidad": linea.cantidad,
                "producto_nombre": (
                    nombres_anteriores.get(linea.producto_id)
                    or next(
                        (p["nombre"] for p in productos.data if int(p["id"]) == linea.producto_id),
                        "Producto",
                    )
                ),
                "precio_unitario": str(
                    precios_anteriores.get(linea.producto_id)
                    if precios_anteriores.get(linea.producto_id) is not None
                    else producto["precio"]
                ),
            })
        lineas_rpc = [
            {
                "producto_id": linea["producto_id"],
                "cantidad": linea["cantidad"],
                "precio_unitario": linea["precio_unitario"],
                "producto_nombre": linea["producto_nombre"],
            }
            for linea in nuevas
        ]
        # Una sola función SQL reemplaza las líneas dentro de una transacción.
        supabase.rpc("reemplazar_lineas_cierre", {
            "p_cierre_id": cierre["id"],
            "p_lineas": lineas_rpc,
            "p_usuario_id": str(usuario.id),
        }).execute()
        return {"guardado": True, "cierre_id": cierre["id"], "cantidad_lineas": len(nuevas)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar el registro. Verifica que la migración esté aplicada.")


@app.post("/api/registro/cerrar")
def cerrar_registro(
    panaderia_id: int,
    fecha_registro: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    if fecha_registro > datetime.now(TZ_PRODUCCION).date():
        raise HTTPException(status_code=422, detail="No puedes cerrar una fecha futura.")
    try:
        cierre = obtener_o_crear_cierre(panaderia_id, fecha_registro, str(usuario.id))
        if cierre["estado"] == "cerrado":
            return {"cerrado": True, "cerrado_en": cierre["cerrado_en"], "mensaje": "Este día ya estaba cerrado."}
        lineas_guardadas = (
            supabase.table("inventario_detalles")
            .select("id")
            .eq("cierre_id", cierre["id"])
            .limit(1)
            .execute()
        )
        if not lineas_guardadas.data:
            raise HTTPException(
                status_code=409,
                detail="Primero guarda al menos un producto en el registro del día.",
            )

        ahora = datetime.now(timezone.utc).isoformat()
        resultado = supabase.rpc("cerrar_cierre_diario", {
            "p_cierre_id": cierre["id"],
            "p_usuario_id": str(usuario.id),
            "p_fecha": ahora,
        }).execute()
        cierre_actualizado = resultado.data
        return {"cerrado": True, "cierre": cierre_actualizado}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo cerrar el día. Verifica que la migración esté aplicada.")



class SolicitudReapertura(BaseModel):
    panaderia_id: int = Field(gt=0)
    fecha: date
    motivo: str | None = Field(default=None, max_length=500)


def es_admin_principal(perfil: dict) -> bool:
    return perfil.get("rol") == "admin" and perfil.get("es_admin_principal") is True


def buscar_cierre(panaderia_id: int, fecha_registro: date):
    resultado = (
        supabase.table("cierres_diarios").select("*")
        .eq("panaderia_id", panaderia_id)
        .eq("fecha", fecha_registro.isoformat()).limit(1).execute()
    )
    if not resultado.data:
        raise HTTPException(status_code=404, detail="No hay un cierre registrado para esa fecha.")
    return resultado.data[0]


@app.post("/api/registro/reabrir")
def reabrir_registro(
    solicitud: SolicitudReapertura,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, solicitud.panaderia_id)
    try:
        cierre = buscar_cierre(solicitud.panaderia_id, solicitud.fecha)
        if cierre["estado"] != "cerrado":
            return {"reabierto": True, "mensaje": "El día ya está abierto."}
        if solicitud.fecha > datetime.now(TZ_PRODUCCION).date():
            raise HTTPException(status_code=422, detail="No puedes reabrir una fecha futura.")
        ahora_local = datetime.now(TZ_PRODUCCION).date()
        dias_inventario = obtener_configuracion_edicion()["dias_inventario"]
        dentro_del_plazo = 0 <= (ahora_local - solicitud.fecha).days <= dias_inventario
        admin = es_admin_principal(perfil)
        if not dentro_del_plazo and not admin:
            raise HTTPException(status_code=403, detail=f"El plazo para editar inventario es de {dias_inventario} días. Solo la dueña puede reabrir registros anteriores.")
        motivo = (solicitud.motivo or "").strip()
        if not dentro_del_plazo and admin and len(motivo) < 5:
            raise HTTPException(status_code=422, detail="Para una corrección fuera del plazo configurado, escribe un motivo de al menos 5 caracteres.")
        resultado = supabase.rpc("reabrir_cierre_diario", {
            "p_cierre_id": cierre["id"],
            "p_usuario_id": str(usuario.id),
            "p_motivo": motivo or "",
            "p_dentro_de_48h": dentro_del_plazo,
            "p_fecha": ahora.isoformat(),
        }).execute()
        return {"reabierto": True, "cierre": resultado.data}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo reabrir el registro. Verifica que la migración esté aplicada.")




def obtener_datos_ultimo_cierre(panaderia_id: int, usuario_id: str, perfil: dict, permitir_produccion: bool = False):
    comprobar_acceso_panaderia(usuario_id, perfil, panaderia_id, permitir_produccion=permitir_produccion)
    cierres = (
        supabase.table("cierres_diarios")
        .select("id,panaderia_id,fecha,estado,cerrado_por,cerrado_por_nombre")
        .eq("panaderia_id", panaderia_id)
        .eq("estado", "cerrado")
        .order("fecha", desc=True)
        .limit(1)
        .execute()
    ).data
    if not cierres:
        return None
    cierre = cierres[0]
    nombre_usuario = cierre.get("cerrado_por_nombre")
    if not nombre_usuario and cierre.get("cerrado_por"):
        perfil_cierre = (
            supabase.table("perfiles").select("nombre")
            .eq("id", cierre["cerrado_por"]).limit(1).execute()
        ).data
        if perfil_cierre:
            nombre_usuario = perfil_cierre[0].get("nombre")
    cierre["cerrado_por_nombre"] = nombre_usuario or "Usuario"
    filas_produccion = (
        supabase.table("produccion_registros")
        .select("pan_nombre,cantidad")
        .eq("panaderia_id", panaderia_id)
        .eq("fecha_produccion", cierre["fecha"])
        .execute()
    ).data
    acumulado_produccion = {}
    for fila in filas_produccion:
        nombre_pan = " ".join(str(fila.get("pan_nombre") or "").split())
        if not nombre_pan:
            continue
        acumulado_produccion[nombre_pan] = acumulado_produccion.get(nombre_pan, 0) + int(fila.get("cantidad") or 0)
    tabla_produccion = [
        {"producto": nombre, "cantidad": cantidad}
        for nombre, cantidad in sorted(acumulado_produccion.items(), key=lambda item: item[0].casefold())
    ]
    total_produccion = sum(item["cantidad"] for item in tabla_produccion)
    detalles = (
        supabase.table("inventario_detalles")
        .select("producto_id,cantidad,precio_unitario,producto_nombre")
        .eq("cierre_id", cierre["id"])
        .execute()
    ).data
    lineas = []
    resumen = {}
    total_piezas = 0
    total_importe = Decimal("0")
    for detalle in detalles:
        cantidad = int(detalle.get("cantidad") or 0)
        precio = Decimal(str(detalle.get("precio_unitario") or "0"))
        importe = precio * cantidad
        nombre = detalle.get("producto_nombre") or f"Producto {detalle.get('producto_id')}"
        lineas.append({
            "producto": nombre,
            "cantidad": cantidad,
            "precio_unitario": str(precio),
            "total": str(importe),
        })
        clave = precio.quantize(Decimal("0.01"))
        if clave not in resumen:
            resumen[clave] = {"cantidad": 0, "total": Decimal("0")}
        resumen[clave]["cantidad"] += cantidad
        resumen[clave]["total"] += importe
        total_piezas += cantidad
        total_importe += importe
    resumen_salida = [
        {"precio": str(precio), "cantidad": valores["cantidad"], "total": str(valores["total"])}
        for precio, valores in sorted(resumen.items())
    ]
    return {
        "cierre": cierre,
        "lineas": lineas,
        "resumen": resumen_salida,
        "total_piezas": total_piezas,
        "total_importe": str(total_importe),
        "produccion": {"fecha": cierre["fecha"], "lineas": tabla_produccion, "total_cantidad": total_produccion},
    }


@app.get("/api/tablas/ultimo-cierre")
def consultar_tablas_ultimo_cierre(
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id, permitir_produccion=True)
    try:
        datos = obtener_datos_ultimo_cierre(panaderia_id, str(usuario.id), perfil, permitir_produccion=True)
        return datos or {"cierre": None, "lineas": [], "resumen": [], "total_piezas": 0, "total_importe": "0", "produccion": {"fecha": None, "lineas": [], "total_cantidad": 0}}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar las tablas del último cierre.")


@app.get("/api/tablas/ultimo-cierre/excel")
def descargar_tablas_ultimo_cierre_excel(
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id, permitir_produccion=True)
    try:
        datos = obtener_datos_ultimo_cierre(panaderia_id, str(usuario.id), perfil, permitir_produccion=True)
        if not datos:
            raise HTTPException(status_code=404, detail="Todavía no hay un día cerrado para descargar.")
        cierre = datos["cierre"]
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Cierre del día"
        hoja.sheet_view.showGridLines = False
        hoja.merge_cells("A1:D1")
        hoja["A1"] = "INVENTARIO Y PRODUCCIÓN DIARIA"
        hoja["A1"].font = Font(name="Arial", size=16, bold=True, color="FFFFFF")
        hoja["A1"].fill = PatternFill("solid", fgColor="713F12")
        hoja["A1"].alignment = Alignment(horizontal="center", vertical="center")
        hoja.row_dimensions[1].height = 28
        hoja.merge_cells("A2:D2")
        hoja["A2"] = f"Fecha: {cierre['fecha']}"
        hoja["A2"].font = Font(name="Arial", size=12, bold=True, color="292524")
        hoja["A2"].alignment = Alignment(horizontal="left")
        hoja.merge_cells("A3:D3")
        hoja["A3"] = f"Cerrado por: {cierre.get('cerrado_por_nombre') or 'Usuario'}"
        hoja["A3"].font = Font(name="Arial", size=10, italic=True, color="78716C")
        hoja["A3"].alignment = Alignment(horizontal="left")
        
        def encabezado_tabla(fila, titulo, columnas):
            hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=len(columnas))
            celda = hoja.cell(fila, 1, titulo)
            celda.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="8A5A2B")
            celda.alignment = Alignment(horizontal="left")
            fila += 1
            for columna, texto in enumerate(columnas, start=1):
                c = hoja.cell(fila, columna, texto)
                c.font = Font(name="Arial", bold=True, color="292524")
                c.fill = PatternFill("solid", fgColor="F3E8D8")
                c.alignment = Alignment(horizontal="center")
                c.border = Border(bottom=Side(style="thin", color="D6C6B5"))
            return fila + 1

        fila = encabezado_tabla(5, "TABLA A · DETALLE POR PRODUCTO", ["Producto", "Cantidad", "Precio unitario", "Importe"])
        for linea in datos["lineas"]:
            hoja.cell(fila, 1, linea["producto"])
            hoja.cell(fila, 2, int(linea["cantidad"]))
            hoja.cell(fila, 3, float(Decimal(linea["precio_unitario"])))
            hoja.cell(fila, 4, float(Decimal(linea["total"])))
            hoja.cell(fila, 3).number_format = '"$"#,##0.00'
            hoja.cell(fila, 4).number_format = '"$"#,##0.00'
            fila += 1
        hoja.cell(fila, 1, "TOTAL GENERAL")
        hoja.cell(fila, 2, datos["total_piezas"])
        hoja.cell(fila, 4, float(Decimal(datos["total_importe"])))
        hoja.cell(fila, 4).number_format = '"$"#,##0.00'
        for c in hoja[fila][:4]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3E8D8")
        fila += 2
        fila = encabezado_tabla(fila, "TABLA B · RESUMEN POR PRECIO", ["Precio unitario", "Cantidad total", "Importe"])
        for linea in datos["resumen"]:
            hoja.cell(fila, 1, float(Decimal(linea["precio"])))
            hoja.cell(fila, 2, int(linea["cantidad"]))
            hoja.cell(fila, 3, float(Decimal(linea["total"])))
            hoja.cell(fila, 1).number_format = '"$"#,##0.00'
            hoja.cell(fila, 3).number_format = '"$"#,##0.00'
            fila += 1
        hoja.cell(fila, 1, "TOTAL GENERAL")
        hoja.cell(fila, 2, datos["total_piezas"])
        hoja.cell(fila, 3, float(Decimal(datos["total_importe"])))
        hoja.cell(fila, 3).number_format = '"$"#,##0.00'
        for c in hoja[fila][:3]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3E8D8")
        fila += 2
        fila = encabezado_tabla(fila, "PRODUCCIÓN · DETALLE POR PRODUCTO", ["Producto producido", "Cantidad"])
        produccion = datos.get("produccion") or {"lineas": [], "total_cantidad": 0}
        for linea in produccion.get("lineas", []):
            hoja.cell(fila, 1, linea["producto"])
            hoja.cell(fila, 2, int(linea["cantidad"]))
            fila += 1
        hoja.cell(fila, 1, "TOTAL PRODUCCIÓN")
        hoja.cell(fila, 2, int(produccion.get("total_cantidad") or 0))
        for c in hoja[fila][:2]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="F3E8D8")

        for row in hoja.iter_rows(min_row=5, max_row=fila, min_col=1, max_col=4):
            for c in row:
                c.alignment = Alignment(vertical="center", wrap_text=True)
                if c.row > 5 and c.row not in (fila,):
                    c.border = Border(bottom=Side(style="hair", color="E7DED2"))
        for col, width in {"A": 38, "B": 15, "C": 19, "D": 19}.items():
            hoja.column_dimensions[col].width = width
        hoja.freeze_panes = "A6"
        hoja.sheet_properties.pageSetUpPr.fitToPage = True
        hoja.page_setup.orientation = "landscape"
        hoja.page_setup.paperSize = hoja.PAPERSIZE_A4
        hoja.page_setup.fitToWidth = 1
        hoja.page_setup.fitToHeight = 1
        hoja.page_margins.left = 0.25
        hoja.page_margins.right = 0.25
        hoja.page_margins.top = 0.35
        hoja.page_margins.bottom = 0.35
        hoja.print_area = f"A1:D{fila}"
        hoja.sheet_properties.pageSetUpPr.autoPageBreaks = False
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = f"cierre_diario_{panaderia_id}_{cierre['fecha']}.xlsx"
        return StreamingResponse(
            salida,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el Excel del cierre.")


@app.get("/api/historial")
def consultar_historial(
    panaderia_id: int,
    desde: date,
    hasta: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    hoy = date.today()
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la fecha final.")
    if hasta > hoy:
        raise HTTPException(status_code=422, detail="La fecha final no puede estar en el futuro.")
    if (hasta - desde).days > 29 or (hoy - desde).days > 29:
        raise HTTPException(status_code=422, detail="El historial disponible en la aplicación se limita a los últimos 30 días.")
    try:
        cierres = (
            supabase.table("cierres_diarios").select("id,fecha,estado,cerrado_en")
            .eq("panaderia_id", panaderia_id)
            .gte("fecha", desde.isoformat()).lte("fecha", hasta.isoformat())
            .order("fecha", desc=True).execute()
        )
        salida = []
        for cierre in cierres.data:
            detalles = (
                supabase.table("inventario_detalles")
                .select("producto_id,cantidad,precio_unitario,producto_nombre")
                .eq("cierre_id", cierre["id"]).execute()
            )
            productos_ids = [int(d["producto_id"]) for d in detalles.data]
            nombres = {}
            if productos_ids:
                productos = supabase.table("productos").select("id,nombre").in_("id", productos_ids).execute()
                nombres = {int(p["id"]): p["nombre"] for p in productos.data}
            lineas = []
            for d in detalles.data:
                precio = Decimal(str(d.get("precio_unitario") or "0"))
                cantidad = int(d["cantidad"])
                lineas.append({                    "producto_id": d["producto_id"],
                    "producto": d.get("producto_nombre") or nombres.get(int(d["producto_id"]), "Producto histórico"),
                    "cantidad": cantidad,
                    "precio_unitario": str(precio),
                    "total": str(precio * cantidad),
                })
            salida.append({"cierre": cierre, "lineas": lineas})
        return {"historial": salida}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar el historial. Verifica que la migración esté aplicada.")



@app.get("/api/historial/excel")
def descargar_historial_excel(
    panaderia_id: int,
    desde: date,
    hasta: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    hoy = date.today()
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la fecha final.")
    if hasta > hoy:
        raise HTTPException(status_code=422, detail="La fecha final no puede estar en el futuro.")
    if (hasta - desde).days > 29 or (hoy - desde).days > 29:
        raise HTTPException(status_code=422, detail="La descarga se limita a los últimos 30 días.")
    try:
        datos = consultar_historial(panaderia_id, desde, hasta, authorization)
        historial = datos["historial"]
        libro = Workbook()
        detalle = libro.active
        detalle.title = "Detalle"
        detalle.append(["Fecha", "Producto", "Cantidad", "Precio unitario", "Total"])
        resumen = {}
        total_general = Decimal("0")
        for dia in historial:
            fecha_texto = str(dia["cierre"]["fecha"])
            for linea in dia["lineas"]:
                precio = Decimal(str(linea["precio_unitario"]))
                cantidad = int(linea["cantidad"])
                total = Decimal(str(linea["total"]))
                detalle.append([fecha_texto, linea["producto"], cantidad, float(precio), float(total)])
                clave = precio.quantize(Decimal("0.01"))
                if clave not in resumen:
                    resumen[clave] = {"cantidad": 0, "total": Decimal("0")}
                resumen[clave]["cantidad"] += cantidad
                resumen[clave]["total"] += total
                total_general += total
        detalle.freeze_panes = "A2"
        detalle.auto_filter.ref = detalle.dimensions
        for col, width in {"A": 14, "B": 30, "C": 14, "D": 18, "E": 18}.items():
            detalle.column_dimensions[col].width = width
        hoja_resumen = libro.create_sheet("Resumen")
        hoja_resumen.append(["Precio", "Cantidad total", "Importe"])
        cantidad_general = 0
        for precio, valores in sorted(resumen.items()):
            hoja_resumen.append([float(precio), valores["cantidad"], float(valores["total"])])
            cantidad_general += valores["cantidad"]
        hoja_resumen.append(["TOTAL GENERAL", cantidad_general, float(total_general)])
        hoja_resumen.freeze_panes = "A2"
        for col, width in {"A": 20, "B": 20, "C": 20}.items():
            hoja_resumen.column_dimensions[col].width = width
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = f"historial_panaderia_{panaderia_id}_{desde.isoformat()}_{hasta.isoformat()}.xlsx"
        return StreamingResponse(
            salida,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el Excel.")


@app.get("/api/productos/precios/excel")
def descargar_lista_precios(
    authorization: str | None = Header(default=None),
):
    """Descarga bajo demanda el historial de precios que sí quedó registrado."""
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    if perfil.get("rol") == "produccion":
        raise HTTPException(status_code=403, detail="Tu cuenta solo tiene acceso al módulo de Producción.")
    try:
        if es_admin_principal(perfil):
            panaderias = (
                supabase.table("panaderias")
                .select("id,nombre")
                .order("nombre")
                .execute()
            ).data
        else:
            accesos = (
                supabase.table("accesos_panaderias")
                .select("panaderia_id")
                .eq("usuario_id", str(usuario.id))
                .execute()
            ).data
            ids = [int(x["panaderia_id"]) for x in accesos]
            if not ids:
                raise HTTPException(status_code=403, detail="Tu cuenta no tiene panaderías asignadas.")
            panaderias = (
                supabase.table("panaderias")
                .select("id,nombre")
                .in_("id", ids)
                .order("nombre")
                .execute()
            ).data

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Lista de productos"
        hoja.append(["Panadería", "Producto", "Fecha del precio", "Precio"])
        for panaderia in panaderias:
            productos = (
                supabase.table("productos")
                .select("id,nombre,precio,creado_en")
                .eq("panaderia_id", panaderia["id"])
                .order("nombre")
                .execute()
            ).data
            if not productos:
                continue
            ids_productos = [int(p["id"]) for p in productos]
            detalles = (
                supabase.table("inventario_detalles")
                .select("producto_id,precio_unitario,cierre_id,registrado_en")
                .in_("producto_id", ids_productos)
                .order("registrado_en")
                .execute()
            ).data
            cierres_ids = list({int(d["cierre_id"]) for d in detalles if d.get("cierre_id") is not None})
            fechas_cierres = {}
            if cierres_ids:
                cierres = (
                    supabase.table("cierres_diarios")
                    .select("id,fecha")
                    .in_("id", cierres_ids)
                    .execute()
                ).data
                fechas_cierres = {int(c["id"]): c["fecha"] for c in cierres}

            por_producto = {}
            for detalle in detalles:
                pid = int(detalle["producto_id"])
                fecha = fechas_cierres.get(int(detalle["cierre_id"])) if detalle.get("cierre_id") is not None else None
                fecha = fecha or (str(detalle.get("registrado_en", ""))[:10] or "")
                por_producto.setdefault(pid, []).append((fecha, detalle["precio_unitario"]))

            for producto in productos:
                historial = por_producto.get(int(producto["id"]), [])
                if historial:
                    # Una fila por precio observado en un registro; conserva los cambios históricos.
                    for fecha, precio in historial:
                        hoja.append([panaderia["nombre"], producto["nombre"], fecha, float(Decimal(str(precio)))])
                else:
                    # Producto existente en catálogo pero nunca incluido en un registro.
                    fecha = str(producto.get("creado_en", ""))[:10]
                    hoja.append([panaderia["nombre"], producto["nombre"], fecha, float(Decimal(str(producto["precio"])))])
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions
        for col, width in {"A": 24, "B": 36, "C": 20, "D": 16}.items():
            hoja.column_dimensions[col].width = width
        for fila in range(2, hoja.max_row + 1):
            hoja.cell(fila, 4).number_format = '"$"#,##0.00'
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        return StreamingResponse(
            salida,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="lista_de_productos.xlsx"'},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar la lista de productos.")

# Resumen agregado de inventario por periodo (máximo 30 días).
@app.get("/api/inventario/resumen/excel")
def descargar_resumen_periodo(
    panaderia_id: int,
    desde: date,
    hasta: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    hoy = date.today()
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial debe ser anterior a la fecha final.")
    if (hasta - desde).days > 29:
        raise HTTPException(status_code=422, detail="El periodo máximo es de 30 días.")
    if hasta > hoy or desde < hoy - __import__("datetime").timedelta(days=29):
        raise HTTPException(status_code=422, detail="Solo puedes consultar los últimos 30 días.")
    try:
        cierres = supabase.table("cierres_diarios").select("id,fecha,estado").eq("panaderia_id", panaderia_id).gte("fecha", desde.isoformat()).lte("fecha", hasta.isoformat()).order("fecha").execute().data
        cierre_ids = [int(c["id"]) for c in cierres]
        lineas = []
        if cierre_ids:
            lineas = supabase.table("inventario_detalles").select("cierre_id,producto_id,cantidad,precio_unitario,producto_nombre").in_("cierre_id", cierre_ids).execute().data
        fechas = {int(c["id"]): str(c["fecha"]) for c in cierres}
        acumulado = {}
        diario = {}
        for linea in lineas:
            fecha = fechas.get(int(linea["cierre_id"]), "")
            nombre = linea.get("producto_nombre") or f"Producto {linea['producto_id']}"
            cantidad = int(linea.get("cantidad") or 0)
            precio = Decimal(str(linea.get("precio_unitario") or 0))
            key = (nombre, precio)
            acumulado[key] = acumulado.get(key, 0) + cantidad
            diario.setdefault(fecha, {})
            diario[fecha][key] = diario[fecha].get(key, 0) + cantidad

        libro = Workbook()
        resumen = libro.active
        resumen.title = "Resumen del periodo"
        resumen.append(["Producto", "Precio unitario", "Cantidad total", "Importe total"])
        for (nombre, precio), cantidad in sorted(acumulado.items(), key=lambda x: (x[0][0].casefold(), x[0][1])):
            resumen.append([nombre, float(precio), cantidad, float(precio * cantidad)])
        resumen.freeze_panes = "A2"
        resumen.auto_filter.ref = resumen.dimensions
        for col, width in {"A": 36, "B": 18, "C": 18, "D": 18}.items():
            resumen.column_dimensions[col].width = width
        for row in range(2, resumen.max_row + 1):
            resumen.cell(row, 2).number_format = '"$"#,##0.00'
            resumen.cell(row, 4).number_format = '"$"#,##0.00'

        detalle = libro.create_sheet("Detalle diario")
        detalle.append(["Fecha", "Producto", "Precio unitario", "Cantidad", "Importe"])
        for fecha in sorted(diario):
            for (nombre, precio), cantidad in sorted(diario[fecha].items(), key=lambda x: (x[0][0].casefold(), x[0][1])):
                detalle.append([fecha, nombre, float(precio), cantidad, float(precio * cantidad)])
        detalle.freeze_panes = "A2"
        detalle.auto_filter.ref = detalle.dimensions
        for col, width in {"A": 16, "B": 36, "C": 18, "D": 14, "E": 18}.items():
            detalle.column_dimensions[col].width = width
        for row in range(2, detalle.max_row + 1):
            detalle.cell(row, 3).number_format = '"$"#,##0.00'
            detalle.cell(row, 5).number_format = '"$"#,##0.00'

        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre_archivo = f"resumen_inventario_{panaderia_id}_{desde.isoformat()}_{hasta.isoformat()}.xlsx"
        return StreamingResponse(salida, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el resumen del periodo.")


# Administración de cuentas: solo la administradora principal puede acceder.
from pydantic import BaseModel, Field


def exigir_admin_principal(authorization: str | None):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    if not es_admin_principal(perfil):
        raise HTTPException(status_code=403, detail="Solo la administradora principal puede gestionar cuentas.")
    return usuario, perfil

class ConfiguracionEdicionCambio(BaseModel):
    dias_inventario: int = Field(ge=0, le=365)
    dias_produccion: int = Field(ge=0, le=365)


def obtener_configuracion_edicion():
    try:
        filas = supabase.table("configuracion_edicion").select("dias_inventario,dias_produccion").eq("id", 1).limit(1).execute().data or []
        if filas:
            return {"dias_inventario": int(filas[0]["dias_inventario"]), "dias_produccion": int(filas[0]["dias_produccion"])}
        supabase.table("configuracion_edicion").insert({"id": 1, "dias_inventario": 2, "dias_produccion": 1}).execute()
        return {"dias_inventario": 2, "dias_produccion": 1}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar la configuración de días editables.")


@app.get("/api/admin/configuracion-edicion")
def admin_obtener_configuracion_edicion(authorization: str | None = Header(default=None)):
    exigir_admin_principal(authorization)
    return obtener_configuracion_edicion()


@app.put("/api/admin/configuracion-edicion")
def admin_guardar_configuracion_edicion(datos: ConfiguracionEdicionCambio, authorization: str | None = Header(default=None)):
    usuario, _ = exigir_admin_principal(authorization)
    try:
        supabase.table("configuracion_edicion").upsert({
            "id": 1, "dias_inventario": datos.dias_inventario,
            "dias_produccion": datos.dias_produccion,
            "actualizado_por": str(usuario.id), "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="id").execute()
        return {"guardado": True, **obtener_configuracion_edicion()}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar la configuración de días editables.")



def email_interno_encargado(username: str) -> str:
    limpio = "".join(c.lower() for c in username if c.isalnum() or c in "._-")
    if not limpio or limpio != username.lower():
        raise HTTPException(status_code=422, detail="El usuario solo puede contener letras, números, punto, guion y guion bajo.")
    return f"{limpio}@usuarios.pizzan.invalid"


class CuentaEncargadoNueva(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    tipo_usuario: str = Field(default="encargado", pattern="^(encargado|produccion)$")
    locales: list[int] = Field(min_length=1, max_length=100)


class CuentaEncargadoCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    tipo_usuario: str = Field(default="encargado", pattern="^(encargado|produccion)$")
    locales: list[int] = Field(min_length=1, max_length=100)


class NombreAdminCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


@app.get("/api/admin/usuarios")
def admin_listar_usuarios(authorization: str | None = Header(default=None)):
    admin, perfil_admin = exigir_admin_principal(authorization)
    try:
        perfiles = supabase.table("perfiles").select("id,nombre,rol,es_admin_principal").execute().data
        accesos = supabase.table("accesos_panaderias").select("usuario_id,panaderia_id").execute().data
        locales = supabase.table("panaderias").select("id,nombre,activa").order("nombre").execute().data
        por_local = {int(x["id"]): x for x in locales}
        acceso_por_usuario = {}
        for a in accesos:
            acceso_por_usuario.setdefault(str(a["usuario_id"]), []).append(int(a["panaderia_id"]))
        auth_users = {}
        pagina = 1
        while pagina <= 20:
            lote = supabase.auth.admin.list_users(page=pagina, per_page=100)
            # supabase-py puede devolver directamente una lista de usuarios;
            # otras versiones devuelven un objeto con .users o .data.users.
            if isinstance(lote, list):
                lista = lote
            elif isinstance(lote, dict):
                datos_lote = lote.get("data") or {}
                lista = lote.get("users") or (
                    datos_lote.get("users", []) if isinstance(datos_lote, dict) else []
                )
            else:
                lista = getattr(lote, "users", None)
                if lista is None:
                    datos_lote = getattr(lote, "data", None)
                    lista = getattr(datos_lote, "users", None) if datos_lote is not None else None
                lista = lista or []
            for u in lista:
                uid_auth = u.get("id") if isinstance(u, dict) else getattr(u, "id", None)
                if uid_auth:
                    auth_users[str(uid_auth)] = u
            if len(lista) < 100:
                break
            pagina += 1
        salida = []
        for p in perfiles:
            uid = str(p["id"])
            au = auth_users.get(uid)
            if not au:
                # Respaldo individual para distintas respuestas de Supabase Auth.
                try:
                    detalle = supabase.auth.admin.get_user_by_id(uid)
                    if isinstance(detalle, dict):
                        au = detalle.get("user") or (detalle.get("data") or {}).get("user")
                    else:
                        au = getattr(detalle, "user", None)
                        if au is None:
                            datos_detalle = getattr(detalle, "data", None)
                            au = getattr(datos_detalle, "user", None) if datos_detalle is not None else None
                        if au is None and getattr(detalle, "id", None):
                            au = detalle
                except Exception:
                    au = None
            if not au:
                continue
            meta = (au.get("user_metadata") if isinstance(au, dict) else getattr(au, "user_metadata", None)) or {}
            correo = (au.get("email") if isinstance(au, dict) else getattr(au, "email", None)) or ""
            if meta.get("pizzan_cuenta_tecnica") is True:
                continue
            es_admin = bool(p.get("es_admin_principal"))
            salida.append({
                "id": uid, "nombre": p["nombre"], "rol": p["rol"],
                "es_admin_principal": es_admin,
                "usuario": correo if es_admin else str(meta.get("pizzan_username") or correo.split("@")[0]),
                "locales": ([{"id": int(x["id"]), "nombre": x["nombre"]} for x in locales] if es_admin else [
                    {"id": lid, "nombre": por_local[lid]["nombre"]} for lid in acceso_por_usuario.get(uid, []) if lid in por_local
                ])
            })
        return {"usuarios": salida, "total_usuarios": len(salida), "total_locales": len(locales)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar las cuentas.")


@app.post("/api/admin/usuarios", status_code=201)
def admin_crear_usuario(datos: CuentaEncargadoNueva, authorization: str | None = Header(default=None)):
    exigir_admin_principal(authorization)
    nombre = " ".join(datos.nombre.split())
    username = datos.username.strip().lower()
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe un nombre.")
    if len(set(datos.locales)) != len(datos.locales):
        raise HTTPException(status_code=422, detail="No repitas locales.")
    try:
        existentes = supabase.table("panaderias").select("id").in_("id", datos.locales).execute().data
        if len({int(x["id"]) for x in existentes}) != len(set(datos.locales)):
            raise HTTPException(status_code=422, detail="Uno de los locales seleccionados no existe.")
        email = email_interno_encargado(username)
        creado = supabase.auth.admin.create_user({"email": email, "password": datos.password, "email_confirm": True, "user_metadata": {"pizzan_username": username}})
        auth_user = getattr(creado, "user", None) or getattr(getattr(creado, "data", None), "user", None)
        if not auth_user:
            raise HTTPException(status_code=503, detail="No se pudo crear la cuenta de acceso.")
        uid = str(auth_user.id)
        try:
            supabase.table("perfiles").insert({"id": uid, "nombre": nombre, "rol": datos.tipo_usuario, "es_admin_principal": False}).execute()
            supabase.table("accesos_panaderias").insert([{"usuario_id": uid, "panaderia_id": x} for x in datos.locales]).execute()
        except Exception:
            try:
                supabase.auth.admin.delete_user(uid)
            except Exception:
                pass
            raise
        return {"creado": True, "id": uid}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo crear el usuario. Comprueba que el nombre de usuario no esté ocupado.")


@app.patch("/api/admin/usuarios/{usuario_id}")
def admin_actualizar_usuario(usuario_id: str, datos: CuentaEncargadoCambio, authorization: str | None = Header(default=None)):
    exigir_admin_principal(authorization)
    nombre = " ".join(datos.nombre.split())
    username = datos.username.strip().lower()
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe un nombre.")
    try:
        perfil_result = supabase.table("perfiles").select("id,rol,es_admin_principal").eq("id", usuario_id).limit(1).execute().data
        if not perfil_result or perfil_result[0].get("es_admin_principal") or perfil_result[0].get("rol") not in ("encargado", "produccion"):
            raise HTTPException(status_code=403, detail="Esta cuenta no se puede editar desde aquí.")
        if len(set(datos.locales)) != len(datos.locales):
            raise HTTPException(status_code=422, detail="No repitas locales.")
        existentes = supabase.table("panaderias").select("id").in_("id", datos.locales).execute().data
        if len({int(x["id"]) for x in existentes}) != len(set(datos.locales)):
            raise HTTPException(status_code=422, detail="Uno de los locales seleccionados no existe.")
        email = email_interno_encargado(username)
        cambio_auth = {"email": email, "user_metadata": {"pizzan_username": username}}
        if datos.password:
            cambio_auth["password"] = datos.password
        supabase.auth.admin.update_user_by_id(usuario_id, cambio_auth)
        supabase.table("perfiles").update({"nombre": nombre, "rol": datos.tipo_usuario}).eq("id", usuario_id).execute()
        supabase.table("accesos_panaderias").delete().eq("usuario_id", usuario_id).execute()
        supabase.table("accesos_panaderias").insert([{"usuario_id": usuario_id, "panaderia_id": x} for x in datos.locales]).execute()
        return {"actualizado": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron guardar los cambios del usuario.")


@app.delete("/api/admin/usuarios/{usuario_id}")
def admin_eliminar_usuario(usuario_id: str, authorization: str | None = Header(default=None)):
    exigir_admin_principal(authorization)
    try:
        p = supabase.table("perfiles").select("id,rol,es_admin_principal").eq("id", usuario_id).limit(1).execute().data
        if not p or p[0].get("es_admin_principal") or p[0].get("rol") not in ("encargado", "produccion"):
            raise HTTPException(status_code=403, detail="Esta cuenta no se puede eliminar desde aquí.")
        supabase.auth.admin.delete_user(usuario_id)
        restantes = supabase.table("perfiles").select("id").eq("id", usuario_id).limit(1).execute().data or []
        if restantes:
            raise HTTPException(status_code=409, detail="La cuenta no se eliminó por completo; revisa sus relaciones históricas.")
        return {"eliminado": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar la cuenta.")


@app.patch("/api/admin/perfil")
def admin_cambiar_nombre(datos: NombreAdminCambio, authorization: str | None = Header(default=None)):
    usuario, perfil = exigir_admin_principal(authorization)
    nombre = " ".join(datos.nombre.split())
    if not nombre:
        raise HTTPException(status_code=422, detail="Escribe un nombre.")
    try:
        supabase.table("perfiles").update({"nombre": nombre}).eq("id", str(usuario.id)).execute()
        return {"actualizado": True, "nombre": nombre}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar el nombre.")


# API del catálogo con categorías por panadería.
from catalogo import router as catalogo_router
app.include_router(catalogo_router)

# Archivado privado en Cloudflare R2 (sin modificar la interfaz).
from archivado import router as archivado_router
app.include_router(archivado_router)

# Historial unificado: Supabase para datos activos y R2 para archivos verificados.
from historial_archivos import router as historial_archivos_router
app.include_router(historial_archivos_router)

# Informes del Historial: consultas agregadas y Excel con gráficas nativas.
from historial_reportes import router as historial_reportes_router
app.include_router(historial_reportes_router)

# Creación de locales y fotografías privadas en Cloudflare R2.
from locales import router as locales_router
app.include_router(locales_router)


# ---------------------------------------------------------------------------
# Producción diaria: independiente del inventario y con nombre de pan libre.
# ---------------------------------------------------------------------------
from datetime import timedelta, time
from zoneinfo import ZoneInfo

TZ_PRODUCCION = ZoneInfo("America/Mexico_City")


class ProduccionNueva(BaseModel):
    panaderia_id: int = Field(gt=0)
    fecha_produccion: date
    pan_nombre: str = Field(min_length=1, max_length=120)
    cantidad: int = Field(ge=0)
    observaciones: str | None = Field(default=None, max_length=1000)


class ProduccionCambio(BaseModel):
    pan_nombre: str = Field(min_length=1, max_length=120)
    cantidad: int = Field(ge=0)
    observaciones: str | None = Field(default=None, max_length=1000)


def _perfil_con_acceso_produccion(usuario_id: str, perfil: dict, panaderia_id: int):
    if perfil["rol"] not in ("produccion", "admin"):
        raise HTTPException(status_code=403, detail="Tu cuenta no tiene acceso al módulo de Producción.")
    if perfil["rol"] == "admin" and perfil.get("es_admin_principal"):
        return
    try:
        acceso = (
            supabase.table("accesos_panaderias")
            .select("panaderia_id")
            .eq("usuario_id", usuario_id)
            .eq("panaderia_id", panaderia_id)
            .limit(1)
            .execute()
        )
        if not acceso.data:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta panadería.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo verificar el acceso a la panadería.")


def _produccion_es_editable(fecha_produccion: str | date, dias_editables: int | None = None) -> bool:
    fecha = fecha_produccion if isinstance(fecha_produccion, date) else date.fromisoformat(str(fecha_produccion)[:10])
    dias = obtener_configuracion_edicion()["dias_produccion"] if dias_editables is None else dias_editables
    transcurridos = (datetime.now(TZ_PRODUCCION).date() - fecha).days
    return 0 <= transcurridos <= dias


def _normalizar_pan_produccion(nombre: str) -> str:
    return " ".join(nombre.strip().split())


@app.get("/api/produccion")
def consultar_produccion(
    panaderia_id: int,
    fecha_produccion: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    _perfil_con_acceso_produccion(str(usuario.id), perfil, panaderia_id)
    if fecha_produccion > datetime.now(TZ_PRODUCCION).date():
        raise HTTPException(status_code=422, detail="No puedes consultar una fecha futura.")
    try:
        filas = (
            supabase.table("produccion_registros")
            .select("id,panaderia_id,fecha_produccion,pan_nombre,cantidad,observaciones,usuario_id,usuario_nombre,registrado_en,actualizado_en")
            .eq("panaderia_id", panaderia_id)
            .eq("fecha_produccion", fecha_produccion.isoformat())
            .order("registrado_en")
            .execute().data or []
        )
        ids = list({str(f["usuario_id"]) for f in filas if f.get("usuario_id")})
        perfiles = (
            supabase.table("perfiles").select("id,nombre").in_("id", ids).execute().data
            if ids else []
        )
        nombres = {str(p["id"]): p["nombre"] for p in perfiles}
        dias_editables = obtener_configuracion_edicion()["dias_produccion"]
        for fila in filas:
            fila["usuario_nombre"] = fila.get("usuario_nombre") or nombres.get(str(fila.get("usuario_id")), "Usuario")
            fila["editable"] = _produccion_es_editable(fila["fecha_produccion"], dias_editables)
        return {"registros": filas, "total": len(filas), "dias_editables": dias_editables}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar los registros de producción.")


@app.post("/api/produccion", status_code=201)
def crear_registro_produccion(
    datos: ProduccionNueva,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    _perfil_con_acceso_produccion(str(usuario.id), perfil, datos.panaderia_id)
    ahora_local = datetime.now(TZ_PRODUCCION).date()
    dias_produccion = obtener_configuracion_edicion()["dias_produccion"]
    dias_transcurridos = (ahora_local - datos.fecha_produccion).days
    if dias_transcurridos < 0:
        raise HTTPException(status_code=422, detail="No puedes registrar producción en una fecha futura.")
    if dias_transcurridos > dias_produccion:
        raise HTTPException(status_code=403, detail=f"El plazo para registrar o editar producción es de {dias_produccion} días.")
    pan = _normalizar_pan_produccion(datos.pan_nombre)
    if not pan:
        raise HTTPException(status_code=422, detail="Escribe el nombre del pan.")
    try:
        fila = supabase.table("produccion_registros").insert({
            "panaderia_id": datos.panaderia_id,
            "fecha_produccion": datos.fecha_produccion.isoformat(),
            "pan_nombre": pan,
            "cantidad": datos.cantidad,
            "observaciones": (datos.observaciones or "").strip() or None,
            "usuario_id": str(usuario.id),
            "usuario_nombre": obtener_perfil(str(usuario.id))["nombre"],
        }).execute().data[0]
        return {"creado": True, "registro": fila}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar el registro de producción.")


@app.patch("/api/produccion/{registro_id}")
def actualizar_registro_produccion(
    registro_id: int,
    datos: ProduccionCambio,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    try:
        encontrado = (
            supabase.table("produccion_registros")
            .select("id,panaderia_id,fecha_produccion")
            .eq("id", registro_id).limit(1).execute().data
        )
        if not encontrado:
            raise HTTPException(status_code=404, detail="No se encontró el registro de producción.")
        actual = encontrado[0]
        _perfil_con_acceso_produccion(str(usuario.id), perfil, int(actual["panaderia_id"]))
        if not _produccion_es_editable(actual["fecha_produccion"]):
            raise HTTPException(status_code=403, detail="Terminó el plazo de edición de este registro. Solo puedes consultarlo.")
        pan = _normalizar_pan_produccion(datos.pan_nombre)
        if not pan:
            raise HTTPException(status_code=422, detail="Escribe el nombre del pan.")
        actualizado = (
            supabase.table("produccion_registros")
            .update({
                "pan_nombre": pan,
                "cantidad": datos.cantidad,
                "observaciones": (datos.observaciones or "").strip() or None,
                "actualizado_en": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", registro_id).execute().data
        )
        if not actualizado:
            raise HTTPException(status_code=404, detail="No se pudo localizar el registro para actualizarlo.")
        return {"actualizado": True, "registro": actualizado[0]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar el registro de producción.")


@app.delete("/api/produccion/{registro_id}")
def eliminar_registro_produccion(
    registro_id: int,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    try:
        encontrado = (
            supabase.table("produccion_registros")
            .select("id,panaderia_id,fecha_produccion")
            .eq("id", registro_id).limit(1).execute().data
        )
        if not encontrado:
            raise HTTPException(status_code=404, detail="No se encontró el registro de producción.")
        actual = encontrado[0]
        _perfil_con_acceso_produccion(str(usuario.id), perfil, int(actual["panaderia_id"]))
        if not _produccion_es_editable(actual["fecha_produccion"]):
            raise HTTPException(status_code=403, detail="Terminó el plazo de edición. Este registro solo se puede consultar.")
        eliminado = (
            supabase.table("produccion_registros")
            .delete()
            .eq("id", registro_id)
            .select("id")
            .execute().data
        )
        if not eliminado:
            raise HTTPException(status_code=404, detail="No se pudo localizar el registro para eliminarlo.")
        return {"eliminado": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar el registro de producción.")


@app.get("/api/produccion/excel")
def descargar_produccion_excel(
    panaderia_id: int,
    fecha_produccion: date,
    authorization: str | None = Header(default=None),
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    _perfil_con_acceso_produccion(str(usuario.id), perfil, panaderia_id)
    datos = consultar_produccion(panaderia_id, fecha_produccion, authorization)
    try:
        local = supabase.table("panaderias").select("nombre").eq("id", panaderia_id).limit(1).execute().data
        nombre_local = local[0]["nombre"] if local else f"Panadería {panaderia_id}"
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Producción diaria"
        hoja.append(["Fecha", fecha_produccion.isoformat()])
        hoja.append(["Panadería", nombre_local])
        hoja.append([])
        hoja.append(["Pan", "Cantidad", "Observaciones", "Registró", "Fecha y hora de captura"])
        for registro in datos["registros"]:
            marca_captura = registro.get("registrado_en")
            fecha_hora_captura = None
            if marca_captura:
                fecha_hora_captura = datetime.fromisoformat(
                    str(marca_captura).replace("Z", "+00:00")
                )
                if fecha_hora_captura.tzinfo is None:
                    fecha_hora_captura = fecha_hora_captura.replace(tzinfo=timezone.utc)
                fecha_hora_captura = fecha_hora_captura.astimezone(TZ_PRODUCCION).replace(tzinfo=None)
            hoja.append([
                registro["pan_nombre"],
                int(registro["cantidad"]),
                registro.get("observaciones") or "",
                registro.get("usuario_nombre") or "Usuario",
                fecha_hora_captura,
            ])
            hoja.cell(row=hoja.max_row, column=5).number_format = "dd/mm/yy hh:mm"
        hoja.freeze_panes = "A5"
        hoja.auto_filter.ref = f"A4:E{max(4, hoja.max_row)}"
        for col, width in {"A": 34, "B": 14, "C": 42, "D": 24, "E": 28}.items():
            hoja.column_dimensions[col].width = width
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre_archivo = f"produccion_{panaderia_id}_{fecha_produccion.isoformat()}.xlsx"
        return StreamingResponse(
            salida,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el Excel de producción.")

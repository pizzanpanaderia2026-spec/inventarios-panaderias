
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
            .select("id,nombre,rol,es_admin_principal,permisos")
            .eq("id", usuario_id)
            .limit(1)
            .execute()
        )

        if not respuesta.data:
            raise HTTPException(
                status_code=403,
                detail="Tu cuenta no tiene un perfil autorizado.",
            )

        perfil = dict(respuesta.data[0])
        permisos = perfil.get("permisos")
        if not isinstance(permisos, list) or not permisos:
            permisos = ["produccion"] if perfil.get("rol") == "produccion" else ["inventarios"]
        perfil["permisos"] = [x for x in permisos if x in ("inventarios", "produccion", "ventas")]
        return perfil

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
        "permisos": perfil.get("permisos", []),
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
    if es_admin_principal(perfil):
        return
    permisos = perfil.get("permisos") or (["produccion"] if perfil.get("rol") == "produccion" else ["inventarios"])
    modulos_requeridos = {"inventarios", "produccion"} if permitir_produccion else {"inventarios"}
    if not any(modulo in permisos for modulo in modulos_requeridos):
        raise HTTPException(status_code=403, detail="Tu cuenta no tiene permiso para esta operación.")
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


from datetime import date, datetime, timezone, timedelta
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


class LineaRegistroIndividual(BaseModel):
    panaderia_id: int = Field(gt=0)
    fecha: date
    producto_id: int = Field(gt=0)
    cantidad: int = Field(ge=0)


@app.put("/api/registro/linea")
def guardar_linea_registro(datos: LineaRegistroIndividual, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, datos.panaderia_id)
    hoy = datetime.now(TZ_PRODUCCION).date()
    if datos.fecha > hoy:
        raise HTTPException(status_code=422, detail="No puedes registrar una fecha futura.")
    config = obtener_configuracion_edicion()
    if not plazo_edicion_vigente(datos.fecha, config["dias_inventario"], config["horas_inventario"]) and not es_admin_principal(perfil):
        raise HTTPException(status_code=403, detail="Terminó el plazo configurado para editar inventario.")
    try:
        resultado = supabase.rpc("guardar_linea_inventario", {
            "p_panaderia_id": datos.panaderia_id,
            "p_fecha": datos.fecha.isoformat(),
            "p_producto_id": datos.producto_id,
            "p_cantidad": datos.cantidad,
            "p_usuario_id": str(usuario.id),
        }).execute().data
        return {"guardado": True, "linea": resultado}
    except HTTPException:
        raise
    except Exception as exc:
        mensaje = str(exc).lower()
        if "cerrado" in mensaje:
            raise HTTPException(status_code=409, detail="El día está cerrado. Reábrelo antes de modificarlo.")
        if "producto" in mensaje:
            raise HTTPException(status_code=422, detail="El producto no existe o está inactivo en este local.")
        raise HTTPException(status_code=503, detail="No se pudo guardar el producto del registro.")


@app.delete("/api/registro/linea")
def eliminar_linea_registro(
    panaderia_id: int, fecha: date, producto_id: int,
    authorization: str | None = Header(default=None)
):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
    config = obtener_configuracion_edicion()
    if not plazo_edicion_vigente(fecha, config["dias_inventario"], config["horas_inventario"]) and not es_admin_principal(perfil):
        raise HTTPException(status_code=403, detail="Terminó el plazo configurado para editar inventario.")
    try:
        eliminado = supabase.rpc("eliminar_linea_inventario", {
            "p_panaderia_id": panaderia_id, "p_fecha": fecha.isoformat(),
            "p_producto_id": producto_id, "p_usuario_id": str(usuario.id)
        }).execute().data
        return {"eliminado": bool(eliminado)}
    except Exception as exc:
        if "cerrado" in str(exc).lower():
            raise HTTPException(status_code=409, detail="El día está cerrado. Reábrelo antes de modificarlo.")
        raise HTTPException(status_code=503, detail="No se pudo retirar el producto del registro.")


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
    config_edicion = obtener_configuracion_edicion()
    if not plazo_edicion_vigente(registro.fecha, config_edicion["dias_inventario"], config_edicion["horas_inventario"]) and not es_admin_principal(perfil):
        raise HTTPException(status_code=403, detail="Terminó el plazo configurado para editar inventario.")
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
        config_edicion = obtener_configuracion_edicion()
        dentro_del_plazo = plazo_edicion_vigente(solicitud.fecha, config_edicion["dias_inventario"], config_edicion["horas_inventario"])
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
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    """Descarga exclusivamente el catálogo y los precios históricos del local seleccionado."""
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "inventarios")
    try:
        local = (supabase.table("panaderias").select("id,nombre")
                 .eq("id", panaderia_id).limit(1).execute().data or [])
        if not local:
            raise HTTPException(status_code=404, detail="No se encontró la panadería seleccionada.")
        panaderia = local[0]
        productos = (supabase.table("productos").select("id,nombre,precio,creado_en")
                     .eq("panaderia_id", panaderia_id).order("nombre").execute().data or [])
        ids_productos = [int(p["id"]) for p in productos]
        detalles = []
        if ids_productos:
            detalles = (supabase.table("inventario_detalles")
                .select("producto_id,precio_unitario,cierre_id,registrado_en")
                .in_("producto_id", ids_productos).order("registrado_en").execute().data or [])
        cierres_ids = list({int(d["cierre_id"]) for d in detalles if d.get("cierre_id") is not None})
        fechas_cierres = {}
        if cierres_ids:
            cierres = (supabase.table("cierres_diarios").select("id,fecha")
                       .in_("id", cierres_ids).execute().data or [])
            fechas_cierres = {int(x["id"]): x["fecha"] for x in cierres}
        por_producto = {}
        for detalle in detalles:
            pid = int(detalle["producto_id"])
            fecha = fechas_cierres.get(int(detalle["cierre_id"])) if detalle.get("cierre_id") is not None else None
            fecha = fecha or str(detalle.get("registrado_en", ""))[:10]
            por_producto.setdefault(pid, []).append((fecha, detalle.get("precio_unitario")))
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Lista de productos"
        hoja.append(["Panadería", "Producto", "Fecha del precio", "Precio"])
        for producto in productos:
            historial = por_producto.get(int(producto["id"]), [])
            if historial:
                for fecha, precio in historial:
                    hoja.append([panaderia["nombre"], producto["nombre"], fecha,
                                 float(Decimal(str(precio))) if precio is not None else None])
            else:
                hoja.append([panaderia["nombre"], producto["nombre"],
                             str(producto.get("creado_en", ""))[:10],
                             float(Decimal(str(producto["precio"])))])
        hoja.freeze_panes = "A2"
        hoja.auto_filter.ref = hoja.dimensions
        for col, width in {"A":24,"B":36,"C":20,"D":16}.items():
            hoja.column_dimensions[col].width = width
        for row in range(2, hoja.max_row + 1):
            hoja.cell(row, 4).number_format = '"$"#,##0.00'
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = "lista_productos_" + str(panaderia_id) + ".xlsx"
        return StreamingResponse(salida,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
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
    horas_inventario: int = Field(default=0, ge=0, le=23)
    dias_produccion: int = Field(ge=0, le=365)
    horas_produccion: int = Field(default=0, ge=0, le=23)
    dias_ventas: int = Field(default=0, ge=0, le=365)
    horas_ventas: int = Field(default=0, ge=0, le=23)


def obtener_configuracion_edicion():
    try:
        columnas = "dias_inventario,horas_inventario,dias_produccion,horas_produccion,dias_ventas,horas_ventas"
        filas = supabase.table("configuracion_edicion").select(columnas).eq("id", 1).limit(1).execute().data or []
        if filas:
            return {k: int(filas[0].get(k) or 0) for k in ("dias_inventario","horas_inventario","dias_produccion","horas_produccion","dias_ventas","horas_ventas")}
        valores = {"id":1,"dias_inventario":2,"horas_inventario":0,"dias_produccion":1,"horas_produccion":0,"dias_ventas":0,"horas_ventas":0}
        supabase.table("configuracion_edicion").insert(valores).execute()
        return {k:v for k,v in valores.items() if k != "id"}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar la configuración de tolerancias de edición.")


def plazo_edicion_vigente(fecha_registro: date, dias: int, horas: int = 0) -> bool:
    ahora = datetime.now(TZ_PRODUCCION)
    limite = datetime.combine(fecha_registro + timedelta(days=dias + 1), datetime.min.time()).replace(tzinfo=TZ_PRODUCCION)
    limite += timedelta(hours=horas)
    return fecha_registro <= ahora.date() and ahora < limite


@app.get("/api/admin/configuracion-edicion")
def admin_obtener_configuracion_edicion(authorization: str | None = Header(default=None)):
    exigir_admin_principal(authorization)
    return obtener_configuracion_edicion()


@app.put("/api/admin/configuracion-edicion")
def admin_guardar_configuracion_edicion(datos: ConfiguracionEdicionCambio, authorization: str | None = Header(default=None)):
    usuario, _ = exigir_admin_principal(authorization)
    try:
        supabase.table("configuracion_edicion").upsert({
            "id": 1, "dias_inventario": datos.dias_inventario, "horas_inventario": datos.horas_inventario,
            "dias_produccion": datos.dias_produccion, "horas_produccion": datos.horas_produccion,
            "dias_ventas": datos.dias_ventas, "horas_ventas": datos.horas_ventas,
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
    permisos: list[str] | None = Field(default=None, min_length=1, max_length=3)
    locales: list[int] = Field(min_length=1, max_length=100)


class CuentaEncargadoCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    tipo_usuario: str = Field(default="encargado", pattern="^(encargado|produccion)$")
    permisos: list[str] | None = Field(default=None, min_length=1, max_length=3)
    locales: list[int] = Field(min_length=1, max_length=100)


MODULOS_CUENTA = {"inventarios", "produccion", "ventas"}


def permisos_para_cuenta(datos) -> list[str]:
    permisos = datos.permisos
    if permisos is None:
        permisos = ["produccion"] if datos.tipo_usuario == "produccion" else ["inventarios"]
    permisos = list(dict.fromkeys(permisos))
    if not permisos or any(modulo not in MODULOS_CUENTA for modulo in permisos):
        raise HTTPException(status_code=422, detail="Selecciona al menos un módulo válido.")
    return permisos


def rol_compatibilidad(permisos: list[str]) -> str:
    return "produccion" if permisos == ["produccion"] else "encargado"


class NombreAdminCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


@app.get("/api/admin/usuarios")
def admin_listar_usuarios(authorization: str | None = Header(default=None)):
    admin, perfil_admin = exigir_admin_principal(authorization)
    try:
        perfiles = supabase.table("perfiles").select("id,nombre,rol,es_admin_principal,permisos").execute().data
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
                "permisos": (p.get("permisos") or (["inventarios", "produccion", "ventas"] if es_admin else (["produccion"] if p.get("rol") == "produccion" else ["inventarios"]))),
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
    permisos = permisos_para_cuenta(datos)
    rol = rol_compatibilidad(permisos)
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
            supabase.table("perfiles").insert({"id": uid, "nombre": nombre, "rol": rol, "es_admin_principal": False, "permisos": permisos}).execute()
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
    permisos = permisos_para_cuenta(datos)
    rol = rol_compatibilidad(permisos)
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
        supabase.table("perfiles").update({"nombre": nombre, "rol": rol, "permisos": permisos}).eq("id", usuario_id).execute()
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
    producto_id: int | None = Field(default=None, gt=0)
    cantidad: int = Field(ge=0)
    observaciones: str | None = Field(default=None, max_length=1000)


class ProduccionCambio(BaseModel):
    pan_nombre: str = Field(min_length=1, max_length=120)
    cantidad: int = Field(ge=0)
    observaciones: str | None = Field(default=None, max_length=1000)


def _perfil_con_acceso_produccion(usuario_id: str, perfil: dict, panaderia_id: int):
    if es_admin_principal(perfil):
        return
    permisos = perfil.get("permisos") or (["produccion"] if perfil.get("rol") == "produccion" else ["inventarios"])
    if "produccion" not in permisos:
        raise HTTPException(status_code=403, detail="Tu cuenta no tiene acceso al módulo de Producción.")
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
    config = obtener_configuracion_edicion()
    dias = config["dias_produccion"] if dias_editables is None else dias_editables
    horas = config["horas_produccion"] if dias_editables is None else 0
    return plazo_edicion_vigente(fecha, dias, horas)


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
            .select("id,panaderia_id,fecha_produccion,pan_nombre,cantidad,precio_unitario,importe,observaciones,usuario_id,usuario_nombre,registrado_en,actualizado_en")
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
        config_edicion = obtener_configuracion_edicion()
        total_cantidad = 0
        total_importe = Decimal("0")
        importe_completo = True
        for fila in filas:
            fila["usuario_nombre"] = fila.get("usuario_nombre") or nombres.get(str(fila.get("usuario_id")), "Usuario")
            fila["editable"] = _produccion_es_editable(fila["fecha_produccion"])
            total_cantidad += int(fila.get("cantidad") or 0)
            if fila.get("importe") is None:
                importe_completo = False
            else:
                total_importe += Decimal(str(fila["importe"]))
        return {"registros": filas, "total": len(filas), "dias_editables": config_edicion["dias_produccion"],
                "horas_editables": config_edicion["horas_produccion"], "total_cantidad": total_cantidad,
                "total_importe": str(total_importe.quantize(Decimal("0.01"))) if importe_completo else None}
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
    config_edicion = obtener_configuracion_edicion()
    if datos.fecha_produccion > ahora_local:
        raise HTTPException(status_code=422, detail="No puedes registrar producción en una fecha futura.")
    if not plazo_edicion_vigente(datos.fecha_produccion, config_edicion["dias_produccion"], config_edicion["horas_produccion"]):
        raise HTTPException(status_code=403, detail="Terminó el plazo configurado para registrar o editar producción.")
    pan = _normalizar_pan_produccion(datos.pan_nombre)
    if not pan:
        raise HTTPException(status_code=422, detail="Escribe el nombre del pan.")
    try:
        producto = None
        if datos.producto_id:
            productos_encontrados = (supabase.table("productos").select("id,nombre,precio,activo")
                .eq("id", datos.producto_id).eq("panaderia_id", datos.panaderia_id).limit(1).execute().data or [])
            producto = productos_encontrados[0] if productos_encontrados else None
        else:
            productos_encontrados = (supabase.table("productos").select("id,nombre,precio,activo")
                .eq("panaderia_id", datos.panaderia_id).ilike("nombre", pan).limit(10).execute().data or [])
            producto = next((x for x in productos_encontrados if _normalizar_pan_produccion(x["nombre"]).casefold() == pan.casefold()), None)
        precio_unitario = Decimal(str(producto["precio"])) if producto and producto.get("activo") else None
        importe = (precio_unitario * datos.cantidad).quantize(Decimal("0.01")) if precio_unitario is not None else None
        fila = supabase.table("produccion_registros").insert({
            "panaderia_id": datos.panaderia_id,
            "fecha_produccion": datos.fecha_produccion.isoformat(),
            "pan_nombre": pan,
            "cantidad": datos.cantidad,
            "precio_unitario": str(precio_unitario) if precio_unitario is not None else None,
            "importe": str(importe) if importe is not None else None,
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
            .select("id,panaderia_id,fecha_produccion,precio_unitario")
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
                "importe": (str((Decimal(str(actual["precio_unitario"])) * datos.cantidad).quantize(Decimal("0.01"))) if actual.get("precio_unitario") is not None else None),
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
        hoja.append(["Pan", "Cantidad", "Precio unitario", "Importe", "Observaciones", "Registró", "Fecha y hora de captura"])
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
                float(Decimal(str(registro["precio_unitario"]))) if registro.get("precio_unitario") is not None else None,
                float(Decimal(str(registro["importe"]))) if registro.get("importe") is not None else None,
                registro.get("observaciones") or "",
                registro.get("usuario_nombre") or "Usuario",
                fecha_hora_captura,
            ])
            hoja.cell(row=hoja.max_row, column=3).number_format = '"$"#,##0.00'
            hoja.cell(row=hoja.max_row, column=4).number_format = '"$"#,##0.00'
            hoja.cell(row=hoja.max_row, column=7).number_format = "dd/mm/yy hh:mm"
        total_row = hoja.max_row + 1
        hoja.cell(total_row, 1, "TOTAL")
        hoja.cell(total_row, 2, datos.get("total_cantidad", 0))
        hoja.cell(total_row, 4, float(Decimal(str(datos.get("total_importe") or 0))))
        hoja.cell(total_row, 4).number_format = '"$"#,##0.00'
        hoja.freeze_panes = "A5"
        hoja.auto_filter.ref = f"A4:G{max(4, total_row - 1)}"
        for col, width in {"A": 34, "B": 14, "C": 18, "D": 18, "E": 42, "F": 24, "G": 28}.items():
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


# Punto de venta: disponibilidad diaria y ventas individuales.
class DisponibilidadVentaCambio(BaseModel):
    panaderia_id: int = Field(gt=0)
    producto_id: int = Field(gt=0)
    disponible: bool


class AnclajeVentaCambio(BaseModel):
    panaderia_id: int = Field(gt=0)
    producto_id: int = Field(gt=0)
    anclado: bool


class VentaPosLineaNueva(BaseModel):
    producto_id: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=100000)


class VentaPosNueva(BaseModel):
    panaderia_id: int = Field(gt=0)
    lineas: list[VentaPosLineaNueva] = Field(min_length=1, max_length=200)


def comprobar_permiso_local(usuario_id: str, perfil: dict, panaderia_id: int, modulo: str):
    if es_admin_principal(perfil):
        return
    permisos = perfil.get("permisos") or (["produccion"] if perfil.get("rol") == "produccion" else ["inventarios"])
    if modulo not in permisos:
        raise HTTPException(status_code=403, detail=f"Tu cuenta no tiene acceso al módulo de {modulo}.")
    try:
        acceso = (supabase.table("accesos_panaderias").select("panaderia_id")
            .eq("usuario_id", usuario_id).eq("panaderia_id", panaderia_id).limit(1).execute())
        if not acceso.data:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta panadería.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo verificar el acceso a la panadería.")


def fecha_operativa_hoy() -> date:
    return datetime.now(TZ_PRODUCCION).date()


@app.get("/api/ventas/disponibilidad")
def ventas_consultar_disponibilidad(panaderia_id: int, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    fecha = fecha_operativa_hoy()
    try:
        productos = (supabase.table("productos")
            .select("id,nombre,precio,categoria_id,activo,pos_anclado")
            .eq("panaderia_id", panaderia_id).eq("activo", True).order("nombre").execute().data or [])
        categorias = (supabase.table("categorias_productos")
            .select("id,nombre,activa").eq("panaderia_id", panaderia_id)
            .eq("activa", True).order("nombre").execute().data or [])
        filas = (supabase.table("disponibilidad_ventas")
            .select("producto_id,disponible").eq("panaderia_id", panaderia_id)
            .eq("fecha", fecha.isoformat()).execute().data or [])
        disponibles = {int(x["producto_id"]): bool(x["disponible"]) for x in filas}
        for producto in productos:
            # Los productos anclados se habilitan por defecto cada día.
            # Una desactivación explícita del día actual siempre tiene prioridad.
            producto["disponible"] = disponibles.get(
                int(producto["id"]), bool(producto.get("pos_anclado"))
            )
        return {"fecha": fecha.isoformat(), "productos": productos, "categorias": categorias}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar la disponibilidad de productos.")


@app.put("/api/ventas/disponibilidad")
def ventas_cambiar_disponibilidad(datos: DisponibilidadVentaCambio, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, datos.panaderia_id, "ventas")
    try:
        producto = (supabase.table("productos").select("id,panaderia_id,activo")
            .eq("id", datos.producto_id).eq("panaderia_id", datos.panaderia_id).limit(1).execute().data or [])
        if not producto or not producto[0].get("activo"):
            raise HTTPException(status_code=404, detail="El producto no existe o está desactivado.")
        fecha = fecha_operativa_hoy()
        supabase.table("disponibilidad_ventas").upsert({
            "panaderia_id": datos.panaderia_id, "producto_id": datos.producto_id,
            "fecha": fecha.isoformat(), "disponible": datos.disponible,
            "actualizado_por": str(usuario.id)
        }, on_conflict="panaderia_id,fecha,producto_id").execute()
        return {"guardado": True, "fecha": fecha.isoformat(), "disponible": datos.disponible}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar la disponibilidad.")


@app.put("/api/ventas/anclado")
def ventas_cambiar_anclaje(datos: AnclajeVentaCambio, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, datos.panaderia_id, "ventas")
    try:
        producto = (supabase.table("productos").select("id,panaderia_id,activo")
            .eq("id", datos.producto_id).eq("panaderia_id", datos.panaderia_id).limit(1).execute().data or [])
        if not producto or not producto[0].get("activo"):
            raise HTTPException(status_code=404, detail="El producto no existe o está desactivado.")
        actualizado = (supabase.table("productos").update({"pos_anclado": datos.anclado})
            .eq("id", datos.producto_id).eq("panaderia_id", datos.panaderia_id)
            .execute().data or [])
        if not actualizado:
            raise HTTPException(status_code=404, detail="No se pudo actualizar el anclaje del producto.")
        if datos.anclado:
            fecha = fecha_operativa_hoy()
            supabase.table("disponibilidad_ventas").upsert({
                "panaderia_id": datos.panaderia_id,
                "producto_id": datos.producto_id,
                "fecha": fecha.isoformat(),
                "disponible": True,
                "actualizado_por": str(usuario.id)
            }, on_conflict="panaderia_id,fecha,producto_id").execute()
        return {"guardado": True, "anclado": datos.anclado, "producto_id": datos.producto_id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo guardar el anclaje del producto.")


@app.post("/api/ventas", status_code=201)
def ventas_registrar(datos: VentaPosNueva, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, datos.panaderia_id, "ventas")
    ids = [linea.producto_id for linea in datos.lineas]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="No repitas productos en una misma venta.")
    try:
        resultado = supabase.rpc("registrar_venta_pos", {
            "p_panaderia_id": datos.panaderia_id,
            "p_fecha": fecha_operativa_hoy().isoformat(),
            "p_usuario_id": str(usuario.id),
            "p_usuario_nombre": perfil.get("nombre") or "Usuario",
            "p_lineas": [{"producto_id": x.producto_id, "cantidad": x.cantidad} for x in datos.lineas]
        }).execute().data
        if isinstance(resultado, list) and resultado:
            resultado = resultado[0]
        return {"registrada": True, "venta": resultado}
    except HTTPException:
        raise
    except Exception as exc:
        detalle = str(exc).lower()
        if "disponible" in detalle or "availability" in detalle:
            raise HTTPException(status_code=409, detail="Uno o más productos ya no están disponibles para venta hoy.")
        raise HTTPException(status_code=503, detail="No se pudo registrar la venta. Verifica la disponibilidad e inténtalo de nuevo.")


def obtener_ventas_pos_dia(panaderia_id: int, fecha: date):
    ventas = (supabase.table("ventas_pos")
        .select("id,numero_venta,fecha,usuario_nombre,total,creado_en")
        .eq("panaderia_id", panaderia_id).eq("fecha", fecha.isoformat())
        .order("numero_venta").execute().data or [])
    if not ventas:
        return []
    ids = [int(v["id"]) for v in ventas]
    detalles = (supabase.table("ventas_pos_detalles")
        .select("venta_id,producto_id,producto_nombre,cantidad,precio_unitario,importe")
        .in_("venta_id", ids).order("id").execute().data or [])
    por_venta = {int(v["id"]): [] for v in ventas}
    for linea in detalles:
        por_venta.setdefault(int(linea["venta_id"]), []).append(linea)
    for venta in ventas:
        venta["lineas"] = por_venta.get(int(venta["id"]), [])
    return ventas


@app.get("/api/ventas/dia")
def ventas_consultar_dia(panaderia_id: int, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    try:
        fecha = fecha_operativa_hoy()
        ventas = obtener_ventas_pos_dia(panaderia_id, fecha)
        return {"fecha": fecha.isoformat(), "ventas": ventas, "total_ventas": len(ventas)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron consultar las ventas del día.")


@app.get("/api/ventas/dia/excel")
def ventas_descargar_dia_excel(panaderia_id: int, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    try:
        fecha = fecha_operativa_hoy()
        ventas = obtener_ventas_pos_dia(panaderia_id, fecha)
        local = (supabase.table("panaderias").select("nombre").eq("id",panaderia_id).limit(1).execute().data or [])
        nombre_local = local[0]["nombre"] if local else "Panadería"
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Ventas del día"
        hoja.append(["Panadería", nombre_local])
        hoja.append(["Fecha", fecha.isoformat()])
        hoja.append([])
        hoja.append(["Venta", "Hora", "Cuenta", "Producto", "Cantidad", "Precio unitario", "Importe", "Total de venta"])
        cantidad_total = 0
        importe_total = Decimal("0")
        for venta in ventas:
            hora = datetime.fromisoformat(str(venta["creado_en"]).replace("Z","+00:00")).astimezone(TZ_PRODUCCION).replace(tzinfo=None) if venta.get("creado_en") else None
            for indice, linea in enumerate(venta.get("lineas", [])):
                cantidad = int(linea.get("cantidad") or 0)
                precio = Decimal(str(linea.get("precio_unitario") or 0))
                importe = Decimal(str(linea.get("importe") or 0))
                cantidad_total += cantidad
                importe_total += importe
                hoja.append([
                    "Venta " + str(venta["numero_venta"]), hora,
                    venta.get("usuario_nombre") or "Usuario",
                    linea.get("producto_nombre") or "Producto", cantidad,
                    float(precio), float(importe), float(Decimal(str(venta.get("total") or 0))) if indice == 0 else None
                ])
                hoja.cell(row=hoja.max_row,column=2).number_format = "hh:mm"
                for col in (6,7,8): hoja.cell(row=hoja.max_row,column=col).number_format = '"$"#,##0.00'
        total_row = hoja.max_row + 1
        hoja.cell(total_row,4,"TOTAL DEL DÍA")
        hoja.cell(total_row,5,cantidad_total)
        hoja.cell(total_row,7,float(importe_total.quantize(Decimal("0.01"))))
        hoja.cell(total_row,7).number_format = '"$"#,##0.00'
        hoja.freeze_panes = "A5"
        hoja.auto_filter.ref = f"A4:H{max(4,total_row-1)}"
        for col,width in {"A":16,"B":14,"C":22,"D":34,"E":14,"F":18,"G":18,"H":18}.items():
            hoja.column_dimensions[col].width = width
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = "ventas_" + str(panaderia_id) + "_" + fecha.isoformat() + ".xlsx"
        return StreamingResponse(salida,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":f'attachment; filename="{nombre}"'})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el Excel de ventas del día.")


@app.get("/api/ventas/resumen")
def ventas_consultar_resumen(panaderia_id: int, authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    try:
        fecha = fecha_operativa_hoy()
        ventas = obtener_ventas_pos_dia(panaderia_id, fecha)
        resumen = {}
        total = Decimal("0")
        cantidad_total = 0
        for venta in ventas:
            for linea in venta["lineas"]:
                pid = linea.get("producto_id")
                clave = int(pid) if pid is not None else str(linea["producto_nombre"])
                if clave not in resumen:
                    resumen[clave] = {"producto_id": pid, "producto": linea["producto_nombre"], "cantidad": 0, "importe": Decimal("0")}
                cantidad = int(linea["cantidad"])
                importe = Decimal(str(linea["importe"]))
                resumen[clave]["cantidad"] += cantidad
                resumen[clave]["importe"] += importe
                cantidad_total += cantidad
                total += importe
        salida = sorted(resumen.values(), key=lambda x: x["producto"].casefold())
        for fila in salida:
            fila["importe"] = str(fila["importe"].quantize(Decimal("0.01")))
        return {"fecha": fecha.isoformat(), "resumen": salida, "cantidad_total": cantidad_total,
                "importe_total": str(total.quantize(Decimal("0.01"))), "total_ventas": len(ventas)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el resumen de ventas.")


# Personalización visual de módulos: los colores no sustituyen los permisos.
COLORES_MODULOS_PREDETERMINADOS = {
    "ventas": "#B9D7EA", "produccion": "#B9DCC6",
    "inventarios": "#F2C99B", "administracion": "#D8CBE8"
}


@app.get("/api/colores")
def consultar_colores(authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    obtener_perfil(str(usuario.id))
    try:
        filas = supabase.table("configuracion_colores").select("ventas,produccion,inventarios,administracion").eq("id", 1).limit(1).execute().data or []
        return filas[0] if filas else COLORES_MODULOS_PREDETERMINADOS
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar la personalización de colores.")


class ColoresModulosCambio(BaseModel):
    ventas: str = Field(pattern="^#[0-9A-Fa-f]{6}$")
    produccion: str = Field(pattern="^#[0-9A-Fa-f]{6}$")
    inventarios: str = Field(pattern="^#[0-9A-Fa-f]{6}$")
    administracion: str = Field(default="#D8CBE8", pattern="^#[0-9A-Fa-f]{6}$")


@app.put("/api/admin/colores")
def guardar_colores(datos: ColoresModulosCambio, authorization: str | None = Header(default=None)):
    usuario, perfil = exigir_admin_principal(authorization)
    try:
        fila = {"id": 1, "ventas": datos.ventas.upper(), "produccion": datos.produccion.upper(),
                "inventarios": datos.inventarios.upper(), "administracion": datos.administracion.upper(),
                "actualizado_por": str(usuario.id)}
        supabase.table("configuracion_colores").upsert(fila, on_conflict="id").execute()
        return {"guardado": True, "colores": {k: fila[k] for k in ("ventas", "produccion", "inventarios", "administracion")}}
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudieron guardar los colores.")




def obtener_ventas_pos_periodo(panaderia_id: int, desde: date, hasta: date):
    ventas = []
    inicio = 0
    while True:
        pagina = (supabase.table("ventas_pos")
            .select("id,numero_venta,fecha,usuario_nombre,total,creado_en")
            .eq("panaderia_id", panaderia_id)
            .gte("fecha", desde.isoformat()).lte("fecha", hasta.isoformat())
            .order("fecha").order("numero_venta")
            .range(inicio, inicio + 999).execute().data or [])
        ventas.extend(pagina)
        if len(pagina) < 1000:
            break
        inicio += 1000
    if not ventas:
        return []
    por_venta = {int(v["id"]): [] for v in ventas}
    ids = list(por_venta)
    for i in range(0, len(ids), 300):
        bloque = ids[i:i + 300]
        detalles = (supabase.table("ventas_pos_detalles")
            .select("venta_id,producto_id,producto_nombre,cantidad,precio_unitario,importe")
            .in_("venta_id", bloque).order("id").execute().data or [])
        for linea in detalles:
            por_venta.setdefault(int(linea["venta_id"]), []).append(linea)
    for venta in ventas:
        venta["lineas"] = por_venta.get(int(venta["id"]), [])
    return ventas


def construir_resumen_ventas(ventas: list[dict]):
    resumen = {}
    por_precio = {}
    cantidad_total = 0
    importe_total = Decimal("0")
    for venta in ventas:
        for linea in venta.get("lineas", []):
            nombre = str(linea.get("producto_nombre") or "Producto")
            clave = (linea.get("producto_id"), nombre.casefold())
            if clave not in resumen:
                resumen[clave] = {"producto": nombre, "cantidad": 0, "importe": Decimal("0")}
            cantidad = int(linea.get("cantidad") or 0)
            precio = Decimal(str(linea.get("precio_unitario") or "0")).quantize(Decimal("0.01"))
            importe = Decimal(str(linea.get("importe") or "0"))
            resumen[clave]["cantidad"] += cantidad
            resumen[clave]["importe"] += importe
            if precio not in por_precio:
                por_precio[precio] = {"precio":precio,"cantidad":0,"importe":Decimal("0")}
            por_precio[precio]["cantidad"] += cantidad
            por_precio[precio]["importe"] += importe
            cantidad_total += cantidad
            importe_total += importe
    filas = sorted(resumen.values(), key=lambda x: x["producto"].casefold())
    for fila in filas:
        fila["importe"] = str(fila["importe"].quantize(Decimal("0.01")))
    filas_precio = [{"precio":str(x["precio"]), "cantidad":x["cantidad"],
                     "importe":str(x["importe"].quantize(Decimal("0.01")))}
                    for x in sorted(por_precio.values(), key=lambda x:x["precio"])]
    return {"resumen":filas,"por_precio":filas_precio,"cantidad_total":cantidad_total,
            "importe_total":str(importe_total.quantize(Decimal("0.01"))),
            "total_ventas":len(ventas),"operaciones":len(ventas)}


def validar_periodo_ventas(desde: date, hasta: date):
    if desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la fecha final.")
    if hasta > fecha_operativa_hoy():
        raise HTTPException(status_code=422, detail="No puedes consultar ventas de fechas futuras.")
    if (hasta - desde).days > 3649:
        raise HTTPException(status_code=422, detail="El periodo de ventas no puede superar diez años.")


@app.get("/api/ventas/historial")
def ventas_consultar_historial(panaderia_id: int, desde: date, hasta: date,
                               authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    validar_periodo_ventas(desde, hasta)
    try:
        ventas = obtener_ventas_pos_periodo(panaderia_id, desde, hasta)
        return {"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                "ventas": ventas, **construir_resumen_ventas(ventas)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar el historial de ventas.")


@app.get("/api/ventas/historial/excel")
def ventas_descargar_historial_excel(panaderia_id: int, desde: date, hasta: date,
                                     authorization: str | None = Header(default=None)):
    usuario = obtener_usuario_autenticado(authorization)
    perfil = obtener_perfil(str(usuario.id))
    comprobar_permiso_local(str(usuario.id), perfil, panaderia_id, "ventas")
    validar_periodo_ventas(desde, hasta)
    try:
        ventas = obtener_ventas_pos_periodo(panaderia_id, desde, hasta)
        datos = construir_resumen_ventas(ventas)
        libro = Workbook()
        resumen = libro.active
        resumen.title = "Resumen"
        resumen.append(["Producto", "Cantidad", "Importe"])
        for fila in datos["resumen"]:
            resumen.append([fila["producto"], fila["cantidad"], float(Decimal(fila["importe"]))])
        resumen.append(["TOTAL GENERAL", datos["cantidad_total"], float(Decimal(datos["importe_total"]))])
        resumen.freeze_panes = "A2"
        resumen.auto_filter.ref = resumen.dimensions
        resumen.column_dimensions["A"].width = 36
        resumen.column_dimensions["B"].width = 16
        resumen.column_dimensions["C"].width = 18
        for row in resumen.iter_rows(min_row=2, min_col=3, max_col=3):
            row[0].number_format = '"$"#,##0.00'

        detalle = libro.create_sheet("Ventas")
        detalle.append(["Fecha", "Venta", "Hora", "Registró", "Producto", "Cantidad", "Precio unitario", "Importe"])
        for venta in ventas:
            hora = ""
            if venta.get("creado_en"):
                marca = datetime.fromisoformat(str(venta["creado_en"]).replace("Z", "+00:00"))
                if marca.tzinfo is None:
                    marca = marca.replace(tzinfo=timezone.utc)
                hora = marca.astimezone(TZ_PRODUCCION).strftime("%H:%M")
            for linea in venta.get("lineas", []):
                detalle.append([venta["fecha"], "Venta #" + str(venta["numero_venta"]), hora,
                    venta.get("usuario_nombre") or "Usuario", linea["producto_nombre"],
                    int(linea["cantidad"]), float(Decimal(str(linea["precio_unitario"]))),
                    float(Decimal(str(linea["importe"])) )])
        detalle.freeze_panes = "A2"
        detalle.auto_filter.ref = detalle.dimensions
        for col, width in {"A":14,"B":14,"C":12,"D":22,"E":34,"F":13,"G":18,"H":18}.items():
            detalle.column_dimensions[col].width = width
        for row in detalle.iter_rows(min_row=2, min_col=7, max_col=8):
            for cell in row:
                cell.number_format = '"$"#,##0.00'
        salida = BytesIO()
        libro.save(salida)
        salida.seek(0)
        nombre = f"ventas_{panaderia_id}_{desde.isoformat()}_{hasta.isoformat()}.xlsx"
        return StreamingResponse(salida, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo generar el Excel del historial de ventas.")


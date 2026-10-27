
from pathlib import Path
import os
import unicodedata

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from io import BytesIO
from openpyxl import Workbook
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
                .select("id,nombre,activa")
                .order("id")                .execute()
            )
            return {"panaderias": resultado.data}

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
            .select("id,nombre,activa")
            .in_("id", ids)
            .order("id")
            .execute()
        )

        return {"panaderias": resultado.data}

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


def comprobar_acceso_panaderia(usuario_id: str, perfil: dict, panaderia_id: int):
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
    comprobar_acceso_panaderia(str(usuario.id), perfil, panaderia_id)
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
            .select("id,producto_id,cantidad,precio_unitario")
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
    if registro.fecha > date.today():
        raise HTTPException(status_code=422, detail="No puedes registrar una fecha futura.")
    ids = [linea.producto_id for linea in registro.lineas]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="No repitas el mismo producto en el registro.")
    try:
        cierre = obtener_o_crear_cierre(registro.panaderia_id, registro.fecha, str(usuario.id))
        if cierre["estado"] == "cerrado":
            cerrado_en = datetime.fromisoformat(cierre["cerrado_en"].replace("Z", "+00:00"))
            ahora = datetime.now(timezone.utc)
            es_admin_principal = (
                perfil["rol"] == "admin" and perfil["es_admin_principal"]
            )
            if (
                (ahora - cerrado_en).total_seconds() >= 48 * 3600
                and not es_admin_principal
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Pasaron 48 horas desde el cierre. Solo el administrador principal puede reabrirlo para corregirlo.",
                )
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
    if fecha_registro > date.today():
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
        if solicitud.fecha > date.today():
            raise HTTPException(status_code=422, detail="No puedes reabrir una fecha futura.")
        cerrado_en = datetime.fromisoformat(cierre["cerrado_en"].replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        dentro_de_48h = (ahora - cerrado_en).total_seconds() < 48 * 3600
        admin = es_admin_principal(perfil)
        if not dentro_de_48h and not admin:
            raise HTTPException(status_code=403, detail="Pasaron 48 horas. Solo el administrador principal puede reabrir este registro.")
        motivo = (solicitud.motivo or "").strip()
        if not dentro_de_48h and admin and len(motivo) < 5:
            raise HTTPException(status_code=422, detail="Para una corrección después de 48 horas, escribe un motivo de al menos 5 caracteres.")
        resultado = supabase.rpc("reabrir_cierre_diario", {
            "p_cierre_id": cierre["id"],
            "p_usuario_id": str(usuario.id),
            "p_motivo": motivo or "",
            "p_dentro_de_48h": dentro_de_48h,
            "p_fecha": ahora.isoformat(),
        }).execute()
        return {"reabierto": True, "cierre": resultado.data}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo reabrir el registro. Verifica que la migración esté aplicada.")


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


def email_interno_encargado(username: str) -> str:
    limpio = "".join(c.lower() for c in username if c.isalnum() or c in "._-")
    if not limpio or limpio != username.lower():
        raise HTTPException(status_code=422, detail="El usuario solo puede contener letras, números, punto, guion y guion bajo.")
    return f"{limpio}@usuarios.pizzan.invalid"


class CuentaEncargadoNueva(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    locales: list[int] = Field(min_length=1, max_length=100)


class CuentaEncargadoCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=60)
    password: str | None = Field(default=None, min_length=8, max_length=128)
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
            lista = getattr(lote, "users", None) or getattr(getattr(lote, "data", None), "users", None) or []
            for u in lista:
                auth_users[str(u.id)] = u
            if len(lista) < 100:
                break
            pagina += 1
        salida = []
        for p in perfiles:
            uid = str(p["id"])
            au = auth_users.get(uid)
            if not au:
                continue
            meta = getattr(au, "user_metadata", {}) or {}
            correo = getattr(au, "email", None) or ""
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
            supabase.table("perfiles").insert({"id": uid, "nombre": nombre, "rol": "encargado", "es_admin_principal": False}).execute()
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
        if not perfil_result or perfil_result[0].get("es_admin_principal") or perfil_result[0].get("rol") != "encargado":
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
        supabase.table("perfiles").update({"nombre": nombre}).eq("id", usuario_id).execute()
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
        if not p or p[0].get("es_admin_principal") or p[0].get("rol") != "encargado":
            raise HTTPException(status_code=403, detail="Esta cuenta no se puede eliminar desde aquí.")
        supabase.auth.admin.delete_user(usuario_id)
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

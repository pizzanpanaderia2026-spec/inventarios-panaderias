
from pathlib import Path
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
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
                .order("id")
                .execute()
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
    return " ".join(nombre.strip().split())


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
            .select("id,nombre")
            .eq("panaderia_id", producto.panaderia_id)
            .execute()
        )
        if any(p["nombre"].strip().casefold() == nombre.casefold() for p in existentes.data):
            raise HTTPException(status_code=409, detail="Ya existe un producto con ese nombre en esta panadería.")
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
        if any(int(p["id"]) != producto_id and p["nombre"].strip().casefold() == nombre.casefold() for p in existentes.data):
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
    creado = supabase.table("cierres_diarios").insert({
        "panaderia_id": panaderia_id,
        "fecha": fecha_registro.isoformat(),
        "estado": "abierto",
    }).execute()
    if not creado.data:
        # Puede haber una solicitud simultánea creando el mismo día.
        reintento = (
            supabase.table("cierres_diarios").select("*")
            .eq("panaderia_id", panaderia_id)
            .eq("fecha", fecha_registro.isoformat()).limit(1).execute()
        )
        if not reintento.data:
            raise HTTPException(status_code=503, detail="No se pudo preparar el registro diario.")
        return reintento.data[0]
    return creado.data[0]


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
            puede_reabrir = perfil["rol"] == "admin" and perfil["es_admin_principal"]
            if not puede_reabrir and (ahora - cerrado_en).total_seconds() >= 48 * 3600:
                raise HTTPException(status_code=403, detail="Pasaron 48 horas desde el cierre. Solo el administrador principal puede corregirlo.")
            if not puede_reabrir:
                raise HTTPException(status_code=409, detail="El día está cerrado. Usa la opción de reabrir antes de modificarlo.")
        productos = (
            supabase.table("productos")
            .select("id,panaderia_id,precio,activo")
            .eq("panaderia_id", registro.panaderia_id).execute()
        )
        por_id = {int(p["id"]): p for p in productos.data}
        nuevas = []
        for linea in registro.lineas:
            producto = por_id.get(linea.producto_id)
            if not producto or not producto["activo"]:
                raise HTTPException(status_code=422, detail="Uno de los productos no existe o está inactivo.")
            nuevas.append({
                "cierre_id": cierre["id"],
                "producto_id": linea.producto_id,
                "cantidad": linea.cantidad,
                "precio_unitario": str(producto["precio"]),
            })
        actuales = supabase.table("inventario_detalles").select("id").eq("cierre_id", cierre["id"]).execute()
        for detalle in actuales.data:
            supabase.table("inventario_detalles").delete().eq("id", detalle["id"]).execute()
        if nuevas:
            supabase.table("inventario_detalles").insert(nuevas).execute()
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
    try:
        cierre = obtener_o_crear_cierre(panaderia_id, fecha_registro, str(usuario.id))
        if cierre["estado"] == "cerrado":
            return {"cerrado": True, "cerrado_en": cierre["cerrado_en"], "mensaje": "Este día ya estaba cerrado."}
        actualizado = supabase.table("cierres_diarios").update({
            "estado": "cerrado",
            "cerrado_en": datetime.now(timezone.utc).isoformat(),
            "cerrado_por": str(usuario.id),
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }).eq("id", cierre["id"]).execute()
        supabase.table("auditoria_inventario").insert({
            "cierre_id": cierre["id"],
            "panaderia_id": panaderia_id,
            "usuario_id": str(usuario.id),
            "accion": "cierre_diario",
            "detalles": {"fecha": fecha_registro.isoformat()},
        }).execute()
        return {"cerrado": True, "cierre": actualizado.data[0] if actualizado.data else None}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo cerrar el día. Verifica que la migración esté aplicada.")

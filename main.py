
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

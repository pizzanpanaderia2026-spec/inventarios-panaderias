
from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from supabase import create_client


app = FastAPI(
    title="Inventarios de Panaderías",
    description="Sistema para administrar inventarios de panaderías",
    version="0.1.0",
)


# Conexión con Supabase
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
        "mensaje": "La aplicación de inventarios está funcionando.",
        "panaderias": [
            "Panadería Pizzan",
            "Panaderías Alonzo",
        ],
    }


# Prueba de conexión con Supabase
@app.get("/api/probar-supabase")
def probar_supabase():
    if supabase is None:
        return {
            "conectado": False,
            "mensaje": "Faltan las variables de conexión en Render.",
        }

    try:
        resultado = (
            supabase
            .table("panaderias")
            .select("id,nombre")
            .execute()
        )

        return {
            "conectado": True,
            "panaderias": resultado.data,
        }

    except Exception:
        return {
            "conectado": False,
            "mensaje": (
                "No se pudo consultar Supabase. "
                "Revisa los logs de Render."
            ),
        }

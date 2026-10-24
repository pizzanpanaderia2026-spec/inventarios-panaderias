
from pathlib import Path
import os

from supabase import create_client, Client

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Inventarios de Panaderías",
    description="Sistema para administrar inventarios de panaderías",
    version="0.1.0",
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/")
def inicio():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api")
def estado_api():
    return {
        "mensaje": "La aplicación de inventarios está funcionando.",
        "panaderias": [
            "Panadería Pizzan",
            "Panaderías Alonzo",
        ],
    }

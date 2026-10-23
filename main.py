
from fastapi import FastAPI

app = FastAPI(
    title="Inventarios de Panaderías",
    description="Sistema para administrar inventarios de panaderías",
    version="0.1.0",
)

@app.get("/")
def inicio():
    return {
        "mensaje": "¡Nuestra aplicación de inventarios ya está comenzando!",
        "panaderias": ["Panadería Pizzan", "Panadería Alonso"],
    }

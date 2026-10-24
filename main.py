
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Inventarios de Panaderías",
        description="Sistema para administrar inventarios de panaderías",
            version="0.1.0",
            )

            BASE_DIR = Path(__file__).resolve().parent
            STATIC_DIR = BASE_DIR / "static"

            app.mount(
                "/static",
                    StaticFiles(directory=STATIC_DIR),
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
                                                                                    
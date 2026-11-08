"""Endpoints administrativos para comprobar la conexión de archivado."""
from fastapi import APIRouter, Header, HTTPException

from r2_storage import R2ConfigurationError, comprobar_conexion_r2

router = APIRouter()


@router.get("/api/admin/archivado/estado-r2")
def admin_estado_r2(authorization: str | None = Header(default=None)):
    # Importación diferida para reutilizar la autorización central de main.py
    # sin crear una dependencia circular al cargar los módulos.
    from main import exigir_admin_principal

    exigir_admin_principal(authorization)
    try:
        return comprobar_conexion_r2()
    except R2ConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No se pudo comprobar la conexión con Cloudflare R2. Revisa las variables de entorno y los permisos del token.",
        )

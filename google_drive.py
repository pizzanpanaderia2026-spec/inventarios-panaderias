"""Conexión segura con Google Drive para los respaldos de Sorrender.

La credencial se lee desde un Secret File de Render; nunca debe guardarse
en el repositorio ni imprimirse en logs.
"""
import os
from functools import lru_cache
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


DRIVE_SCOPE = ["https://www.googleapis.com/auth/drive"]
DEFAULT_CREDENTIALS_PATH = "/etc/secrets/google-drive-service-account.json"


class GoogleDriveConfigurationError(RuntimeError):
    """La conexión con Google Drive no está configurada correctamente."""


@lru_cache(maxsize=1)
def obtener_servicio_drive():
    """Construye el cliente de Drive usando un Secret File de Render."""
    credentials_path = Path(
        os.environ.get("GOOGLE_DRIVE_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_PATH)
    )
    if not credentials_path.is_file():
        raise GoogleDriveConfigurationError(
            "No está configurado el archivo secreto de Google Drive en el servidor."
        )

    try:
        credentials = Credentials.from_service_account_file(
            str(credentials_path),
            scopes=DRIVE_SCOPE,
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except Exception as exc:
        # No propagar detalles de credenciales ni contenido del archivo secreto.
        raise GoogleDriveConfigurationError(
            "No se pudo inicializar la conexión con Google Drive."
        ) from exc


def verificar_carpeta_respaldo():
    """Comprueba que la cuenta de servicio puede acceder a la carpeta raíz."""
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise GoogleDriveConfigurationError(
            "Falta configurar el ID de la carpeta de respaldos de Google Drive."
        )

    try:
        metadata = (
            obtener_servicio_drive()
            .files()
            .get(
                fileId=folder_id,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:
        raise GoogleDriveConfigurationError(
            "Google Drive no permitió verificar la carpeta de respaldos."
        ) from exc

    if metadata.get("mimeType") != "application/vnd.google-apps.folder":
        raise GoogleDriveConfigurationError(
            "El elemento configurado como respaldo no es una carpeta de Google Drive."
        )

    return {"id": metadata["id"], "nombre": metadata["name"]}

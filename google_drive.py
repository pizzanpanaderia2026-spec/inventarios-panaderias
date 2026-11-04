"""Conexión segura con Google Drive para los respaldos de Sorrender.

La credencial se lee desde un Secret File de Render; nunca debe guardarse
en el repositorio ni imprimirse en logs.
"""
import os
from functools import lru_cache
from io import BytesIO
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


def _escapar_consulta_drive(valor: str) -> str:
    return str(valor).replace("\\", "\\\\").replace("'", "\\'")


def obtener_o_crear_carpeta(nombre: str, carpeta_padre_id: str) -> dict:
    """Busca una subcarpeta por nombre y la crea si todavía no existe."""
    servicio = obtener_servicio_drive()
    nombre_q = _escapar_consulta_drive(nombre)
    consulta = (
        f"name = '{nombre_q}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false and "
        f"'{carpeta_padre_id}' in parents"
    )
    try:
        existentes = servicio.files().list(
            q=consulta,
            pageSize=20,
            orderBy="createdTime",
            fields="files(id,name,mimeType)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if existentes:
            return existentes[0]
        return servicio.files().create(
            body={
                "name": nombre,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [carpeta_padre_id],
            },
            fields="id,name,mimeType",
            supportsAllDrives=True,
        ).execute()
    except Exception as exc:
        raise GoogleDriveConfigurationError(
            "No se pudo preparar la carpeta del respaldo en Google Drive."
        ) from exc


def preparar_carpeta_periodo(nombre_panaderia: str, anio: int) -> str:
    """Crea la ruta raíz/local/año y devuelve el ID de la carpeta anual."""
    raiz = verificar_carpeta_respaldo()
    local = obtener_o_crear_carpeta(nombre_panaderia, raiz["id"])
    carpeta_anio = obtener_o_crear_carpeta(str(anio), local["id"])
    return carpeta_anio["id"]


def _buscar_archivo_por_clave(clave: str) -> list[dict]:
    servicio = obtener_servicio_drive()
    clave_q = _escapar_consulta_drive(clave)
    consulta = (
        "trashed = false and "
        f"appProperties has {{ key='archive_key' and value='{clave_q}' }}"
    )
    return servicio.files().list(
        q=consulta,
        pageSize=20,
        fields="files(id,name,mimeType,size,md5Checksum,appProperties,parents)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])


def descargar_archivo_drive(file_id: str) -> bytes:
    """Descarga el contenido binario de un archivo guardado en Drive."""
    from googleapiclient.http import MediaIoBaseDownload

    salida = BytesIO()
    try:
        solicitud = obtener_servicio_drive().files().get_media(
            fileId=file_id,
            supportsAllDrives=True,
        )
        descarga = MediaIoBaseDownload(salida, solicitud)
        terminado = False
        while not terminado:
            _, terminado = descarga.next_chunk()
        return salida.getvalue()
    except Exception as exc:
        raise GoogleDriveConfigurationError(
            "No se pudo descargar el archivo de respaldo desde Google Drive."
        ) from exc


def subir_y_verificar_excel(
    carpeta_id: str,
    nombre_archivo: str,
    contenido: bytes,
    clave_archivo: str,
) -> dict:
    """Sube el Excel una sola vez y verifica que Drive conserva los mismos bytes."""
    import hashlib
    from googleapiclient.http import MediaIoBaseUpload

    servicio = obtener_servicio_drive()
    sha256 = hashlib.sha256(contenido).hexdigest()
    try:
        existentes = _buscar_archivo_por_clave(clave_archivo)
        if len(existentes) > 1:
            raise GoogleDriveConfigurationError(
                "Hay más de un archivo asociado al mismo periodo. No se modificó ninguno."
            )
        if existentes:
            archivo = existentes[0]
            contenido_existente = descargar_archivo_drive(archivo["id"])
            sha_existente = hashlib.sha256(contenido_existente).hexdigest()
            sha_guardado = (archivo.get("appProperties") or {}).get("content_sha256")
            if sha_guardado:
                coincide = sha_existente == sha_guardado
            else:
                coincide = sha_existente == sha256
            if not coincide:
                raise GoogleDriveConfigurationError(
                    "El archivo existente no superó la verificación de integridad. No se modificó."
                )
            return {
                "id": archivo["id"],
                "nombre": archivo["name"],
                "sha256": sha_existente,
                "bytes": len(contenido_existente),
                "verificado": True,
                "reutilizado": True,
            }

        nombre_q = _escapar_consulta_drive(nombre_archivo)
        carpeta_q = _escapar_consulta_drive(carpeta_id)
        colision = servicio.files().list(
            q=(
                f"name = '{nombre_q}' and trashed = false and "
                f"'{carpeta_q}' in parents"
            ),
            pageSize=10,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if colision:
            raise GoogleDriveConfigurationError(
                "Ya existe un archivo con el mismo nombre que no pertenece al registro de archivado. No se sobrescribió."
            )

        media = MediaIoBaseUpload(
            BytesIO(contenido),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=True,
        )
        creado = servicio.files().create(
            body={
                "name": nombre_archivo,
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "parents": [carpeta_id],
                "appProperties": {
                    "archive_key": clave_archivo,
                    "content_sha256": sha256,
                },
            },
            media_body=media,
            fields="id,name,size,md5Checksum,appProperties",
            supportsAllDrives=True,
        ).execute()

        contenido_verificado = descargar_archivo_drive(creado["id"])
        sha_verificado = hashlib.sha256(contenido_verificado).hexdigest()
        if sha_verificado != sha256 or len(contenido_verificado) != len(contenido):
            raise GoogleDriveConfigurationError(
                "Google Drive recibió el archivo, pero la verificación del contenido no coincidió."
            )
        return {
            "id": creado["id"],
            "nombre": creado["name"],
            "sha256": sha256,
            "bytes": len(contenido_verificado),
            "verificado": True,
            "reutilizado": False,
        }
    except GoogleDriveConfigurationError:
        raise
    except Exception as exc:
        raise GoogleDriveConfigurationError(
            "No se pudo subir y verificar el Excel en Google Drive."
        ) from exc


def obtener_archivo_archivado(clave_archivo: str) -> dict | None:
    """Devuelve el archivo de Drive asociado a una clave de periodo."""
    try:
        archivos = _buscar_archivo_por_clave(clave_archivo)
        return archivos[0] if archivos else None
    except Exception as exc:
        if isinstance(exc, GoogleDriveConfigurationError):
            raise
        raise GoogleDriveConfigurationError(
            "No se pudo consultar el archivo histórico en Google Drive."
        ) from exc

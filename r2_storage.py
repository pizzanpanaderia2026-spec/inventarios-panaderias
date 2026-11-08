"""Cliente privado de Cloudflare R2 mediante la API compatible con S3."""
from __future__ import annotations

import os
import uuid

import boto3
from botocore.config import Config


class R2ConfigurationError(RuntimeError):
    """La configuración de R2 está incompleta."""


def crear_cliente_r2():
    required = (
        "R2_ENDPOINT",
        "R2_BUCKET_NAME",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise R2ConfigurationError(
            "Faltan variables de entorno de R2: " + ", ".join(missing)
        )

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"].rstrip("/"),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name=os.getenv("R2_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=15,
        ),
    )


def comprobar_conexion_r2() -> dict:
    """Prueba escritura, lectura de metadatos y borrado en el bucket privado."""
    bucket = os.environ.get("R2_BUCKET_NAME")
    cliente = crear_cliente_r2()
    key = f"__healthcheck__/render-{uuid.uuid4().hex}.txt"
    contenido = b"R2 connection check"
    subido = False

    try:
        cliente.put_object(
            Bucket=bucket,
            Key=key,
            Body=contenido,
            ContentType="text/plain",
        )
        subido = True
        metadata = cliente.head_object(Bucket=bucket, Key=key)
        if int(metadata.get("ContentLength", -1)) != len(contenido):
            raise RuntimeError("La verificación del objeto de prueba no coincidió.")
        cliente.delete_object(Bucket=bucket, Key=key)
        subido = False
        return {
            "conectado": True,
            "bucket": bucket,
            "mensaje": "Cloudflare R2 está conectado y permite guardar y verificar objetos.",
        }
    finally:
        if subido:
            try:
                cliente.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass

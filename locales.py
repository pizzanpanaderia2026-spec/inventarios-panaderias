"""Creación de locales y fotografías privadas almacenadas en Cloudflare R2."""
from __future__ import annotations

from io import BytesIO
import os
import uuid

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

router = APIRouter(tags=["locales"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_EDGE = 1600
PHOTO_URL_TTL = 15 * 60


def _core():
    import main
    return main


def _admin(authorization: str | None):
    core = _core()
    return core.exigir_admin_principal(authorization)


def _r2():
    from r2_storage import crear_cliente_r2
    bucket = os.environ.get("R2_BUCKET_NAME")
    if not bucket:
        raise HTTPException(status_code=503, detail="Falta configurar el bucket de fotografías.")
    return crear_cliente_r2(), bucket


def _foto_url(key: str | None):
    if not key:
        return None
    try:
        client, bucket = _r2()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=PHOTO_URL_TTL,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo preparar la fotografía del local.")


async def _optimizar_foto(file: UploadFile | None) -> bytes | None:
    if file is None or not file.filename:
        return None
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="La fotografía está vacía.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="La fotografía debe pesar 10 MB o menos.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}:
                raise HTTPException(status_code=415, detail="Usa una imagen JPG, PNG o WEBP.")
            if getattr(source, "is_animated", False):
                source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=6)
            return output.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=415, detail="El archivo seleccionado no es una imagen válida.")


def _subir_foto(key: str, contenido: bytes):
    client, bucket = _r2()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=contenido,
        ContentType="image/webp",
        CacheControl="private, max-age=300",
    )


def _copiar_catalogo(core, source_id: int, target_id: int):
    source_categories = (
        core.supabase.table("categorias_productos").select("*")
        .eq("panaderia_id", source_id).order("id").execute().data or []
    )
    category_map = {}
    for category in source_categories:
        inserted = core.supabase.table("categorias_productos").insert({
            "panaderia_id": target_id,
            "nombre": category["nombre"],
            "activa": bool(category.get("activa", True)),
            "protegida": bool(category.get("protegida", False)),
        }).execute().data[0]
        category_map[int(category["id"])] = int(inserted["id"])

    source_products = (
        core.supabase.table("productos").select("*")
        .eq("panaderia_id", source_id).order("id").execute().data or []
    )
    for product in source_products:
        category_id = category_map.get(int(product["categoria_id"])) if product.get("categoria_id") is not None else None
        original_id = category_map.get(int(product["categoria_original_id"])) if product.get("categoria_original_id") is not None else None
        core.supabase.table("productos").insert({
            "panaderia_id": target_id,
            "nombre": product["nombre"],
            "precio": str(product["precio"]),
            "activo": bool(product.get("activo", True)),
            "categoria_id": category_id,
            "categoria_original_id": original_id,
        }).execute()


@router.post("/api/admin/panaderias", status_code=201)
async def crear_panaderia(
    nombre: str = Form(..., min_length=1, max_length=120),
    copiar_de: int | None = Form(default=None),
    foto: UploadFile | None = File(default=None),
    authorization: str | None = Header(default=None),
):
    user, profile = _admin(authorization)
    core = _core()
    clean_name = " ".join(nombre.split())
    if not clean_name:
        raise HTTPException(status_code=422, detail="Escribe el nombre del local.")
    image_bytes = await _optimizar_foto(foto)
    photo_key = None
    local_id = None
    try:
        duplicate = core.supabase.table("panaderias").select("id").ilike("nombre", clean_name).limit(1).execute().data
        if duplicate:
            raise HTTPException(status_code=409, detail="Ya existe un local con ese nombre.")
        if copiar_de is not None:
            source = core.supabase.table("panaderias").select("id").eq("id", copiar_de).eq("activa", True).limit(1).execute().data
            if not source:
                raise HTTPException(status_code=404, detail="No se encontró el local del que deseas copiar la configuración.")
        created = core.supabase.table("panaderias").insert({"nombre": clean_name, "activa": True}).execute().data[0]
        local_id = int(created["id"])
        if copiar_de is not None:
            _copiar_catalogo(core, copiar_de, local_id)
        else:
            core.supabase.table("categorias_productos").insert({
                "panaderia_id": local_id,
                "nombre": "Productos desactivados",
                "activa": True,
                "protegida": True,
            }).execute()
        if image_bytes:
            photo_key = f"panaderias/{local_id}/fotos/{uuid.uuid4().hex}.webp"
            _subir_foto(photo_key, image_bytes)
            core.supabase.table("panaderias").update({"foto_key": photo_key}).eq("id", local_id).execute()
        core.supabase.table("auditoria_inventario").insert({
            "panaderia_id": local_id,
            "usuario_id": str(user.id),
            "accion": "crear_panaderia",
            "detalles": {"nombre": clean_name, "copiado_de": copiar_de, "con_foto": bool(photo_key)},
        }).execute()
        row = core.supabase.table("panaderias").select("id,nombre,activa,foto_key").eq("id", local_id).single().execute().data
        return {"panaderia": {**row, "foto_url": _foto_url(row.get("foto_key"))}}
    except HTTPException:
        if photo_key:
            try:
                client, bucket = _r2()
                client.delete_object(Bucket=bucket, Key=photo_key)
            except Exception:
                pass
        if local_id:
            try:
                core.supabase.table("productos").delete().eq("panaderia_id", local_id).execute()
                core.supabase.table("categorias_productos").delete().eq("panaderia_id", local_id).execute()
                core.supabase.table("panaderias").delete().eq("id", local_id).execute()
            except Exception:
                pass
        raise
    except Exception:
        if photo_key:
            try:
                client, bucket = _r2()
                client.delete_object(Bucket=bucket, Key=photo_key)
            except Exception:
                pass
        if local_id:
            try:
                core.supabase.table("productos").delete().eq("panaderia_id", local_id).execute()
                core.supabase.table("categorias_productos").delete().eq("panaderia_id", local_id).execute()
                core.supabase.table("panaderias").delete().eq("id", local_id).execute()
            except Exception:
                pass
        raise HTTPException(status_code=503, detail="No se pudo crear el local. No se modificó ningún otro local.")


@router.put("/api/admin/panaderias/{panaderia_id}/foto")
async def actualizar_foto_panaderia(
    panaderia_id: int,
    foto: UploadFile = File(...),
    authorization: str | None = Header(default=None),
):
    user, profile = _admin(authorization)
    core = _core()
    image_bytes = await _optimizar_foto(foto)
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Selecciona una fotografía.")
    rows = core.supabase.table("panaderias").select("id,foto_key").eq("id", panaderia_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="No se encontró el local.")
    old_key = rows[0].get("foto_key")
    new_key = f"panaderias/{panaderia_id}/fotos/{uuid.uuid4().hex}.webp"
    try:
        _subir_foto(new_key, image_bytes)
        core.supabase.table("panaderias").update({"foto_key": new_key}).eq("id", panaderia_id).execute()
        core.supabase.table("auditoria_inventario").insert({
            "panaderia_id": panaderia_id,
            "usuario_id": str(user.id),
            "accion": "actualizar_foto_panaderia",
            "detalles": {"formato": "webp", "tamano_bytes": len(image_bytes)},
        }).execute()
        if old_key:
            try:
                client, bucket = _r2()
                client.delete_object(Bucket=bucket, Key=old_key)
            except Exception:
                pass
        return {"actualizada": True, "foto_url": _foto_url(new_key)}
    except HTTPException:
        raise
    except Exception:
        try:
            client, bucket = _r2()
            client.delete_object(Bucket=bucket, Key=new_key)
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="No se pudo actualizar la fotografía.")

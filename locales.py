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


def foto_url_para_clave(key: str | None):
    try:
        return _foto_url(key)
    except HTTPException:
        # Una falla temporal de R2 no debe impedir abrir la lista de locales.
        return None


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
            if source.width * source.height > 40_000_000:
                raise HTTPException(status_code=413, detail="La resolución de la imagen es demasiado grande.")
            if getattr(source, "is_animated", False):
                source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=6)
            return output.getvalue()
    except HTTPException:
        raise
    except Image.DecompressionBombError:
        raise HTTPException(status_code=413, detail="La resolución de la imagen es demasiado grande.")
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
    has_protected = any(bool(category.get("protegida")) for category in source_categories)
    for category in source_categories:
        inserted = core.supabase.table("categorias_productos").insert({
            "panaderia_id": target_id,
            "nombre": category["nombre"],
            "activa": bool(category.get("activa", True)),
            "protegida": bool(category.get("protegida", False)),
        }).execute().data[0]
        category_map[int(category["id"])] = int(inserted["id"])
    if not has_protected:
        protected = core.supabase.table("categorias_productos").insert({
            "panaderia_id": target_id,
            "nombre": "Productos desactivados",
            "activa": True,
            "protegida": True,
        }).execute().data[0]
        category_map[-1] = int(protected["id"])

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
                core.supabase.table("auditoria_inventario").delete().eq("panaderia_id", local_id).execute()
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
                core.supabase.table("auditoria_inventario").delete().eq("panaderia_id", local_id).execute()
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
        new_url = _foto_url(new_key)
        core.supabase.table("panaderias").update({"foto_key": new_key}).eq("id", panaderia_id).execute()
        try:
            core.supabase.table("auditoria_inventario").insert({
                "panaderia_id": panaderia_id,
                "usuario_id": str(user.id),
                "accion": "actualizar_foto_panaderia",
                "detalles": {"formato": "webp", "tamano_bytes": len(image_bytes)},
            }).execute()
        except Exception:
            pass
        if old_key:
            try:
                client, bucket = _r2()
                client.delete_object(Bucket=bucket, Key=old_key)
            except Exception:
                pass
        return {"actualizada": True, "foto_url": new_url}
    except HTTPException:
        raise
    except Exception:
        try:
            client, bucket = _r2()
            client.delete_object(Bucket=bucket, Key=new_key)
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="No se pudo actualizar la fotografía.")


def _estado_eliminacion_local(core, panaderia_id: int):
    """Solo permite retirar locales realmente vacíos; no toca datos operativos."""
    local = core.supabase.table("panaderias").select("id,nombre,foto_key,activa").eq("id", panaderia_id).limit(1).execute().data
    if not local:
        raise HTTPException(status_code=404, detail="No se encontró el local.")
    motivos = []
    restantes = core.supabase.table("panaderias").select("id").eq("activa", True).neq("id", panaderia_id).limit(1).execute().data or []
    if not restantes:
        motivos.append("Debe conservarse al menos un local activo.")
    productos = core.supabase.table("productos").select("id,activo").eq("panaderia_id", panaderia_id).execute().data or []
    if any(bool(p.get("activo", True)) for p in productos):
        motivos.append("Productos activos registrados")
    ids_productos = [int(p["id"]) for p in productos]
    if ids_productos:
        detalles = core.supabase.table("inventario_detalles").select("id").in_("producto_id", ids_productos).limit(1).execute().data or []
        if detalles:
            motivos.append("Los productos conservan detalles de inventario históricos")
    comprobaciones = [
        ("cierres_diarios", "Cierres o inventarios registrados"),
        ("produccion_registros", "Registros de producción"),
        ("archivos_archivados", "Archivos históricos o respaldos"),
    ]
    for tabla, etiqueta in comprobaciones:
        filas = core.supabase.table(tabla).select("id").eq("panaderia_id", panaderia_id).limit(1).execute().data or []
        if filas:
            motivos.append(etiqueta)

    # Una cuenta puede estar asignada a varios locales. Solo bloqueamos si
    # eliminar este local la dejaría sin ningún otro local autorizado.
    accesos = core.supabase.table("accesos_panaderias").select("usuario_id").eq("panaderia_id", panaderia_id).execute().data or []
    usuarios_sin_otro_local = []
    for acceso in accesos:
        otros = (
            core.supabase.table("accesos_panaderias")
            .select("panaderia_id")
            .eq("usuario_id", acceso["usuario_id"])
            .neq("panaderia_id", panaderia_id)
            .limit(1).execute().data or []
        )
        if not otros:
            usuarios_sin_otro_local.append(acceso["usuario_id"])
    if usuarios_sin_otro_local:
        motivos.append("Hay usuarios que solo tienen asignado este local")
    return local[0], motivos


@router.get("/api/admin/panaderias/{panaderia_id}/estado-eliminacion")
def estado_eliminacion_panaderia(
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    _admin(authorization)
    core = _core()
    try:
        local, motivos = _estado_eliminacion_local(core, panaderia_id)
        return {
            "panaderia_id": panaderia_id,
            "nombre": local["nombre"],
            "eliminable": not motivos,
            "motivos": motivos,
            "mensaje": "El local está vacío y puede eliminarse." if not motivos else "No se puede eliminar porque aún contiene información o tiene dependencias.",
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo comprobar si el local está vacío.")


@router.delete("/api/admin/panaderias/{panaderia_id}")
def eliminar_panaderia_vacia(
    panaderia_id: int,
    authorization: str | None = Header(default=None),
):
    user, profile = _admin(authorization)
    core = _core()
    try:
        local, motivos = _estado_eliminacion_local(core, panaderia_id)
        if motivos:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar este local: " + "; ".join(motivos) + ".",
            )
        # Solo se limpian categorías y auditoría administrativa del local vacío.
        # Los registros operativos se validaron antes y no se eliminan aquí.
        # Los productos inactivos y las categorías propias se eliminan junto con
        # el local; la validación previa protege cualquier producto con historial.
        core.supabase.table("productos").delete().eq("panaderia_id", panaderia_id).eq("activo", False).execute()
        core.supabase.table("categorias_productos").delete().eq("panaderia_id", panaderia_id).execute()
        core.supabase.table("auditoria_inventario").delete().eq("panaderia_id", panaderia_id).execute()
        # Se retiran únicamente las asignaciones de este local; la comprobación
        # previa garantiza que cada cuenta conserva al menos otro local.
        core.supabase.table("accesos_panaderias").delete().eq("panaderia_id", panaderia_id).execute()
        eliminado = core.supabase.table("panaderias").delete().eq("id", panaderia_id).select("id").execute().data or []
        if not eliminado:
            raise HTTPException(status_code=409, detail="El local ya no existe o no pudo eliminarse.")
        foto_key = local.get("foto_key")
        if foto_key:
            try:
                client, bucket = _r2()
                client.delete_object(Bucket=bucket, Key=foto_key)
            except Exception:
                # La eliminación del local ya quedó confirmada; la foto huérfana no afecta los datos.
                pass
        return {"eliminado": True, "panaderia_id": panaderia_id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar el local vacío. No se modificaron sus inventarios ni registros.")

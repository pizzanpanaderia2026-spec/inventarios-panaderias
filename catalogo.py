from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/catalogo", tags=["catálogo"])


def _core():
    import main
    return main


def _context(authorization, panaderia_id):
    core = _core()
    user = core.obtener_usuario_autenticado(authorization)
    profile = core.obtener_perfil(str(user.id))
    core.comprobar_acceso_panaderia(str(user.id), profile, panaderia_id)
    return core, user, profile


def _categoria(core, panaderia_id, categoria_id, allow_protected=False):
    rows = core.supabase.table("categorias_productos").select("*").eq("id", categoria_id).eq("panaderia_id", panaderia_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="No se encontró la categoría.")
    category = rows[0]
    if category.get("protegida") and not allow_protected:
        raise HTTPException(status_code=400, detail="Esta categoría está protegida.")
    return category



def _tiene_historial_cerrado(core, product_id):
    details = core.supabase.table("inventario_detalles").select("id,cierre_id").eq("producto_id", product_id).execute().data
    if not details:
        return False
    closure_ids = list({int(d["cierre_id"]) for d in details if d.get("cierre_id") is not None})
    closures = core.supabase.table("cierres_diarios").select("id,estado").in_("id", closure_ids).execute().data if closure_ids else []
    status = {int(c["id"]): c["estado"] for c in closures}
    historical = any(d.get("cierre_id") is None or status.get(int(d["cierre_id"])) != "abierto" for d in details)
    open_ids = [d["id"] for d in details if d.get("cierre_id") is not None and status.get(int(d["cierre_id"])) == "abierto"]
    if open_ids:
        # Retira las líneas provisionales de días que siguen abiertos, pero nunca toca cierres.
        core.supabase.table("inventario_detalles").delete().in_("id", open_ids).execute()
    return historical


def _desactivar(core, product, protected_id):
    _tiene_historial_cerrado(core, product["id"])  # Retira líneas provisionales de días abiertos.
    current_category = product.get("categoria_id")
    original = product.get("categoria_original_id")
    if current_category != protected_id and not original:
        original = current_category
    return core.supabase.table("productos").update({
        "activo": False,
        "categoria_original_id": original,
        "categoria_id": protected_id,
    }).eq("id", product["id"]).eq("panaderia_id", product["panaderia_id"]).execute().data[0]


class CategoriaNueva(BaseModel):
    panaderia_id: int = Field(gt=0)
    nombre: str = Field(min_length=1, max_length=100)


class CategoriaCambio(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    activa: Optional[bool] = None


class ProductoNuevoCatalogo(BaseModel):
    panaderia_id: int = Field(gt=0)
    categoria_id: int = Field(gt=0)
    nombre: str = Field(min_length=1, max_length=120)
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class ProductoCambioCatalogo(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=120)
    precio: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    categoria_id: Optional[int] = Field(default=None, gt=0)
    activo: Optional[bool] = None


class AccionProductos(BaseModel):
    panaderia_id: int = Field(gt=0)
    producto_ids: list[int] = Field(min_length=1, max_length=300)
    accion: str
    categoria_destino_id: Optional[int] = Field(default=None, gt=0)


@router.get("")
def listar_catalogo(panaderia_id: int, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, panaderia_id)
    try:
        categories = core.supabase.table("categorias_productos").select("*").eq("panaderia_id", panaderia_id).order("protegida").order("nombre").execute().data
        products = core.supabase.table("productos").select("id,panaderia_id,nombre,precio,activo,creado_en,categoria_id,categoria_original_id").eq("panaderia_id", panaderia_id).order("nombre").execute().data
        counts = {}
        for p in products:
            counts[p.get("categoria_id")] = counts.get(p.get("categoria_id"), 0) + 1
        category_map = {int(c["id"]): c for c in categories}
        for c in categories:
            c["productos_count"] = counts.get(c["id"], 0)
        for p in products:
            category = category_map.get(int(p["categoria_id"])) if p.get("categoria_id") is not None else None
            p["categoria_nombre"] = category.get("nombre") if category else None
            p["categoria_activa"] = bool(category and category.get("activa"))
            p["categoria_protegida"] = bool(category and category.get("protegida"))
        return {"categorias": categories, "productos": products, "es_admin": bool(profile.get("es_admin_principal") or profile.get("rol") == "admin")}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo consultar el catálogo.")


@router.post("/categorias", status_code=201)
def crear_categoria(data: CategoriaNueva, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, data.panaderia_id)
    name = " ".join(data.nombre.split())
    if not name:
        raise HTTPException(status_code=422, detail="Escribe el nombre de la categoría.")
    try:
        exists = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", data.panaderia_id).ilike("nombre", name).limit(1).execute().data
        if exists:
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
        result = core.supabase.table("categorias_productos").insert({"panaderia_id": data.panaderia_id, "nombre": name}).execute().data[0]
        core.supabase.table("auditoria_inventario").insert({"panaderia_id": data.panaderia_id, "usuario_id": str(user.id), "accion": "crear_categoria", "detalles": {"categoria_id": result["id"], "nombre": name}}).execute()
        return {"categoria": result}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo crear la categoría.")


@router.patch("/categorias/{categoria_id}")
def cambiar_categoria(categoria_id: int, data: CategoriaCambio, panaderia_id: int, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, panaderia_id)
    category = _categoria(core, panaderia_id, categoria_id)
    changes = {}
    if data.nombre is not None:
        name = " ".join(data.nombre.split())
        if not name:
            raise HTTPException(status_code=422, detail="Escribe el nombre de la categoría.")
        dup = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", panaderia_id).ilike("nombre", name).neq("id", categoria_id).limit(1).execute().data
        if dup:
            raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre.")
        changes["nombre"] = name
    if data.activa is not None:
        changes["activa"] = data.activa
    if not changes:
        raise HTTPException(status_code=422, detail="No hay cambios para guardar.")
    try:
        result = core.supabase.table("categorias_productos").update(changes).eq("id", categoria_id).eq("panaderia_id", panaderia_id).execute().data[0]
        core.supabase.table("auditoria_inventario").insert({"panaderia_id": panaderia_id, "usuario_id": str(user.id), "accion": "editar_categoria", "detalles": {"categoria_id": categoria_id, "cambios": changes}}).execute()
        return {"categoria": result}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar la categoría.")


@router.delete("/categorias/{categoria_id}")
def eliminar_categoria(categoria_id: int, panaderia_id: int, authorization: str | None = Header(default=None)):
    core, user, _profile = _context(authorization, panaderia_id)
    category = _categoria(core, panaderia_id, categoria_id)
    try:
        products = core.supabase.table("productos").select("id,panaderia_id,categoria_id,categoria_original_id,activo").eq("panaderia_id", panaderia_id).eq("categoria_id", categoria_id).execute().data
        protected = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", panaderia_id).eq("protegida", True).limit(1).execute().data
        if not protected:
            raise HTTPException(status_code=503, detail="No existe la categoría protegida.")
            _tiene_historial_cerrado(core, product["id"])
        # Pierden su categoría original, pero siguen localizables en la carpeta protegida.
        for product in products:
            core.supabase.table("productos").update({"activo": False, "categoria_id": protected[0]["id"], "categoria_original_id": None}).eq("id", product["id"]).execute()
        core.supabase.table("categorias_productos").delete().eq("id", categoria_id).eq("panaderia_id", panaderia_id).execute()
        core.supabase.table("auditoria_inventario").insert({"panaderia_id": panaderia_id, "usuario_id": str(user.id), "accion": "eliminar_categoria", "detalles": {"categoria_id": categoria_id, "nombre": category["nombre"], "productos_desactivados": len(products)}}).execute()
        return {"eliminada": True, "productos_desactivados": len(products)}
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar la categoría.")


@router.post("/productos", status_code=201)
def crear_producto(data: ProductoNuevoCatalogo, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, data.panaderia_id)
    category = _categoria(core, data.panaderia_id, data.categoria_id)
    if not category.get("activa"):
        raise HTTPException(status_code=409, detail="No puedes agregar productos a una categoría desactivada.")
    name = core.normalizar_nombre_producto(data.nombre)
    if not name:
        raise HTTPException(status_code=422, detail="Escribe un nombre de producto.")
    try:
        existing = core.supabase.table("productos").select("id,nombre,activo").eq("panaderia_id", data.panaderia_id).execute().data
        if any(core.clave_nombre_producto(x["nombre"]) == core.clave_nombre_producto(name) for x in existing):
            raise HTTPException(status_code=409, detail="Ese producto ya existe en esta panadería.")
        result = core.supabase.table("productos").insert({"panaderia_id": data.panaderia_id, "nombre": name, "precio": str(data.precio), "activo": True, "categoria_id": data.categoria_id}).execute().data[0]
        core.supabase.table("auditoria_inventario").insert({"panaderia_id": data.panaderia_id, "usuario_id": str(user.id), "accion": "crear_producto", "detalles": {"producto_id": result["id"], "nombre": name, "categoria_id": data.categoria_id, "precio": str(data.precio)}}).execute()
        return {"producto": result}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo agregar el producto.")


@router.patch("/productos/{producto_id}")
def actualizar_producto_catalogo(producto_id: int, data: ProductoCambioCatalogo, panaderia_id: int, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, panaderia_id)
    rows = core.supabase.table("productos").select("*").eq("id", producto_id).eq("panaderia_id", panaderia_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="No se encontró el producto.")
    product = rows[0]
    changes = {}
    if data.nombre is not None:
        name = core.normalizar_nombre_producto(data.nombre)
        if not name:
            raise HTTPException(status_code=422, detail="Escribe un nombre de producto.")
        all_products = core.supabase.table("productos").select("id,nombre").eq("panaderia_id", panaderia_id).execute().data
        if any(int(x["id"]) != producto_id and core.clave_nombre_producto(x["nombre"]) == core.clave_nombre_producto(name) for x in all_products):
            raise HTTPException(status_code=409, detail="Ese nombre ya existe en esta panadería.")
        changes["nombre"] = name
    if data.precio is not None:
        changes["precio"] = str(data.precio)
    if data.categoria_id is not None:
        cat = _categoria(core, panaderia_id, data.categoria_id)
        if not cat.get("activa"):
            raise HTTPException(status_code=409, detail="La categoría seleccionada está desactivada.")
        changes["categoria_id"] = data.categoria_id
        changes["categoria_original_id"] = data.categoria_id
    if data.activo is not None:
        if data.activo:
            target_id = data.categoria_id or product.get("categoria_original_id")
            if not target_id:
                raise HTTPException(status_code=422, detail="Selecciona una categoría para reactivar este producto.")
            target = _categoria(core, panaderia_id, target_id)
            if not target.get("activa"):
                raise HTTPException(status_code=409, detail="La categoría de destino está desactivada.")
            changes.update({"activo": True, "categoria_id": target_id, "categoria_original_id": target_id})
        else:
            protected = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", panaderia_id).eq("protegida", True).limit(1).execute().data
            if not protected:
                raise HTTPException(status_code=503, detail="No existe la categoría protegida de productos desactivados.")
            changes.update({"activo": False, "categoria_original_id": product.get("categoria_original_id") or product.get("categoria_id"), "categoria_id": protected[0]["id"]})
    if not changes:
        raise HTTPException(status_code=422, detail="No hay cambios para guardar.")
    try:
        result = core.supabase.table("productos").update(changes).eq("id", producto_id).eq("panaderia_id", panaderia_id).execute().data[0]
        core.supabase.table("auditoria_inventario").insert({"panaderia_id": panaderia_id, "usuario_id": str(user.id), "accion": "editar_producto", "detalles": {"producto_id": producto_id, "cambios": changes}}).execute()
        return {"producto": result}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo actualizar el producto.")


@router.post("/productos/acciones")
def accion_multiple_productos(data: AccionProductos, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, data.panaderia_id)
    if len(set(data.producto_ids)) != len(data.producto_ids):
        raise HTTPException(status_code=422, detail="No repitas productos.")
    products = core.supabase.table("productos").select("*").eq("panaderia_id", data.panaderia_id).in_("id", data.producto_ids).execute().data
    if len(products) != len(data.producto_ids):
        raise HTTPException(status_code=404, detail="Uno o más productos no pertenecen a esta panadería.")
    try:
        if data.accion == "mover":
            if not data.categoria_destino_id:
                raise HTTPException(status_code=422, detail="Selecciona la categoría de destino.")
            target = _categoria(core, data.panaderia_id, data.categoria_destino_id)
            if not target.get("activa"):
                raise HTTPException(status_code=409, detail="La categoría de destino está desactivada.")
            for p in products:
                if not p.get("activo"):
                    raise HTTPException(status_code=409, detail="Reactiva los productos antes de moverlos.")
                core.supabase.table("productos").update({"categoria_id": target["id"], "categoria_original_id": target["id"]}).eq("id", p["id"]).execute()
            return {"accion": "movidos", "total": len(products)}
        if data.accion == "desactivar":
            protected = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", data.panaderia_id).eq("protegida", True).limit(1).execute().data
            if not protected:
                raise HTTPException(status_code=503, detail="No existe la categoría protegida.")
            for p in products:
                _desactivar(core, p, protected[0]["id"])
            return {"accion": "desactivados", "total": len(products)}
        if data.accion == "eliminar":
            eliminados, desactivados = 0, 0
            for p in products:
                if _tiene_historial_cerrado(core, p["id"]):
                    protected = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", data.panaderia_id).eq("protegida", True).limit(1).execute().data
                    _desactivar(core, p, protected[0]["id"])
                    desactivados += 1
                else:
                    core.supabase.table("productos").delete().eq("id", p["id"]).eq("panaderia_id", data.panaderia_id).execute()
                    eliminados += 1
            return {"accion": "eliminar_mixto", "eliminados": eliminados, "desactivados": desactivados}
        raise HTTPException(status_code=422, detail="Acción no válida.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo completar la acción sobre los productos.")


@router.delete("/productos/{producto_id}")
def eliminar_producto_catalogo(producto_id: int, panaderia_id: int, authorization: str | None = Header(default=None)):
    core, user, profile = _context(authorization, panaderia_id)
    rows = core.supabase.table("productos").select("*").eq("id", producto_id).eq("panaderia_id", panaderia_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="No se encontró el producto.")
    product = rows[0]
    try:
        if _tiene_historial_cerrado(core, producto_id):
            protected = core.supabase.table("categorias_productos").select("id").eq("panaderia_id", panaderia_id).eq("protegida", True).limit(1).execute().data
            _desactivar(core, product, protected[0]["id"])
            return {"accion": "desactivado"}
        core.supabase.table("productos").delete().eq("id", producto_id).eq("panaderia_id", panaderia_id).execute()
        core.supabase.table("auditoria_inventario").insert({
            "panaderia_id": panaderia_id,
            "usuario_id": str(user.id),
            "accion": "eliminar_producto",
            "detalles": {"producto_id": producto_id, "nombre": product.get("nombre")},
        }).execute()
        return {"accion": "eliminado"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="No se pudo eliminar el producto.")

// Administrador de categorías y productos, independiente por panadería.
(function () {
  const root = document.getElementById("catalogoProductos");
  if (!root) return;
  let token = null, bakery = null, categories = [], products = [];
  let openCategory = null, globalMenuOpen = false, categoryMenuOpen = null, selectionMode = false, selected = new Set(), editingProduct = null, editingCategory = null;
  const message = document.getElementById("mensajeProductos");
  const form = document.getElementById("formProducto");
  const nameInput = document.getElementById("nombreProducto");
  const priceInput = document.getElementById("precioProducto");
  const saveButton = document.getElementById("botonGuardarProducto");
  const categoryInput = document.getElementById("categoriaProducto");

  window.iniciarCatalogoProductos = function (session, selectedBakery) {
    token = session.access_token;
    bakery = selectedBakery;
    return load();
  };

  async function api(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const maxAttempts = method === "GET" ? 6 : 1;
    let lastError;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const response = await fetch(url, { ...options, headers: {
          Authorization: "Bearer " + token, Accept: "application/json",
          ...(options.body ? {"Content-Type":"application/json"} : {})
        }});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const error = new Error(data.detail || "No se pudo completar la operación.");
          error.status = response.status;
          if (![429, 502, 503, 504].includes(response.status) || attempt === maxAttempts - 1) throw error;
          lastError = error;
        } else {
          return data;
        }
      } catch (error) {
        lastError = error;
        if (error.status && ![429, 502, 503, 504].includes(error.status)) throw error;
        if (attempt === maxAttempts - 1) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, Math.min(1000 * (2 ** attempt), 8000)));
    }
    throw lastError || new Error("No se pudo consultar el catálogo.");
  }

  function notice(text, type="error") {
    message.textContent = text;
    message.className = "mensaje " + type;
  }
  function hideForm() { form.classList.add("oculto"); editingProduct=null; editingCategory=null; form.reset(); saveButton.textContent="Guardar producto"; }
  function showProductForm(product=null, categoryId=null) {
    editingProduct = product ? product.id : null;
    editingCategory = null;
    form.classList.remove("oculto");
    form.querySelector("h4").textContent = product ? "Editar producto" : "Agregar producto";
    nameInput.value = product ? product.nombre : "";
    priceInput.value = product ? Number(product.precio).toFixed(2) : "";
    categoryInput.innerHTML = "";
    categories.filter(c=>c.activa && !c.protegida).forEach(c=>{
      const o=document.createElement("option");o.value=c.id;o.textContent=c.nombre;categoryInput.append(o);
    });
    if (categoryId) categoryInput.value=String(categoryId);
    else if (product && product.categoria_id) categoryInput.value=String(product.categoria_id);
    saveButton.textContent=product?"Guardar cambios":"Agregar producto";
    form.scrollIntoView({behavior:"smooth",block:"start"});
  }
  function showCategoryForm(category=null) {
    editingCategory=category?category.id:null;
    const current=document.getElementById("formCategoria");
    current.classList.remove("oculto");
    document.getElementById("nombreCategoria").value=category?category.nombre:"";
    document.getElementById("tituloFormCategoria").textContent=category?"Editar categoría":"Nueva categoría";
    current.scrollIntoView({behavior:"smooth",block:"start"});
  }

  async function load() {
    if (!token || !bakery) return;
    root.textContent="Cargando catálogo...";
    try {
      const data=await api("/api/catalogo?panaderia_id="+encodeURIComponent(bakery.id));
      categories=data.categorias||[];products=data.productos||[];
      draw();
      if(window.actualizarRegistroCatalogo) await window.actualizarRegistroCatalogo(products,categories);
      return { productos: products, categorias: categories };
    } catch(e) {
      root.textContent="";
      notice("No se pudo cargar el catálogo: " + e.message + " Puedes tocar Actualizar para volver a intentarlo.");
      return null;
    }
  }

  function makeButton(label, action, cls="secundario") {
    const b=document.createElement("button");b.type="button";b.className=cls;b.textContent=label;b.addEventListener("click",action);return b;
  }
  function categoryProducts(category) {
    return products.filter(p=>String(p.categoria_id)===String(category.id));
  }
  function draw() {
    root.replaceChildren();
    const heading=document.createElement("div");heading.className="catalogo-encabezado";
    const title=document.createElement("div");
    const h=document.createElement("h4");h.textContent="Categorías";
    const sub=document.createElement("p");sub.className="nota";sub.textContent="Organiza los productos de esta panadería.";
    title.append(h,sub);
    const global=document.createElement("div");global.className="catalogo-menu-wrap";
    const dots=makeButton("⋮",()=>{globalMenuOpen=!globalMenuOpen;draw()},"catalogo-tres-puntos");
    dots.setAttribute("aria-label","Opciones del catálogo");global.append(dots);
    if(globalMenuOpen){
      const menu=document.createElement("div");menu.className="catalogo-menu";
      menu.append(makeButton("＋ Nueva categoría",()=>{globalMenuOpen=false;showCategoryForm()}));
      menu.append(makeButton("＋ Nuevo producto",()=>{globalMenuOpen=false;showProductForm()}));
      menu.append(makeButton("Ver productos desactivados",()=>{globalMenuOpen=false;openCategory=categories.find(c=>c.protegida)?.id||null;draw()}));
      global.append(menu);
    }
    heading.append(title,global);root.append(heading);
    const search=document.createElement("input");search.type="search";search.placeholder="Buscar categoría o producto...";search.className="catalogo-busqueda";search.addEventListener("input",()=>drawFiltered(search.value));root.append(search);
    const list=document.createElement("div");list.id="listaCategorias";list.className="catalogo-categorias";root.append(list);
    drawFiltered("");
  }

  function drawFiltered(query) {
    const list=document.getElementById("listaCategorias");if(!list)return;list.replaceChildren();
    const q=query.trim().toLocaleLowerCase("es");
    categories.filter(c=>!q||c.nombre.toLocaleLowerCase("es").includes(q)||categoryProducts(c).some(p=>p.nombre.toLocaleLowerCase("es").includes(q))).forEach(c=>{
      const card=document.createElement("section");card.className="catalogo-categoria";
      const head=document.createElement("div");head.className="catalogo-categoria-cabecera";
      const open=makeButton("",()=>{openCategory=openCategory===c.id?null:c.id;draw()});open.className="catalogo-categoria-abrir";
      const name=document.createElement("span");name.className="catalogo-icono-carpeta";name.textContent=c.protegida?"▣":"▰";
      const label=document.createElement("span");label.className="catalogo-categoria-texto";
      const strong=document.createElement("strong");strong.textContent=c.nombre;
      const small=document.createElement("small");small.textContent=c.protegida?"Categoría permanente":(c.activa?categoryProducts(c).length+" productos":"Categoría desactivada");
      label.append(strong,small);const arrow=document.createElement("span");arrow.textContent=openCategory===c.id?"⌃":"›";
      open.append(name,label,arrow);
      head.append(open);
      if(!c.protegida){
        const actions=document.createElement("div");actions.className="catalogo-menu-wrap";
        const dots=makeButton("⋮",()=>{openCategory=c.id;categoryMenuOpen=categoryMenuOpen===c.id?null:c.id;draw()},"catalogo-tres-puntos");
        dots.setAttribute("aria-label","Opciones de "+c.nombre);actions.append(dots);
        if(categoryMenuOpen===c.id){
          const menu=document.createElement("div");menu.className="catalogo-menu";
          menu.append(makeButton("Seleccionar productos",()=>{openCategory=c.id;selectionMode=true;selected.clear();categoryMenuOpen=null;draw()}));
          menu.append(makeButton("Agregar producto",()=>showProductForm(null,c.id)));
          menu.append(makeButton("Editar categoría",()=>showCategoryForm(c)));
          menu.append(makeButton(c.activa?"Desactivar categoría":"Reactivar categoría",()=>toggleCategory(c)));
          menu.append(makeButton("Eliminar categoría",()=>deleteCategory(c),"boton-peligro"));
          actions.append(menu);
        }
        head.append(actions);
      } else {
        const protectedTag=document.createElement("small");protectedTag.className="catalogo-protegida";protectedTag.textContent="Protegida";head.append(protectedTag);
      }
      card.append(head);
      if(openCategory===c.id){
        const body=document.createElement("div");body.className="catalogo-productos";
        let rows=categoryProducts(c);
        if(q) rows=rows.filter(p=>p.nombre.toLocaleLowerCase("es").includes(q)||c.nombre.toLocaleLowerCase("es").includes(q));
        if(!rows.length){const empty=document.createElement("p");empty.className="nota";empty.textContent="No hay productos en esta categoría.";body.append(empty);}
        rows.forEach(p=>{
          const row=document.createElement("div");row.className="catalogo-producto";
          if(selectionMode){
            const check=document.createElement("input");check.type="checkbox";check.checked=selected.has(p.id);check.addEventListener("change",()=>{check.checked?selected.add(p.id):selected.delete(p.id);drawSelectionActions()});row.append(check);
          }
          const info=document.createElement("button");info.type="button";info.className="catalogo-producto-info";
          const pn=document.createElement("strong");pn.textContent=p.nombre+(p.activo?"":" · Desactivado");
          const price=document.createElement("small");price.textContent="$"+Number(p.precio).toFixed(2);
          info.append(pn,price);info.addEventListener("click",()=>{if(selectionMode){selected.has(p.id)?selected.delete(p.id):selected.add(p.id);draw()}else showProductForm(p,p.categoria_id)});
          row.append(info);
          if(c.protegida){
            row.append(makeButton("Reactivar",()=>reactivate(p),"secundario"));
            if(!selectionMode) row.append(makeButton("Eliminar",()=>deleteInactiveProduct(p),"boton-peligro"));
          } else if(!selectionMode) {
            row.append(makeButton("Editar",()=>showProductForm(p,p.categoria_id),"secundario"));
          }
          body.append(row);
        });
        if(selectionMode){
          const actions=document.createElement("div");actions.id="accionesSeleccion";actions.className="catalogo-acciones-seleccion";
          const count=document.createElement("strong");count.textContent=selected.size+" seleccionados";actions.append(count);
          actions.append(makeButton("Mover",()=>bulkAction("mover")));
          actions.append(makeButton("Desactivar",()=>bulkAction("desactivar")));
          actions.append(makeButton("Eliminar",()=>bulkAction("eliminar"),"boton-peligro"));
          actions.append(makeButton("Cancelar",()=>{selectionMode=false;selected.clear();draw()}));
          body.append(actions);
        }
        card.append(body);
      }
      list.append(card);
    });
  }
  function drawSelectionActions(){const search=document.querySelector(".catalogo-busqueda");drawFiltered(search?search.value:"");}
  async function toggleCategory(c){
    try{await api("/api/catalogo/categorias/"+c.id+"?panaderia_id="+bakery.id,{method:"PATCH",body:JSON.stringify({activa:!c.activa})});categoryMenuOpen=null;await load();notice(c.activa?"Categoría desactivada.":"Categoría reactivada.","exito");}
    catch(e){notice(e.message);}
  }
  async function deleteCategory(c){
    if(!confirm("¿Eliminar la categoría "+c.nombre+"? Sus productos quedarán desactivados y sin categoría original; el historial se conservará."))return;
    try{const r=await api("/api/catalogo/categorias/"+c.id+"?panaderia_id="+bakery.id,{method:"DELETE"});notice("Categoría eliminada. "+r.productos_desactivados+" productos quedaron desactivados y sin categoría.","exito");categoryMenuOpen=null;openCategory=null;await load();}
    catch(e){notice(e.message);}
  }
  async function bulkAction(action){
    if(!selected.size)return notice("Selecciona al menos un producto.");
    if(action==="mover"){
      const options=categories.filter(c=>c.activa&&!c.protegida);
      if(!options.length)return notice("No hay categorías activas para mover los productos.");
      const actions=document.querySelector(".catalogo-acciones-seleccion");
      if(actions.querySelector(".catalogo-mover-selector"))return;
      const picker=document.createElement("div");picker.className="catalogo-mover-selector";picker.style.cssText="display:flex;gap:8px;flex-wrap:wrap;width:100%;margin-top:8px";
      const select=document.createElement("select");select.style.cssText="flex:1;min-width:180px;padding:10px;border:1px solid #cfc5b8;border-radius:8px";
      options.forEach(c=>{const o=document.createElement("option");o.value=c.id;o.textContent=c.nombre;select.append(o)});
      picker.append(select,makeButton("Confirmar",()=>ejecutarAccionMultiple("mover",Number(select.value))),makeButton("Cancelar",()=>picker.remove()));
      actions.append(picker);return;
    }
    if(action==="desactivar"&&!confirm("¿Desactivar los productos seleccionados? Se moverán a Productos desactivados."))return;
    if(action==="eliminar"&&!confirm("Los productos con historial se desactivarán; los que nunca se registraron se eliminarán definitivamente. ¿Continuar?"))return;
    await ejecutarAccionMultiple(action,null);
  }
  async function ejecutarAccionMultiple(action,categoryId){
    try{
      const r=await api("/api/catalogo/productos/acciones",{method:"POST",body:JSON.stringify({panaderia_id:bakery.id,producto_ids:[...selected],accion:action,categoria_destino_id:categoryId})});
      if(action==="eliminar")notice("Eliminados: "+r.eliminados+". Desactivados por tener historial: "+r.desactivados+".","exito");
      else notice(action==="mover"?"Productos movidos.":"Productos desactivados.","exito");
      selected.clear();selectionMode=false;categoryMenuOpen=null;await load();
    }catch(e){notice(e.message);}
  }
  async function deleteInactiveProduct(p){
    if(!confirm("¿Eliminar definitivamente este producto? Solo se permitirá si nunca ha formado parte de un registro histórico."))return;
    try{const r=await api("/api/catalogo/productos/"+p.id+"?panaderia_id="+bakery.id,{method:"DELETE"});notice(r.accion==="eliminado"?"Producto eliminado.":"El producto tenía historial y permanece desactivado.","exito");await load();}
    catch(e){notice(e.message);}
  }
  async function reactivate(p){
    const options=categories.filter(c=>c.activa&&!c.protegida);
    if(!options.length)return notice("Primero crea o reactiva una categoría para asignar el producto.");
    const row=[...document.querySelectorAll(".catalogo-producto")].find(el=>el.textContent.includes(p.nombre));
    if(!row)return;
    if(row.querySelector(".catalogo-reactivar-selector"))return;
    const originalIndex=options.findIndex(c=>String(c.id)===String(p.categoria_original_id));
    const picker=document.createElement("div");picker.className="catalogo-reactivar-selector";
    picker.style.cssText="display:flex;gap:8px;flex-wrap:wrap;align-items:center;width:100%;max-width:100%;min-width:0;box-sizing:border-box;padding:8px 0";
    const select=document.createElement("select");select.style.cssText="flex:1 1 100%;width:100%;min-width:0;max-width:100%;box-sizing:border-box;padding:9px;border:1px solid #cfc5b8;border-radius:8px";
    options.forEach((c,i)=>{const o=document.createElement("option");o.value=c.id;o.textContent=c.nombre+(i===originalIndex?" (original)":"");if(i===originalIndex)o.selected=true;select.append(o)});
    picker.append(select,makeButton("Confirmar",()=>confirmarReactivacion(p,Number(select.value))),makeButton("Cancelar",()=>picker.remove()));
    row.insertAdjacentElement("afterend",picker);
  }
  async function confirmarReactivacion(p,categoryId){
    try{await api("/api/catalogo/productos/"+p.id+"?panaderia_id="+bakery.id,{method:"PATCH",body:JSON.stringify({activo:true,categoria_id:categoryId})});await load();notice("Producto reactivado.","exito");}
    catch(e){notice(e.message);}
  }
  form.addEventListener("submit",async e=>{
    e.preventDefault();const name=nameInput.value.trim(),price=Number(priceInput.value),cat=Number(categoryInput.value);
    if(!name||!Number.isFinite(price)||price<0||!Number.isFinite(cat))return notice("Completa el nombre, precio y categoría.");
    saveButton.disabled=true;
    try{
      if(editingProduct!==null){
        await api("/api/catalogo/productos/"+editingProduct+"?panaderia_id="+bakery.id,{method:"PATCH",body:JSON.stringify({nombre:name,precio:price,categoria_id:cat})});
        notice("Producto actualizado.","exito");
      }else{
        await api("/api/catalogo/productos",{method:"POST",body:JSON.stringify({panaderia_id:bakery.id,categoria_id:cat,nombre:name,precio:price})});
        notice("Producto agregado.","exito");
      }
      hideForm();await load();
    }catch(e2){notice(e2.message);}finally{saveButton.disabled=false;}
  });
  document.getElementById("botonCancelarEdicion").addEventListener("click",hideForm);
  document.getElementById("botonActualizarProductos").addEventListener("click",load);
  document.getElementById("formCategoria").addEventListener("submit",async e=>{
    e.preventDefault();const name=document.getElementById("nombreCategoria").value.trim();if(!name)return;
    try{
      if(editingCategory)await api("/api/catalogo/categorias/"+editingCategory+"?panaderia_id="+bakery.id,{method:"PATCH",body:JSON.stringify({nombre:name})});
      else await api("/api/catalogo/categorias",{method:"POST",body:JSON.stringify({panaderia_id:bakery.id,nombre:name})});
      document.getElementById("formCategoria").classList.add("oculto");editingCategory=null;await load();notice("Categoría guardada.","exito");
    }catch(e2){notice(e2.message);}
  });
  document.getElementById("botonCancelarCategoria").addEventListener("click",()=>document.getElementById("formCategoria").classList.add("oculto"));
})();

// Punto de venta: disponibilidad diaria, ventas individuales y resumen.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { session: null, bakery: null, products: [], categories: [], availabilityDate: null, cart: new Map(), view: "nueva", salesView:"tickets", sales: [], summary: null };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        Authorization: "Bearer " + state.session.access_token,
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    const message = typeof detail === "string" ? detail :
      Array.isArray(detail) ? detail.map(x => x?.msg || x?.message || JSON.stringify(x)).join(" · ") :
      detail && typeof detail === "object" ? (detail.message || detail.msg || JSON.stringify(detail)) :
      "No se pudo completar la operación.";
    if (!response.ok) throw new Error(message);
    return data;
  }

  function money(value) {
    return Number(value || 0).toLocaleString("es-MX", { style: "currency", currency: "MXN" });
  }

  function notice(message, type = "error") {
    const node = $("posMensaje");
    if (!node) return;
    node.textContent = message;
    node.className = "mensaje " + (type === "success" ? "exito" : "error");
  }

  function clearNotice() {
    const node = $("posMensaje");
    if (node) { node.textContent = ""; node.className = "mensaje oculto"; }
  }

  function switchView(view) {
    state.view = view;
    const views = {
      nueva: "posVistaNueva",
      dia: "posVistaDia",
      resumen: "posVistaResumen",
      productos: "posVistaProductos"
    };
    Object.entries(views).forEach(([key, id]) => $(id)?.classList.toggle("oculto", key !== view));
    document.querySelectorAll("[data-pos-vista]").forEach(button => {
      const active = button.dataset.posVista === view;
      button.classList.toggle("activo", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    clearNotice();
    if (view === "productos" || view === "nueva") {
      loadAvailability().then(() => {
        if (view === "productos") drawProducts();
        if (view === "nueva") drawNewSale();
      }).catch(error => notice(error.message));
    }
    if (view === "dia") loadSales();
    if (view === "resumen") loadSummary();
  }

  function productCategoryName(product) {
    return state.categories.find(c => String(c.id) === String(product.categoria_id))?.nombre || "Sin categoría";
  }

  async function loadAvailability() {
    const data = await api("/api/ventas/disponibilidad?panaderia_id=" + encodeURIComponent(state.bakery.id));
    state.products = data.productos || [];
    state.categories = data.categorias || [];
    state.availabilityDate = data.fecha;
    return data;
  }

  function drawProducts(query = $("posBuscarProducto")?.value || "") {
    const root = $("posListaProductos");
    if (!root) return;
    root.replaceChildren();
    const q = query.trim().toLocaleLowerCase("es");
    const categoriesBase = state.categories.slice();
    const categoryIds = new Set(categoriesBase.map(c => String(c.id)));
    if (state.products.some(p => !p.categoria_id || !categoryIds.has(String(p.categoria_id)))) {
      categoriesBase.push({ id: "__sin_categoria", nombre: "Sin categoría" });
    }
    const productsForCategory = category => category.id === "__sin_categoria"
      ? state.products.filter(p => !p.categoria_id || !categoryIds.has(String(p.categoria_id)))
      : state.products.filter(p => String(p.categoria_id) === String(category.id));
    const categories = categoriesBase.filter(category => {
      const rows = productsForCategory(category);
      return !q || category.nombre.toLocaleLowerCase("es").includes(q) || rows.some(p => p.nombre.toLocaleLowerCase("es").includes(q));
    });
    if (!categories.length) {
      const empty = document.createElement("p");
      empty.className = "nota";
      empty.textContent = q ? "No se encontraron productos o categorías." : "No hay categorías disponibles en este local.";
      root.append(empty);
      return;
    }
    categories.forEach(category => {
      const rows = productsForCategory(category)
        .filter(p => !q || category.nombre.toLocaleLowerCase("es").includes(q) || p.nombre.toLocaleLowerCase("es").includes(q));
      const section = document.createElement("section");
      section.className = "pos-categoria";
      const heading = document.createElement("h4");
      heading.textContent = category.nombre;
      section.append(heading);
      rows.forEach(product => {
        const row = document.createElement("div");
        row.className = "pos-producto-disponibilidad";
        const info = document.createElement("span");
        info.className = "pos-producto-info";
        const name = document.createElement("strong");
        name.textContent = product.nombre;
        const price = document.createElement("small");
        price.textContent = money(product.precio);
        info.append(name, price);
        const control = document.createElement("span");
        control.className = "pos-switch-label";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(product.disponible);
        checkbox.setAttribute("aria-label", (product.disponible ? "Desactivar " : "Activar ") + product.nombre + " para venta");
        checkbox.addEventListener("change", async () => {
          checkbox.disabled = true;
          try {
            await api("/api/ventas/disponibilidad", {
              method: "PUT",
              body: JSON.stringify({ panaderia_id: state.bakery.id, producto_id: product.id, disponible: checkbox.checked })
            });
            product.disponible = checkbox.checked;
            if (!checkbox.checked) state.cart.delete(product.id);
            drawNewSale();
            clearNotice();
          } catch (error) {
            checkbox.checked = !checkbox.checked;
            notice(error.message);
          } finally { checkbox.disabled = false; }
        });
        const text = document.createElement("span");
        text.textContent = product.disponible ? "Disponible" : "No disponible";
        control.append(checkbox, text);
        const pin = document.createElement("button");
        pin.type = "button";
        pin.className = "secundario pos-anclar";
        pin.textContent = product.pos_anclado ? "Desanclar" : "Anclar";
        pin.setAttribute("aria-pressed", product.pos_anclado ? "true" : "false");
        pin.setAttribute("aria-label", (product.pos_anclado ? "Desanclar " : "Anclar ") + product.nombre);
        pin.addEventListener("click", async () => {
          pin.disabled = true;
          try {
            await api("/api/ventas/anclado", {method:"PUT", body:JSON.stringify({
              panaderia_id:state.bakery.id, producto_id:product.id, anclado:!product.pos_anclado
            })});
            product.pos_anclado = !product.pos_anclado;
            if (product.pos_anclado) product.disponible = true;
            drawProducts();
            drawNewSale();
            clearNotice();
          } catch(error) { notice(error.message); }
          finally { pin.disabled = false; }
        });
        row.append(info, control, pin);
        section.append(row);
      });
      root.append(section);
    });
  }

  function drawNewSale() {
    const root = $("posListaVenta");
    if (!root) return;
    root.replaceChildren();
    const available = state.products.filter(p => p.disponible).slice().sort((a,b) =>
      Number(Boolean(b.pos_anclado)) - Number(Boolean(a.pos_anclado)) || a.nombre.localeCompare(b.nombre, "es"));
    if (!available.length) {
      const empty = document.createElement("div");
      empty.className = "pos-vacio";
      empty.innerHTML = "<strong>No hay productos disponibles.</strong><p>Entra a Productos y activa los que se venderán hoy en este local.</p>";
      root.append(empty);
    } else {
      available.forEach(product => {
        const row = document.createElement("div");
        row.className = "pos-fila-venta";
        const info = document.createElement("div");
        info.className = "pos-venta-info";
        const name = document.createElement("strong");
        name.textContent = product.nombre;
        const price = document.createElement("small");
        price.textContent = money(product.precio) + " por pieza";
        info.append(name, price);
        const controls = document.createElement("div");
        controls.className = "pos-cantidad-controles";
        const minus = document.createElement("button");
        minus.type = "button"; minus.className = "secundario"; minus.textContent = "−"; minus.setAttribute("aria-label", "Restar " + product.nombre);
        minus.addEventListener("click", () => setQuantity(product, (state.cart.get(product.id)?.cantidad || 0) - 1));
        const input = document.createElement("input");
        input.type = "number"; input.min = "0"; input.step = "1"; input.inputMode = "numeric";
        input.value = String(state.cart.get(product.id)?.cantidad || 0);
        input.setAttribute("aria-label", "Cantidad de " + product.nombre);
        input.addEventListener("change", () => {
          const value = Number.parseInt(input.value, 10);
          setQuantity(product, Number.isFinite(value) && value > 0 ? value : 0);
        });
        const plus = document.createElement("button");
        plus.type = "button"; plus.textContent = "+"; plus.setAttribute("aria-label", "Sumar " + product.nombre);
        plus.addEventListener("click", () => setQuantity(product, (state.cart.get(product.id)?.cantidad || 0) + 1));
        controls.append(minus, input, plus);
        row.append(info, controls);
        root.append(row);
      });
    }
    drawCartTotal();
  }

  function setQuantity(product, quantity) {
    const amount = Math.max(0, Math.min(100000, Math.trunc(Number(quantity) || 0)));
    if (amount === 0) state.cart.delete(product.id);
    else state.cart.set(product.id, { producto_id: product.id, nombre: product.nombre, precio: Number(product.precio), cantidad: amount });
    drawNewSale();
  }

  function drawCartTotal() {
    const items = [...state.cart.values()];
    const quantity = items.reduce((sum, item) => sum + item.cantidad, 0);
    const total = items.reduce((sum, item) => sum + item.cantidad * item.precio, 0);
    $("posCantidadTotal").textContent = quantity.toLocaleString("es-MX");
    $("posImporteTotal").textContent = money(total);
    $("posRegistrarVenta").disabled = items.length === 0;
  }

  async function registerSale() {
    const items = [...state.cart.values()];
    if (!items.length) return;
    const button = $("posRegistrarVenta");
    button.disabled = true;
    try {
      const result = await api("/api/ventas", {
        method: "POST",
        body: JSON.stringify({ panaderia_id: state.bakery.id, lineas: items.map(x => ({ producto_id: x.producto_id, cantidad: x.cantidad })) })
      });
      state.cart.clear();
      await loadAvailability();
      drawNewSale();
      const saleNo = result.venta?.numero_venta;
      notice(saleNo ? "Venta #" + saleNo + " registrada correctamente." : "Venta registrada correctamente.", "success");
      await Promise.all([loadSales(), loadSummary()]);
    } catch (error) {
      notice(error.message);
    } finally { button.disabled = state.cart.size === 0; }
  }

  async function loadSales() {
    const root = $("posListaVentasDia");
    if (!root) return;
    root.textContent = "Cargando ventas del día…";
    try {
      const data = await api("/api/ventas/dia?panaderia_id=" + encodeURIComponent(state.bakery.id));
      state.sales = data.ventas || [];
      root.replaceChildren();
      $("posFechaDia").textContent = "Fecha: " + new Date(data.fecha + "T12:00:00").toLocaleDateString("es-MX");
      if (!state.sales.length) {
        const empty = document.createElement("p"); empty.className = "nota"; empty.textContent = "Todavía no hay ventas registradas hoy."; root.append(empty); return;
      }
      updateSalesViewButtons();
      if (state.salesView === "tabla") {
        drawSalesTable(root);
      } else {
        state.sales.forEach(sale => {
          const card = document.createElement("article"); card.className = "pos-venta-card";
          const head = document.createElement("div"); head.className = "pos-venta-card-head";
          const title = document.createElement("strong"); title.textContent = "Venta #" + sale.numero_venta;
          const total = document.createElement("strong"); total.textContent = money(sale.total);
          head.append(title, total);
          const meta = document.createElement("p"); meta.className = "nota";
          const time = sale.creado_en ? new Date(sale.creado_en).toLocaleTimeString("es-MX", {hour:"2-digit",minute:"2-digit"}) : "";
          meta.textContent = (sale.usuario_nombre || "Usuario") + (time ? " · " + time : "");
          const list = document.createElement("ul");
          (sale.lineas || []).forEach(line => {
            const li = document.createElement("li");
            li.textContent = line.cantidad + " × " + line.producto_nombre + " — " + money(line.importe);
            list.append(li);
          });
          const actions = document.createElement("div"); actions.className = "barra";
          const ticket = document.createElement("button"); ticket.type = "button"; ticket.className = "secundario";
          ticket.textContent = "Descargar ticket PNG";
          ticket.addEventListener("click", () => downloadTicketPNG(sale));
          const edit = document.createElement("button"); edit.type = "button"; edit.className = "secundario";
          edit.textContent = "Corregir venta";
          edit.addEventListener("click", () => showSaleEditor(sale,card));
          actions.append(ticket,edit);
          card.append(head, meta, list, actions); root.append(card);
        });
      }
    } catch (error) { root.textContent = error.message; }
  }

  function showSaleEditor(sale, card) {
    card.replaceChildren();
    const title=document.createElement("h4");title.textContent="Corregir venta "+sale.numero_venta;card.append(title);
    const note=document.createElement("p");note.className="nota";note.textContent="Modifica cantidades. El precio registrado de cada producto se conserva; los productos nuevos toman el precio vigente al momento de la corrección.";card.append(note);
    const inputs=[];
    (sale.lineas||[]).forEach(line=>{
      const row=document.createElement("div");row.className="pos-fila-venta";
      const label=document.createElement("label");label.textContent=line.producto_nombre+" · "+money(line.precio_unitario);
      const input=document.createElement("input");input.type="number";input.min="0";input.max="100000";input.step="1";input.value=String(line.cantidad);
      input.setAttribute("aria-label","Cantidad de "+line.producto_nombre);
      row.append(label,input);card.append(row);
      inputs.push({line,input});
    });
    const actions=document.createElement("div");actions.className="barra";
    const save=document.createElement("button");save.type="button";save.textContent="Guardar corrección";
    const cancel=document.createElement("button");cancel.type="button";cancel.className="secundario";cancel.textContent="Cancelar";
    cancel.addEventListener("click",loadSales);
    save.addEventListener("click",async()=>{
      const lineas=[];
      for(const item of inputs){
        const n=Number(item.input.value);
        if(!Number.isInteger(n)||n<0||n>100000){notice("Las cantidades deben ser enteros entre 0 y 100,000.");return;}
        if(n>0)lineas.push({producto_id:Number(item.line.producto_id),cantidad:n});
      }
      if(!lineas.length){notice("La venta debe conservar al menos un producto.");return;}
      save.disabled=true;
      try{
        await api("/api/ventas/"+encodeURIComponent(sale.id),{method:"PATCH",body:JSON.stringify({lineas})});
        notice("Venta corregida y cambio registrado en auditoría.","success");
        await Promise.all([loadSales(),loadSummary()]);
      }catch(error){notice(error.message);save.disabled=false;}
    });
    actions.append(save,cancel);card.append(actions);
  }

  function updateSalesViewButtons() {
    const tickets = $("posVerTickets"), table = $("posVerTabla");
    if (tickets) { tickets.classList.toggle("activo",state.salesView==="tickets"); tickets.classList.toggle("secundario",state.salesView!=="tickets"); tickets.setAttribute("aria-pressed",state.salesView==="tickets"?"true":"false"); }
    if (table) { table.classList.toggle("activo",state.salesView==="tabla"); table.classList.toggle("secundario",state.salesView!=="tabla"); table.setAttribute("aria-pressed",state.salesView==="tabla"?"true":"false"); }
  }

  function drawSalesTable(root) {
    const table=document.createElement("table"); table.className="pos-tabla";
    const thead=document.createElement("thead");
    thead.innerHTML="<tr><th>Venta</th><th>Hora</th><th>Cuenta</th><th>Producto</th><th>Cantidad</th><th>Precio</th><th>Importe</th><th>Total venta</th></tr>";
    const tbody=document.createElement("tbody");
    state.sales.forEach(sale=>{
      const time=sale.creado_en?new Date(sale.creado_en).toLocaleTimeString("es-MX",{hour:"2-digit",minute:"2-digit"}):"";
      (sale.lineas||[]).forEach((line,index)=>{
        const tr=document.createElement("tr");
        const values=["Venta "+sale.numero_venta,time,sale.usuario_nombre||"Usuario",line.producto_nombre,
          String(line.cantidad),money(line.precio_unitario),money(line.importe),index===0?money(sale.total):""];
        values.forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});
        tbody.append(tr);
      });
    });
    table.append(thead,tbody);
    table.style.minWidth="760px";
    const wrapper=document.createElement("div");wrapper.style.cssText="max-width:100%;overflow-x:auto";
    wrapper.append(table);root.append(wrapper);
  }

  function downloadTicketPNG(sale) {
    const lines=sale.lineas||[];
    const height=350+lines.length*42;
    const canvas=document.createElement("canvas"); canvas.width=640; canvas.height=height;
    const ctx=canvas.getContext("2d");
    ctx.fillStyle="#ffffff";ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle="#222222";ctx.textAlign="center";ctx.font="bold 30px Arial";
    ctx.fillText(state.bakery.nombre||"Panadería",320,42);
    ctx.font="bold 25px Arial";ctx.fillText("TICKET DE VENTA",320,82);
    ctx.textAlign="left";ctx.font="20px Arial";
    const fecha=sale.fecha||state.availabilityDate||"";
    const hora=sale.creado_en?new Date(sale.creado_en).toLocaleTimeString("es-MX",{hour:"2-digit",minute:"2-digit"}):"";
    ctx.fillText("Venta "+sale.numero_venta+"   "+fecha+"   "+hora,36,124);
    ctx.fillText("Atendió: "+(sale.usuario_nombre||"Usuario"),36,157);
    ctx.beginPath();ctx.moveTo(32,178);ctx.lineTo(608,178);ctx.stroke();
    let y=214;
    ctx.font="bold 18px Arial";ctx.fillText("Producto",36,y);ctx.fillText("Cant.",390,y);ctx.fillText("Importe",485,y);
    ctx.font="18px Arial";
    lines.forEach(line=>{
      y+=38;
      const name=String(line.producto_nombre||"Producto");
      ctx.fillText(name.length>30?name.slice(0,27)+"…":name,36,y);
      ctx.fillText(String(line.cantidad),400,y);
      ctx.textAlign="right";ctx.fillText(money(line.importe),604,y);ctx.textAlign="left";
    });
    y+=24;ctx.beginPath();ctx.moveTo(32,y);ctx.lineTo(608,y);ctx.stroke();
    y+=42;ctx.font="bold 25px Arial";ctx.textAlign="right";ctx.fillText("TOTAL: "+money(sale.total),604,y);
    y+=42;ctx.font="16px Arial";ctx.textAlign="center";ctx.fillText("Gracias por su compra",320,y);
    canvas.toBlob(blob=>{
      if(!blob){notice("No se pudo generar la imagen del ticket.");return;}
      const url=URL.createObjectURL(blob);const a=document.createElement("a");
      a.href=url;a.download="ticket_venta_"+sale.numero_venta+".png";document.body.append(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1500);
    },"image/png");
  }

  async function downloadDailyExcel() {
    const button=$("posDescargarExcelDia"); if(!button)return;
    button.disabled=true;
    try{
      const response=await fetch("/api/ventas/dia/excel?panaderia_id="+encodeURIComponent(state.bakery.id),
        {headers:{Authorization:"Bearer "+state.session.access_token}});
      if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||"No se pudo generar el Excel.");}
      const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");
      a.href=url;a.download="ventas_"+state.bakery.id+"_"+(state.availabilityDate||"dia")+".xlsx";
      document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);
      notice("Excel del día descargado.","success");
    }catch(error){notice(error.message);}
    finally{button.disabled=false;}
  }

  async function loadSummary() {
    const root = $("posTablaResumen");
    if (!root) return;
    root.textContent = "Calculando resumen…";
    try {
      const data = await api("/api/ventas/resumen?panaderia_id=" + encodeURIComponent(state.bakery.id));
      root.replaceChildren();
      $("posFechaResumen").textContent = "Fecha: " + new Date(data.fecha + "T12:00:00").toLocaleDateString("es-MX");
      if (!data.resumen?.length) {
        const empty = document.createElement("p"); empty.className = "nota"; empty.textContent = "Todavía no hay ventas registradas hoy."; root.append(empty);
      } else {
        const table = document.createElement("table"); table.className = "pos-tabla";
        const thead = document.createElement("thead"); thead.innerHTML = "<tr><th>Producto</th><th>Cantidad</th><th>Importe</th></tr>"; table.append(thead);
        const tbody = document.createElement("tbody");
        data.resumen.forEach(item => {
          const tr = document.createElement("tr");
          [item.producto, String(item.cantidad), money(item.importe)].forEach(value => { const td = document.createElement("td"); td.textContent = value; tr.append(td); });
          tbody.append(tr);
        });
        table.append(tbody); root.append(table);
      }
      $("posTotalCantidadResumen").textContent = Number(data.cantidad_total || 0).toLocaleString("es-MX");
      $("posTotalImporteResumen").textContent = money(data.importe_total);
      $("posNumeroVentasResumen").textContent = Number(data.total_ventas || 0).toLocaleString("es-MX");
    } catch (error) { root.textContent = error.message; }
  }

  window.iniciarVentas = async function (session, bakery) {
    state.session = session;
    state.bakery = bakery;
    state.cart.clear();
    document.querySelectorAll("[data-pos-vista]").forEach(button => {
      button.onclick = () => switchView(button.dataset.posVista);
    });
    $("posRegistrarVenta").onclick = registerSale;
    $("posActualizarDia").onclick = loadSales;
    $("posVerTickets").onclick = () => {state.salesView="tickets";loadSales();};
    $("posVerTabla").onclick = () => {state.salesView="tabla";loadSales();};
    $("posDescargarExcelDia").onclick = downloadDailyExcel;
    await loadAvailability();
    switchView("nueva");
    return true;
  };

  $("posBuscarProducto")?.addEventListener("input", event => drawProducts(event.target.value));
})();

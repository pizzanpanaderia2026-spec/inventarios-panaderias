// Punto de venta: disponibilidad diaria, ventas individuales y resumen.
(function () {
  const $ = (id) => document.getElementById(id);
  const state = { session: null, bakery: null, products: [], categories: [], availabilityDate: null, cart: new Map(), view: "nueva", sales: [], summary: null };

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
            drawProducts();
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
        card.append(head, meta, list); root.append(card);
      });
    } catch (error) { root.textContent = error.message; }
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
    await loadAvailability();
    switchView("nueva");
    return true;
  };

  $("posBuscarProducto")?.addEventListener("input", event => drawProducts(event.target.value));
})();

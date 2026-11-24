(function () {
  const panel = document.getElementById("panelHistorial");
  if (!panel) return;

  const $ = id => document.getElementById(id);
  const today = new Date();
  const pad = n => String(n).padStart(2, "0");
  const iso = d => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const todayISO = iso(today);
  const months = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"];
  let token = null, bakery = null, category = "inventario", period = "dia", view = "tablas", lastQuery = null, lastData = null;
  const dateDay = $("histFechaDia"), from = $("histDesde"), to = $("histHasta");
  const result = $("historialResultadoNuevo"), summary = $("histResumenConsulta");
  const consultButton = $("histConsultar"), downloadButton = $("histDescargarExcel");
  [dateDay, from, to].forEach(el => { el.max = todayISO; });
  dateDay.value = todayISO;
  to.value = todayISO;
  let selectedMonth = today.getMonth() + 1;
  const monthGrid = $("histMesOpciones");
  months.forEach((name, index) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "historial-mes-opcion" + (index + 1 === selectedMonth ? " activo" : "");
    b.textContent = name;
    b.setAttribute("aria-pressed", index + 1 === selectedMonth ? "true" : "false");
    b.addEventListener("click", () => {
      selectedMonth = index + 1;
      invalidateQuery();
      monthGrid.querySelectorAll("button").forEach(x => {
        const active = Number(x.dataset.mes) === selectedMonth;
        x.classList.toggle("activo", active);
        x.setAttribute("aria-pressed", active ? "true" : "false");
      });
    });
    b.dataset.mes = String(index + 1);
    monthGrid.appendChild(b);
  });

  const yearSelect = $("histAnioMes");
  for (let y = today.getFullYear(); y >= 2016; y--) yearSelect.add(new Option(String(y), String(y)));

  const yearGrid = $("histAnioOpciones");
  let selectedYear = today.getFullYear();
  for (let y = today.getFullYear(); y >= 2016; y--) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "historial-anio-opcion" + (y === selectedYear ? " activo" : "");
    b.textContent = String(y);
    b.setAttribute("aria-pressed", y === selectedYear ? "true" : "false");
    b.addEventListener("click", () => {
      selectedYear = y;
      invalidateQuery();
      yearGrid.querySelectorAll("button").forEach(x => {
        const active = Number(x.textContent) === y;
        x.classList.toggle("activo", active);
        x.setAttribute("aria-pressed", active ? "true" : "false");
      });
    });
    yearGrid.appendChild(b);
  }

  function setActive(selector, attr, value) {
    panel.querySelectorAll(selector).forEach(b => {
      const active = b.getAttribute(attr) === value;
      b.classList.toggle("activo", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  function showField() {
    panel.querySelectorAll("[data-hist-campo]").forEach(el => {
      el.classList.toggle("oculto", el.getAttribute("data-hist-campo") !== period);
    });
    const messages = {
      dia: "Consulta únicamente los registros de la fecha seleccionada.",
      mes: "Consulta el mes completo. En el mes actual se consideran los días transcurridos.",
      anio: "Consulta el año seleccionado. Para el año actual se consideran los días transcurridos.",
      periodo: "Selecciona un intervalo personalizado. Hasta 365 días se genera el detalle diario; periodos mayores generan un resumen para cuidar los recursos."
    };
    $("histAyudaPeriodo").textContent = messages[period];
    lastData = null;
    lastQuery = null;
    downloadButton.disabled = true;
    result.innerHTML = '<div class="historial-vacio"><strong>Configura tu consulta</strong><p class="nota">Selecciona los filtros y pulsa Consultar para cargar información real.</p></div>';
    summary.textContent = "Categoría: " + category + " · Consulta: " + period;
  }

  panel.querySelectorAll("[data-hist-categoria]").forEach(b => b.addEventListener("click", () => {
    category = b.getAttribute("data-hist-categoria");
    setActive("[data-hist-categoria]", "data-hist-categoria", category);
    showField();
  }));
  panel.querySelectorAll("[data-hist-periodo]").forEach(b => b.addEventListener("click", () => {
    period = b.getAttribute("data-hist-periodo");
    setActive("[data-hist-periodo]", "data-hist-periodo", period);
    showField();
  }));
  panel.querySelectorAll("[data-hist-vista]").forEach(b => b.addEventListener("click", () => {
    view = b.getAttribute("data-hist-vista");
    setActive("[data-hist-vista]", "data-hist-vista", view);
    if (lastData) render(lastData);
  }));
  function invalidateQuery() {
    lastQuery = null;
    lastData = null;
    downloadButton.disabled = true;
    summary.textContent = "Los filtros cambiaron. Vuelve a consultar para actualizar los resultados.";
    result.replaceChildren(el("div", "Pulsa Consultar para actualizar la información con los filtros nuevos.", "historial-vacio"));
    $("histEstadoDescarga").textContent = "Vuelve a consultar para descargar los filtros actuales.";
  }
  dateDay.addEventListener("change", invalidateQuery);
  yearSelect.addEventListener("change", invalidateQuery);
  from.addEventListener("change", () => {
    invalidateQuery();
    to.min = from.value || "";
    if (from.value && (!to.value || to.value < from.value)) to.value = from.value;
    updatePeriodHint();
  });
  to.addEventListener("change", () => { invalidateQuery(); updatePeriodHint(); });
  function updatePeriodHint() {
    if (!from.value || !to.value || from.value > to.value) return;
    const days = Math.floor((Date.parse(to.value + "T00:00:00Z") - Date.parse(from.value + "T00:00:00Z")) / 86400000) + 1;
    $("histAyudaPeriodo").textContent = "Periodo seleccionado: " + days + " días." +
      (days > 365 ? " Se descargará un resumen sin hojas diarias para evitar archivos demasiado pesados." : " Se incluirán hojas diarias con registros.");
  }

  function queryRange() {
    if (!bakery) throw new Error("No se ha seleccionado una panadería.");
    let start, end;
    if (period === "dia") {
      start = end = dateDay.value;
    } else if (period === "mes") {
      const y = Number(yearSelect.value), m = selectedMonth;
      start = y + "-" + pad(m) + "-01";
      const last = new Date(y, m, 0).getDate();
      end = y === today.getFullYear() && m === today.getMonth() + 1 ? todayISO : y + "-" + pad(m) + "-" + pad(last);
    } else if (period === "anio") {
      const y = selectedYear;
      start = y + "-01-01";
      end = y === today.getFullYear() ? todayISO : y + "-12-31";
    } else {
      start = from.value;
      end = to.value;
    }
    if (!start || !end) throw new Error("Selecciona las fechas de la consulta.");
    if (start > end) throw new Error("La fecha inicial debe ser anterior o igual a la final.");
    if (end > todayISO) throw new Error("No puedes consultar fechas futuras.");
    const days = Math.floor((Date.parse(end + "T00:00:00Z") - Date.parse(start + "T00:00:00Z")) / 86400000) + 1;
    if (days > 3650) throw new Error("El intervalo supera el máximo técnico de diez años. Divide la consulta.");
    return { start, end, days };
  }

  function formatMoney(v) {
    return Number(v || 0).toLocaleString("es-MX", { style: "currency", currency: "MXN" });
  }
  function formatNumber(v) { return Number(v || 0).toLocaleString("es-MX"); }
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  }
  function addTable(parent, title, headers, rows, total) {
    parent.appendChild(el("h4", title));
    const wrap = el("div", null, "tabla-scroll");
    const table = el("table");
    const thead = el("thead"), hr = el("tr");
    headers.forEach(h => hr.appendChild(el("th", h)));
    thead.appendChild(hr); table.appendChild(thead);
    const tbody = el("tbody");
    rows.forEach(row => {
      const tr = el("tr");
      row.forEach(value => tr.appendChild(el("td", value)));
      tbody.appendChild(tr);
    });
    if (total) {
      const tr = el("tr", null, "tablas-total");
      total.forEach(value => tr.appendChild(el("td", value)));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody); wrap.appendChild(table); parent.appendChild(wrap);
  }
  function chartSVG(title, series, labels) {
    const wrapper = el("div", null, "historial-grafica");
    wrapper.appendChild(el("h4", title));
    if (!labels.length || !series.length) {
      wrapper.appendChild(el("p", "No hay datos suficientes para esta gráfica.", "nota"));
      return wrapper;
    }
    const width = 760, rowHeight = 34, top = 12, left = 145, right = 70;
    const height = top + labels.length * rowHeight + 12;
    const max = Math.max(1, ...series.flatMap(s => s.values.map(Number)));
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", title);
    labels.forEach((label, i) => {
      const y = top + i * rowHeight;
      const text = document.createElementNS(svg.namespaceURI, "text");
      text.setAttribute("x", left - 10); text.setAttribute("y", y + 16);
      text.setAttribute("text-anchor", "end"); text.setAttribute("font-size", "12");
      text.textContent = label.length > 20 ? label.slice(0, 18) + "…" : label;
      svg.appendChild(text);
      series.forEach((s, j) => {
        const val = Number(s.values[i] || 0);
        const bars = series.length > 1 ? series.length : 1;
        const bh = Math.min(18, (rowHeight - 4) / bars);
        const by = y + 2 + j * bh;
        const rect = document.createElementNS(svg.namespaceURI, "rect");
        rect.setAttribute("x", left); rect.setAttribute("y", by);
        rect.setAttribute("width", Math.max(0, (width - left - right) * val / max));
        rect.setAttribute("height", bh - 2); rect.setAttribute("rx", "3");
        rect.setAttribute("fill", ["#8b5e34", "#c58b50", "#648a72"][j % 3]);
        svg.appendChild(rect);
        const value = document.createElementNS(svg.namespaceURI, "text");
        value.setAttribute("x", left + (width - left - right) * val / max + 6);
        value.setAttribute("y", by + bh - 4); value.setAttribute("font-size", "11");
        value.textContent = formatNumber(val);
        svg.appendChild(value);
      });
    });
    wrapper.appendChild(svg);
    if (series.length > 1) {
      const legend = el("div", null, "historial-leyenda");
      series.forEach((s, i) => {
        const item = el("span", null);
        const dot = el("i", null); dot.style.background = ["#8b5e34", "#c58b50", "#648a72"][i % 3];
        item.append(dot, document.createTextNode(s.name)); legend.appendChild(item);
      });
      wrapper.appendChild(legend);
    }
    return wrapper;
  }

  function renderTables(data) {
    const host = el("div", null, "historial-tablas");
    if (category === "ventas") {
      addTable(host, "Ventas por producto", ["Producto", "Cantidad", "Importe"],
        (data.resumen || []).map(x => [x.producto, formatNumber(x.cantidad), formatMoney(x.importe)]),
        ["TOTAL", formatNumber(data.cantidad_total), formatMoney(data.importe_total)]);
      const rows = [];
      (data.ventas || []).forEach(venta => {
        const hora = venta.creado_en ? new Date(venta.creado_en).toLocaleTimeString("es-MX", {hour:"2-digit",minute:"2-digit"}) : "";
        (venta.lineas || []).forEach(linea => rows.push([
          venta.fecha, "Venta #" + venta.numero_venta, hora, venta.usuario_nombre || "Usuario",
          linea.producto_nombre, formatNumber(linea.cantidad), formatMoney(linea.precio_unitario), formatMoney(linea.importe)
        ]));
      });
      addTable(host, "Detalle de ventas", ["Fecha", "Venta", "Hora", "Registró", "Producto", "Cantidad", "Precio unitario", "Importe"], rows);
      return host;
    }
    const inv = data.inventario, prod = data.produccion;
    if (category === "inventario" || category === "analisis") {
      addTable(host, "Inventario por tipo de pan", ["Pan", "Cantidad", "Importe"],
        inv.por_producto.map(x => [x.producto, formatNumber(x.cantidad), formatMoney(x.importe)]),
        ["TOTAL", formatNumber(inv.total_piezas), formatMoney(inv.total_importe)]);
      addTable(host, "Inventario por precio", ["Precio", "Cantidad", "Importe"],
        inv.por_precio.map(x => [formatMoney(x.precio), formatNumber(x.cantidad), formatMoney(x.importe)]),
        ["TOTAL", formatNumber(inv.total_piezas), formatMoney(inv.total_importe)]);
    }
    if (category === "produccion" || category === "analisis") {
      addTable(host, "Producción por tipo de pan", ["Pan", "Cantidad producida"],
        prod.por_pan.map(x => [x.pan, formatNumber(x.cantidad)]),
        ["TOTAL PRODUCIDO", formatNumber(prod.total)]);
    }
    if (category === "analisis") {
      addTable(host, "Producción y sobrantes", ["Pan", "Producido", "Sobrante", "% sobrante"],
        data.analisis.por_pan.map(x => [x.pan, formatNumber(x.producido), formatNumber(x.sobrante),
          x.porcentaje_sobrante == null ? "N/D" : Number(x.porcentaje_sobrante).toFixed(2) + "%"]));
      host.appendChild(el("p", "El porcentaje compara los sobrantes registrados con la producción del mismo pan y periodo. No representa ventas.", "nota"));
    }
    if (period === "anio") {
      const monthly = new Map();
      data.resumen_diario.forEach(x => {
        const key = x.fecha.slice(0, 7);
        const item = monthly.get(key) || { inventario_cantidad: 0, inventario_importe: 0, produccion_cantidad: 0 };
        item.inventario_cantidad += Number(x.inventario_cantidad || 0);
        item.inventario_importe += Number(x.inventario_importe || 0);
        item.produccion_cantidad += Number(x.produccion_cantidad || 0);
        monthly.set(key, item);
      });
      for (let m = 1; m <= 12; m++) {
        const key = selectedYear + "-" + pad(m);
        if (!monthly.has(key)) monthly.set(key, { inventario_cantidad: 0, inventario_importe: 0, produccion_cantidad: 0 });
      }
      const items = [...monthly.entries()].sort((a,b) => a[0].localeCompare(b[0]));
      if (category === "inventario") {
        addTable(host, "Resumen mensual del año", ["Mes", "Inventario", "Importe"],
          items.map(([mes,x]) => [mes, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe)]));
      } else if (category === "produccion") {
        addTable(host, "Resumen mensual del año", ["Mes", "Producción"],
          items.map(([mes,x]) => [mes, formatNumber(x.produccion_cantidad)]));
      } else {
        addTable(host, "Resumen mensual del año", ["Mes", "Inventario", "Importe", "Producción"],
          items.map(([mes,x]) => [mes, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe), formatNumber(x.produccion_cantidad)]));
      }
    } else if (period !== "dia" && !data.resumen_only) {
      const items = data.resumen_diario.filter(x => x.tiene_inventario || x.tiene_produccion);
      if (category === "inventario") {
        addTable(host, "Resumen diario", ["Fecha", "Inventario", "Importe"],
          items.map(x => [x.fecha, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe)]));
      } else if (category === "produccion") {
        addTable(host, "Resumen diario", ["Fecha", "Producción"],
          items.map(x => [x.fecha, formatNumber(x.produccion_cantidad)]));
      } else {
        addTable(host, "Resumen diario", ["Fecha", "Inventario", "Importe", "Producción"],
          items.map(x => [x.fecha, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe), formatNumber(x.produccion_cantidad)]));
      }
    } else if (data.resumen_only) {
      if (category === "inventario") {
        addTable(host, "Resumen mensual del periodo", ["Mes", "Inventario", "Importe"],
          data.resumen_mensual.map(x => [x.mes, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe)]));
      } else if (category === "produccion") {
        addTable(host, "Resumen mensual del periodo", ["Mes", "Producción"],
          data.resumen_mensual.map(x => [x.mes, formatNumber(x.produccion_cantidad)]));
      } else {
        addTable(host, "Resumen mensual del periodo", ["Mes", "Inventario", "Importe", "Producción"],
          data.resumen_mensual.map(x => [x.mes, formatNumber(x.inventario_cantidad), formatMoney(x.inventario_importe), formatNumber(x.produccion_cantidad)]));
      }
    }
    return host;
  }
  function renderCharts(data) {
    const host = el("div", null, "historial-graficas");
    if (category === "ventas") {
      host.appendChild(chartSVG("Importe vendido por producto",
        [{name:"Importe", values:(data.resumen || []).map(x => Number(x.importe))}],
        (data.resumen || []).map(x => x.producto)));
      return host;
    }
    if (category === "inventario" || category === "analisis") {
      host.appendChild(chartSVG("Inventario por tipo de pan",
        [{ name: "Cantidad", values: data.inventario.por_producto.map(x => x.cantidad) }],
        data.inventario.por_producto.map(x => x.producto)));
      host.appendChild(chartSVG("Inventario por precio",
        [{ name: "Cantidad", values: data.inventario.por_precio.map(x => x.cantidad) }],
        data.inventario.por_precio.map(x => formatMoney(x.precio))));
    }
    if (category === "produccion") {
      host.appendChild(chartSVG("Producción por tipo de pan",
        [{ name: "Producido", values: data.produccion.por_pan.map(x => x.cantidad) }],
        data.produccion.por_pan.map(x => x.pan)));
    }
    if (category === "analisis") {
      host.appendChild(chartSVG("Producción frente a sobrantes", [
        { name: "Producido", values: data.analisis.por_pan.map(x => x.producido) },
        { name: "Sobrante", values: data.analisis.por_pan.map(x => x.sobrante) }
      ], data.analisis.por_pan.map(x => x.pan)));
    }
    if (category === "analisis" && (period === "anio" || data.resumen_only)) {
      const monthly = new Map();
      if (data.resumen_only) {
        (data.resumen_mensual || []).forEach(x => monthly.set(x.mes, Number(x.produccion_cantidad || 0)));
      } else {
        data.resumen_diario.forEach(x => {
          const key = x.fecha.slice(0,7);
          monthly.set(key, (monthly.get(key) || 0) + Number(x.produccion_cantidad || 0));
        });
        if (period === "anio") {
          for (let m = 1; m <= 12; m++) {
            const key = selectedYear + "-" + pad(m);
            if (!monthly.has(key)) monthly.set(key, 0);
          }
        }
      }
      const keys = [...monthly.keys()].sort();
      host.appendChild(chartSVG("Producción por mes", [{ name: "Producción", values: keys.map(k => monthly.get(k)) }], keys));
    }
    if (category === "produccion" && (period === "anio" || data.resumen_only)) {
      const monthsMap = new Map();
      if (data.resumen_only) {
        (data.resumen_mensual || []).forEach(d => monthsMap.set(d.mes, Number(d.produccion_cantidad || 0)));
      } else {
        data.resumen_diario.forEach(d => {
          const key = d.fecha.slice(0,7);
          monthsMap.set(key, (monthsMap.get(key) || 0) + Number(d.produccion_cantidad || 0));
        });
        if (period === "anio") {
          for (let m = 1; m <= 12; m++) {
            const key = selectedYear + "-" + pad(m);
            if (!monthsMap.has(key)) monthsMap.set(key, 0);
          }
        }
      }
      const keys = [...monthsMap.keys()].sort();
      host.appendChild(chartSVG("Producción por mes", [{ name: "Producción", values: keys.map(k => monthsMap.get(k)) }], keys));
    }
    return host;
  }
  function render(data) {
    result.replaceChildren();
    const empty = category === "ventas" ? !(data.resumen || []).length :
      category === "inventario" ? !data.inventario.por_producto.length :
      category === "produccion" ? !data.produccion.por_pan.length :
      !data.inventario.por_producto.length && !data.produccion.por_pan.length;
    if (empty) {
      result.appendChild(el("div", "No hay registros para la categoría y las fechas seleccionadas.", "historial-vacio"));
    } else {
      result.appendChild(view === "tablas" ? renderTables(data) : renderCharts(data));
    }
    if (data.resumen_only) {
      const note = el("p", "El intervalo supera 365 días. Se generará un resumen general y mensual sin hojas diarias.", "nota");
      result.appendChild(note);
    }
  }
  function queryString(q) {
    const params = category === "ventas"
      ? new URLSearchParams({panaderia_id:String(bakery.id),desde:q.start,hasta:q.end})
      : new URLSearchParams({panaderia_id:String(bakery.id),categoria:category,tipo:period,desde:q.start,hasta:q.end});
    return params.toString();
  }
  async function api(url, asBlob = false) {
    const response = await fetch(url, { headers: { Authorization: "Bearer " + token, Accept: asBlob ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/json" } });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "No se pudo completar la consulta.");
    }
    return asBlob ? response.blob() : response.json();
  }
  async function consult() {
    if (!token || !bakery) return;
    let q;
    try { q = queryRange(); } catch (e) { $("histAyudaPeriodo").textContent = e.message; return; }
    consultButton.disabled = true;
    downloadButton.disabled = true;
    result.replaceChildren(el("p", "Consultando información histórica…", "nota"));
    summary.textContent = "Consultando " + category + " · " + q.start + " a " + q.end;
    try {
      const data = category === "ventas"
        ? await api("/api/ventas/historial?" + queryString(q))
        : await api("/api/historial/informe?" + queryString(q));
      lastQuery = q; lastData = data;
      summary.textContent = data.dias_consultados + " días consultados · " + (data.resumen_only ? "Resumen optimizado" : "Detalle disponible");
      render(data);
      const hasRecords = category === "ventas" ? (data.resumen || []).length > 0 :
        category === "inventario" ? data.inventario.por_producto.length > 0 :
        category === "produccion" ? data.produccion.por_pan.length > 0 :
        data.inventario.por_producto.length > 0 || data.produccion.por_pan.length > 0;
      downloadButton.disabled = !hasRecords;
    } catch (e) {
      result.replaceChildren(el("div", e.message, "mensaje error"));
      summary.textContent = "No se pudo completar la consulta.";
    } finally {
      consultButton.disabled = false;
    }
  }
  async function download() {
    if (!lastQuery || !token || !bakery) return;
    downloadButton.disabled = true;
    const oldText = downloadButton.textContent;
    downloadButton.textContent = "Generando Excel…";
    try {
      const blob = category === "ventas"
        ? await api("/api/ventas/historial/excel?" + queryString(lastQuery), true)
        : await api("/api/historial/informe/excel?" + queryString(lastQuery), true);
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = "historial_" + category + "_" + lastQuery.start + "_" + lastQuery.end + ".xlsx";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1500);
      $("histEstadoDescarga").textContent = "El archivo Excel se generó correctamente.";
    } catch (e) {
      $("histEstadoDescarga").textContent = e.message;
    } finally {
      downloadButton.disabled = false;
      downloadButton.textContent = oldText;
    }
  }

  consultButton.addEventListener("click", consult);
  downloadButton.addEventListener("click", download);
  window.iniciarHistorial = function (session, local, profile) {
    token = session && session.access_token;
    bakery = local;
    const admin = profile?.es_admin_principal === true && String(profile?.rol || "").toLowerCase() === "admin";
    const permisos = Array.isArray(profile?.permisos) && profile.permisos.length
      ? profile.permisos
      : (String(profile?.rol || "").toLowerCase() === "produccion" ? ["produccion"] : ["inventarios"]);
    const permitida = {
      inventario: admin || permisos.includes("inventarios"),
      produccion: admin || permisos.includes("produccion"),
      ventas: admin || permisos.includes("ventas"),
      analisis: admin
    };
    panel.querySelectorAll("[data-hist-categoria]").forEach(b => {
      const key = b.getAttribute("data-hist-categoria");
      b.classList.toggle("oculto", !permitida[key]);
    });
    category = permitida.inventario ? "inventario" : permitida.produccion ? "produccion" : "ventas";
    setActive("[data-hist-categoria]", "data-hist-categoria", category);
    showField();
  };
  showField();
})();
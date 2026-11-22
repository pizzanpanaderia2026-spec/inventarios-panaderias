(function () {
  const panel = document.getElementById("panelHistorial");
  if (!panel) return;

  const hoy = new Date();
  const isoHoy = [hoy.getFullYear(), String(hoy.getMonth()+1).padStart(2,"0"), String(hoy.getDate()).padStart(2,"0")].join("-");
  const fechaDia = document.getElementById("histFechaDia");
  const desde = document.getElementById("histDesde");
  const hasta = document.getElementById("histHasta");
  const ayuda = document.getElementById("histAyudaPeriodo");
  const resultado = document.getElementById("historialResultadoNuevo");
  const resumen = document.getElementById("histResumenConsulta");
  let categoria = "inventario";
  let periodo = "dia";
  let vista = "graficas";

  [fechaDia, desde, hasta].forEach(input => { input.max = isoHoy; });
  fechaDia.value = isoHoy;
  hasta.value = isoHoy;
  const anioActual = hoy.getFullYear();
  document.querySelectorAll("#panelHistorial .historial-anios").forEach(select => {
    for (let y = anioActual; y >= 2016; y--) {
      const option = document.createElement("option");
      option.value = String(y);
      option.textContent = String(y);
      select.appendChild(option);
    }
    select.value = String(anioActual);
  });
  document.getElementById("histMes").value = String(hoy.getMonth()+1);

  function seleccionar(selector, atributo, valor) {
    panel.querySelectorAll(selector).forEach(button => {
      const activo = button.getAttribute(atributo) === valor;
      button.classList.toggle("activo", activo);
      button.setAttribute("aria-pressed", activo ? "true" : "false");
    });
  }
  function mostrarCampo() {
    panel.querySelectorAll("[data-hist-campo]").forEach(campo => {
      campo.classList.toggle("oculto", campo.getAttribute("data-hist-campo") !== periodo);
    });
    const textos = {
      dia:"Elige una fecha para consultar únicamente ese día.",
      mes:"Se consultará el mes completo del año seleccionado.",
      anio:"Se consultará el año completo, organizado por meses.",
      periodo:"Selecciona un intervalo de hasta 365 días. Las fechas inicial y final son inclusivas."
    };
    ayuda.textContent = textos[periodo];
    resumen.textContent = "Consulta: " + periodo + " · Categoría: " + categoria;
  }
  panel.querySelectorAll("[data-hist-categoria]").forEach(button => {
    button.addEventListener("click", () => {
      categoria = button.getAttribute("data-hist-categoria");
      seleccionar("[data-hist-categoria]","data-hist-categoria",categoria);
      mostrarCampo();
    });
  });
  panel.querySelectorAll("[data-hist-periodo]").forEach(button => {
    button.addEventListener("click", () => {
      periodo = button.getAttribute("data-hist-periodo");
      seleccionar("[data-hist-periodo]","data-hist-periodo",periodo);
      mostrarCampo();
    });
  });
  panel.querySelectorAll("[data-hist-vista]").forEach(button => {
    button.addEventListener("click", () => {
      vista = button.getAttribute("data-hist-vista");
      seleccionar("[data-hist-vista]","data-hist-vista",vista);
      resumen.textContent = "Visualización seleccionada: " + (vista === "tablas" ? "Tablas" : "Gráficas") + ".";
    });
  });
  desde.addEventListener("change", () => {
    hasta.min = desde.value || "";
    if (desde.value && (!hasta.value || hasta.value < desde.value)) hasta.value = desde.value;
    validarRango();
  });
  hasta.addEventListener("change", validarRango);

  function validarRango() {
    if (!desde.value || !hasta.value) return;
    const dias = Math.floor((Date.parse(hasta.value+"T00:00:00Z") - Date.parse(desde.value+"T00:00:00Z")) / 86400000) + 1;
    ayuda.textContent = dias > 365
      ? "El periodo seleccionado supera el máximo recomendado de 365 días. Reduce el intervalo."
      : "Periodo seleccionado: " + dias + " días (máximo recomendado: 365).";
  }
  document.getElementById("histConsultar").addEventListener("click", () => {
    if (periodo === "periodo") {
      if (!desde.value || !hasta.value || desde.value > hasta.value) {
        ayuda.textContent = "Selecciona un intervalo válido: la fecha inicial debe ser anterior o igual a la final.";
        return;
      }
      const dias = Math.floor((Date.parse(hasta.value+"T00:00:00Z") - Date.parse(desde.value+"T00:00:00Z")) / 86400000) + 1;
      if (dias > 365) {
        ayuda.textContent = "El periodo supera los 365 días recomendados. Selecciona un intervalo menor.";
        return;
      }
    }
    resultado.replaceChildren();
    const mensaje = document.createElement("div");
    mensaje.className = "historial-vacio";
    const titulo = document.createElement("strong");
    titulo.textContent = "Filtros listos";
    const detalle = document.createElement("p");
    detalle.className = "nota";
    detalle.textContent = "La interfaz ya permite elegir " + categoria + ", consultar por " + periodo + " y alternar entre " + vista + ". La conexión de resultados reales y la exportación avanzada se integrarán después de completar y verificar los servicios de consulta.";
    mensaje.append(titulo, detalle);
    resultado.appendChild(mensaje);
    resumen.textContent = "Filtros seleccionados: " + categoria + " · " + periodo + " · " + vista;
  });
  mostrarCampo();
})();
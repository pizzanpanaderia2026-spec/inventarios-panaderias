(function () {
  const panel = document.getElementById("panelTablas");
  if (!panel) return;

  const detalle = document.getElementById("tablaDetalle");
  const resumen = document.getElementById("tablaResumen");
  const fecha = document.getElementById("fechaTablas");
  const msg = document.getElementById("mensajeTablas");
  const botonExcel = document.getElementById("botonDescargarExcel");
  let token = null;
  let panaderia = null;
  let datosCierre = null;

  const dinero = valor => Number(valor || 0).toLocaleString("es-MX", {
    style: "currency", currency: "MXN"
  });

  function aviso(texto, tipo) {
    msg.textContent = texto;
    msg.className = "mensaje " + (tipo || "error");
  }

  function crearTabla(destino, encabezados, filas, total) {
    const wrap = document.createElement("div");
    wrap.className = "tabla-scroll";
    const tabla = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    encabezados.forEach(texto => {
      const th = document.createElement("th");
      th.textContent = texto;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    tabla.appendChild(thead);

    const tbody = document.createElement("tbody");
    filas.forEach(fila => {
      const tr = document.createElement("tr");
      fila.forEach((valor, indice) => {
        const td = document.createElement("td");
        td.textContent = valor;
        if (indice > 0) td.style.whiteSpace = "nowrap";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    if (total) {
      const tr = document.createElement("tr");
      tr.className = "tablas-total";
      total.forEach(valor => {
        const td = document.createElement("td");
        td.textContent = valor;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    tabla.appendChild(tbody);
    wrap.appendChild(tabla);
    destino.replaceChildren(wrap);
  }

  function mostrarVacio() {
    datosCierre = null;
    fecha.textContent = "Todavía no hay un día cerrado para mostrar.";
    const cerradoPor = document.getElementById("usuarioCierreTablas");
    if (cerradoPor) cerradoPor.textContent = "";
    detalle.textContent = "Las tablas aparecerán aquí cuando se cierre el primer día.";
    resumen.replaceChildren();
    botonExcel.disabled = true;
  }

  function dibujar(datos) {
    datosCierre = datos && datos.cierre ? datos : null;
    if (!datosCierre) {
      mostrarVacio();
      return;
    }
    const cierre = datos.cierre;
    const fechaBonita = new Date(cierre.fecha + "T12:00:00").toLocaleDateString("es-MX", {
      day: "numeric", month: "long", year: "numeric"
    });
    fecha.textContent = "Fecha: " + fechaBonita;
    const cerradoPor = document.getElementById("usuarioCierreTablas");
    if (cerradoPor) cerradoPor.textContent = "Cerrado por: " + (cierre.cerrado_por_nombre || "Usuario");

    const filasDetalle = (datos.lineas || []).map(linea => [
      linea.producto,
      Number(linea.cantidad || 0).toLocaleString("es-MX"),
      dinero(linea.precio_unitario),
      dinero(linea.total)
    ]);
    crearTabla(detalle, ["Producto", "Cantidad", "Precio unitario", "Importe"], filasDetalle, [
      "TOTAL GENERAL",
      Number(datos.total_piezas || 0).toLocaleString("es-MX"),
      "",
      dinero(datos.total_importe)
    ]);

    const filasResumen = (datos.resumen || []).map(linea => [
      dinero(linea.precio),
      Number(linea.cantidad || 0).toLocaleString("es-MX"),
      dinero(linea.total)
    ]);
    crearTabla(resumen, ["Precio unitario", "Cantidad total", "Importe"], filasResumen, [
      "TOTAL GENERAL",
      Number(datos.total_piezas || 0).toLocaleString("es-MX"),
      dinero(datos.total_importe)
    ]);
    botonExcel.disabled = false;
  }

  async function actualizar() {
    if (!token || !panaderia) return;
    msg.className = "mensaje oculto";
    try {
      const response = await fetch("/api/tablas/ultimo-cierre?panaderia_id=" + encodeURIComponent(panaderia.id), {
        headers: { Authorization: "Bearer " + token, Accept: "application/json" }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "No se pudieron cargar las tablas.");
      dibujar(data);
    } catch (error) {
      aviso(error.message || "No se pudieron cargar las tablas.");
    }
  }

  window.iniciarTablasHistorial = function (sesion, local) {
    token = sesion && sesion.access_token;
    panaderia = local;
    return actualizar();
  };
  window.actualizarTablasDiarias = actualizar;

  botonExcel.addEventListener("click", async () => {
    if (!token || !panaderia || !datosCierre) return;
    botonExcel.disabled = true;
    const textoOriginal = botonExcel.textContent;
    botonExcel.textContent = "Preparando Excel…";
    try {
      const response = await fetch("/api/tablas/ultimo-cierre/excel?panaderia_id=" + encodeURIComponent(panaderia.id), {
        headers: { Authorization: "Bearer " + token }
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "No se pudo descargar el Excel.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = "cierre_diario_" + panaderia.id + "_" + datosCierre.cierre.fecha + ".xlsx";
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      URL.revokeObjectURL(url);
      aviso("Excel descargado correctamente.", "exito");
    } catch (error) {
      aviso(error.message || "No se pudo descargar el Excel.");
    } finally {
      botonExcel.disabled = !datosCierre;
      botonExcel.textContent = textoOriginal;
    }
  });
})();
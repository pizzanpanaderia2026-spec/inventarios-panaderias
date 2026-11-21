(function () {
  const panel = document.getElementById("panelProduccion");
  if (!panel) return;

  const fecha = document.getElementById("fechaProduccion");
  const pan = document.getElementById("panProduccion");
  const cantidad = document.getElementById("cantidadProduccion");
  const observaciones = document.getElementById("observacionesProduccion");
  const botonAgregar = document.getElementById("botonAgregarProduccion");
  const botonExcel = document.getElementById("botonExcelProduccion");
  const estado = document.getElementById("estadoProduccion");
  const mensaje = document.getElementById("mensajeProduccion");
  const tabla = document.getElementById("tablaProduccion");

  let token = null;
  let bakery = null;
  let cargando = false;

  function fechaLocal(d = new Date()) {
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function puedeAgregarEnFecha(valor) {
    if (!valor) return false;
    const inicio = new Date(valor + "T00:00:00");
    const ahora = new Date();
    return valor <= fechaLocal() && ahora.getTime() - inicio.getTime() <= 24 * 60 * 60 * 1000;
  }

  function aviso(texto, tipo = "error") {
    mensaje.textContent = texto;
    mensaje.className = "mensaje " + tipo;
  }

  function limpiarAviso() {
    mensaje.textContent = "";
    mensaje.className = "mensaje oculto";
  }

  async function api(ruta, opciones = {}) {
    const respuesta = await fetch(ruta, {
      ...opciones,
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/json",
        ...(opciones.body ? { "Content-Type": "application/json" } : {})
      }
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) {
      const error = new Error(datos.detail || "No se pudo completar la operación.");
      error.status = respuesta.status;
      throw error;
    }
    return datos;
  }

  function crearCelda(fila, valor) {
    const celda = document.createElement("td");
    celda.textContent = valor == null || valor === "" ? "—" : String(valor);
    fila.appendChild(celda);
    return celda;
  }

  function construirTabla(registros) {
    tabla.replaceChildren();
    if (!registros.length) {
      const vacio = document.createElement("p");
      vacio.className = "nota";
      vacio.textContent = "No hay registros de producción para esta fecha.";
      tabla.appendChild(vacio);
      return;
    }

    const envoltura = document.createElement("div");
    envoltura.style.overflowX = "auto";
    const table = document.createElement("table");
    table.className = "tabla";
    table.style.width = "100%";
    const thead = document.createElement("thead");
    const encabezado = document.createElement("tr");
    ["Pan", "Cantidad", "Observaciones", "Registró", "Fecha y hora", "Acciones"].forEach(t => {
      const th = document.createElement("th");
      th.textContent = t;
      encabezado.appendChild(th);
    });
    thead.appendChild(encabezado);
    const tbody = document.createElement("tbody");

    registros.forEach(registro => {
      const fila = document.createElement("tr");
      crearCelda(fila, registro.pan_nombre);
      crearCelda(fila, Number(registro.cantidad).toLocaleString("es-MX"));
      crearCelda(fila, registro.observaciones || "—");
      crearCelda(fila, registro.usuario_nombre || "Usuario");
      crearCelda(fila, registro.registrado_en
        ? new Date(registro.registrado_en).toLocaleString("es-MX")
        : "—");
      const acciones = document.createElement("td");
      if (registro.editable) {
        const editar = document.createElement("button");
        editar.type = "button";
        editar.className = "secundario";
        editar.textContent = "Editar";
        editar.addEventListener("click", () => mostrarEdicion(fila, registro));
        acciones.appendChild(editar);
      } else {
        const soloLectura = document.createElement("span");
        soloLectura.className = "nota";
        soloLectura.textContent = "Solo consulta";
        acciones.appendChild(soloLectura);
      }
      fila.appendChild(acciones);
      tbody.appendChild(fila);
    });

    table.append(thead, tbody);
    envoltura.appendChild(table);
    tabla.appendChild(envoltura);
  }

  function mostrarEdicion(fila, registro) {
    fila.replaceChildren();
    const panInput = document.createElement("input");
    panInput.value = registro.pan_nombre;
    panInput.maxLength = 120;
    panInput.setAttribute("aria-label", "Nombre del pan");
    const cantidadInput = document.createElement("input");
    cantidadInput.type = "number";
    cantidadInput.min = "0";
    cantidadInput.step = "1";
    cantidadInput.value = String(registro.cantidad);
    cantidadInput.setAttribute("aria-label", "Cantidad");
    const observacionesInput = document.createElement("textarea");
    observacionesInput.rows = 2;
    observacionesInput.maxLength = 1000;
    observacionesInput.value = registro.observaciones || "";
    observacionesInput.setAttribute("aria-label", "Observaciones");

    const campos = [panInput, cantidadInput, observacionesInput];
    campos.forEach(campo => {
      const td = document.createElement("td");
      td.appendChild(campo);
      fila.appendChild(td);
    });
    crearCelda(fila, registro.usuario_nombre || "Usuario");
    crearCelda(fila, registro.registrado_en ? new Date(registro.registrado_en).toLocaleString("es-MX") : "—");

    const acciones = document.createElement("td");
    const guardar = document.createElement("button");
    guardar.type = "button";
    guardar.textContent = "Guardar";
    const cancelar = document.createElement("button");
    cancelar.type = "button";
    cancelar.className = "secundario";
    cancelar.textContent = "Cancelar";
    acciones.append(guardar, cancelar);
    fila.appendChild(acciones);

    cancelar.addEventListener("click", cargar);
    guardar.addEventListener("click", async () => {
      const nombre = panInput.value.trim();
      const n = Number(cantidadInput.value);
      if (!nombre) { aviso("Escribe el nombre del pan."); panInput.focus(); return; }
      if (!Number.isInteger(n) || n < 0 || cantidadInput.value.trim() === "") {
        aviso("La cantidad debe ser un número entero de cero o más.");
        cantidadInput.focus();
        return;
      }
      guardar.disabled = true;
      try {
        await api("/api/produccion/" + encodeURIComponent(registro.id), {
          method: "PATCH",
          body: JSON.stringify({
            pan_nombre: nombre,
            cantidad: n,
            observaciones: observacionesInput.value.trim() || null
          })
        });
        aviso("Registro actualizado.", "exito");
        await cargar();
      } catch (error) {
        aviso(error.message);
        guardar.disabled = false;
      }
    });
  }

  async function cargar() {
    if (!token || !bakery || !fecha.value || cargando) return;
    cargando = true;
    limpiarAviso();
    botonAgregar.disabled = true;
    botonExcel.disabled = true;
    estado.textContent = "Consultando producción…";
    try {
      const datos = await api(
        "/api/produccion?panaderia_id=" + encodeURIComponent(bakery.id) +
        "&fecha_produccion=" + encodeURIComponent(fecha.value)
      );
      const registros = datos.registros || [];
      construirTabla(registros);
      const permiteAgregar = puedeAgregarEnFecha(fecha.value);
      document.getElementById("formularioProduccion").classList.toggle("oculto", !permiteAgregar);
      botonAgregar.disabled = !permiteAgregar;
      botonExcel.disabled = false;
      if (registros.length) {
        estado.textContent = registros.length + (registros.length === 1 ? " registro encontrado." : " registros encontrados.") +
          (registros.some(r => r.editable) ? " Puedes editar los que siguen dentro del plazo." : " Los registros están en consulta.");
      } else if (permiteAgregar) {
        estado.textContent = "Sin registros. Puedes agregar la producción de esta fecha.";
      } else {
        estado.textContent = "Sin registros. Esta fecha ya está fuera del plazo para capturar producción.";
      }
    } catch (error) {
      tabla.replaceChildren();
      estado.textContent = "No se pudo cargar la producción.";
      aviso(error.message);
    } finally {
      cargando = false;
    }
  }

  window.iniciarProduccion = async function (sesion, panaderia) {
    token = sesion.access_token;
    bakery = panaderia;
    fecha.max = fechaLocal();
    if (!fecha.value) fecha.value = fechaLocal();
    await cargar();
  };

  fecha.addEventListener("change", () => {
    if (fecha.value > fechaLocal()) {
      fecha.value = fechaLocal();
      aviso("No puedes seleccionar una fecha futura.");
      return;
    }
    cargar();
  });

  botonAgregar.addEventListener("click", async () => {
    const nombre = pan.value.trim();
    const n = Number(cantidad.value);
    if (!nombre) { aviso("Escribe el nombre del pan."); pan.focus(); return; }
    if (!Number.isInteger(n) || n < 0 || cantidad.value.trim() === "") {
      aviso("La cantidad debe ser un número entero de cero o más.");
      cantidad.focus();
      return;
    }
    botonAgregar.disabled = true;
    try {
      await api("/api/produccion", {
        method: "POST",
        body: JSON.stringify({
          panaderia_id: Number(bakery.id),
          fecha_produccion: fecha.value,
          pan_nombre: nombre,
          cantidad: n,
          observaciones: observaciones.value.trim() || null
        })
      });
      pan.value = "";
      cantidad.value = "";
      observaciones.value = "";
      aviso("Producción agregada correctamente.", "exito");
      await cargar();
    } catch (error) {
      aviso(error.message);
      botonAgregar.disabled = false;
    }
  });

  botonExcel.addEventListener("click", async () => {
    if (!token || !bakery || !fecha.value) return;
    botonExcel.disabled = true;
    try {
      const respuesta = await fetch(
        "/api/produccion/excel?panaderia_id=" + encodeURIComponent(bakery.id) +
        "&fecha_produccion=" + encodeURIComponent(fecha.value),
        { headers: { Authorization: "Bearer " + token } }
      );
      if (!respuesta.ok) {
        const datos = await respuesta.json().catch(() => ({}));
        throw new Error(datos.detail || "No se pudo descargar el Excel.");
      }
      const blob = await respuesta.blob();
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = "produccion_" + fecha.value + ".xlsx";
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      URL.revokeObjectURL(url);
      aviso("Se descargó el Excel de la fecha seleccionada.", "exito");
    } catch (error) {
      aviso(error.message);
    } finally {
      botonExcel.disabled = false;
    }
  });
})();

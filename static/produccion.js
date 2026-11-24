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
  let catalogo = [];
  let categorias = [];
  let capturaHabilitada = false;
  let totalCantidadDia = 0;
  let totalImporteDia = 0;
  const campoCantidad = cantidad.closest(".campo");
  campoCantidad.classList.add("oculto");
  const sugerencias = document.createElement("div");
  sugerencias.className = "oculto";
  sugerencias.style.cssText = "border:1px solid #cfc5b8;border-radius:8px;overflow:hidden;margin-top:-8px;margin-bottom:14px;background:#fff";
  pan.closest(".campo").after(sugerencias);
  pan.autocomplete = "off";
  pan.placeholder = "Escribe el nombre del pan";

  function fechaLocal(d = new Date()) {
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  let diasEditables = 1;
  let horasEditables = 0;
  function puedeAgregarEnFecha(valor) {
    if (!valor || valor > fechaLocal()) return false;
    const inicio = new Date(valor + "T00:00:00");
    const limite = new Date(inicio.getTime() + (diasEditables + 1) * 86400000 + horasEditables * 3600000);
    const ahora = new Date();
    return inicio <= ahora && ahora < limite;
  }

  function aviso(texto, tipo = "error") {
    mensaje.textContent = texto;
    mensaje.className = "mensaje " + tipo;
  }

  function limpiarAviso() {
    mensaje.textContent = "";
    mensaje.className = "mensaje oculto";
  }

  function actualizarBotonAgregar() {
    const n = Number(cantidad.value);
    botonAgregar.disabled = !capturaHabilitada ||
      !pan.dataset.nombreSeleccionado ||
      !Number.isInteger(n) || n < 0 || cantidad.value.trim() === "";
  }

  function activarCaptura(nombre, producto = null) {
    pan.value = nombre;
    pan.dataset.nombreSeleccionado = nombre;
    pan.dataset.productoId = producto ? String(producto.id) : "";
    sugerencias.classList.add("oculto");
    campoCantidad.classList.remove("oculto");
    cantidad.value = "";
    actualizarBotonAgregar();
    cantidad.focus();
  }

  function dibujarSugerencias() {
    sugerencias.replaceChildren();
    const q = pan.value.trim().toLocaleLowerCase("es");
    delete pan.dataset.nombreSeleccionado;
    delete pan.dataset.productoId;
    campoCantidad.classList.add("oculto");
    actualizarBotonAgregar();
    if (!q) {
      sugerencias.classList.add("oculto");
      return;
    }

    const categoriasCoincidentes = categorias.filter(c =>
      c.activa && !c.protegida && c.nombre.toLocaleLowerCase("es").includes(q)
    );
    const idsCategorias = new Set(categoriasCoincidentes.map(c => String(c.id)));
    const coincidencias = catalogo.filter(p =>
      p.activo && p.categoria_activa !== false && !p.categoria_protegida &&
      (p.nombre.toLocaleLowerCase("es").includes(q) || idsCategorias.has(String(p.categoria_id)))
    );

    if (coincidencias.length) {
      coincidencias.forEach(producto => {
        const opcion = document.createElement("button");
        opcion.type = "button";
        opcion.className = "secundario ancho";
        opcion.style.cssText = "display:flex;justify-content:space-between;align-items:center;border-radius:0;border-bottom:1px solid #eee7df;text-align:left";
        const nombre = document.createElement("strong");
        nombre.textContent = producto.nombre;
        const precio = document.createElement("span");
        precio.textContent = "$" + Number(producto.precio).toFixed(2);
        const categoria = document.createElement("small");
        categoria.textContent = producto.categoria_nombre || "";
        categoria.style.cssText = "display:block;color:#78716c;font-size:12px";
        const texto = document.createElement("span");
        texto.append(nombre, categoria);
        opcion.append(texto, precio);
        opcion.addEventListener("click", () => activarCaptura(producto.nombre, producto));
        sugerencias.appendChild(opcion);
      });
    }

    const libre = document.createElement("button");
    libre.type = "button";
    libre.className = "secundario ancho";
    libre.style.cssText = "display:block;width:100%;border-radius:0;text-align:left";
    libre.textContent = "Usar nombre libre: " + pan.value.trim();
    libre.addEventListener("click", () => activarCaptura(pan.value.trim()));
    sugerencias.appendChild(libre);
    sugerencias.classList.remove("oculto");
  }

  pan.addEventListener("input", dibujarSugerencias);
  cantidad.addEventListener("input", actualizarBotonAgregar);

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

  function formatearFechaHora(valor) {
    if (!valor) return "—";
    const partes = new Intl.DateTimeFormat("es-MX", {
      timeZone: "America/Mexico_City",
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23"
    }).formatToParts(new Date(valor));
    const obtener = tipo => partes.find(parte => parte.type === tipo)?.value || "";
    return obtener("day") + "/" + obtener("month") + "/" + obtener("year") +
      " " + obtener("hour") + ":" + obtener("minute");
  }

  function crearCelda(fila, valor) {
    const celda = document.createElement("td");
    celda.textContent = valor == null || valor === "" ? "—" : String(valor);
    fila.appendChild(celda);
    return celda;
  }

  function construirTabla(registros) {
    tabla.replaceChildren();
    const resumenDia = document.createElement("div");
    resumenDia.className = "panel";
    resumenDia.style.cssText = "display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px";
    const piezas = document.createElement("strong");
    piezas.textContent = "Total producido: " + Number(totalCantidadDia || 0).toLocaleString("es-MX") + " piezas";
    const importe = document.createElement("strong");
    importe.textContent = "Valor producido: " + (totalImporteDia == null ? "No disponible" : Number(totalImporteDia || 0).toLocaleString("es-MX",{style:"currency",currency:"MXN"}));
    resumenDia.append(piezas,importe);
    tabla.appendChild(resumenDia);
    if (!registros.length) {
      const vacio = document.createElement("p");
      vacio.className = "nota";
      vacio.textContent = "No hay registros de producción para esta fecha.";
      tabla.appendChild(vacio);
      return;
    }

    const envoltura = document.createElement("div");
    envoltura.className = "produccion-tabla-scroll";
    const table = document.createElement("table");
    table.className = "tabla produccion-tabla";
    const thead = document.createElement("thead");
    const encabezado = document.createElement("tr");
    ["Pan", "Cantidad", "Precio unitario", "Importe", "Observaciones", "Registró", "Fecha y hora", "Acciones"].forEach(t => {
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
      crearCelda(fila, registro.precio_unitario == null ? "No disponible" : Number(registro.precio_unitario).toLocaleString("es-MX",{style:"currency",currency:"MXN"}));
      crearCelda(fila, registro.importe == null ? "No disponible" : Number(registro.importe).toLocaleString("es-MX",{style:"currency",currency:"MXN"}));
      crearCelda(fila, registro.observaciones || "—");
      crearCelda(fila, registro.usuario_nombre || "Usuario");
      crearCelda(fila, formatearFechaHora(registro.registrado_en));
      const acciones = document.createElement("td");
      if (registro.editable) {
        const grupoAcciones = document.createElement("div");
        grupoAcciones.className = "produccion-acciones";
        const editar = document.createElement("button");
        editar.type = "button";
        editar.className = "secundario";
        editar.textContent = "Editar";
        editar.addEventListener("click", () => mostrarEdicion(fila, registro));

        const eliminar = document.createElement("button");
        eliminar.type = "button";
        eliminar.className = "boton-peligro";
        eliminar.textContent = "Eliminar";
        eliminar.addEventListener("click", async () => {
          const confirmar = window.confirm("¿Deseas eliminar este registro de producción? Esta acción no se puede deshacer.");
          if (!confirmar) return;
          eliminar.disabled = true;
          try {
            await api("/api/produccion/" + encodeURIComponent(registro.id), { method: "DELETE" });
            aviso("Registro eliminado correctamente.", "exito");
            await cargar();
          } catch (error) {
            aviso(error.message);
            eliminar.disabled = false;
          }
        });
        grupoAcciones.append(editar, eliminar);
        acciones.appendChild(grupoAcciones);
      } else {
        const soloLectura = document.createElement("span");
        soloLectura.className = "nota";
        soloLectura.textContent = "Solo consulta";
        acciones.appendChild(soloLectura);
      }
      fila.appendChild(acciones);
      tbody.appendChild(fila);
    });

    const totalRow = document.createElement("tr");
    const totalLabel = document.createElement("th");
    totalLabel.textContent = "TOTAL";
    totalRow.appendChild(totalLabel);
    const totalQty = document.createElement("th");
    totalQty.textContent = Number(totalCantidadDia || 0).toLocaleString("es-MX");
    totalRow.appendChild(totalQty);
    const emptyPrice = document.createElement("th"); emptyPrice.textContent = "—"; totalRow.appendChild(emptyPrice);
    const totalAmount = document.createElement("th");
    totalAmount.textContent = totalImporteDia == null ? "No disponible" : Number(totalImporteDia || 0).toLocaleString("es-MX",{style:"currency",currency:"MXN"});
    totalRow.appendChild(totalAmount);
    for (let i=0;i<4;i++){const th=document.createElement("th");th.textContent="";totalRow.appendChild(th);}
    const tfoot = document.createElement("tfoot"); tfoot.appendChild(totalRow);
    table.append(thead, tbody, tfoot);
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
    crearCelda(fila, formatearFechaHora(registro.registrado_en));

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
      diasEditables = Number.isInteger(Number(datos.dias_editables)) ? Number(datos.dias_editables) : 1;
      horasEditables = Number.isInteger(Number(datos.horas_editables)) ? Number(datos.horas_editables) : 0;
      const registros = datos.registros || [];
      totalCantidadDia = Number(datos.total_cantidad || 0);
      totalImporteDia = datos.total_importe == null ? null : Number(datos.total_importe);
      construirTabla(registros);
      const permiteAgregar = puedeAgregarEnFecha(fecha.value);
      capturaHabilitada = permiteAgregar;
      document.getElementById("formularioProduccion").classList.toggle("oculto", !permiteAgregar);
      actualizarBotonAgregar();
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
    try {
      const datosCatalogo = await api("/api/catalogo?panaderia_id=" + encodeURIComponent(bakery.id));
      catalogo = datosCatalogo.productos || [];
      categorias = datosCatalogo.categorias || [];
    } catch (error) {
      catalogo = [];
      categorias = [];
      aviso("No se pudieron cargar las sugerencias del catálogo: " + error.message);
    }
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
    const nombre = pan.dataset.nombreSeleccionado || "";
    const n = Number(cantidad.value);
    if (!nombre) { aviso("Selecciona una sugerencia o confirma el nombre libre."); pan.focus(); return; }
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
          producto_id: pan.dataset.productoId ? Number(pan.dataset.productoId) : null,
          cantidad: n,
          observaciones: observaciones.value.trim() || null
        })
      });
      pan.value = "";
      delete pan.dataset.nombreSeleccionado;
      delete pan.dataset.productoId;
      sugerencias.classList.add("oculto");
      campoCantidad.classList.add("oculto");
      cantidad.value = "";
      observaciones.value = "";
      actualizarBotonAgregar();
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

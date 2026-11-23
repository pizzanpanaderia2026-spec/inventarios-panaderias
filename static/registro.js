// Registro diario: interfaz de búsqueda y captura por producto.
// Conserva los endpoints y las operaciones existentes del registro.
(function () {
  const panel = document.getElementById("panelRegistro");
  if (!panel) return;

  let token = null, bakery = null, catalogo = [], categorias = [], cierre = null;
  let seleccionados = new Map();
  const fecha = document.getElementById("fechaRegistro");
  const filas = document.getElementById("filasRegistro");
  const mensaje = document.getElementById("mensajeRegistro");

  // Resumen visual del registro: se actualiza sin alterar los datos del servidor.
  const resumen = document.createElement("div");
  resumen.className = "panel";
  resumen.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-top:14px";
  const totalPiezas = document.createElement("div");
  const etiquetaPiezas = document.createElement("p");
  etiquetaPiezas.className = "nota";
  etiquetaPiezas.textContent = "Total de piezas";
  const valorPiezas = document.createElement("strong");
  valorPiezas.style.cssText = "display:block;font-size:1.5rem;color:#713f12";
  const totalImporte = document.createElement("div");
  const etiquetaImporte = document.createElement("p");
  etiquetaImporte.className = "nota";
  etiquetaImporte.textContent = "Importe total";
  const valorImporte = document.createElement("strong");
  valorImporte.style.cssText = "display:block;font-size:1.5rem;color:#713f12";
  totalPiezas.append(etiquetaPiezas, valorPiezas);
  totalImporte.append(etiquetaImporte, valorImporte);
  resumen.append(totalPiezas, totalImporte);
  filas.after(resumen);

  // Controles visuales de captura: no crean ni modifican reglas del servidor.
  const busqueda = document.createElement("div");
  busqueda.className = "campo";
  const labelBusqueda = document.createElement("label");
  labelBusqueda.textContent = "Nombre del producto";
  labelBusqueda.htmlFor = "buscarProductoRegistro";
  const inputBusqueda = document.createElement("input");
  inputBusqueda.id = "buscarProductoRegistro";
  inputBusqueda.type = "search";
  inputBusqueda.placeholder = "Escribe el nombre del producto";
  inputBusqueda.autocomplete = "off";

  const sugerencias = document.createElement("div");
  sugerencias.className = "oculto";
  sugerencias.style.cssText = "border:1px solid #cfc5b8;border-radius:8px;overflow:hidden;margin-top:-8px;margin-bottom:14px;background:#fff";

  const captura = document.createElement("div");
  captura.className = "campo oculto";
  const labelCantidad = document.createElement("label");
  labelCantidad.textContent = "Cantidad";
  labelCantidad.htmlFor = "cantidadProductoRegistro";
  const inputCantidad = document.createElement("input");
  inputCantidad.id = "cantidadProductoRegistro";
  inputCantidad.type = "number";
  inputCantidad.min = "0";
  inputCantidad.step = "1";
  inputCantidad.inputMode = "numeric";
  inputCantidad.placeholder = "Escribe la cantidad";
  const botonAgregar = document.createElement("button");
  botonAgregar.type = "button";
  botonAgregar.textContent = "Agregar al registro";
  captura.append(labelCantidad, inputCantidad, botonAgregar);
  busqueda.append(labelBusqueda, inputBusqueda);
  filas.before(busqueda, sugerencias, captura);

  function fechaLocal(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function actualizarLimitesFecha() {
    const hoy = new Date();
    const anteayer = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - 2);
    fecha.max = fechaLocal(hoy);
    fecha.min = fechaLocal(anteayer);
    if (!fecha.value || fecha.value < fecha.min || fecha.value > fecha.max) {
      fecha.value = fecha.max;
    }
  }

  actualizarLimitesFecha();

  window.iniciarRegistroDiario = async function (sesion, panaderia, productos, categoriasIniciales) {
    token = sesion.access_token;
    bakery = panaderia;
    catalogo = productos || [];
    categorias = categoriasIniciales || [];
    await cargar();
  };

  async function api(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const maxAttempts = method === "GET" ? 6 : 1;
    let lastError;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const response = await fetch(url, {
          ...options,
          headers: {
            Authorization: "Bearer " + token,
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {})
          }
        });
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
    throw lastError || new Error("No se pudo consultar el registro.");
  }

  function aviso(t, tipo = "error") {
    mensaje.textContent = t;
    mensaje.className = "mensaje " + tipo;
  }

  function productoPorId(id) {
    return catalogo.find(p => String(p.id) === String(id));
  }

  async function cargar() {
    actualizarLimitesFecha();
    if (!token || !bakery || !fecha.value) return;
    try {
      const d = await api("/api/registro?panaderia_id=" + bakery.id + "&fecha_registro=" + fecha.value);
      cierre = d.cierre;
      seleccionados = new Map();
      (d.lineas || []).forEach(linea => {
        const productoBase = productoPorId(linea.producto_id);
        if (productoBase) {
          const producto = {
            ...productoBase,
            nombre: linea.producto_nombre || productoBase.nombre,
            precio: linea.precio_unitario !== null && linea.precio_unitario !== undefined
              ? linea.precio_unitario : productoBase.precio
          };
          seleccionados.set(String(producto.id), {
            producto,
            cantidad: Number(linea.cantidad)
          });
        }
      });
      dibujar();
      const cerrado = cierre && cierre.estado === "cerrado";
      document.getElementById("botonGuardarRegistro").disabled = !!cerrado;
      document.getElementById("botonCerrarDia").disabled = !!cerrado;
      document.getElementById("botonReabrirDia").disabled = !cerrado;
      document.getElementById("estadoRegistro").textContent = cerrado ? "Día cerrado" : "Día abierto";
      inputBusqueda.disabled = !!cerrado;
      inputCantidad.disabled = !!cerrado;
      botonAgregar.disabled = !!cerrado;
    } catch (e) {
      aviso(e.message);
      filas.replaceChildren();
    }
  }

  function dibujarSugerencias() {
    sugerencias.replaceChildren();
    const q = inputBusqueda.value.trim().toLocaleLowerCase("es");
    if (!q) {
      sugerencias.classList.add("oculto");
      return;
    }

    const categoriasCoincidentes = categorias.filter(c => c.activa && !c.protegida && c.nombre.toLocaleLowerCase("es").includes(q));
    const idsCategorias = new Set(categoriasCoincidentes.map(c => String(c.id)));
    const coincidencias = catalogo.filter(p =>
      p.activo && p.categoria_activa !== false && !p.categoria_protegida &&
      (p.nombre.toLocaleLowerCase("es").includes(q) || idsCategorias.has(String(p.categoria_id))) &&
      !seleccionados.has(String(p.id))
    );

    if (!coincidencias.length) {
      const vacio = document.createElement("div");
      vacio.className = "nota";
      vacio.style.padding = "12px";
      vacio.textContent = "No hay productos coincidentes en el catálogo.";
      sugerencias.appendChild(vacio);
    } else {
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
        opcion.addEventListener("click", () => {
          inputBusqueda.value = producto.nombre;
          inputBusqueda.dataset.productoId = String(producto.id);
          sugerencias.classList.add("oculto");
          captura.classList.remove("oculto");
          inputCantidad.value = "";
          inputCantidad.focus();
        });
        sugerencias.appendChild(opcion);
      });
    }
    sugerencias.classList.remove("oculto");
  }

  inputBusqueda.addEventListener("input", () => {
    delete inputBusqueda.dataset.productoId;
    captura.classList.add("oculto");
    dibujarSugerencias();
  });

  inputCantidad.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      botonAgregar.click();
    }
  });

  botonAgregar.addEventListener("click", () => {
    const producto = productoPorId(inputBusqueda.dataset.productoId);
    const cantidad = Number(inputCantidad.value);
    if (!producto) {
      aviso("Selecciona un producto del catálogo.");
      return;
    }
    if (!Number.isInteger(cantidad) || cantidad < 0 || inputCantidad.value.trim() === "") {
      aviso("Escribe una cantidad entera de cero o más.");
      return;
    }
    seleccionados.set(String(producto.id), { producto, cantidad });
    inputBusqueda.value = "";
    delete inputBusqueda.dataset.productoId;
    inputCantidad.value = "";
    captura.classList.add("oculto");
    sugerencias.classList.add("oculto");
    dibujar();
    aviso("Producto agregado al registro.", "exito");
  });

  function actualizarResumen() {
    let piezas = 0;
    let importe = 0;
    seleccionados.forEach(({ producto, cantidad }) => {
      const cantidadValida = Number(cantidad) || 0;
      piezas += cantidadValida;
      importe += Number(producto.precio || 0) * cantidadValida;
    });
    valorPiezas.textContent = piezas.toLocaleString("es-MX");
    valorImporte.textContent = importe.toLocaleString("es-MX", {
      style: "currency",
      currency: "MXN"
    });
  }

  function dibujar() {
    actualizarResumen();
    filas.replaceChildren();
    const activos = catalogo.filter(p => p.activo);
    if (!activos.length) {
      filas.textContent = "Primero agrega productos en el catálogo.";
      return;
    }

    const titulo = document.createElement("h4");
    titulo.textContent = "Productos registrados";
    filas.appendChild(titulo);

    if (!seleccionados.size) {
      const nota = document.createElement("p");
      nota.className = "nota";
      nota.textContent = "Busca un producto del catálogo para comenzar el conteo.";
      filas.appendChild(nota);
      return;
    }

    seleccionados.forEach(({ producto, cantidad }, id) => {
      const row = document.createElement("div");
      row.className = "panel";
      const top = document.createElement("div");
      top.className = "barra";
      const nombre = document.createElement("strong");
      nombre.textContent = producto.nombre;
      const precio = document.createElement("span");
      precio.textContent = "$" + Number(producto.precio).toFixed(2) + " por pieza";
      top.append(nombre, precio);

      const campo = document.createElement("div");
      campo.className = "campo";
      const label = document.createElement("label");
      label.textContent = "Cantidad";
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "1";
      input.inputMode = "numeric";
      input.value = String(cantidad);
      input.setAttribute("aria-label", "Cantidad de " + producto.nombre);
      input.disabled = !!(cierre && cierre.estado === "cerrado");
      input.addEventListener("change", () => {
        const n = Number(input.value);
        if (Number.isInteger(n) && n >= 0) {
          seleccionados.set(id, { producto, cantidad: n });
          subtotal.textContent = "Subtotal: $" + (Number(producto.precio) * n).toFixed(2);
          actualizarResumen();
        } else {
          input.value = String(cantidad);
          aviso("La cantidad debe ser un número entero de cero o más.");
        }
      });
      campo.append(label, input);

      const subtotal = document.createElement("p");
      subtotal.className = "nota";
      subtotal.textContent = "Subtotal: $" + (Number(producto.precio) * cantidad).toFixed(2);
      const quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "secundario";
      quitar.textContent = "Quitar";
      quitar.disabled = !!(cierre && cierre.estado === "cerrado");
      quitar.addEventListener("click", () => {
        seleccionados.delete(id);
        dibujar();
      });
      row.append(top, campo, subtotal, quitar);
      filas.appendChild(row);
    });
  }

  fecha.addEventListener("change", () => {
    actualizarLimitesFecha();
    if (fecha.value < fecha.min || fecha.value > fecha.max) {
      aviso("Selecciona hoy o uno de los dos días calendario anteriores.");
      return;
    }
    seleccionados.clear();
    cargar();
  });

  document.getElementById("botonGuardarRegistro").addEventListener("click", async () => {
    try {
      const lineas = [...seleccionados.values()].map(x => ({
        producto_id: Number(x.producto.id),
        cantidad: Number(x.cantidad)
      }));
      if (lineas.some(x => !Number.isInteger(x.cantidad) || x.cantidad < 0)) {
        aviso("Las cantidades deben ser números enteros de cero o más.");
        return;
      }
      await api("/api/registro", {
        method: "PUT",
        body: JSON.stringify({ panaderia_id: bakery.id, fecha: fecha.value, lineas })
      });
      aviso("Registro guardado. Aún no has cerrado el día.", "exito");
      await cargar();
    } catch (e) {
      aviso(e.message);
    }
  });

  document.getElementById("botonCerrarDia").addEventListener("click", async () => {
    if (!confirm("¿Cerrar el día? Se guardarán automáticamente las cantidades capturadas antes de cerrar.")) return;
    const botonCerrar = document.getElementById("botonCerrarDia");
    botonCerrar.disabled = true;
    try {
      // Primero persistir el contenido actual de la captura. Si falla, no cerrar el día.
      const lineas = [...seleccionados.values()].map(x => ({
        producto_id: Number(x.producto.id),
        cantidad: Number(x.cantidad)
      }));
      if (lineas.some(x => !Number.isInteger(x.cantidad) || x.cantidad < 0)) {
        throw new Error("Las cantidades deben ser números enteros de cero o más.");
      }
      await api("/api/registro", {
        method: "PUT",
        body: JSON.stringify({ panaderia_id: bakery.id, fecha: fecha.value, lineas })
      });
      await api("/api/registro/cerrar?panaderia_id=" + bakery.id + "&fecha_registro=" + fecha.value, { method: "POST" });
      aviso("Registro guardado y día cerrado correctamente.", "exito");
      await cargar();
      if (window.actualizarTablasDiarias) await window.actualizarTablasDiarias();
    } catch (e) {
      aviso("No se cerró el día. " + e.message);
    } finally {
      botonCerrar.disabled = !!(cierre && cierre.estado === "cerrado");
    }
  });

  document.getElementById("botonReabrirDia").addEventListener("click", async () => {
    const motivo = prompt("Si la fecha está fuera de los días editables configurados, escribe el motivo de la corrección:") || "";
    try {
      await api("/api/registro/reabrir", {
        method: "POST",
        body: JSON.stringify({ panaderia_id: Number(bakery.id), fecha: fecha.value, motivo })
      });
      aviso("Registro reabierto. Los cambios quedarán sujetos a auditoría.", "exito");
      await cargar();
      if (window.actualizarTablasDiarias) await window.actualizarTablasDiarias();
    } catch (e) {
      aviso(e.message);
    }
  });

  window.actualizarRegistroCatalogo = async function (productos, categoriasNuevas) {
    catalogo = productos || [];
    categorias = categoriasNuevas || [];
    await cargar();
  };
})();

// Registro diario: prototipo de interfaz. No consulta ni modifica el servidor.
(function () {
  const panel = document.getElementById("panelRegistro");
  if (!panel) return;

  let catalogo = [];
  let productoElegido = null;
  let productosRegistro = [];
  let estadoDia = "abierto";

  const fecha = document.getElementById("fechaRegistro");
  const filas = document.getElementById("filasRegistro");
  const mensaje = document.getElementById("mensajeRegistro");
  const buscar = document.getElementById("buscarProductoRegistro");
  const sugerencias = document.getElementById("sugerenciasProductoRegistro");
  const elegido = document.getElementById("productoElegidoRegistro");
  const cantidad = document.getElementById("cantidadProductoRegistro");

  function fechaLocal(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function configurarFechas() {
    const hoy = new Date();
    const max = fechaLocal(hoy);
    const minimo = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - 2);
    fecha.max = max;
    fecha.min = fechaLocal(minimo);
    if (!fecha.value || fecha.value > max || fecha.value < fecha.min) fecha.value = max;
  }

  window.iniciarRegistroDiario = function (_sesion, _panaderia, productos) {
    catalogo = Array.isArray(productos) ? productos : [];
    configurarFechas();
    dibujar();
  };

  window.actualizarRegistroCatalogo = async function (productos) {
    catalogo = Array.isArray(productos) ? productos : [];
    mostrarSugerencias();
    return true;
  };

  function productosDisponibles() {
    const activos = catalogo.filter(p => p && p.activo !== false);
    if (activos.length) return activos;
    // Productos de muestra para que la maqueta pueda apreciarse antes de cargar un catálogo.
    return [
      {id:"demo-mini", nombre:"Dona mini", precio:3, activo:true},
      {id:"demo-glaseada", nombre:"Dona glaseada", precio:5, activo:true},
      {id:"demo-grande", nombre:"Dona grande", precio:8, activo:true}
    ];
  }

  function aviso(texto, tipo = "exito") {
    mensaje.textContent = texto;
    mensaje.className = "mensaje " + tipo;
  }

  function limpiarSeleccion() {
    productoElegido = null;
    elegido.classList.add("oculto");
    buscar.value = "";
    cantidad.value = "";
    sugerencias.replaceChildren();
    sugerencias.classList.add("oculto");
    buscar.focus();
  }

  function seleccionarProducto(producto) {
    productoElegido = producto;
    document.getElementById("nombreProductoElegido").textContent = producto.nombre;
    document.getElementById("precioProductoElegido").textContent = "$" + Number(producto.precio).toFixed(2) + " por pieza";
    elegido.classList.remove("oculto");
    sugerencias.classList.add("oculto");
    sugerencias.replaceChildren();
    cantidad.value = "";
    cantidad.focus();
  }

  function mostrarSugerencias() {
    const consulta = buscar.value.trim().toLocaleLowerCase("es");
    sugerencias.replaceChildren();
    if (!consulta) {
      sugerencias.classList.add("oculto");
      return;
    }
    const coincidencias = productosDisponibles().filter(p =>
      String(p.nombre || "").toLocaleLowerCase("es").includes(consulta)
    ).slice(0, 8);
    if (!coincidencias.length) {
      const vacio = document.createElement("div");
      vacio.className = "nota";
      vacio.style.padding = "12px";
      vacio.textContent = "No hay coincidencias en el catálogo.";
      sugerencias.append(vacio);
    } else {
      coincidencias.forEach(producto => {
        const opcion = document.createElement("button");
        opcion.type = "button";
        opcion.className = "registro-sugerencia";
        opcion.setAttribute("role", "option");
        const nombre = document.createElement("span");
        nombre.textContent = producto.nombre;
        const precio = document.createElement("strong");
        precio.textContent = "$" + Number(producto.precio).toFixed(2);
        opcion.append(nombre, precio);
        opcion.addEventListener("click", () => seleccionarProducto(producto));
        sugerencias.append(opcion);
      });
    }
    sugerencias.classList.remove("oculto");
  }

  function dibujar() {
    filas.replaceChildren();
    if (!productosRegistro.length) {
      const vacio = document.createElement("p");
      vacio.className = "nota";
      vacio.textContent = "Aún no has agregado productos.";
      filas.append(vacio);
    } else {
      productosRegistro.forEach((item, indice) => {
        const fila = document.createElement("div");
        fila.className = "registro-fila";
        const detalle = document.createElement("div");
        const nombre = document.createElement("strong");
        nombre.textContent = item.nombre;
        const meta = document.createElement("small");
        meta.textContent = "$" + Number(item.precio).toFixed(2) + " × " + item.cantidad + " piezas";
        detalle.append(nombre, meta);
        const subtotal = document.createElement("strong");
        subtotal.className = "registro-subtotal";
        subtotal.textContent = "$" + (Number(item.precio) * item.cantidad).toFixed(2);
        const quitar = document.createElement("button");
        quitar.type = "button";
        quitar.textContent = "Quitar";
        quitar.setAttribute("aria-label", "Quitar " + item.nombre);
        quitar.addEventListener("click", () => {
          productosRegistro.splice(indice, 1);
          dibujar();
        });
        fila.append(detalle, subtotal, quitar);
        filas.append(fila);
      });
    }
    const total = productosRegistro.reduce((suma, item) => suma + Number(item.precio) * item.cantidad, 0);
    document.getElementById("totalRegistro").textContent = "$" + total.toFixed(2);
    document.getElementById("estadoRegistro").textContent = estadoDia === "cerrado" ? "Día cerrado (simulación)" : "Día abierto (simulación)";
    document.getElementById("botonGuardarRegistro").disabled = estadoDia === "cerrado";
    document.getElementById("botonCerrarDia").disabled = estadoDia === "cerrado";
    document.getElementById("botonReabrirDia").disabled = estadoDia !== "cerrado";
  }

  buscar.addEventListener("input", mostrarSugerencias);
  buscar.addEventListener("focus", mostrarSugerencias);
  document.addEventListener("click", event => {
    if (!event.target.closest(".registro-buscador")) sugerencias.classList.add("oculto");
  });
  fecha.addEventListener("change", () => {
    productosRegistro = [];
    estadoDia = "abierto";
    limpiarSeleccion();
    dibujar();
    aviso("Fecha seleccionada. La vista es una simulación; no se cargaron datos guardados.");
  });
  document.getElementById("botonAgregarProductoRegistro").addEventListener("click", () => {
    if (!productoElegido) return;
    const unidades = Number(cantidad.value);
    if (!Number.isInteger(unidades) || unidades < 1) {
      aviso("Escribe una cantidad entera mayor que cero.", "error");
      cantidad.focus();
      return;
    }
    const existente = productosRegistro.find(x => String(x.id) === String(productoElegido.id));
    if (existente) existente.cantidad += unidades;
    else productosRegistro.push({
      id: productoElegido.id,
      nombre: productoElegido.nombre,
      precio: Number(productoElegido.precio),
      cantidad: unidades
    });
    limpiarSeleccion();
    dibujar();
    aviso("Producto agregado a la vista del registro.");
  });
  document.getElementById("botonCancelarProductoRegistro").addEventListener("click", limpiarSeleccion);
  document.getElementById("botonGuardarRegistro").addEventListener("click", () => {
    aviso("Simulación: el registro se mostraría guardado. No se enviaron datos al servidor.");
  });
  document.getElementById("botonCerrarDia").addEventListener("click", () => {
    estadoDia = "cerrado";
    dibujar();
    aviso("Simulación: el día aparece cerrado solo en esta pantalla.");
  });
  document.getElementById("botonReabrirDia").addEventListener("click", () => {
    estadoDia = "abierto";
    dibujar();
    aviso("Simulación: el día aparece reabierto solo en esta pantalla.");
  });

  configurarFechas();
  dibujar();
})();

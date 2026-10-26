// Catálogo básico de productos de la panadería seleccionada.
(function () {
  const form = document.getElementById("formProducto");
  if (!form) return;
  let token = null;
  let panaderia = null;
  let productos = [];
  let editando = null;
  const lista = document.getElementById("listaProductos");
  const mensaje = document.getElementById("mensajeProductos");
  const nombre = document.getElementById("nombreProducto");
  const precio = document.getElementById("precioProducto");
  const guardar = document.getElementById("botonGuardarProducto");

  window.iniciarCatalogoProductos = function (sesion, panaderiaSeleccionada) {
    token = sesion.access_token;
    panaderia = panaderiaSeleccionada;
    cargar();
  };

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/json",
        ...(options.body ? {"Content-Type": "application/json"} : {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "No se pudo completar la operación.");
    return data;
  }

  function aviso(texto, tipo = "error") {
    mensaje.textContent = texto;
    mensaje.className = "mensaje " + tipo;
  }

  async function cargar() {
    if (!panaderia || !token) return;
    lista.textContent = "Cargando productos...";
    try {
      const data = await api("/api/productos?panaderia_id=" + encodeURIComponent(panaderia.id));
      productos = data.productos || [];
      dibujar();
    } catch (error) {
      lista.textContent = "";
      aviso(error.message);
    }
  }

  function dibujar() {
    lista.replaceChildren();
    if (!productos.length) {
      lista.textContent = "Todavía no hay productos en esta panadería.";
      return;
    }
    productos.forEach(producto => {
      const item = document.createElement("div");
      item.className = "panel";
      const title = document.createElement("strong");
      title.textContent = producto.nombre + (producto.activo ? "" : " (Inactivo)");
      const price = document.createElement("p");
      price.textContent = "Precio: $" + Number(producto.precio).toFixed(2);
      const actions = document.createElement("div");
      actions.className = "barra";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "secundario";
      edit.textContent = "Editar";
      edit.addEventListener("click", () => {
        editando = producto.id;
        nombre.value = producto.nombre;
        precio.value = Number(producto.precio).toFixed(2);
        guardar.textContent = "Guardar cambios";
        document.getElementById("botonCancelarEdicion").classList.remove("oculto");
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "secundario";
      toggle.textContent = producto.activo ? "Desactivar" : "Activar";
      toggle.addEventListener("click", async () => {
        try {
          await api("/api/productos/" + producto.id, {
            method: "PATCH",
            body: JSON.stringify({nombre: producto.nombre, precio: Number(producto.precio), activo: !producto.activo})
          });
          await cargar();
        } catch (error) { aviso(error.message); }
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Eliminar";
      remove.addEventListener("click", async () => {
        if (!confirm("¿Eliminar o desactivar este producto? Si tiene historial se conservará desactivado.")) return;
        try {
          const result = await api("/api/productos/" + producto.id, {method: "DELETE"});
          aviso(result.accion === "desactivado" ? "El producto tenía historial y se desactivó." : "Producto eliminado.", "exito");
          await cargar();
        } catch (error) { aviso(error.message); }
      });
      actions.append(edit, toggle, remove);
      item.append(title, price, actions);
      lista.appendChild(item);
    });
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!panaderia || !token) return aviso("Selecciona una panadería e inicia sesión nuevamente.");
    const n = nombre.value.trim();
    const p = Number(precio.value);
    if (!n || !Number.isFinite(p) || p < 0) return aviso("Escribe un nombre y un precio válido.");
    guardar.disabled = true;
    try {
      if (editando !== null) {
        const producto = productos.find(x => String(x.id) === String(editando));
        await api("/api/productos/" + editando, {
          method: "PATCH",
          body: JSON.stringify({nombre: n, precio: p, activo: producto ? producto.activo : true})
        });
        aviso("Producto actualizado.", "exito");
      } else {
        await api("/api/productos", {
          method: "POST",
          body: JSON.stringify({panaderia_id: panaderia.id, nombre: n, precio: p})
        });
        aviso("Producto agregado.", "exito");
      }
      cancelar();
      await cargar();
    } catch (error) {
      aviso(error.message);
    } finally { guardar.disabled = false; }
  });

  function cancelar() {
    editando = null;
    form.reset();
    guardar.textContent = "Agregar producto";
    document.getElementById("botonCancelarEdicion").classList.add("oculto");
  }
  document.getElementById("botonCancelarEdicion").addEventListener("click", cancelar);
  document.getElementById("botonActualizarProductos").addEventListener("click", cargar);
})();
// Registro diario: interfaz de búsqueda y captura rápida de productos.
(function () {
  const panel = document.getElementById("panelRegistro");
  if (!panel) return;
  let token = null, bakery = null, catalogo = [], cierre = null;
  let seleccionados = new Map();
  const fecha = document.getElementById("fechaRegistro");
  const filas = document.getElementById("filasRegistro");
  const mensaje = document.getElementById("mensajeRegistro");

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
  labelCantidad.htmlFor = "cantidadProductoRegistro";
  labelCantidad.textContent = "Cantidad";
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
    const y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,"0"), day=String(d.getDate()).padStart(2,"0");
    return y+"-"+m+"-"+day;
  }
  function actualizarLimitesFecha() {
    const hoy = new Date();
    const limite = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate()-2);
    fecha.max = fechaLocal(hoy);
    fecha.min = fechaLocal(limite);
    if (!fecha.value || fecha.value > fecha.max || fecha.value < fecha.min) fecha.value = fecha.max;
  }
  const hoy = new Date();
  fecha.value = fechaLocal(hoy);
  actualizarLimitesFecha();

  window.iniciarRegistroDiario = async function (sesion, panaderia, productos) {
    token = sesion.access_token; bakery = panaderia; catalogo = productos || [];
    await cargar();
  };
  async function api(url, options={}) {
    const r=await fetch(url,{...options,headers:{Authorization:"Bearer "+token,Accept:"application/json",...(options.body?{"Content-Type":"application/json"}:{})}});
    const d=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.detail || "No se pudo completar la operación.");
    return d;
  }
  function aviso(t, tipo="error") { mensaje.textContent=t; mensaje.className="mensaje "+tipo; }
  function productoPorId(id) { return catalogo.find(p=>String(p.id)===String(id)); }

  async function cargar() {
    actualizarLimitesFecha();
    if(!token||!bakery||!fecha.value) return;
    try {
      const d=await api("/api/registro?panaderia_id="+bakery.id+"&fecha_registro="+fecha.value);
      cierre=d.cierre;
      seleccionados = new Map();
      (d.lineas||[]).forEach(linea => {
        const p=productoPorId(linea.producto_id);
        if(p) seleccionados.set(String(p.id),{producto:p,cantidad:Number(linea.cantidad)});
      });
      dibujar();
      const cerrado=cierre && cierre.estado==="cerrado";
      document.getElementById("botonGuardarRegistro").disabled=!!cerrado;
      document.getElementById("botonCerrarDia").disabled=!!cerrado;
      document.getElementById("botonReabrirDia").disabled=!cerrado;
      document.getElementById("estadoRegistro").textContent=cerrado?"Día cerrado":"Día abierto";
      inputBusqueda.disabled=!!cerrado;
      inputCantidad.disabled=!!cerrado;
      botonAgregar.disabled=!!cerrado;
    } catch(e) { aviso(e.message); filas.replaceChildren(); }
  }

  function dibujarSugerencias() {
    sugerencias.replaceChildren();
    const q=inputBusqueda.value.trim().toLocaleLowerCase("es");
    if(!q){sugerencias.classList.add("oculto");return;}
    const coincidencias=catalogo.filter(p=>p.activo && p.nombre.toLocaleLowerCase("es").includes(q) && !seleccionados.has(String(p.id)));
    if(!coincidencias.length) {
      const vacio=document.createElement("div");vacio.className="nota";vacio.style.padding="12px";
      vacio.textContent="No hay productos coincidentes en el catálogo.";sugerencias.appendChild(vacio);
    } else {
      coincidencias.forEach(p=>{
        const opcion=document.createElement("button");opcion.type="button";opcion.className="secundario ancho";
        opcion.style.cssText="display:flex;justify-content:space-between;align-items:center;border-radius:0;border-bottom:1px solid #eee7df;text-align:left";
        const nombre=document.createElement("strong");nombre.textContent=p.nombre;
        const precio=document.createElement("span");precio.textContent="$"+Number(p.precio).toFixed(2);
        opcion.append(nombre,precio);
        opcion.addEventListener("click",()=>{
          inputBusqueda.value=p.nombre;
          inputBusqueda.dataset.productoId=String(p.id);
          sugerencias.classList.add("oculto");
          captura.classList.remove("oculto");
          inputCantidad.value="";
          inputCantidad.focus();
        });
        sugerencias.appendChild(opcion);
      });
    }
    sugerencias.classList.remove("oculto");
  }

  inputBusqueda.addEventListener("input",()=>{
    delete inputBusqueda.dataset.productoId;
    captura.classList.add("oculto");
    dibujarSugerencias();
  });
  inputCantidad.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();botonAgregar.click();}});
  botonAgregar.addEventListener("click",()=>{
    const id=inputBusqueda.dataset.productoId;
    const cantidad=Number(inputCantidad.value);
    const p=productoPorId(id);
    if(!p){aviso("Selecciona un producto del catálogo.");return;}
    if(!Number.isInteger(cantidad)||cantidad<0||inputCantidad.value.trim()===""){aviso("Escribe una cantidad entera de cero o más.");return;}
    seleccionados.set(String(p.id),{producto:p,cantidad});
    inputBusqueda.value="";delete inputBusqueda.dataset.productoId;inputCantidad.value="";
    captura.classList.add("oculto");sugerencias.classList.add("oculto");
    dibujar();aviso("Producto agregado al registro.","exito");
  });

  function dibujar() {
    filas.replaceChildren();
    const activos=catalogo.filter(p=>p.activo);
    if(!activos.length){filas.textContent="Primero agrega productos en el catálogo.";return;}
    const titulo=document.createElement("h4");titulo.textContent="Productos registrados";filas.appendChild(titulo);
    if(!seleccionados.size){const nota=document.createElement("p");nota.className="nota";nota.textContent="Busca un producto del catálogo para comenzar el conteo.";filas.appendChild(nota);return;}
    seleccionados.forEach(({producto,cantidad},id)=>{
      const row=document.createElement("div");row.className="panel";
      const top=document.createElement("div");top.className="barra";
      const nombre=document.createElement("strong");nombre.textContent=producto.nombre;
      const precio=document.createElement("span");precio.textContent="$"+Number(producto.precio).toFixed(2)+" por pieza";
      top.append(nombre,precio);
      const campo=document.createElement("div");campo.className="campo";
      const label=document.createElement("label");label.textContent="Cantidad";
      const input=document.createElement("input");input.type="number";input.min="0";input.step="1";input.inputMode="numeric";input.value=String(cantidad);input.setAttribute("aria-label","Cantidad de "+producto.nombre);
      input.addEventListener("change",()=>{
        const n=Number(input.value);
        if(Number.isInteger(n)&&n>=0){seleccionados.set(id,{producto,cantidad:n});subtotal.textContent="Subtotal: $"+(Number(producto.precio)*n).toFixed(2);}
        else {input.value=String(seleccionados.get(id).cantidad);aviso("La cantidad debe ser un número entero de cero o más.");}
      });
      campo.append(label,input);
      const subtotal=document.createElement("p");subtotal.className="nota";subtotal.textContent="Subtotal: $"+(Number(producto.precio)*cantidad).toFixed(2);
      const quitar=document.createElement("button");quitar.type="button";quitar.className="secundario";quitar.textContent="Quitar";
      quitar.addEventListener("click",()=>{seleccionados.delete(id);dibujar();});
      row.append(top,campo,subtotal,quitar);filas.appendChild(row);
    });
  }

  fecha.addEventListener("change",()=>{
    actualizarLimitesFecha();
    if(fecha.value<fecha.min||fecha.value>fecha.max){aviso("Solo puedes seleccionar hoy y los dos días calendario anteriores.");fecha.value=fechaLocal(new Date());return;}
    seleccionados.clear();cargar();
  });
  document.getElementById("botonGuardarRegistro").addEventListener("click",async()=>{
    try {
      const lineas=[...seleccionados.values()].map(x=>({producto_id:Number(x.producto.id),cantidad:Number(x.cantidad)}));
      if(lineas.some(x=>!Number.isInteger(x.cantidad)||x.cantidad<0)){aviso("Las cantidades deben ser números enteros de cero o más.");return;}
      await api("/api/registro",{method:"PUT",body:JSON.stringify({panaderia_id:bakery.id,fecha:fecha.value,lineas})});
      aviso("Registro guardado. Aún no has cerrado el día.","exito");await cargar();
    } catch(e){aviso(e.message);}
  });
  document.getElementById("botonCerrarDia").addEventListener("click",async()=>{
    if(!confirm("¿Cerrar el día? Revisa las cantidades antes de continuar.")) return;
    try {
      await api("/api/registro/cerrar?panaderia_id="+bakery.id+"&fecha_registro="+fecha.value,{method:"POST"});
      aviso("Día cerrado correctamente.","exito");await cargar();
    } catch(e){aviso(e.message);}
  });
  document.getElementById("botonReabrirDia").addEventListener("click",async()=>{
    const motivo=prompt("Motivo de la reapertura (obligatorio para correcciones después de 48 horas):") || "";
    try {
      await api("/api/registro/reabrir",{method:"POST",body:JSON.stringify({panaderia_id:Number(bakery.id),fecha:fecha.value,motivo})});
      aviso("Registro reabierto. Los cambios quedarán sujetos a auditoría.","exito");await cargar();
    } catch(e){aviso(e.message);}
  });
  window.actualizarRegistroCatalogo = async function(productos){catalogo=productos||[];await cargar();};
})();

// Registro diario de cantidades por producto.
(function () {
  const panel = document.getElementById("panelRegistro");
  if (!panel) return;
  let token = null, bakery = null, catalogo = [], cierre = null;
  const fecha = document.getElementById("fechaRegistro");
  const filas = document.getElementById("filasRegistro");
  const mensaje = document.getElementById("mensajeRegistro");
  const hoy = new Date();
  fecha.value = new Date(hoy.getTime() - hoy.getTimezoneOffset() * 60000).toISOString().slice(0,10);

  window.iniciarRegistroDiario = async function (sesion, panaderia, productos) {
    token = sesion.access_token; bakery = panaderia; catalogo = productos || [];
    await cargar();
  };
  async function api(url, options={}) {
    const r = await fetch(url,{...options,headers:{Authorization:"Bearer "+token,Accept:"application/json",...(options.body?{"Content-Type":"application/json"}:{})}});
    const d=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.detail || "No se pudo completar la operación.");
    return d;
  }
  function aviso(t, tipo="error") { mensaje.textContent=t; mensaje.className="mensaje "+tipo; }
  async function cargar() {
    if(!token||!bakery||!fecha.value) return;
    try {
      const d=await api("/api/registro?panaderia_id="+bakery.id+"&fecha_registro="+fecha.value);
      cierre=d.cierre;
      const guardadas=new Map((d.lineas||[]).map(x=>[String(x.producto_id),x]));
      dibujar(guardadas);
      const cerrado=cierre && cierre.estado==="cerrado";
      document.getElementById("botonGuardarRegistro").disabled=!!cerrado;
      document.getElementById("botonCerrarDia").disabled=!!cerrado;
      document.getElementById("botonReabrirDia").disabled=!cerrado;
      document.getElementById("estadoRegistro").textContent=cerrado?"Día cerrado":"Día abierto";
    } catch(e) { aviso(e.message); filas.replaceChildren(); }
  }
  function dibujar(guardadas) {
    filas.replaceChildren();
    const activos=catalogo.filter(p=>p.activo);
    if(!activos.length){filas.textContent="Primero agrega productos en el catálogo.";return;}
    activos.forEach(p=>{
      const row=document.createElement("div");row.className="panel";
      const label=document.createElement("label");label.textContent=p.nombre+" · $"+Number(p.precio).toFixed(2);
      const input=document.createElement("input");input.type="number";input.min="0";input.step="1";input.inputMode="numeric";input.placeholder="Cantidad en piezas";input.dataset.productoId=p.id;
      const value=guardadas.get(String(p.id)); if(value) input.value=value.cantidad;
      row.append(label,input);filas.appendChild(row);
    });
  }
  document.getElementById("fechaRegistro").addEventListener("change",cargar);
  document.getElementById("botonGuardarRegistro").addEventListener("click",async()=>{
    try {
      const lineas=[...filas.querySelectorAll("input[data-producto-id]")].filter(i=>i.value.trim()!=="").map(i=>({producto_id:Number(i.dataset.productoId),cantidad:Number(i.value)}));
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
  window.actualizarRegistroCatalogo = async function(productos){catalogo=productos||[];await cargar();};
})();
  document.getElementById("botonReabrirDia").addEventListener("click",async()=>{
    const motivo=prompt("Motivo de la reapertura (obligatorio para correcciones después de 48 horas):") || "";
    try {
      await api("/api/registro/reabrir",{method:"POST",body:JSON.stringify({panaderia_id:Number(bakery.id),fecha:fecha.value,motivo})});
      aviso("Registro reabierto. Los cambios quedarán sujetos a auditoría.","exito");await cargar();
    } catch(e){aviso(e.message);}
  });

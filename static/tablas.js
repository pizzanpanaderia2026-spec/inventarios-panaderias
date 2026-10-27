(function(){
const panel=document.getElementById("panelTablas");if(!panel)return;
const detalle=document.getElementById("tablaDetalle"),resumen=document.getElementById("tablaResumen"),msg=document.getElementById("mensajeTablas");
function draw(target,heads){const w=document.createElement("div");w.className="tabla-scroll";const t=document.createElement("table"),h=document.createElement("tr");heads.forEach(x=>{const e=document.createElement("th");e.textContent=x;h.appendChild(e)});const hd=document.createElement("thead");hd.appendChild(h);t.appendChild(hd);const body=document.createElement("tbody"),r=document.createElement("tr"),c=document.createElement("td");c.colSpan=heads.length;c.textContent="Los datos del día anterior aparecerán aquí.";r.appendChild(c);body.appendChild(r);t.appendChild(body);w.appendChild(t);target.replaceChildren(w)}
draw(detalle,["Fecha","Producto","Cantidad","Precio unitario","Total"]);draw(resumen,["Precio","Cantidad total","Importe"]);
document.getElementById("botonDescargarExcel").addEventListener("click",()=>{msg.textContent="La descarga de las tablas se conectará en el siguiente paso.";msg.className="mensaje"});
window.iniciarTablasHistorial=function(sesion,panaderia){const f=document.getElementById("fechaTablas");if(f)f.textContent="Resultado del día anterior al último cierre registrado.";};
})();
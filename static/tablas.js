(function(){
 const panel=document.getElementById("panelTablas"); if(!panel)return;
 let token=null,bakery=null;
 const desde=document.getElementById("histDesde"),hasta=document.getElementById("histHasta");
 const msg=document.getElementById("mensajeTablas"),detalle=document.getElementById("tablaDetalle"),resumen=document.getElementById("tablaResumen");
 const now=new Date(), today=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,10);
 desde.value=today; hasta.value=today;
 window.iniciarTablasHistorial=function(sesion,panaderia){token=sesion.access_token;bakery=panaderia;};
 async function api(url){const r=await fetch(url,{headers:{Authorization:"Bearer "+token,Accept:"application/json"}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||"No se pudo consultar el historial.");return d;}
 function cell(tr,text,tag="td"){const el=document.createElement(tag);el.textContent=text;tr.appendChild(el);}
 function tableDraw(target,heads,rows){target.replaceChildren();const t=document.createElement("table");t.style.width="100%";t.style.borderCollapse="collapse";const thead=document.createElement("thead"),hr=document.createElement("tr");heads.forEach(h=>cell(hr,h,"th"));thead.append(hr);t.append(thead);const tb=document.createElement("tbody");rows.forEach(row=>{const tr=document.createElement("tr");row.forEach(v=>cell(tr,String(v)));tb.append(tr);});t.append(tb);target.append(t);}
 function money(n){return "$"+Number(n).toFixed(2);}
 document.getElementById("botonConsultarTablas").addEventListener("click",async()=>{
  try{
   if(!token||!bakery)throw new Error("Selecciona una panadería primero.");
   const d=await api("/api/historial?panaderia_id="+bakery.id+"&desde="+desde.value+"&hasta="+hasta.value);
   const rows=[],sum=new Map();let grand=0;
   (d.historial||[]).forEach(day=>(day.lineas||[]).forEach(x=>{
    const price=Number(x.precio_unitario),qty=Number(x.cantidad),total=Number(x.total);grand+=total;
    rows.push([day.cierre.fecha,x.producto,qty,money(price),money(total)]);
    const key=price.toFixed(2),old=sum.get(key)||{qty:0,total:0};old.qty+=qty;old.total+=total;sum.set(key,old);
   }));
   tableDraw(detalle,["Fecha","Producto","Cantidad","Precio unitario","Total"],rows);
   const summary=[...sum.entries()].sort((a,b)=>Number(a[0])-Number(b[0])).map(([p,v])=>[money(p),v.qty,money(v.total)]);
   summary.push(["TOTAL GENERAL",summary.reduce((n,x)=>n+Number(x[1]),0),money(grand)]);
   tableDraw(resumen,["Precio","Cantidad total","Importe"],summary);
   msg.textContent="Consulta actualizada.";msg.className="mensaje exito";
  }catch(e){msg.textContent=e.message;msg.className="mensaje error";}
 });
})();
(function(){
  const root=document.getElementById("histCalendario"); if(!root)return;
  const title=document.getElementById("histMesTitulo"), out=document.getElementById("historialResultado"), msg=document.getElementById("mensajeHistorial");
  let shown=new Date(), selected="", token=null, panaderia=null;
  const pad=n=>String(n).padStart(2,"0"), iso=d=>d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());
  const dinero=v=>Number(v||0).toLocaleString("es-MX",{style:"currency",currency:"MXN"});
  function aviso(t,tipo){msg.textContent=t;msg.className="mensaje "+(tipo||"error");}
  function tabla(heads,rows,total){
    const wrap=document.createElement("div");wrap.className="tabla-scroll";
    const t=document.createElement("table"),thd=document.createElement("thead"),hr=document.createElement("tr");
    heads.forEach(x=>{const c=document.createElement("th");c.textContent=x;hr.appendChild(c);});thd.appendChild(hr);t.appendChild(thd);
    const body=document.createElement("tbody");
    rows.forEach(row=>{const tr=document.createElement("tr");row.forEach(x=>{const td=document.createElement("td");td.textContent=String(x??"");tr.appendChild(td);});body.appendChild(tr);});
    if(total){const tr=document.createElement("tr");tr.className="tablas-total";total.forEach(x=>{const td=document.createElement("td");td.textContent=String(x??"");tr.appendChild(td);});body.appendChild(tr);}
    t.appendChild(body);wrap.appendChild(t);out.appendChild(wrap);
  }
  async function descargar(fecha){
    const url="/api/historial/periodo/excel?panaderia_id="+encodeURIComponent(panaderia.id)+"&desde="+fecha+"&hasta="+fecha;
    const r=await fetch(url,{headers:{Authorization:"Bearer "+token}});
    if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||"No se pudo descargar el inventario.");}
    const href=URL.createObjectURL(await r.blob()),a=document.createElement("a");a.href=href;a.download="inventario_"+fecha+".xlsx";document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(href);
  }
  async function choose(value){
    selected=value;draw();out.replaceChildren();msg.textContent="";msg.className="mensaje oculto";
    if(!token||!panaderia){const p=document.createElement("p");p.className="nota";p.textContent="Selecciona una panadería para consultar su historial.";out.appendChild(p);return;}
    const wait=document.createElement("p");wait.className="nota";wait.textContent="Buscando inventario…";out.appendChild(wait);
    try{
      const url="/api/historial/consulta?panaderia_id="+encodeURIComponent(panaderia.id)+"&desde="+value+"&hasta="+value;
      const r=await fetch(url,{headers:{Authorization:"Bearer "+token,Accept:"application/json"}}),data=await r.json().catch(()=>({}));
      if(!r.ok)throw new Error(data.detail||"No se pudo consultar el inventario.");
      out.replaceChildren();const d=(data.historial||[])[0];
      if(!d){const p=document.createElement("p");p.className="nota";p.textContent="No hay un inventario registrado para esta fecha en esta panadería.";out.appendChild(p);return;}
      const p=document.createElement("p");p.className="nota";p.textContent="Fecha: "+d.cierre.fecha+" · Registrado por: "+(d.cierre.cerrado_por_nombre||"Usuario");out.appendChild(p);
      const h1=document.createElement("h4");h1.textContent="Tabla A · Detalle por producto";out.appendChild(h1);
      tabla(["Producto","Cantidad","Precio unitario","Importe"],(d.lineas||[]).map(x=>[x.producto,Number(x.cantidad||0).toLocaleString("es-MX"),dinero(x.precio_unitario),dinero(x.total)]),["TOTAL GENERAL",Number(d.total_piezas||0).toLocaleString("es-MX"),"",dinero(d.total_importe)]);
      const h2=document.createElement("h4");h2.textContent="Tabla B · Resumen por precio";out.appendChild(h2);
      tabla(["Precio unitario","Cantidad total","Importe"],(d.resumen||[]).map(x=>[dinero(x.precio),Number(x.cantidad||0).toLocaleString("es-MX"),dinero(x.total)]),["TOTAL GENERAL",Number(d.total_piezas||0).toLocaleString("es-MX"),dinero(d.total_importe)]);
      const b=document.createElement("button");b.type="button";b.textContent="Descargar inventario";b.onclick=async()=>{b.disabled=true;try{await descargar(value);aviso("Excel descargado correctamente.","exito");}catch(e){aviso(e.message||"No se pudo descargar.");}finally{b.disabled=false;}};out.appendChild(b);
    }catch(e){out.replaceChildren();aviso(e.message||"No se pudo consultar el historial.");}
  }
  function draw(){
    root.replaceChildren();title.textContent=shown.toLocaleDateString("es-MX",{month:"long",year:"numeric"});
    ["L","M","X","J","V","S","D"].forEach(day=>{const l=document.createElement("div");l.className="nota";l.style.textAlign="center";l.textContent=day;root.appendChild(l);});
    const first=new Date(shown.getFullYear(),shown.getMonth(),1),offset=(first.getDay()+6)%7;
    for(let i=0;i<offset;i++)root.appendChild(document.createElement("span"));
    const total=new Date(shown.getFullYear(),shown.getMonth()+1,0).getDate(),today=new Date();today.setHours(0,0,0,0);
    for(let n=1;n<=total;n++){const dt=new Date(shown.getFullYear(),shown.getMonth(),n),v=iso(dt),age=Math.floor((today-dt)/86400000),b=document.createElement("button");b.type="button";b.className="calendario-dia"+(age>30?" antiguo":"")+(selected===v?" seleccionado":"");b.textContent=n;b.disabled=dt>today;b.setAttribute("aria-label",v+(age>30?", fecha histórica":""));b.onclick=()=>choose(v);root.appendChild(b);}
  }
  document.getElementById("histMesAnterior").addEventListener("click",()=>{shown=new Date(shown.getFullYear(),shown.getMonth()-1,1);draw();});
  document.getElementById("histMesSiguiente").addEventListener("click",()=>{const n=new Date(shown.getFullYear(),shown.getMonth()+1,1),now=new Date();if(n.getFullYear()<now.getFullYear()||(n.getFullYear()===now.getFullYear()&&n.getMonth()<=now.getMonth())){shown=n;draw();}});
  window.iniciarHistorialInventarios=function(sesion,local){token=sesion&&sesion.access_token;panaderia=local;draw();if(selected)choose(selected);};
  draw();
})();
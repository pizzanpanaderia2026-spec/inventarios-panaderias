(function(){
  const root = document.getElementById("histCalendario");
  if (!root) return;
  const title = document.getElementById("histMesTitulo");
  const out = document.getElementById("historialResultado");
  const msg = document.getElementById("mensajeHistorial");
  let shown = new Date();
  let selected = "";
  const pad = n => String(n).padStart(2, "0");
  const iso = d => d.getFullYear() + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate());

  function table(heads) {
    const wrap = document.createElement("div");
    wrap.className = "tabla-scroll";
    const t = document.createElement("table");
    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    heads.forEach(label => {
      const th = document.createElement("th");
      th.textContent = label;
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (let i = 0; i < 4; i++) {
      const tr = document.createElement("tr");
      heads.forEach(() => {
        const td = document.createElement("td");
        td.innerHTML = "&nbsp;";
        td.style.height = "34px";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    t.appendChild(tbody);
    wrap.appendChild(t);
    out.appendChild(wrap);
  }

  function choose(value) {
    selected = value;
    draw();
    out.replaceChildren();
    msg.textContent = "";
    msg.className = "mensaje oculto";
    const today = new Date();
    today.setHours(0,0,0,0);
    const date = new Date(value + "T00:00:00");
    const age = Math.floor((today - date) / 86400000);
    if (age > 30) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Descargar inventario";
      button.addEventListener("click", () => {
        msg.textContent = "El enlace del archivo en Google Drive se conectará en el siguiente paso.";
        msg.className = "mensaje";
      });
      out.appendChild(button);
      return;
    }
    const hA = document.createElement("h4");
    hA.textContent = "Tabla A · Detalle por producto";
    out.appendChild(hA);
    table(["Fecha", "Producto", "Cantidad", "Precio unitario", "Total"]);
    const hB = document.createElement("h4");
    hB.textContent = "Tabla B · Resumen por precio";
    out.appendChild(hB);
    table(["Precio", "Cantidad total", "Importe"]);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Descargar inventario";
    button.addEventListener("click", () => {
      msg.textContent = "La descarga del inventario se conectará en el siguiente paso.";
      msg.className = "mensaje";
    });
    out.appendChild(button);
  }

  function draw() {
    root.replaceChildren();
    title.textContent = shown.toLocaleDateString("es-MX", {month:"long", year:"numeric"});
    ["L","M","X","J","V","S","D"].forEach(day => {
      const label = document.createElement("div");
      label.className = "nota";
      label.style.textAlign = "center";
      label.textContent = day;
      root.appendChild(label);
    });
    const first = new Date(shown.getFullYear(), shown.getMonth(), 1);
    const offset = (first.getDay()+6)%7;
    for (let i=0; i<offset; i++) root.appendChild(document.createElement("span"));
    const total = new Date(shown.getFullYear(), shown.getMonth()+1, 0).getDate();
    const today = new Date();
    today.setHours(0,0,0,0);
    for (let n=1; n<=total; n++) {
      const date = new Date(shown.getFullYear(), shown.getMonth(), n);
      const value = iso(date);
      const age = Math.floor((today-date)/86400000);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "calendario-dia" + (age>30 ? " antiguo" : "") + (selected===value ? " seleccionado" : "");
      button.textContent = n;
      button.disabled = date > today;
      button.setAttribute("aria-label", value + (age>30 ? ", inventario archivado" : ""));
      button.addEventListener("click", () => choose(value));
      root.appendChild(button);
    }
  }

  document.getElementById("histMesAnterior").addEventListener("click", () => {
    shown = new Date(shown.getFullYear(), shown.getMonth()-1, 1);
    draw();
  });
  document.getElementById("histMesSiguiente").addEventListener("click", () => {
    const next = new Date(shown.getFullYear(), shown.getMonth()+1, 1);
    const now = new Date();
    if (next.getFullYear() < now.getFullYear() || (next.getFullYear() === now.getFullYear() && next.getMonth() <= now.getMonth())) {
      shown = next;
      draw();
    }
  });
  draw();
})();
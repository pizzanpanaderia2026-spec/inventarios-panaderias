(function(){
  const panel = document.getElementById("panelTablas");
  if (!panel) return;
  const detalle = document.getElementById("tablaDetalle");
  const resumen = document.getElementById("tablaResumen");
  const msg = document.getElementById("mensajeTablas");

  function draw(target, heads, blankRows = 4) {
    const wrap = document.createElement("div");
    wrap.className = "tabla-scroll";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    heads.forEach(label => {
      const th = document.createElement("th");
      th.textContent = label;
      header.appendChild(th);
    });
    thead.appendChild(header);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (let i = 0; i < blankRows; i++) {
      const tr = document.createElement("tr");
      heads.forEach(() => {
        const td = document.createElement("td");
        td.innerHTML = "&nbsp;";
        td.style.height = "34px";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    target.replaceChildren(wrap);
  }

  draw(detalle, ["Fecha", "Producto", "Cantidad", "Precio unitario", "Total"]);
  draw(resumen, ["Precio", "Cantidad total", "Importe"]);

  document.getElementById("botonDescargarExcel").addEventListener("click", () => {
    msg.textContent = "La descarga de las tablas se conectará en el siguiente paso.";
    msg.className = "mensaje";
  });

  window.iniciarTablasHistorial = function(sesion, panaderia) {
    const f = document.getElementById("fechaTablas");
    if (f) f.textContent = "Datos del cierre del día anterior. La conexión con los inventarios se agregará en el siguiente paso.";
  };
})();
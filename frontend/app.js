const API_URL = "http://127.0.0.1:8000";

// Selección de Elementos del DOM
const formProducto = document.getElementById("formProducto");
const tablaProductos = document.getElementById("tablaProductos");
const totalProductos = document.getElementById("totalProductos");
const kpiTransacciones = document.getElementById("kpiTransacciones");
const kpiIngresos = document.getElementById("kpiIngresos");
const kpiEstrella = document.getElementById("kpiEstrella");
const kpiTicket = document.getElementById("kpiTicket");
const estadoTurno = document.getElementById("estadoTurno");
const estadoUltimo = document.getElementById("estadoUltimo");
const estadoProximo = document.getElementById("estadoProximo");

const formatoPesos = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
const pesos = valor => formatoPesos.format(valor);

// Guardamos las instancias de las gráficas para poder destruirlas antes de redibujar
let graficaBarras = null;
let graficaLinea = null;

// Colores de la tiendita (los mismos que en el CSS del index)
const COLOR_PRINCIPAL = "#c2410c";
const COLOR_SECUNDARIO = "#0f766e";


// 1. Función para Cargar Productos (GET)
async function cargarProductos() {
    try {
        const respuesta = await fetch(`${API_URL}/productos`);
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        const productos = await respuesta.json();

        tablaProductos.innerHTML = "";
        totalProductos.textContent = `${productos.length} productos`;

        if (productos.length === 0) {
            tablaProductos.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-muted py-4">
                        No hay productos registrados en la tiendita.
                    </td>
                </tr>`;
            return;
        }

        productos.forEach(p => {
            const fila = document.createElement("tr");
            fila.innerHTML = `
                <td class="fw-bold text-secondary">#${p.id}</td>
                <td>${p.nombre}</td>
                <td class="precio fw-bold">$${p.precio.toFixed(2)}</td>
                <td>
                    <span class="badge ${p.cantidad < 10 ? 'bg-danger' : 'bg-success'}">
                        ${p.cantidad} unidades
                    </span>
                </td>
                <td>
                    <div class="input-group input-group-sm" style="width: 130px;">
                        <input type="number" class="form-control" id="piezas-${p.id}" value="1" min="1" max="${p.cantidad}" ${p.cantidad === 0 ? "disabled" : ""}>
                        <button class="btn btn-tienda" onclick="comprarProducto(${p.id})" ${p.cantidad === 0 ? "disabled" : ""}>
                            Comprar
                        </button>
                    </div>
                </td>
                <td>
                    <button class="btn btn-outline-danger btn-sm" onclick="eliminarProducto(${p.id})">
                        Eliminar
                    </button>
                </td>
            `;
            tablaProductos.appendChild(fila);
        });

    } catch (error) {
        console.error("Error al cargar productos:", error);
    }
}

// 2. Agregar producto (POST)
async function agregarProducto(event) {
    event.preventDefault();

    const nombre = document.getElementById("nombre").value;
    const precio = parseFloat(document.getElementById("precio").value);
    const cantidad = parseInt(document.getElementById("cantidad").value);

    const nuevoContenido = { nombre, precio, cantidad };
    try {
        const respuesta = await fetch(`${API_URL}/productos`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(nuevoContenido)
        });

        if (respuesta.ok) {
            formProducto.reset();
            await cargarProductos();
        } else {
            const error = await respuesta.json();
            console.error("Hubo algo malo al guardar:", error.detail);
            alert("No se pudo guardar el producto");
        }
    } catch (error) {
        console.error("Error al guardar:", error);
    }
}

// 3. Eliminar producto (DELETE)
async function eliminarProducto(id_producto) {
    try {
        const respuesta = await fetch(`${API_URL}/productos/${id_producto}`, { method: "DELETE" });

        if (respuesta.ok) {
            await cargarProductos();
        } else {
            const error = await respuesta.json();
            console.error("Hubo algo malo al eliminar:", error.detail);
        }
    } catch (error) {
        console.error("Error al eliminar:", error);
    }
}

// 4. Comprar producto (POST /productos/{id})
async function comprarProducto(id_producto) {
    const cantidad = parseInt(document.getElementById(`piezas-${id_producto}`).value) || 1;
    try {
        const respuesta = await fetch(`${API_URL}/productos/${id_producto}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cantidad })
        });

        if (respuesta.ok) {
            // Después de comprar se refresca todo: tabla, KPIs y gráficas
            await Promise.all([
                cargarProductos(),
                cargarKpis(),
                cargarGraficaBarras(),
                cargarGraficaLinea(),
                cargarEstadoCorte()
            ]);
        } else {
            const error = await respuesta.json();
            console.error("Hubo algo malo al comprar:", error.detail);
            alert(error.detail);
        }
    } catch (error) {
        console.error("Error al comprar:", error);
    }
}


// ---------- Dashboard ----------

// KPIs generales
async function cargarKpis() {
    try {
        const respuesta = await fetch(`${API_URL}/api/analisis/kpis`);
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        const kpis = await respuesta.json();

        kpiTransacciones.textContent = kpis.total_transacciones.toLocaleString("es-MX");
        kpiIngresos.textContent = pesos(kpis.ingresos_totales);
        kpiTicket.textContent = pesos(kpis.ticket_promedio);
        kpiEstrella.textContent = kpis.producto_estrella;
    } catch (error) {
        console.error("Error al cargar KPIs:", error);
    }
}

// Gráfica de barras: unidades vendidas por producto
async function cargarGraficaBarras() {
    try {
        const respuesta = await fetch(`${API_URL}/api/analisis/mas-vendidos`);
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        const datos = await respuesta.json();

        // Si ya existía una gráfica se destruye para no encimar instancias en el mismo canvas
        if (graficaBarras) {
            graficaBarras.destroy();
        }

        graficaBarras = new Chart(document.getElementById("graficaBarras"), {
            type: "bar",
            data: {
                labels: datos.map(d => d.producto),
                datasets: [{
                    label: "Unidades vendidas",
                    data: datos.map(d => d.cantidad_vendida),
                    backgroundColor: COLOR_PRINCIPAL,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
            }
        });
    } catch (error) {
        console.error("Error al cargar la gráfica de barras:", error);
    }
}

// Gráfica de línea: piezas vendidas por día (histórico + turno actual)
async function cargarGraficaLinea() {
    try {
        const respuesta = await fetch(`${API_URL}/api/analisis/ventas-por-dia`);
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        const datos = await respuesta.json();

        if (graficaLinea) {
            graficaLinea.destroy();
        }

        graficaLinea = new Chart(document.getElementById("graficaLinea"), {
            type: "line",
            data: {
                labels: datos.map(d => d.dia),
                datasets: [{
                    label: "Piezas vendidas",
                    data: datos.map(d => d.cantidad),
                    borderColor: COLOR_SECUNDARIO,
                    backgroundColor: "rgba(15, 118, 110, 0.15)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                animation: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
            }
        });
    } catch (error) {
        console.error("Error al cargar la gráfica de línea:", error);
    }
}


// Estado del corte de caja: ventas que siguen en el CSV y hora del próximo corte
async function cargarEstadoCorte() {
    try {
        const respuesta = await fetch(`${API_URL}/api/corte-de-caja`);
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        const estado = await respuesta.json();

        const turnoAnterior = estadoTurno.textContent;
        estadoTurno.textContent = estado.ventas_en_turno;
        estadoUltimo.textContent = estado.ultimo_corte ?? "todavía no";
        estadoProximo.textContent = estado.proximo_corte ? estado.proximo_corte.slice(11, 16) : "-";

        // Si hubo corte desde la última revisión, se refrescan los KPIs para comprobar que no cambian
        if (turnoAnterior !== "" && Number(turnoAnterior) > 0 && estado.ventas_en_turno === 0) {
            cargarKpis();
        }
    } catch (error) {
        console.error("Error al consultar el corte de caja:", error);
    }
}

async function hacerCorteAhora() {
    try {
        const respuesta = await fetch(`${API_URL}/api/corte-de-caja`, { method: "POST" });
        if (!respuesta.ok) {
            throw new Error(`El servidor respondió ${respuesta.status}`);
        }
        await Promise.all([cargarEstadoCorte(), cargarKpis()]);
    } catch (error) {
        console.error("Error al hacer el corte:", error);
    }
}


// Al abrir la página se carga el catálogo y el dashboard
document.addEventListener("DOMContentLoaded", () => {
    cargarProductos();
    cargarKpis();
    cargarGraficaBarras();
    cargarGraficaLinea();
    cargarEstadoCorte();
    // El corte corre solo en el servidor; cada 15 s se revisa si ya pasó
    setInterval(cargarEstadoCorte, 15000);
});

// Evento para guardar producto al dar clic en el botón del formulario
formProducto.addEventListener("submit", agregarProducto);

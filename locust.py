from locust import HttpUser, task, between
import random


class UsuarioTiendaCompleta(HttpUser):
    wait_time = between(0.2, 0.8)

    @task(3)
    def comprarProducto(self):
        # El producto 3 empieza con stock=1, así se ve si el lock evita vender de más
        with self.client.post("/productos/3", json={"producto_id": 3}, catch_response=True) as respuesta:
            if respuesta.status_code in (200, 400):
                # 400 = ya no hay stock, también cuenta como respuesta correcta
                respuesta.success()
            else:
                respuesta.failure(f"Código inesperado: {respuesta.status_code}")

    @task(2)
    def comprarOtroProducto(self):
        producto_id = random.randint(1, 6)
        with self.client.post(f"/productos/{producto_id}", name="/productos/[id]", catch_response=True) as respuesta:
            if respuesta.status_code in (200, 400):
                respuesta.success()
            else:
                respuesta.failure(f"Código inesperado: {respuesta.status_code}")

    @task(1)
    def getProducto(self):
        self.client.get("/productos")

    # Estas tres son las que pide el dashboard cada vez que se hace una compra
    @task(1)
    def verKpis(self):
        self.client.get("/api/analisis/kpis")

    @task(1)
    def verMasVendidos(self):
        self.client.get("/api/analisis/mas-vendidos")

    @task(1)
    def verVentasPorDia(self):
        self.client.get("/api/analisis/ventas-por-dia")

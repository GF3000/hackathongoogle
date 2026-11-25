import unittest
from fastapi.testclient import TestClient
from main import app, store

class TestMueblesSSR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Trigger lifespan
        store.load_catalog()
        cls.client = TestClient(app)

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertGreaterEqual(data["products_count"], 4)

    def test_security_headers(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("default-src 'self'", resp.headers.get("content-security-policy", ""))

    def test_catalog_rendering(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("Muebles Cloud", html)
        self.assertIn("Sofá Nórdico", html)

    def test_product_detail(self):
        resp = self.client.get("/producto/sofa-nordico")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("Sofá Nórdico", html)
        self.assertIn("849", html)

    def test_cart_flow(self):
        # 1. Get CSRF token from home
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("cart_session_id", resp.cookies)
        session_id = resp.cookies["cart_session_id"]

        from main import generate_csrf_token
        csrf = generate_csrf_token(session_id)

        # 2. Add to cart
        resp_add = self.client.post(
            "/carrito/agregar",
            data={"sku": "sofa-nordico", "csrf_token": csrf},
            follow_redirects=True
        )
        self.assertEqual(resp_add.status_code, 200)
        self.assertIn("Sofá Nórdico", resp_add.text)
        self.assertIn("849", resp_add.text)

        # 3. Checkout
        resp_check = self.client.post(
            "/checkout",
            data={"nombre": "Laura Gomez", "ciudad": "Madrid", "csrf_token": csrf}
        )
        self.assertEqual(resp_check.status_code, 200)
        self.assertIn("confirmado", resp_check.text)
        self.assertIn("Madrid", resp_check.text)

    def test_asistente_heuristic_fallback(self):
        resp = self.client.get("/asistente")
        session_id = resp.cookies["cart_session_id"]
        from main import generate_csrf_token
        csrf = generate_csrf_token(session_id)

        resp_ai = self.client.post(
            "/asistente",
            data={"pregunta": "Busco un sofá para salón moderno", "csrf_token": csrf}
        )
        self.assertEqual(resp_ai.status_code, 200)
        self.assertIn("Recomendación", resp_ai.text)

    def test_api_v1_compatibility(self):
        resp = self.client.get("/api/v1/furniture")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(len(data["items"]), 4)

        order_resp = self.client.post(
            "/api/v1/orders",
            json={
                "items": [{"furniture_id": "sofa-nordico", "quantity": 1}],
                "payment_token": "tok_12345678",
                "shipping_city": "Valencia"
            }
        )
        self.assertEqual(order_resp.status_code, 201)
        self.assertEqual(order_resp.json()["status"], "confirmed")

if __name__ == "__main__":
    unittest.main()

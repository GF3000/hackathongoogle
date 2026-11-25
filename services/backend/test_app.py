import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from app import StoreState, make_handler


class BackendAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = StoreState()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.state))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.state.reset()

    def _request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(payload))
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        resp_headers = dict(resp.getheaders())
        conn.close()
        return resp.status, resp_headers, data

    def test_healthz_and_security_headers(self):
        status, headers, data = self._request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_list_furniture_and_category_filter(self):
        status, _, data = self._request("GET", "/api/v1/furniture?category=sofas")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["id"], "sofa-nordico-01")

    def test_reject_invalid_category(self):
        status, _, _ = self._request("GET", "/api/v1/furniture?category=%27%20OR%201%3D1--")
        self.assertEqual(status, 400)

    def test_create_order_decrements_stock(self):
        status, _, order = self._request(
            "POST",
            "/api/v1/orders",
            {
                "items": [{"furniture_id": "mesa-roble-02", "quantity": 2}],
                "payment_token": "tok_test_12345678",
                "shipping_city": "Madrid",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(order["total_eur"], 1098.0)

        _, _, catalog = self._request("GET", "/api/v1/furniture?category=mesas")
        self.assertEqual(catalog["items"][0]["stock"], 3)

    def test_reject_invalid_payment_token(self):
        status, _, _ = self._request(
            "POST",
            "/api/v1/orders",
            {
                "items": [{"furniture_id": "mesa-roble-02", "quantity": 1}],
                "payment_token": "4111111111111111",
                "shipping_city": "Madrid",
            },
        )
        self.assertEqual(status, 400)

    def test_insufficient_stock_returns_409(self):
        status, _, _ = self._request(
            "POST",
            "/api/v1/orders",
            {
                "items": [{"furniture_id": "mesa-roble-02", "quantity": 10}],
                "payment_token": "tok_test_12345678",
                "shipping_city": "Valencia",
            },
        )
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()

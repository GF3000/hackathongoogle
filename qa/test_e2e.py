"""Tests E2E de contrato entre Frontend, Backend y cabeceras de seguridad.

Pueden ejecutarse:
1. Levantando instancias locales efimeras automaticamente (por defecto).
2. Apuntando a URLs de preview/despliegue mediante FRONTEND_URL y BACKEND_URL.
"""

import http.client
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


class EndToEndStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.procs = []
        cls.frontend_url = os.environ.get("FRONTEND_URL")
        cls.backend_url = os.environ.get("BACKEND_URL")

        if not cls.backend_url:
            cls.backend_url = "http://127.0.0.1:18081"
            p_back = subprocess.Popen(
                [sys.executable, str(ROOT_DIR / "services/backend/app.py")],
                env={**os.environ, "PORT": "18081"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.procs.append(p_back)

        if not cls.frontend_url:
            cls.frontend_url = "http://127.0.0.1:18080"
            p_front = subprocess.Popen(
                ["node", str(ROOT_DIR / "services/frontend/server.js")],
                env={**os.environ, "PORT": "18080", "BACKEND_URL": cls.backend_url},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.procs.append(p_front)

        cls._wait_ready(cls.backend_url + "/healthz")
        cls._wait_ready(cls.frontend_url + "/healthz")

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.terminate()
            p.wait(timeout=5)

    @staticmethod
    def _wait_ready(url):
        for _ in range(30):
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError(f"Servicio no respondio a tiempo: {url}")

    def test_frontend_serves_ui_with_security_headers(self):
        with urllib.request.urlopen(self.frontend_url + "/", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("default-src 'self'", resp.headers.get("Content-Security-Policy", ""))
            html = resp.read().decode("utf-8")
            self.assertIn("Muebles Cloud", html)

    def test_frontend_proxies_catalog_and_order_to_backend(self):
        with urllib.request.urlopen(self.frontend_url + "/api/v1/furniture", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            catalog = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(len(catalog["items"]), 4)
            target_id = catalog["items"][0]["id"]

        parsed = urllib.parse.urlparse(self.frontend_url)
        conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(parsed.netloc, timeout=5)
        payload = json.dumps(
            {
                "items": [{"furniture_id": target_id, "quantity": 1}],
                "payment_token": "tok_qa_e2e_123456",
                "shipping_city": "Barcelona",
            }
        ).encode("utf-8")
        conn.request(
            "POST",
            "/api/v1/orders",
            body=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = conn.getresponse()
        order = json.loads(resp.read().decode("utf-8"))
        conn.close()

        self.assertEqual(resp.status, 201)
        self.assertEqual(order["status"], "confirmed")
        self.assertEqual(order["shipping_city"], "Barcelona")


if __name__ == "__main__":
    unittest.main()

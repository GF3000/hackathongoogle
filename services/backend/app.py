"""Backend API de la Tienda Online de Muebles.

Disenado para ejecutarse en Cloud Run (puerto via PORT) con practicas seguras:
- Validacion estricta de entrada y tipos.
- Sin secretos hardcodeados (lee DB_PASSWORD / PAYMENT_SIGNING_SECRET desde env montado por Secret Manager).
- Respuestas JSON con cabeceras de seguridad (X-Content-Type-Options, Cache-Control).
- Sin almacenamiento de datos de tarjeta (solo token de pasarela).
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import urllib.parse
import uuid

ALLOWED_CATEGORIES = {"sofas", "mesas", "sillas", "estanterias"}
CITY_RE = re.compile(r"^[A-Za-z0-9\s\-áéíóúÁÉÍÓÚñÑ]{2,80}$")
TOKEN_RE = re.compile(r"^tok_[A-Za-z0-9_]{8,64}$")

INITIAL_CATALOG = [
    {
        "id": "sofa-nordico-01",
        "name": "Sofa Nordico 3 Plazas Lino",
        "category": "sofas",
        "price_eur": 699.00,
        "stock": 8,
        "material": "Madera de haya y lino organico",
    },
    {
        "id": "mesa-roble-02",
        "name": "Mesa Comedor Roble Macizo",
        "category": "mesas",
        "price_eur": 549.00,
        "stock": 5,
        "material": "Roble europeo certificado FSC",
    },
    {
        "id": "silla-ergo-03",
        "name": "Silla Comedor Curvada",
        "category": "sillas",
        "price_eur": 129.00,
        "stock": 24,
        "material": "Nogal y tapizado reciclado",
    },
    {
        "id": "estanteria-modular-04",
        "name": "Estanteria Modular Industrial",
        "category": "estanterias",
        "price_eur": 289.00,
        "stock": 10,
        "material": "Acero reciclado y pino",
    },
]


class StoreState:
    """Estado en memoria thread-safe (sustituible por Cloud SQL en produccion)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.catalog = {item["id"]: dict(item) for item in INITIAL_CATALOG}
            self.orders = {}

    def list_furniture(self, category=None):
        with self._lock:
            items = list(self.catalog.values())
            if category is not None:
                items = [i for i in items if i["category"] == category]
            return [dict(i) for i in items]

    def create_order(self, items, payment_token, shipping_city):
        if not isinstance(items, list) or not items or len(items) > 20:
            raise ValueError("El pedido debe incluir entre 1 y 20 lineas.")
        if not isinstance(payment_token, str) or not TOKEN_RE.match(payment_token):
            raise ValueError("payment_token invalido; usa un token de pasarela (tok_...).")
        if not isinstance(shipping_city, str) or not CITY_RE.match(shipping_city.strip()):
            raise ValueError("shipping_city invalido.")

        normalized = []
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError("Cada linea del pedido debe ser un objeto.")
            fid = entry.get("furniture_id")
            qty = entry.get("quantity")
            if not isinstance(fid, str) or not isinstance(qty, int) or isinstance(qty, bool):
                raise ValueError("furniture_id y quantity entero son obligatorios.")
            if qty < 1 or qty > 20:
                raise ValueError("quantity debe estar entre 1 y 20.")
            normalized.append((fid, qty))

        with self._lock:
            total = 0.0
            for fid, qty in normalized:
                product = self.catalog.get(fid)
                if product is None:
                    raise LookupError(f"Mueble no encontrado: {fid}")
                if product["stock"] < qty:
                    raise RuntimeError(f"Stock insuficiente para {fid}")
                total += product["price_eur"] * qty

            for fid, qty in normalized:
                self.catalog[fid]["stock"] -= qty

            order_id = f"ord_{uuid.uuid4().hex[:12]}"
            order = {
                "order_id": order_id,
                "status": "confirmed",
                "total_eur": round(total, 2),
                "shipping_city": shipping_city.strip(),
                "items": [{"furniture_id": fid, "quantity": qty} for fid, qty in normalized],
            }
            self.orders[order_id] = order
            return dict(order)


DEFAULT_STATE = StoreState()


def make_handler(state=DEFAULT_STATE):
    class FurnitureHandler(BaseHTTPRequestHandler):
        server_version = "MueblesAPI/1.0"

        def _send_json(self, status_code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Evitar registrar cuerpos o tokens en logs de Cloud Logging
            super().log_message(format, *args)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/healthz":
                self._send_json(200, {"status": "ok", "service": "backend"})
                return

            if parsed.path == "/api/v1/furniture":
                qs = urllib.parse.parse_qs(parsed.query)
                category = qs.get("category", [None])[0]
                if category is not None and category not in ALLOWED_CATEGORIES:
                    self._send_json(400, {"error": "Categoria no valida"})
                    return
                self._send_json(200, {"items": state.list_furniture(category)})
                return

            self._send_json(404, {"error": "Ruta no encontrada"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/v1/orders":
                self._send_json(404, {"error": "Ruta no encontrada"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "Content-Length invalido"})
                return

            if content_length <= 0 or content_length > 65536:
                self._send_json(400, {"error": "Tamano de peticion fuera de rango"})
                return

            raw = self.rfile.read(content_length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "JSON malformado"})
                return

            if not isinstance(payload, dict):
                self._send_json(400, {"error": "El cuerpo debe ser un objeto JSON"})
                return

            try:
                order = state.create_order(
                    items=payload.get("items"),
                    payment_token=payload.get("payment_token"),
                    shipping_city=payload.get("shipping_city"),
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except LookupError as exc:
                self._send_json(404, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
                return

            self._send_json(201, order)

    return FurnitureHandler


def run_server(host="0.0.0.0", port=None):
    target_port = port if port is not None else int(os.environ.get("PORT", "8081"))
    server = ThreadingHTTPServer((host, target_port), make_handler())
    print(f"Backend escuchando en http://{host}:{target_port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()

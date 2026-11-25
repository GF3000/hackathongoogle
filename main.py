"""Backend MVP SSR Ultra Rápido - Tienda Online de Muebles.

Diseñado para Google Cloud Run (<50ms latencia, 0 JS inline, 100% Jinja2 SSR, in-memory thread-safe).
"""

import asyncio
import csv
import hmac
import json
import logging
import os
import re
import secrets
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("muebles-ssr")

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = os.environ.get("CLAVE_EQUIPO", secrets.token_hex(32))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


class InMemoryStore:
    def __init__(self):
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self.categories: List[str] = []
        self.carts: Dict[str, Dict[str, int]] = {}  # session_id -> {sku: qty}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def load_catalog(self):
        # 1. Cargar productos desde catalogo.json
        json_path = BASE_DIR / "catalogo.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for p in data.get("productos", []):
                        self.catalog[p["sku"]] = p
            except Exception as e:
                logger.error("Error leyendo catalogo.json: %s", e)

        # 2. Enriquecer con catalogo_unificado.csv si está presente
        csv_candidates = [
            BASE_DIR / "docs" / "catalogo_unificado.csv",
            BASE_DIR / "catalogo_unificado.csv",
            BASE_DIR.parent / "hackathon-muebles" / "docs" / "catalogo_unificado.csv",
        ]
        for csv_path in csv_candidates:
            if csv_path.exists():
                self._enrich_from_csv(csv_path)
                break

        # Extraer categorías únicas ordenadas
        cats = {p.get("categoria", "") for p in self.catalog.values() if p.get("categoria")}
        self.categories = sorted(list(cats))
        logger.info("Catálogo inicializado con %d productos y %d categorías", len(self.catalog), len(self.categories))

    def _enrich_from_csv(self, csv_path: Path):
        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_id = row.get("id", "").strip()
                    nombre = row.get("nombre", "").strip()
                    if not raw_id or not nombre:
                        continue

                    cat = self._normalize_cat(row.get("categoria", ""))
                    price = self._parse_price(row.get("precio_eur"), row.get("iva_incluido"))

                    # Buscar si ya existe por id_origen o nombre similar
                    matched_sku = None
                    for sku, p in self.catalog.items():
                        if raw_id in p.get("ids_origen", []):
                            matched_sku = sku
                            break
                        if p.get("nombre", "").lower() == nombre.lower():
                            matched_sku = sku
                            break

                    if matched_sku:
                        prod = self.catalog[matched_sku]
                        if raw_id not in prod["ids_origen"]:
                            prod["ids_origen"].append(raw_id)
                        if (not prod.get("precio") or prod["precio"] <= 0) and price:
                            prod["precio"] = price
                    else:
                        sku = self._slugify(nombre)
                        if sku in self.catalog:
                            sku = f"{sku}-{raw_id.lower().replace('-', '')}"

                        ancho, plazas = self._parse_dimensions_and_plazas(nombre, row.get("medidas", ""))
                        product = {
                            "sku": sku,
                            "ids_origen": [raw_id],
                            "nombre": nombre.title(),
                            "categoria": cat,
                            "precio": price if price else 79.00,
                            "plazas": plazas,
                            "ancho_cm": ancho,
                            "color": (row.get("color") or "varios").strip().lower(),
                            "material": (row.get("material") or "madera y otros").strip().lower(),
                        }
                        self.catalog[sku] = product
        except Exception as e:
            logger.error("Error al procesar CSV %s: %s", csv_path, e)

    @staticmethod
    def _normalize_cat(cat: str) -> str:
        c = cat.strip().lower()
        if "sofa" in c or "sillon" in c:
            return "sofa"
        if "lamp" in c or "iluminaci" in c or "lighting" in c or "flexo" in c:
            return "iluminacion"
        if any(w in c for w in ["textil", "textile", "almohad", "cojin", "sabana", "manta", "alfombra"]):
            return "textil"
        if any(w in c for w in ["accesori", "accessory", "soporte", "espejo", "reposapies"]):
            return "accesorio"
        if "mesa" in c or "table" in c:
            return "mesa"
        if "silla" in c or "chair" in c:
            return "silla"
        if "cama" in c or "bed" in c or "dormitorio" in c:
            return "cama"
        if "colchon" in c or "descanso" in c or "mattress" in c:
            return "descanso"
        if "despacho" in c or "desk" in c or "escritorio" in c:
            return "escritorio"
        if any(w in c for w in ["almacen", "storage", "armario", "estanter", "cajon"]):
            return "almacenaje"
        return "otros"

    @staticmethod
    def _parse_price(raw_price: Optional[str], raw_iva: Optional[str]) -> Optional[float]:
        if not raw_price:
            return None
        try:
            val = float(str(raw_price).strip().replace(",", "."))
            iva_inc = str(raw_iva).strip().lower() in ("true", "1", "yes", "si")
            if not iva_inc and val > 0:
                val = round(val * 1.21, 2)
            return round(val, 2)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_dimensions_and_plazas(nombre: str, medidas: str):
        plazas = 0
        n_low = nombre.lower()
        p_match = re.search(r"(\d+)\s*plaza", n_low)
        if p_match:
            plazas = int(p_match.group(1))
        elif "tres plazas" in n_low:
            plazas = 3
        elif "dos plazas" in n_low:
            plazas = 2

        ancho = 0
        if medidas:
            cm_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*cm", medidas, re.I)
            if cm_match:
                ancho = int(float(cm_match.group(1)))
            else:
                mm_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*(?:x|\*)\s*(\d+(?:\.\d+)?)\s*mm", medidas, re.I)
                if mm_match:
                    ancho = int(float(mm_match.group(1)) / 10)
                else:
                    m_match = re.search(r"(\d+[\.,]\d+)\s*(?:x|\*)\s*(\d+[\.,]\d+)\s*(?:x|\*)\s*(\d+[\.,]\d+)\s*m", medidas, re.I)
                    if m_match:
                        ancho = int(float(m_match.group(1).replace(",", ".")) * 100)
        return (ancho or 80, plazas)

    @staticmethod
    def _slugify(text: str) -> str:
        text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
        text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
        return re.sub(r"[-\s]+", "-", text)


store = InMemoryStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load_catalog()
    yield


app = FastAPI(title="Muebles Cloud SSR", lifespan=lifespan)

# Montar estáticos y plantillas Jinja2
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "script-src 'none'; "
            "frame-ancestors 'none';"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


def get_session_id(request: Request) -> str:
    session_id = request.cookies.get("cart_session_id")
    if not session_id or len(session_id) < 16 or not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
        session_id = str(uuid.uuid4())
    return session_id


def generate_csrf_token(session_id: str) -> str:
    return hmac.new(SECRET_KEY.encode(), session_id.encode(), "sha256").hexdigest()[:24]


def verify_csrf(session_id: str, token: Optional[str]) -> bool:
    if not token:
        return False
    expected = generate_csrf_token(session_id)
    return hmac.compare_digest(expected, token)


async def get_cart_count(session_id: str) -> int:
    async with store._lock:
        cart = store.carts.get(session_id, {})
        return sum(cart.values())


async def get_cart_details(session_id: str):
    async with store._lock:
        cart = store.carts.get(session_id, {})
        items = []
        total = 0.0
        for sku, qty in cart.items():
            if sku in store.catalog:
                prod = store.catalog[sku]
                subtotal = round(prod["precio"] * qty, 2)
                total += subtotal
                items.append({
                    "producto": prod,
                    "cantidad": qty,
                    "subtotal": subtotal,
                })
        return items, round(total, 2)


# -------------------------------------------------------------
# RUTAS SSR (Jinja2)
# -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, categoria: Optional[str] = None, q: Optional[str] = None):
    session_id = get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    cart_count = await get_cart_count(session_id)

    prods = list(store.catalog.values())

    cat_activa = categoria.strip().lower() if categoria else None
    if cat_activa:
        prods = [p for p in prods if p.get("categoria", "").lower() == cat_activa]

    query = q.strip() if q else ""
    if query:
        q_low = query.lower()
        prods = [
            p for p in prods
            if q_low in p.get("nombre", "").lower()
            or q_low in p.get("material", "").lower()
            or q_low in p.get("color", "").lower()
            or q_low in p.get("categoria", "").lower()
        ]

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "productos": prods,
            "categorias": store.categories,
            "categoria_activa": cat_activa,
            "query": query,
            "cart_count": cart_count,
            "csrf_token": csrf_token,
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


@app.get("/producto/{sku}", response_class=HTMLResponse)
async def detalle_producto(request: Request, sku: str):
    session_id = get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    cart_count = await get_cart_count(session_id)

    prod = store.catalog.get(sku)
    if not prod:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    response = templates.TemplateResponse(
        request=request,
        name="producto.html",
        context={
            "producto": prod,
            "cart_count": cart_count,
            "csrf_token": csrf_token,
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


@app.get("/carrito", response_class=HTMLResponse)
async def ver_carrito(request: Request):
    session_id = get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    items, total = await get_cart_details(session_id)
    cart_count = sum(item["cantidad"] for item in items)

    response = templates.TemplateResponse(
        request=request,
        name="carrito.html",
        context={
            "items": items,
            "total": total,
            "cart_count": cart_count,
            "csrf_token": csrf_token,
            "pedido_confirmado": None,
            "error": None,
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


@app.post("/carrito/agregar")
async def agregar_carrito(
    request: Request,
    sku: str = Form(...),
    csrf_token: str = Form(""),
):
    session_id = get_session_id(request)
    if not verify_csrf(session_id, csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    if sku in store.catalog:
        async with store._lock:
            if session_id not in store.carts:
                store.carts[session_id] = {}
            store.carts[session_id][sku] = store.carts[session_id].get(sku, 0) + 1

    resp = RedirectResponse(url="/carrito", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/carrito/eliminar")
async def eliminar_carrito(
    request: Request,
    sku: str = Form(...),
    csrf_token: str = Form(""),
):
    session_id = get_session_id(request)
    if not verify_csrf(session_id, csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    async with store._lock:
        if session_id in store.carts and sku in store.carts[session_id]:
            del store.carts[session_id][sku]

    resp = RedirectResponse(url="/carrito", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/carrito/vaciar")
async def vaciar_carrito(
    request: Request,
    csrf_token: str = Form(""),
):
    session_id = get_session_id(request)
    if not verify_csrf(session_id, csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    async with store._lock:
        store.carts[session_id] = {}

    resp = RedirectResponse(url="/carrito", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return resp


@app.post("/checkout", response_class=HTMLResponse)
async def checkout(
    request: Request,
    nombre: str = Form(...),
    ciudad: str = Form(...),
    csrf_token: str = Form(""),
):
    session_id = get_session_id(request)
    if not verify_csrf(session_id, csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    items, total = await get_cart_details(session_id)
    if not items:
        response = templates.TemplateResponse(
            request=request,
            name="carrito.html",
            context={
                "items": [],
                "total": 0.0,
                "cart_count": 0,
                "csrf_token": generate_csrf_token(session_id),
                "pedido_confirmado": None,
                "error": "El carrito está vacío. Agrega muebles antes de finalizar el pedido.",
            },
        )
        return response

    order_id = f"PED-{uuid.uuid4().hex[:8].upper()}"
    order_data = {
        "id": order_id,
        "cliente": nombre.strip()[:80],
        "ciudad": ciudad.strip()[:80],
        "items": items,
        "total": total,
    }

    async with store._lock:
        store.orders[order_id] = order_data
        store.carts[session_id] = {}

    response = templates.TemplateResponse(
        request=request,
        name="carrito.html",
        context={
            "items": [],
            "total": 0.0,
            "cart_count": 0,
            "csrf_token": generate_csrf_token(session_id),
            "pedido_confirmado": order_data,
            "error": None,
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


@app.get("/asistente", response_class=HTMLResponse)
async def asistente_get(request: Request):
    session_id = get_session_id(request)
    csrf_token = generate_csrf_token(session_id)
    cart_count = await get_cart_count(session_id)

    response = templates.TemplateResponse(
        request=request,
        name="asistente.html",
        context={
            "pregunta": "",
            "respuesta": None,
            "origen_respuesta": None,
            "error": None,
            "cart_count": cart_count,
            "csrf_token": csrf_token,
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


@app.post("/asistente", response_class=HTMLResponse)
async def asistente_post(
    request: Request,
    pregunta: str = Form(...),
    csrf_token: str = Form(""),
):
    session_id = get_session_id(request)
    if not verify_csrf(session_id, csrf_token):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    cart_count = await get_cart_count(session_id)
    clean_q = pregunta.strip()[:300]

    respuesta, origen = await responder_asistente(clean_q)

    response = templates.TemplateResponse(
        request=request,
        name="asistente.html",
        context={
            "pregunta": clean_q,
            "respuesta": respuesta,
            "origen_respuesta": origen,
            "error": None,
            "cart_count": cart_count,
            "csrf_token": generate_csrf_token(session_id),
        },
    )
    response.set_cookie("cart_session_id", session_id, httponly=True, samesite="lax", max_age=86400)
    return response


async def responder_asistente(pregunta: str) -> tuple[str, str]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key and api_key != "TU_API_KEY" and GENAI_AVAILABLE:
        try:
            client = genai.Client(api_key=api_key)
            catalog_summary = "\n".join([
                f"- SKU: {p['sku']}, Nombre: {p['nombre']}, Categoría: {p['categoria']}, Precio: {p['precio']}€, Material: {p['material']}, Color: {p['color']}"
                for p in list(store.catalog.values())[:25]
            ])
            sys_instruction = (
                "Eres un arquitecto de interiores y asesor experto de 'Muebles Cloud'. "
                "Tu objetivo es dar una recomendación cálida, práctica y concisa (máximo 3-4 párrafos o viñetas) "
                "proponiendo piezas específicas del catálogo y argumentando por qué combinan estética y ergonómicamente."
            )
            user_prompt = f"Catálogo disponible:\n{catalog_summary}\n\nPregunta del cliente: {pregunta}"

            def _call_gemini():
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[sys_instruction, user_prompt],
                )

            res = await asyncio.to_thread(_call_gemini)
            if res and res.text:
                return res.text.strip(), "Gemini 2.5 Flash"
        except Exception as e:
            logger.warning("Fallo en llamada a Gemini (%s), pasando a heurística local", e)

    # Heurística local ultra rápida (garantizada <10ms sin dependencias externas)
    q_low = pregunta.lower()
    matches = []
    for prod in store.catalog.values():
        score = 0
        cat = prod["categoria"].lower()
        if cat in q_low:
            score += 4
        if prod["nombre"].lower() in q_low:
            score += 5
        if prod["color"].lower() in q_low:
            score += 2
        if prod["material"].lower() in q_low:
            score += 2
        for w in q_low.split():
            if len(w) > 3 and w in prod["nombre"].lower():
                score += 1
        if score > 0:
            matches.append((score, prod))

    matches.sort(key=lambda x: x[0], reverse=True)
    if matches:
        destacados = [p for _, p in matches[:3]]
        bullets = " ".join([f"• {p['nombre']} ({p['precio']}€, en {p['material']} {p['color']})." for p in destacados])
        resp = f"Para lo que buscas, las piezas que mejor encajan con tu espacio y estilo son: {bullets} Te aportarán calidez, ergonomía y elegancia contemporánea."
    else:
        sample = list(store.catalog.values())[:3]
        bullets = " ".join([f"• {p['nombre']} ({p['precio']}€)." for p in sample])
        resp = f"Para crear un ambiente acogedor y moderno, te recomendamos nuestras piezas destacadas: {bullets} Su diseño atemporal encaja a la perfección en cualquier estancia."

    return resp, "Motor Asesor Heurístico Local"


# -------------------------------------------------------------
# RUTAS API / HEALTH (Contrato y compatibilidad QA)
# -------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "products_count": len(store.catalog),
        "categories_count": len(store.categories),
    }


@app.get("/api/v1/furniture")
async def api_get_furniture(category: Optional[str] = None):
    items = []
    for p in store.catalog.values():
        if category and p.get("categoria") != category:
            continue
        items.append({
            "id": p["sku"],
            "name": p["nombre"],
            "category": p["categoria"],
            "price_eur": p["precio"],
            "stock": 15,
            "material": p["material"],
            "color": p["color"],
        })
    return {"items": items}


@app.post("/api/v1/orders", status_code=status.HTTP_201_CREATED)
async def api_create_order(payload: Dict[str, Any]):
    items = payload.get("items")
    payment_token = payload.get("payment_token")
    shipping_city = payload.get("shipping_city")

    if not items or not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items debe ser una lista no vacía")
    if not payment_token or not isinstance(payment_token, str):
        raise HTTPException(status_code=400, detail="payment_token es obligatorio")
    if not shipping_city or not isinstance(shipping_city, str):
        raise HTTPException(status_code=400, detail="shipping_city es obligatorio")

    order_id = f"API-{uuid.uuid4().hex[:8].upper()}"
    async with store._lock:
        store.orders[order_id] = {
            "id": order_id,
            "items": items,
            "payment_token": payment_token,
            "shipping_city": shipping_city,
        }

    return {
        "order_id": order_id,
        "status": "confirmed",
        "shipping_city": shipping_city,
        "items": items,
    }

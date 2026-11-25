const cart = new Map();

function updateCartCount() {
  let total = 0;
  for (const qty of cart.values()) total += qty;
  document.getElementById("cart-count").textContent = String(total);
}

async function loadCatalog(category = "") {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  const resp = await fetch(`/api/v1/furniture${query}`);
  const data = await resp.json();
  const container = document.getElementById("catalog");
  container.replaceChildren();

  for (const item of data.items || []) {
    const card = document.createElement("article");
    card.className = "card";

    const title = document.createElement("h3");
    title.textContent = item.name;

    const meta = document.createElement("p");
    meta.textContent = `${item.material} · Stock: ${item.stock}`;

    const price = document.createElement("p");
    price.textContent = `${item.price_eur} EUR`;

    const btn = document.createElement("button");
    btn.textContent = "Anadir al carrito";
    btn.disabled = item.stock < 1;
    btn.addEventListener("click", () => {
      cart.set(item.id, (cart.get(item.id) || 0) + 1);
      updateCartCount();
    });

    card.append(title, meta, price, btn);
    container.appendChild(card);
  }
}

document.querySelectorAll("[data-category]").forEach((btn) => {
  btn.addEventListener("click", () => loadCatalog(btn.dataset.category || ""));
});

document.getElementById("buy-btn").addEventListener("click", async () => {
  const statusEl = document.getElementById("status");
  if (cart.size === 0) {
    statusEl.textContent = "Anade al menos un mueble al carrito.";
    return;
  }
  const items = Array.from(cart.entries()).map(([furniture_id, quantity]) => ({
    furniture_id,
    quantity,
  }));
  const shipping_city = document.getElementById("city").value;

  const resp = await fetch("/api/v1/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items,
      payment_token: "tok_demo_stripe_987654",
      shipping_city,
    }),
  });
  const result = await resp.json();
  if (resp.ok) {
    cart.clear();
    updateCartCount();
    statusEl.textContent = `Pedido ${result.order_id} confirmado (${result.total_eur} EUR).`;
    await loadCatalog();
  } else {
    statusEl.textContent = `Error: ${result.error || "No se pudo completar"}`;
  }
});

loadCatalog();

"""
Frequently Bought Together API Server

Reads recommendations directly from product_recommendations.csv so changes in
the sheet are reflected automatically.

Call /api/fbt?products=id1,id2 to get recommended accessories for cart items.
"""

import csv
import io
import json
import os
import threading
import time
from urllib.parse import quote
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template_string, redirect
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)  # Allow frontend from any origin
DATA_DIR = Path(__file__).parent
CSV_PATH = Path(os.environ.get("RECOMMENDATIONS_CSV", str(DATA_DIR / "product_recommendations.csv")))
CSV_URL = (os.environ.get("RECOMMENDATIONS_CSV_URL") or "").strip()
CSV_REFRESH_SECONDS = int(os.environ.get("RECOMMENDATIONS_CSV_REFRESH_SECONDS", "30"))
CSV_TIMEOUT_SECONDS = float(os.environ.get("RECOMMENDATIONS_CSV_TIMEOUT_SECONDS", "8"))
STOREFRONT_BASE_URL = (os.environ.get("STOREFRONT_BASE_URL") or "").strip().rstrip("/")
STOREFRONT_PRODUCT_PATH_PATTERN = (os.environ.get("STOREFRONT_PRODUCT_PATH_PATTERN") or "/products/{slug}/").strip()

BC_ACCESS_TOKEN = (os.environ.get("BC_ACCESS_TOKEN") or "").strip()
BC_API_PATH = (os.environ.get("BC_API_PATH") or "").strip().rstrip("/")
BC_STORE_HASH = (os.environ.get("BC_STORE_HASH") or "").strip()
BC_API_BASE = (os.environ.get("BC_API_BASE") or "https://api.bigcommerce.com").strip().rstrip("/")
CATALOG_REFRESH_SECONDS = int(os.environ.get("CATALOG_REFRESH_SECONDS", "1800"))

_RULES_LOCK = threading.Lock()
_RULES_CACHE = {
    "explicit_map": {},
    "category_rules": [],
    "fetched_at": 0.0,
    "source": "local",
    "last_error": None,
}
_CATALOG_CACHE = {
    "slug_map": {},
    "fetched_at": 0.0,
    "source": "none",
    "last_error": None,
}


def _get_bc_api_base_path():
    if BC_API_PATH:
        return BC_API_PATH
    if BC_STORE_HASH:
        return f"{BC_API_BASE}/stores/{BC_STORE_HASH}/v3"
    return ""


def _fetch_bigcommerce_catalog_map():
    base_path = _get_bc_api_base_path()
    if not (base_path and BC_ACCESS_TOKEN):
        return {}

    session = requests.Session()
    session.headers.update({
        "X-Auth-Token": BC_ACCESS_TOKEN,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    out = {}
    page = 1
    while True:
        resp = session.get(
            f"{base_path}/catalog/products",
            params={"page": page, "limit": 250, "include": "primary_image", "is_visible": True},
            timeout=CSV_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data", [])
        for row in rows:
            custom_url = (row.get("custom_url") or {}).get("url") or ""
            slug = custom_url.strip("/")
            if not slug:
                continue
            out[slug] = {
                "id": row.get("id"),
                "name": row.get("name") or slug,
                "url": custom_url,
                "price": row.get("price"),
                "image": ((row.get("primary_image") or {}).get("url_standard") or ""),
            }
        meta = payload.get("meta", {}).get("pagination", {})
        total_pages = meta.get("total_pages", page)
        if page >= total_pages:
            break
        page += 1
    return out


def _get_catalog_map(force_refresh: bool = False):
    now = time.time()
    with _RULES_LOCK:
        has_cache = bool(_CATALOG_CACHE["slug_map"])
        is_fresh = (now - _CATALOG_CACHE["fetched_at"]) < CATALOG_REFRESH_SECONDS
        if not force_refresh and has_cache and is_fresh:
            return _CATALOG_CACHE["slug_map"]

    try:
        catalog_map = _fetch_bigcommerce_catalog_map()
        with _RULES_LOCK:
            if catalog_map:
                _CATALOG_CACHE["slug_map"] = catalog_map
                _CATALOG_CACHE["fetched_at"] = now
                _CATALOG_CACHE["source"] = "bigcommerce"
                _CATALOG_CACHE["last_error"] = None
        return _CATALOG_CACHE["slug_map"]
    except Exception as exc:
        with _RULES_LOCK:
            _CATALOG_CACHE["last_error"] = str(exc)
        return _CATALOG_CACHE["slug_map"]


def _build_storefront_url(slug: str) -> str:
    encoded_slug = quote(slug, safe="")
    path = STOREFRONT_PRODUCT_PATH_PATTERN.replace("{slug}", encoded_slug)
    if not path.startswith("/"):
        path = f"/{path}"
    if STOREFRONT_BASE_URL:
        return f"{STOREFRONT_BASE_URL}{path}"
    return path


def _parse_category_keywords(raw_value: str) -> list:
    """
    Parse values like:
      [helmet | visor | shield] (any product)
    into:
      ["helmet", "visor", "shield"]
    """
    text = (raw_value or "").strip()
    if text.startswith("[") and "]" in text:
        inside = text[1:text.index("]")]
        return [part.strip().lower() for part in inside.split("|") if part.strip()]
    return []


def _build_rules_from_reader(reader):
    explicit_map = {}
    category_rules = {}
    for row in reader:
        product_id = (row.get("Product ID") or "").strip()
        rec_id = (row.get("Recommended Product ID") or "").strip()
        label = (row.get("Label") or "").strip()
        row_type = (row.get("Type") or "Explicit").strip().lower()

        if not product_id or not rec_id:
            continue

        priority = (row.get("Priority") or "").strip()
        rec = {"id": rec_id, "label": label, "priority": priority}
        if row_type == "category":
            keywords = tuple(_parse_category_keywords(product_id))
            if not keywords:
                continue
            category_rules.setdefault(keywords, []).append(rec)
        else:
            explicit_map.setdefault(product_id, []).append(rec)

    category_rule_list = [(list(keywords), recs) for keywords, recs in category_rules.items()]
    return explicit_map, category_rule_list


def _load_rules_from_local_csv():
    if not CSV_PATH.exists():
        return {}, []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        return _build_rules_from_reader(csv.DictReader(f))


def _fetch_rules_from_remote_csv():
    response = requests.get(CSV_URL, timeout=CSV_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.text
    return _build_rules_from_reader(csv.DictReader(io.StringIO(payload)))


def _load_rules_from_csv(force_refresh: bool = False):
    """
    Returns:
      explicit_map: {product_id: [{"id": "...", "label": "..."}]}
      category_rules: [(["keyword1", ...], [{"id": "...", "label": "..."}]), ...]
    """
    # Local-only mode: read local CSV every request (existing behavior).
    if not CSV_URL:
        explicit_map, category_rules = _load_rules_from_local_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["fetched_at"] = time.time()
            _RULES_CACHE["source"] = "local"
            _RULES_CACHE["last_error"] = None
        return explicit_map, category_rules

    now = time.time()
    with _RULES_LOCK:
        is_fresh = (now - _RULES_CACHE["fetched_at"]) < CSV_REFRESH_SECONDS
        has_cache = bool(_RULES_CACHE["explicit_map"] or _RULES_CACHE["category_rules"])
        if not force_refresh and is_fresh and has_cache:
            return _RULES_CACHE["explicit_map"], _RULES_CACHE["category_rules"]

    # Remote mode: refresh from URL with stale-cache fallback.
    try:
        explicit_map, category_rules = _fetch_rules_from_remote_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["fetched_at"] = now
            _RULES_CACHE["source"] = "remote"
            _RULES_CACHE["last_error"] = None
        return explicit_map, category_rules
    except Exception as exc:
        with _RULES_LOCK:
            _RULES_CACHE["last_error"] = str(exc)
            if _RULES_CACHE["explicit_map"] or _RULES_CACHE["category_rules"]:
                return _RULES_CACHE["explicit_map"], _RULES_CACHE["category_rules"]

        # No remote cache yet; fall back to local file if present.
        explicit_map, category_rules = _load_rules_from_local_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["fetched_at"] = time.time()
            _RULES_CACHE["source"] = "local-fallback"
        return explicit_map, category_rules


def get_recommendations(product_id: str, explicit_map: dict, category_rules: list) -> list:
    # 1) Exact product match from CSV
    if product_id in explicit_map:
        return explicit_map[product_id]

    # 2) Category fallback rows from CSV
    pid_lower = product_id.lower()
    for keywords, recs in category_rules:
        if any(kw in pid_lower for kw in keywords):
            return recs

    # 3) No match
    return []


def get_recommendations_debug(product_id: str, explicit_map: dict, category_rules: list) -> dict:
    """Return recommendations plus match metadata for debugging."""
    if product_id in explicit_map:
        return {
            "match_type": "explicit",
            "matched_rule": product_id,
            "recommendations": explicit_map[product_id],
        }

    pid_lower = product_id.lower()
    for keywords, recs in category_rules:
        if any(kw in pid_lower for kw in keywords):
            return {
                "match_type": "category",
                "matched_rule": keywords,
                "recommendations": recs,
            }

    return {
        "match_type": "none",
        "matched_rule": None,
        "recommendations": [],
    }


@app.route("/api/health")
def health():
    with _RULES_LOCK:
        return jsonify(
            {
                "status": "ok",
                "csv_path": str(CSV_PATH),
                "csv_url": CSV_URL or None,
                "active_source": _RULES_CACHE.get("source"),
                "last_refresh_epoch": _RULES_CACHE.get("fetched_at"),
                "refresh_seconds": CSV_REFRESH_SECONDS,
                "last_error": _RULES_CACHE.get("last_error"),
                "catalog_source": _CATALOG_CACHE.get("source"),
                "catalog_last_error": _CATALOG_CACHE.get("last_error"),
            }
        )


@app.route("/api/reload", methods=["POST"])
def reload_rules():
    """
    Reload/validate CSV rules.
    Since rules are read on each request, this endpoint validates and reports counts.
    """
    explicit_map, category_rules = _load_rules_from_csv(force_refresh=True)
    explicit_rows = sum(len(v) for v in explicit_map.values())
    category_rows = sum(len(v) for _, v in category_rules)
    return jsonify({
        "status": "ok",
        "csv_path": str(CSV_PATH),
        "csv_url": CSV_URL or None,
        "explicit_products": len(explicit_map),
        "explicit_rows": explicit_rows,
        "category_rules": len(category_rules),
        "category_rows": category_rows,
    })


@app.route("/api/catalog")
def get_catalog():
    """
    GET /api/catalog?ids=id1,id2
    Returns basic catalog metadata (name/url/image/price) for recommendation slugs.
    """
    ids_param = request.args.get("ids", "")
    ids = [p.strip() for p in ids_param.split(",") if p.strip()]
    if not ids:
        return jsonify({"items": {}})

    catalog_map = _get_catalog_map()
    items = {}
    for slug in ids:
        row = dict(catalog_map.get(slug, {}))
        if not row:
            row = {"name": slug}
        if not row.get("url"):
            row["url"] = _build_storefront_url(slug)
        elif row.get("url", "").startswith("/") and STOREFRONT_BASE_URL:
            row["url"] = f"{STOREFRONT_BASE_URL}{row['url']}"
        items[slug] = row
    return jsonify({"items": items})


@app.route("/api/debug/product")
def debug_product():
    """
    Debug how a single product resolves.
    GET /api/debug/product?id=product-slug
    """
    product_id = (request.args.get("id") or "").strip()
    if not product_id:
        return jsonify({"error": "Missing required query param: id"}), 400

    explicit_map, category_rules = _load_rules_from_csv()
    result = get_recommendations_debug(product_id, explicit_map, category_rules)
    return jsonify({
        "product_id": product_id,
        "match_type": result["match_type"],
        "matched_rule": result["matched_rule"],
        "recommendations": result["recommendations"],
    })


@app.route("/widget/fbt-widget.js")
def serve_widget_js():
    """Serve embeddable widget JavaScript from this service."""
    return send_from_directory(DATA_DIR / "widget", "fbt-widget.js")


@app.route("/")
def root():
    return redirect("/simulate", code=302)


@app.route("/simulate")
def simulate():
    """Clickable storefront simulation page."""
    sample_catalog = {
        "agv-pista-gp-rr-mono-carbon-helmet": {"name": "AGV Pista GP RR Mono Carbon Helmet", "price": 1679.99},
        "klim-badlands-pro-jacket": {"name": "Klim Badlands Pro Jacket", "price": 1199.99},
        "motorex-gear-oil-10w30": {"name": "Motorex Gear Oil 10W30", "price": 20.99},
        "twin-air-air-filter-for-2024-kawasaki-kx450": {"name": "Twin Air Filter 2024 KX450", "price": 38.95},
        "sena-30k-hd-communication-system-single-unit": {"name": "Sena 30K HD Communication", "price": 299.00},
        "kriega-r20-backpack": {"name": "Kriega R20 Backpack", "price": 179.99},
        "dunlop-sportmax-q5-sportbike-tires": {"name": "Dunlop Sportmax Q5 Tires", "price": 354.99},
        "ebc-fa103-brake-pad": {"name": "EBC FA103 Brake Pad", "price": 40.95},
        "ogio-head-case-helmet-bag": {"name": "OGIO Head Case Helmet Bag", "price": 89.99},
        "pinlock-earplug-set-w-case": {"name": "Pinlock Earplug Set", "price": 24.99},
    }
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Performance Cycle - Recommendation Simulator</title>
    <style>
      body { font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #f7f7f7; }
      .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
      .panel { background: #fff; border: 1px solid #e5e5e5; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
      .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; background: #fff; }
      .card h4 { margin: 0 0 8px; font-size: 15px; }
      .row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
      button { background: #111; color: #fff; border: none; padding: 8px 10px; border-radius: 6px; cursor: pointer; }
      button.secondary { background: #6b7280; }
      .muted { color: #555; font-size: 14px; }
      .pill { display: inline-block; background: #e5e7eb; border-radius: 999px; padding: 4px 8px; margin: 3px; font-size: 12px; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h2>Performance Cycle Recommendation Simulator</h2>
      <p class="muted">Simulates how recommendations appear on the cart page.</p>
      <div class="panel">
        <h3>Catalog (click to add to cart)</h3>
        <div class="grid" id="catalog"></div>
      </div>
      <div class="panel">
        <div class="row">
          <h3 style="margin:0;">Cart</h3>
          <button class="secondary" id="clear-cart">Clear Cart</button>
        </div>
        <div id="cart-pills"></div>
      </div>
      <div class="panel"><div id="fbt-widget"></div></div>
    </div>
    <script>window.__CATALOG__ = {{ catalog | safe }};</script>
    <script src="/widget/fbt-widget.js"></script>
    <script>
      const catalog = window.__CATALOG__;
      let cartIds = [];
      function renderCatalog() {
        const el = document.getElementById('catalog');
        el.innerHTML = Object.entries(catalog).map(([id, p]) => `
          <div class="card">
            <h4>${p.name}</h4>
            <div class="row"><span>$${Number(p.price || 0).toFixed(2)}</span><button data-id="${id}">Add</button></div>
            <div class="muted" style="margin-top:6px;">${id}</div>
          </div>`).join('');
        el.querySelectorAll('button[data-id]').forEach(btn => btn.addEventListener('click', () => addToCart(btn.dataset.id)));
      }
      function renderCart() {
        const cart = document.getElementById('cart-pills');
        cart.innerHTML = cartIds.length
          ? cartIds.map(id => `<span class="pill">${catalog[id]?.name || id}</span>`).join('')
          : '<span class="muted">Cart is empty</span>';
      }
      function addToCart(id) {
        if (!cartIds.includes(id)) cartIds.push(id);
        renderCart();
        FBTWidget.refresh(cartIds);
      }
      document.getElementById('clear-cart').addEventListener('click', () => {
        cartIds = [];
        renderCart();
        FBTWidget.refresh(cartIds);
      });
      renderCatalog();
      renderCart();
      FBTWidget.init({
        apiUrl: window.location.origin,
        cartProductIds: cartIds,
        productCatalog: catalog,
        containerId: 'fbt-widget',
        title: 'Frequently Bought Together',
        onAddToCart: addToCart
      });
    </script>
  </body>
</html>
"""
    return render_template_string(html, catalog=json.dumps(sample_catalog))


@app.route("/api/fbt")
def get_frequently_bought_together():
    """
    GET /api/fbt?products=product1,product2,product3

    Returns recommended accessories for the given cart product IDs.
    """
    products_param = request.args.get("products", "")
    cart_product_ids = [p.strip() for p in products_param.split(",") if p.strip()]

    if not cart_product_ids:
        return jsonify({"recommendations": [], "message": "No products in cart"})

    explicit_map, category_rules = _load_rules_from_csv()
    priority_rank = {"Primary": 0, "Secondary": 1, "Tertiary": 2}
    rec_info = {}  # id -> {count, label, priority}
    for cart_id in cart_product_ids:
        related_list = get_recommendations(cart_id, explicit_map, category_rules)
        for item in related_list:
            r = item if isinstance(item, dict) else {"id": item, "label": ""}
            rid = r.get("id", r) if isinstance(r, dict) else r
            if rid not in cart_product_ids:
                if rid not in rec_info:
                    rec_info[rid] = {
                        "count": 0,
                        "label": r.get("label", "") if isinstance(r, dict) else "",
                        "priority": r.get("priority", "") if isinstance(r, dict) else "",
                    }
                rec_info[rid]["count"] += 1
                if r.get("label") and not rec_info[rid]["label"]:
                    rec_info[rid]["label"] = r.get("label", "")
                # Keep the best (highest) priority if multiple cart items suggest same recommendation
                current = rec_info[rid].get("priority", "")
                incoming = r.get("priority", "") if isinstance(r, dict) else ""
                if incoming and (
                    not current
                    or priority_rank.get(incoming, 99) < priority_rank.get(current, 99)
                ):
                    rec_info[rid]["priority"] = incoming

    recommendations = [
        {"id": rid, "label": info["label"] or None, "priority": info.get("priority") or None}
        for rid, info in sorted(
            rec_info.items(),
            key=lambda x: (-x[1]["count"], priority_rank.get(x[1].get("priority", ""), 99)),
        )
    ]

    return jsonify({
        "recommendations": recommendations,
        "cart_products": cart_product_ids,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

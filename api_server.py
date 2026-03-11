"""
Frequently Bought Together API Server

Reads recommendations directly from product_recommendations.csv so changes in
the sheet are reflected automatically.

Call /api/fbt?products=id1,id2 to get recommended accessories for cart items.
"""

import csv
import io
import json
import math
import os
import threading
import time
from collections import defaultdict
from urllib.parse import quote
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template_string, redirect
from flask_cors import CORS
import requests
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=True)

app = Flask(__name__)
CORS(app)  # Allow frontend from any origin
DATA_DIR = Path(__file__).parent
CSV_PATH = Path(os.environ.get("RECOMMENDATIONS_CSV", str(DATA_DIR / "product_recommendations.csv")))
CSV_URL = (os.environ.get("RECOMMENDATIONS_CSV_URL") or "").strip()
CSV_REFRESH_SECONDS = int(os.environ.get("RECOMMENDATIONS_CSV_REFRESH_SECONDS", "30"))
CSV_TIMEOUT_SECONDS = float(os.environ.get("RECOMMENDATIONS_CSV_TIMEOUT_SECONDS", "8"))
STOREFRONT_BASE_URL = (os.environ.get("STOREFRONT_BASE_URL") or "").strip().rstrip("/")
STOREFRONT_PRODUCT_PATH_PATTERN = (os.environ.get("STOREFRONT_PRODUCT_PATH_PATTERN") or "/{slug}/").strip()

BC_ACCESS_TOKEN = (os.environ.get("BC_ACCESS_TOKEN") or "").strip()
BC_API_PATH = (os.environ.get("BC_API_PATH") or "").strip().rstrip("/")
BC_STORE_HASH = (os.environ.get("BC_STORE_HASH") or "").strip()
BC_API_BASE = (os.environ.get("BC_API_BASE") or "https://api.bigcommerce.com").strip().rstrip("/")
CATALOG_REFRESH_SECONDS = int(os.environ.get("CATALOG_REFRESH_SECONDS", "1800"))

_RULES_LOCK = threading.Lock()
_RULES_CACHE = {
    "explicit_map": {},
    "category_rules": [],
    "rec_tier_map": {},
    "source_tier_map": {},
    "source_estimated_price_map": {},
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
PRIORITY_RANK = {"Primary": 0, "Secondary": 1, "Tertiary": 2}
PER_PRODUCT_RECOMMENDATION_LIMIT = 3

# Keep this lightweight/type-focused for runtime filtering.
PRODUCT_TYPE_RULES = [
    ("care", ["helmet-care", "helmet care", "windshield-clean", "windshield clean", "visor-clean", "visor clean", "helmet-clean", "helmet clean"]),
    ("helmet_accessory", ["visor", "face-shield", "faceshield", "shield", "pinlock", "cheekpad", "cheek-pad", "cheek pad", "chin curtain", "curtain", "audio-kit", "audio kit", "helmet-kit", "helmet kit"]),
    ("helmet", ["helmet"]),
    ("tshirt", ["t-shirt"]),
    ("hat", ["hat", "snapback", "beanie"]),
    ("jersey", ["jersey", "motocross-shirt", "mx-shirt"]),
    ("jacket", ["jacket", "coat", "parka", "suit", "race-suit", "gp-tech"]),
    ("pants", ["pant", "trouser", "bibs"]),
    ("gloves", ["glove", "gauntlet"]),
    ("boots", ["boot"]),
    ("hydration", ["hydration", "hydradri", "hydralite", "reservoir", "water-pack", "water pack", "bladder"]),
    ("luggage", ["tail-bag", "tail bag", "tank-bag", "tank bag", "drypack", "duffel", "fender-bag", "fender pack", "tool-pack", "tool pack", "toolbag", "fanny", "waist pack", "hip pack", "sling"]),
    ("backpack", ["backpack", "luggage", "airbag"]),
    ("communication", ["communication", "intercom", "bluetooth", "headset", "sena", "cardo", "boss audio"]),
    ("protection", ["protector", "armor", "armour", "chest", "back protector"]),
    ("air_filter", ["air-filter", "air filter", "filter"]),
    ("oil", ["oil", "lubricant", "lube", "fork-oil", "transmission-oil"]),
    ("tire", ["tire", "tyre", "wheel"]),
    ("brake", ["brake", "brake pad", "rotor"]),
    ("chain", ["chain", "sprocket", "degreaser", "chain-lube", "chain-wax"]),
    ("parts", ["stator", "starter", "gasket", "clutch", "bearing", "axle", "spark", "plug", "battery", "lever", "radiator", "hose"]),
]
RUNTIME_COMPLEMENTARY_TYPES = {
    "pants": ["jacket", "jersey", "gloves", "boots", "helmet"],
    "jacket": ["pants", "gloves", "boots", "helmet"],
    "jersey": ["pants", "gloves", "boots", "helmet"],
    "helmet": ["helmet_accessory", "gloves", "jacket", "boots"],
    "helmet_accessory": ["helmet_accessory", "backpack", "care", "gloves"],
    "gloves": ["jacket", "pants", "helmet", "boots"],
    "boots": ["jacket", "pants", "gloves", "helmet"],
    "air_filter": ["oil", "chain", "brake", "tire", "parts"],
    "oil": ["air_filter", "chain", "brake", "parts", "tire"],
    "tire": ["brake", "chain", "oil", "parts", "air_filter"],
    "brake": ["tire", "chain", "oil", "parts", "air_filter"],
    "chain": ["oil", "brake", "tire", "parts", "air_filter"],
    "parts": ["air_filter", "oil", "chain", "brake", "tire"],
    "backpack": ["hydration", "luggage"],
    "hydration": ["backpack", "luggage"],
    "luggage": ["backpack", "hydration"],
    "communication": ["helmet_accessory", "gloves"],
    "protection": ["jacket", "pants", "gloves"],
    "care": ["helmet_accessory", "backpack"],
    "tshirt": ["tshirt", "hat"],
    "hat": ["tshirt", "hat"],
}
GEAR_TYPES = {
    "helmet", "helmet_accessory", "jacket", "jersey", "pants", "gloves", "boots",
    "backpack", "communication", "protection",
}
PARTS_TYPES = {"air_filter", "oil", "tire", "brake", "chain", "parts"}
# Types for which we never filter by price tier — if they pass all other rules, always recommend them.
TIER_EXEMPT_TYPES = {"parts", "oil", "chain", "air_filter", "brake", "helmet_accessory", "care"}
MULTI_REC_TYPES = {"tshirt", "hat"}
VALID_TIERS = {"budget", "mid", "premium", "elite"}
# Per-type tier bands (budget_max, mid_max, premium_max) for catalog fallback tier.
TIER_BANDS = {
    "helmet": (150, 350, 600),
    "jacket": (150, 300, 600),
    "pants": (100, 200, 400),
    "boots": (150, 300, 500),
    "gloves": (50, 100, 200),
    "jersey": (40, 80, 150),
    "tire": (100, 180, 300),
    "luggage": (100, 250, 500),
    "backpack": (75, 150, 300),
    "hydration": (50, 100, 200),
    "communication": (100, 300, 600),
    "protection": (75, 150, 300),
    "parts": (50, 150, 350),
    "oil": (25, 50, 100),
    "chain": (80, 180, 350),
    "brake": (80, 180, 400),
    "air_filter": (40, 80, 150),
    "care": (25, 50, 100),
    "helmet_accessory": (50, 120, 250),
    "default": (75, 200, 500),
}
BACKPACK_ALLOWED_TYPES = {"hydration", "luggage"}
HELMET_ACCESSORY_ALLOWED_TYPES = {"helmet_accessory", "backpack", "care", "gloves"}
VEHICLE_SPECIFIC_TERMS = {
    "harley", "davidson", "goldwing", "indian", "polaris", "can-am",
    "spyder", "ryker", "slingshot",
}
FREECOM_PRODUCTS = {
    "cardo-freecom-2x-jbl-single-unit",
    "cardo-freecom-2x-jbl-dual-pack",
    "cardo-freecom-4x-jbl-single-unit",
    "cardo-freecom-4x-jbl-dual-pack",
}
FREECOM_AUDIO_KIT = "cardo-freecom-2nd-helmet-audio-kit"

# --- Helmet price tiers and matching comm systems ---
# Premium: flagship race / top-of-line helmets
HELMET_PREMIUM_KEYWORDS = [
    "pista", "x-fifteen", "x-14", "supertech-r10", "corsair",
    "rf-1400", "rpha-1", "rpha 1", "rpha-11", "rpha-12",
    "neotec-3", "neotec-ii", "gt-air-3", "gt-air3",
    "c5", "schuberth-c5", "schuberth-e2",
    "6d-atr", "carbon",
]
# Mid-range
HELMET_MID_KEYWORDS = [
    "k6", "rpha", "rf-", "z-8", "gt-air", "neotec",
    "qualifier-dlx", "star-dlx", "srt", "race-r",
    "supertech", "scorpion-exo-r1", "exo-r1",
    "schuberth-c4", "schuberth-e1",
    "klim-f5", "klim-krios",
    "icon-airflite", "icon-airframe",
    "arai",
]
# Everything else is entry-level

COMM_PREMIUM = [
    "cardo-packtalk-pro-jbl-single-bluetooth-unit",
    "cardo-packtalk-edge-jbl-single-bluetooth-unit",
    "cardo-packtalk-edge-jbl-dual-bluetooth-unit",
    "sena-60s-communication-system-with-harman-kardon-speakers-single-unit",
    "sena-60s-communication-system-with-harman-kardon-speakers-dual-unit",
    "sena-50s-communication-system-with-harman-kardon-speakers-single-unit",
    "sena-50r-communication-system-with-harman-kardon-speakers-single-unit",
    "sena-50c-harman-kardon-mesh-intercom-camera",
]
COMM_MID = [
    "cardo-packtalk-neo-single-bluetooth-unit",
    "cardo-packtalk-neo-dual-bluetooth-unit",
    "sena-50s-communication-system-with-harman-kardon-speakers-single-unit",
    "sena-50r-communication-system-with-harman-kardon-speakers-single-unit",
    "sena-30k-hd-communication-system-single-unit",
    "sena-30k-hd-communication-system-dual-pack",
    "cardo-freecom-4x-jbl-single-unit",
    "cardo-freecom-4x-jbl-dual-pack",
    "sena-20s-evo-hd-communication-system-single",
]
COMM_ENTRY = [
    "cardo-freecom-2x-jbl-single-unit",
    "cardo-freecom-2x-jbl-dual-pack",
    "cardo-spirit-hd-single-unit",
    "cardo-spirit-hd-dual-pack",
    "sena-20s-evo-hd-communication-system-single",
    "ls2-focal-bluetooth-intercom-system",
    "hjc-smart-20b-bluetooth-headset",
]
RIDING_TYPE_RULES = {
    "dirt": [
        "dirt", "mx", "motocross", "offroad", "off-road", "enduro",
        "trail", "atv", "cross", "dualsport", "dual-sport",
        "sx", "fx", "kawasaki kx", "yz", "crf", "rmz", "ktm exc", "husqvarna fe",
        "dirtpaw", "patrol", "kinetic", "f-16", "f 16",
        "moto-9", "moto 9", "formula-cc",
        "6d",
        "gate", "moto 10", "lithium",
        "flexair", "elevated",
        "tech 10", "tech-10",
        "pro air",  # dirt gear line (e.g. TCX RT-Race Pro Air boots, Troy Lee GP Pro Air)
    ],
    "street": [
        "street", "sportbike", "supersport", "touring", "commuter",
        "cruiser", "harley", "goldwing", "roadsmart", "pilot road",
        "rpha", "x 15", "x fifteen", "rf 1400", "neotec", "pista", "corsair",
        "gt air", "k6", "k1s", "k3", "challenger", "vortex",
        "celer", "gp pro", "gp r", "gp tech", "spx air",
        "sp 365", "mustang", "chrome",
        "airflite", "airframe", "anthem", "overlord", "pursuit",
        "jab", "louie", "ranger", "recoil", "roulette", "vixen", "ivy",
        "mosca", "avion", "caliber", "cassini", "cayenne", "dominator",
        "hydra", "kodiak", "kryptonite", "league", "rsr",
        "speedart", "stratos", "summit", "taurus",
        "cortech", "dainese", "noru", "highway 21",
        "stunt iii",
        "shoei", "agv", "arai", "schuberth", "nolan", "biltwell", "gmax",
        "kyt",
        "i 10", "i 30", "i 31", "i 80", "i 91", "i 100", "i11", "c 10", "v10", "f 71",
        "scout", "srt", "mag 9", "qualifier",
        "stream", "citation", "dragon", "explorer",
        "hornet",
        "broozer", "custom 500", "pit boss", "recon", "race star",
        "forma", "gaerne", "tcx", "sidi",
        "rev it", "rev-it", "revit", "tornado", "textile",
        "adventure", "adv",  # adventure touring = street (e.g. Forma Adventure boots)
    ],
}
WOMENS_PRODUCT_KEYWORDS = ["womens", "women s", "ladies", "women's", "female"]
YOUTH_PRODUCT_KEYWORDS = ["youth", "kids", "kid s", "child", "children", "junior", " jr", "-jr"]
DIRT_ONLY_BRANDS = {
    "fly", "fasthouse", "troy", "seven", "shift", "thor", "one", "leatt",
    "6d",
}
STREET_ONLY_BRANDS = {
    "dainese", "cortech", "noru", "highway", "rst", "olympia", "firstgear",
    "tourmaster", "warm", "scorpion",
    "cardo", "sena", "schuberth", "boss",
}
STREET_RACE_KEYWORDS = [
    "race", "racing", "track", "pista", "gp", "supersport", "sportbike",
    "r10", "x 15", "x fifteen", "rf 1400", "corsair",
    "missile", "super speed",
]
STREET_TOURING_KEYWORDS = [
    "tour", "touring", "adventure", "adv", "enduro",
    "dual-sport", "dualsport", "commuter", "cruiser",
    "heated", "waterproof", "winter", "h20", "h2o", "liberty",
]
DIRT_MX_KEYWORDS = ["mx", "motocross", "dirtpaw", "cross", "sx", "fx", "flexair", "elevated"]
DIRT_ENDURO_KEYWORDS = [
    "enduro", "adventure", "adv", "gore-tex", "gore tex", "trail",
    "dualsport", "dual-sport", "recon",
]
_GLOBAL_REC_BY_TYPE = defaultdict(list)


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

    limit = 250
    out = {}
    page = 1
    total_pages = None
    while True:
        resp = session.get(
            f"{base_path}/catalog/products",
            params={
                "page": page,
                "limit": limit,
                "include": "primary_image",
                "include_fields": "id,name,price,custom_url",
            },
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
        if total_pages is None:
            total_pages = meta.get("total_pages")
            if total_pages is None and meta.get("total") is not None:
                total_pages = math.ceil(int(meta["total"]) / limit)
            if total_pages is None:
                total_pages = 1
        if page >= total_pages or not rows:
            break
        page += 1
    return out


def _tier_from_price(product_type: str, price: float) -> str:
    """Return tier (budget/mid/premium/elite) for a product type and price."""
    bands = TIER_BANDS.get(product_type, TIER_BANDS["default"])
    budget_max, mid_max, premium_max = bands
    if price < budget_max:
        return "budget"
    if price < mid_max:
        return "mid"
    if price < premium_max:
        return "premium"
    return "elite"


def _get_source_tier_from_catalog(product_id: str):
    """
    When CSV has no Source Tier for this product, try to derive it from the
    BigCommerce catalog (price + product type). Returns tier string or None.
    Tries variant slugs (e.g. arai-corsair-x-bracket-helmet -> arai-corsair-x-helmet).
    """
    catalog_map = _get_catalog_map()
    if not catalog_map:
        return None
    # Try format variants first, then shorter/base slug candidates.
    keys_to_try = list(_candidate_catalog_keys(product_id))
    for candidate in _source_lookup_candidates(product_id):
        for key in _candidate_catalog_keys(candidate):
            if key not in keys_to_try:
                keys_to_try.append(key)
    for key in keys_to_try:
        if key in catalog_map:
            item = catalog_map[key]
            try:
                price = float(item.get("price") or 0)
            except (TypeError, ValueError):
                return None
            ptype = _detect_product_type(product_id)
            return _tier_from_price(ptype, price)
    return None


_CATALOG_JSON_PATH = DATA_DIR / "data" / "catalog.json"


def _load_catalog_from_file() -> dict:
    """Load catalog from build-time data/catalog.json if it exists."""
    if not _CATALOG_JSON_PATH.exists():
        return {}
    try:
        with open(_CATALOG_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    return {}


def _get_catalog_map(force_refresh: bool = False):
    now = time.time()
    with _RULES_LOCK:
        has_cache = bool(_CATALOG_CACHE["slug_map"])
        is_fresh = (now - _CATALOG_CACHE["fetched_at"]) < CATALOG_REFRESH_SECONDS
        if not force_refresh and has_cache and is_fresh:
            return _CATALOG_CACHE["slug_map"]

    # Try build-time catalog file first (fast, no API call needed).
    file_catalog = _load_catalog_from_file()
    if file_catalog and not force_refresh:
        with _RULES_LOCK:
            if not _CATALOG_CACHE["slug_map"]:
                _CATALOG_CACHE["slug_map"] = file_catalog
                _CATALOG_CACHE["fetched_at"] = now
                _CATALOG_CACHE["source"] = "file"
                _CATALOG_CACHE["last_error"] = None
        # Still try to refresh from BigCommerce in background if TTL expired.
        if not has_cache or not is_fresh:
            try:
                catalog_map = _fetch_bigcommerce_catalog_map()
                if catalog_map:
                    with _RULES_LOCK:
                        _CATALOG_CACHE["slug_map"] = catalog_map
                        _CATALOG_CACHE["fetched_at"] = now
                        _CATALOG_CACHE["source"] = "bigcommerce"
                        _CATALOG_CACHE["last_error"] = None
            except Exception as exc:
                with _RULES_LOCK:
                    _CATALOG_CACHE["last_error"] = str(exc)
        return _CATALOG_CACHE["slug_map"]

    # No file — fall back to live BigCommerce API fetch.
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


def _candidate_catalog_keys(raw_id: str) -> list:
    """
    Build multiple key forms to maximize catalog lookup hits.
    Handles IDs like:
    - "agv-pista-gp-rr-mono-carbon-helmet"
    - "/agv-pista-gp-rr-mono-carbon-helmet/"
    - "products/agv-pista-gp-rr-mono-carbon-helmet"
    - "/products/agv-pista-gp-rr-mono-carbon-helmet/"
    """
    val = (raw_id or "").strip()
    if not val:
        return []
    candidates = []

    def add(v):
        v = (v or "").strip()
        if v and v not in candidates:
            candidates.append(v)

    add(val)
    add(val.strip("/"))

    stripped = val.strip("/")
    add(stripped)

    if stripped.lower().startswith("products/"):
        add(stripped[len("products/"):])
    if "/products/" in stripped.lower():
        idx = stripped.lower().find("/products/")
        add(stripped[idx + len("/products/"):])

    # Last path segment fallback
    if "/" in stripped:
        add(stripped.split("/")[-1])

    return candidates


def _source_lookup_candidates(product_id: str) -> list:
    """
    For CSV lookups (source_tier_map, explicit_map): if exact product_id isn't
    found, try shorter keys so e.g. arai-corsair-x-bracket-helmet matches
    arai-corsair-x-helmet. Returns [product_id, ...] with fallback candidates.
    """
    val = (product_id or "").strip()
    if not val:
        return []
    candidates = [val]
    parts = val.split("-")
    for i in range(len(parts) - 1, 0, -1):
        base = "-".join(parts[:i])
        if base not in candidates:
            candidates.append(base)
        if val.endswith("-helmet") and not base.endswith("-helmet"):
            with_helmet = base + "-helmet"
            if with_helmet not in candidates:
                candidates.append(with_helmet)
    return candidates


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


def _normalize_slug_text(value: str) -> str:
    return (value or "").strip().lower()


def _detect_product_type(slug: str) -> str:
    text = _normalize_slug_text(slug)
    for type_name, keywords in PRODUCT_TYPE_RULES:
        if any(keyword in text for keyword in keywords):
            return type_name
    return "unknown"


def _extract_brand_token(slug: str) -> str:
    tokens = [t for t in _normalize_slug_text(slug).split("-") if t]
    for token in tokens:
        if token.isdigit():
            continue
        if any(ch.isalpha() for ch in token):
            return token
    return ""


def _detect_riding_type(slug: str) -> str:
    # Brand first: dirt/street-only brands override keyword matches (e.g. Troy Lee "Scout" gloves are dirt, not street).
    brand = _extract_brand_token(slug)
    if brand in DIRT_ONLY_BRANDS:
        return "dirt"
    if brand in STREET_ONLY_BRANDS:
        return "street"
    text = _normalize_slug_text(slug).replace("-", " ")
    dirt_hit = any(keyword in text for keyword in RIDING_TYPE_RULES["dirt"])
    street_hit = any(keyword in text for keyword in RIDING_TYPE_RULES["street"])
    # When both match (e.g. "pro air" + "race"), prefer dirt so boots/gear like TCX RT-Race Pro Air stay dirt.
    if dirt_hit:
        return "dirt"
    if street_hit:
        return "street"
    return "unknown"


def _detect_street_subtype(slug: str) -> str:
    if _detect_riding_type(slug) != "street":
        return "other"
    text = _normalize_slug_text(slug).replace("-", " ")
    race_hit = any(keyword in text for keyword in STREET_RACE_KEYWORDS)
    touring_hit = any(keyword in text for keyword in STREET_TOURING_KEYWORDS)
    if race_hit and not touring_hit:
        return "race"
    if touring_hit and not race_hit:
        return "touring"
    return "other"


def _detect_dirt_subtype(slug: str) -> str:
    if _detect_riding_type(slug) != "dirt":
        return "other"
    text = _normalize_slug_text(slug).replace("-", " ")
    mx_hit = any(keyword in text for keyword in DIRT_MX_KEYWORDS)
    enduro_hit = any(keyword in text for keyword in DIRT_ENDURO_KEYWORDS)
    if mx_hit and not enduro_hit:
        return "mx"
    if enduro_hit and not mx_hit:
        return "enduro"
    return "other"


SNOW_GEAR_KEYWORDS = ["snow", "snowbike", "snow bike", "snow-bike", "avalanche", "avalanch"]


def _is_snow_gear(slug: str) -> bool:
    text = _normalize_slug_text(slug).replace("-", " ")
    return any(kw in text for kw in SNOW_GEAR_KEYWORDS)


def _is_vehicle_specific(slug: str) -> bool:
    text = _normalize_slug_text(slug)
    return any(term in text for term in VEHICLE_SPECIFIC_TERMS)


def _is_womens_product(slug: str) -> bool:
    text = _normalize_slug_text(slug).replace("-", " ")
    return any(kw in text for kw in WOMENS_PRODUCT_KEYWORDS)


def _is_youth_product(slug: str) -> bool:
    text = _normalize_slug_text(slug).replace("-", " ")
    return any(kw in text for kw in YOUTH_PRODUCT_KEYWORDS)


def _is_race_suit(product_id: str) -> bool:
    """True if product is a one-piece or two-piece race suit (jacket type with suit/race-suit/hyperspeed in slug)."""
    if not product_id:
        return False
    if _detect_product_type(product_id) != "jacket":
        return False
    low = product_id.lower()
    return "suit" in low or "race-suit" in low or "hyperspeed" in low or "gp-tech" in low


# For race suits, only recommend these helmet lines: Shoei X-15, AGV Pista, Alpinestars R10 (Supertech R).
SUIT_ALLOWED_HELMET_KEYWORDS = ("x-15", "x-fifteen", "pista", "supertech-r", "r10")


def _helmet_allowed_for_suit(helmet_slug: str) -> bool:
    """True if helmet is one of the allowed lines for suit recommendations (Shoei X-15, AGV Pista, Alpinestars R10)."""
    if not helmet_slug:
        return False
    low = helmet_slug.lower()
    return any(kw in low for kw in SUIT_ALLOWED_HELMET_KEYWORDS)


def _is_racing_source(product_id: str) -> bool:
    """True if source is racing gear: race suit, racing jacket/pants, or race helmet (X-15, Pista, R-10)."""
    if not product_id:
        return False
    if _is_race_suit(product_id):
        return True
    ptype = _detect_product_type(product_id)
    if ptype in {"jacket", "pants"} and _detect_street_subtype(product_id) == "race":
        return True
    if ptype == "helmet" and _helmet_allowed_for_suit(product_id):
        return True
    return False


def _is_racing_glove(slug: str) -> bool:
    """True if glove is Alpinestars GP (racing glove) by slug."""
    if not slug:
        return False
    low = slug.lower()
    return "alpinestars" in low and "gp" in low


def _is_race_helmet(product_id: str) -> bool:
    """True if product is a race-level helmet: Shoei X-15, AGV Pista, Alpinestars Supertech R10.
    Does NOT require 'helmet' in the slug — some AGV Pista slugs omit it."""
    return bool(product_id) and _helmet_allowed_for_suit(product_id)


def _is_race_grade_apparel(slug: str) -> bool:
    """True if slug is a race suit, race jacket, or race pants (not touring/adventure gear)."""
    if not slug:
        return False
    if _is_race_suit(slug):
        return True
    ptype = _detect_product_type(slug)
    if ptype not in {"jacket", "pants"}:
        return False
    return _detect_street_subtype(slug) == "race"


def _suit_glove_matches_brand(glove_slug: str, suit_brand: str) -> bool:
    """True if glove is the suit-brand racing glove: Alpinestars suit -> GP gloves; Rev'it suit -> Control gloves."""
    if not glove_slug or not suit_brand:
        return False
    low = glove_slug.lower()
    brand_low = (suit_brand or "").lower()
    if "alpinestars" in brand_low:
        return "alpinestars" in low and "gp" in low
    if "revit" in brand_low or "rev-it" in brand_low:
        return ("revit" in low or "rev-it" in low) and "control" in low
    return False


# Race suits recommended for race helmets (Pista, X-15, R-10).
_RACE_HELMET_SUITS = [
    "alpinestars-fusion-1-piece-race-suit",
    "alpinestars-2025-missile-v2-1-piece-ignition-leather-suit",
]

# Hardcoded suit recommendation pools — these are picked directly for any race suit.
_SUIT_HELMETS = [
    "shoei-x-15-marquez-73-v2-helmet",
    "shoei-x-15-diggia-2-tc-1-helmet",
    "shoei-x-15-marquez-thai-tc-2-helmet",
    "alpinestars-supertech-r10-miller-le-helmet",
    "alpinestars-supertech-r10-flyte-le-helmet",
    "alpinestars-supertech-r10-limited-edition-pedro-acosta-helmet",
    "agv-pista-gp-rr-soleluna-2023-limited-edition",
    "agv-pista-gp-rr-mono-carbon-helmet",
]
_SUIT_BOOTS = [
    "alpinestars-smx-plus-v2-vented-boots",
    "alpinestars-smx-6v3-vented-boots",
    "alpinestars-smx-1r-vented-v2-boots",
]
_SUIT_GLOVES_ALPINESTARS = [
    "alpinestars-gp-tech-v2-s-gloves",
    "alpinestars-gp-pro-r4-gloves",
    "alpinestars-gp-r-v3-gloves",
    "alpinestars-gp-r-v2-gloves",
]
_SUIT_GLOVES_REVIT = [
    "revit-control-gloves",
]


def _pick_suit_recommendations(product_id: str) -> list:
    """Directly return hardcoded helmet + gloves + boots for any race suit, bypassing all other logic."""
    brand = _extract_brand_token(product_id)
    brand_low = brand.lower() if brand else ""

    # Pick gloves by suit brand: Alpinestars -> GP; Rev'it -> Control; default -> Alpinestars GP
    if "revit" in brand_low or "rev-it" in brand_low:
        glove_pool = _SUIT_GLOVES_REVIT
    else:
        glove_pool = _SUIT_GLOVES_ALPINESTARS

    offset = hash(product_id) % max(len(_SUIT_HELMETS), 1)
    helmet = _SUIT_HELMETS[offset % len(_SUIT_HELMETS)]

    offset2 = (hash(product_id) + 1) % max(len(_SUIT_BOOTS), 1)
    boots = _SUIT_BOOTS[offset2 % len(_SUIT_BOOTS)]

    offset3 = (hash(product_id) + 2) % max(len(glove_pool), 1)
    gloves = glove_pool[offset3 % len(glove_pool)]

    result = []
    result.append({"id": helmet, "label": "Recommended item", "priority": "Primary"})
    result.append({"id": gloves, "label": "Recommended item", "priority": "Secondary"})
    result.append({"id": boots, "label": "Recommended item", "priority": "Tertiary"})
    return result


def _detect_helmet_tier(slug: str) -> str:
    text = _normalize_slug_text(slug)
    if any(kw in text for kw in HELMET_PREMIUM_KEYWORDS):
        return "premium"
    if any(kw in text for kw in HELMET_MID_KEYWORDS):
        return "mid"
    return "entry"


def _pick_tiered_comm(helmet_slug: str, selected_ids: set) -> str:
    tier = _detect_helmet_tier(helmet_slug)
    if tier == "premium":
        tier_order = [COMM_PREMIUM, COMM_MID, COMM_ENTRY]
    elif tier == "mid":
        tier_order = [COMM_MID, COMM_PREMIUM, COMM_ENTRY]
    else:
        tier_order = [COMM_ENTRY, COMM_MID, COMM_PREMIUM]

    available = set(_GLOBAL_REC_BY_TYPE.get("communication", []))
    for tier_list in tier_order:
        for cid in tier_list:
            if cid in available and cid not in selected_ids and not _is_vehicle_specific(cid):
                return cid
    return ""


def _sort_by_priority(recommendations: list) -> list:
    return sorted(
        recommendations,
        key=lambda rec: PRIORITY_RANK.get((rec.get("priority") or "").strip(), 99),
    )


def _refresh_global_rec_pool(explicit_map: dict, category_rule_list: list) -> None:
    pool = defaultdict(list)
    seen_by_type = defaultdict(set)

    def add_candidate(rec_id: str) -> None:
        rec_id = (rec_id or "").strip()
        if not rec_id:
            return
        rec_type = _detect_product_type(rec_id)
        if rec_type == "unknown":
            return
        if rec_id in seen_by_type[rec_type]:
            return
        seen_by_type[rec_type].add(rec_id)
        pool[rec_type].append(rec_id)

    for recs in explicit_map.values():
        for rec in recs:
            add_candidate(rec.get("id"))
    # Also include source product IDs as candidates so high-quality SKUs
    # that are not currently used as recommendations remain available.
    for source_id in explicit_map.keys():
        add_candidate(source_id)
    for _, recs in category_rule_list:
        for rec in recs:
            add_candidate(rec.get("id"))

    _GLOBAL_REC_BY_TYPE.clear()
    for rec_type, ids in pool.items():
        _GLOBAL_REC_BY_TYPE[rec_type] = ids


def _pick_global_candidate(source_product_id: str, source_type: str, source_brand: str, source_riding: str, source_street_subtype: str, source_dirt_subtype: str, rec_type: str, selected_ids: set, source_tier: str = None, rec_tier_map: dict = None, boots_slug_must_contain: str = None, helmet_slug_any_of: tuple = None, gloves_racing_only: bool = False, source_is_suit: bool = False, apparel_race_only: bool = False) -> str:
    rec_tier_map = rec_tier_map or {}
    candidates = _GLOBAL_REC_BY_TYPE.get(rec_type, [])
    if rec_type == "boots" and boots_slug_must_contain:
        candidates = [r for r in candidates if boots_slug_must_contain in r.lower()]
    if rec_type == "helmet" and helmet_slug_any_of:
        candidates = [r for r in candidates if any(kw in r.lower() for kw in helmet_slug_any_of)]
    if rec_type == "gloves" and source_is_suit:
        candidates = [r for r in candidates if _suit_glove_matches_brand(r, source_brand)]
    elif rec_type == "gloves" and gloves_racing_only:
        candidates = [r for r in candidates if _is_racing_glove(r)]
    if rec_type in {"jacket", "pants"} and apparel_race_only:
        candidates = [r for r in candidates if _is_race_grade_apparel(r)]

    def _tier_ok(rid):
        if not source_tier:
            return True
        if source_type in TIER_EXEMPT_TYPES or rec_type in TIER_EXEMPT_TYPES:
            return True
        return rec_tier_map.get(rid) == source_tier

    # Special fallback preference:
    # For jacket/pants -> gloves, if same-brand gloves are unavailable,
    # prefer Alpinestars gloves.
    if source_type in {"jacket", "pants"} and rec_type == "gloves":
        for rid in candidates:
            if rid in selected_ids:
                continue
            if rid == source_product_id:
                continue
            if not _tier_ok(rid):
                continue
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand == source_brand:
                return rid
        for rid in candidates:
            if rid in selected_ids:
                continue
            if rid == source_product_id:
                continue
            if not _tier_ok(rid):
                continue
            rec_brand = _extract_brand_token(rid)
            if rec_brand == "alpinestars":
                return rid

    # First pass: prefer same brand
    for rid in candidates:
        if rid in selected_ids or rid == source_product_id:
            continue
        if not _tier_ok(rid):
            continue
        if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
            continue
        if _is_snow_gear(rid) and not _is_snow_gear(source_product_id):
            continue
        if source_type in {"helmet_accessory", "care"} and rec_type not in HELMET_ACCESSORY_ALLOWED_TYPES:
            continue
        rec_brand = _extract_brand_token(rid)
        same_brand = source_brand and rec_brand and source_brand == rec_brand
        if not same_brand:
            continue
        if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
            continue
        if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
            continue
        if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
            continue
        if source_type == "backpack" and rec_type == "backpack":
            continue
        if source_riding == "dirt" and source_dirt_subtype == "mx" and _detect_dirt_subtype(rid) == "enduro":
            continue
        if _is_womens_product(rid) != _is_womens_product(source_product_id):
            continue
        if _is_youth_product(rid) != _is_youth_product(source_product_id):
            continue
        return rid

    # Second pass: any brand, with riding type filter. Collect all viable and
    # rotate by source product id so different products get different recs.
    viable = []
    for rid in candidates:
        if rid in selected_ids or rid == source_product_id:
            continue
        if not _tier_ok(rid):
            continue
        if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
            continue
        if _is_snow_gear(rid) and not _is_snow_gear(source_product_id):
            continue
        if source_type in {"helmet_accessory", "care"} and rec_type not in HELMET_ACCESSORY_ALLOWED_TYPES:
            continue
        # For visor source, allow unknown riding type for backpack/care/gloves.
        # For race suit, allow unknown riding type for helmet/gloves/boots (we explicitly choose street racing gear).
        if not (source_type == "helmet_accessory" and rec_type in {"backpack", "care", "gloves"}):
            rec_rt = _detect_riding_type(rid)
            if source_riding in {"street", "dirt"} and (rec_rt == "unknown" or rec_rt != source_riding):
                if not (source_is_suit and rec_type in {"gloves", "boots", "helmet"} and rec_rt == "unknown"):
                    continue
            if source_riding == "street" and source_street_subtype == "race" and _detect_street_subtype(rid) == "touring":
                continue
            if source_riding == "dirt" and source_dirt_subtype == "mx" and _detect_dirt_subtype(rid) == "enduro":
                continue
        if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
            continue
        if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
            continue
        if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
            continue
        if source_type == "backpack" and rec_type == "backpack":
            continue
        if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        if source_type == "helmet_accessory" and rec_type == "helmet_accessory":
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        if _is_womens_product(rid) != _is_womens_product(source_product_id):
            continue
        if _is_youth_product(rid) != _is_youth_product(source_product_id):
            continue
        viable.append(rid)
    if viable:
        offset = hash(source_product_id) % len(viable)
        return viable[offset]
    return ""


def _pick_global_candidate_any(source_product_id: str, source_type: str, source_brand: str, source_riding: str, source_street_subtype: str, source_dirt_subtype: str, selected_ids: set, used_types: set, source_tier: str = None, rec_tier_map: dict = None, boots_slug_must_contain: str = None, helmet_slug_any_of: tuple = None, gloves_racing_only: bool = False, exclude_types: set = None, source_is_suit: bool = False, apparel_race_only: bool = False) -> tuple:
    rec_tier_map = rec_tier_map or {}
    exclude_types = exclude_types or set()

    def _tier_ok(rid, rec_type):
        if not source_tier:
            return True
        if source_type in TIER_EXEMPT_TYPES or rec_type in TIER_EXEMPT_TYPES:
            return True
        return rec_tier_map.get(rid) == source_tier

    def _candidates_for_type(rec_type, candidates):
        if rec_type == "boots" and boots_slug_must_contain:
            return [r for r in candidates if boots_slug_must_contain in r.lower()]
        if rec_type == "helmet" and helmet_slug_any_of:
            return [r for r in candidates if any(kw in r.lower() for kw in helmet_slug_any_of)]
        if rec_type == "gloves" and source_is_suit:
            return [r for r in candidates if _suit_glove_matches_brand(r, source_brand)]
        if rec_type == "gloves" and gloves_racing_only:
            return [r for r in candidates if _is_racing_glove(r)]
        if rec_type in {"jacket", "pants"} and apparel_race_only:
            return [r for r in candidates if _is_race_grade_apparel(r)]
        return list(candidates)

    # First pass: prefer same brand for gear-to-gear
    if source_type in GEAR_TYPES and source_brand:
        for rec_type, candidates in _GLOBAL_REC_BY_TYPE.items():
            if rec_type in used_types or rec_type not in GEAR_TYPES:
                continue
            if rec_type in exclude_types:
                continue
            for rid in _candidates_for_type(rec_type, candidates):
                if rid in selected_ids or rid == source_product_id:
                    continue
                if not _tier_ok(rid, rec_type):
                    continue
                if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
                    continue
                if _is_snow_gear(rid) and not _is_snow_gear(source_product_id):
                    continue
                if source_type in {"hydration", "backpack", "luggage"} and rec_type == "helmet":
                    continue
                if source_type in {"helmet_accessory", "care"} and rec_type not in HELMET_ACCESSORY_ALLOWED_TYPES:
                    continue
                _rec_rt_a = _detect_riding_type(rid)
                if source_riding in {"street", "dirt"} and (_rec_rt_a == "unknown" or _rec_rt_a != source_riding):
                    if not (source_is_suit and rec_type in {"gloves", "boots", "helmet"} and _rec_rt_a == "unknown"):
                        continue
                if source_riding == "street" and source_street_subtype == "race" and _detect_street_subtype(rid) == "touring":
                    continue
                if source_riding == "dirt" and source_dirt_subtype == "mx" and _detect_dirt_subtype(rid) == "enduro":
                    continue
                if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
                    continue
                if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
                    continue
                if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
                    continue
                if source_type == "backpack" and rec_type == "backpack":
                    continue
                if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
                    rec_brand = _extract_brand_token(rid)
                    if source_brand and rec_brand and source_brand != rec_brand:
                        continue
                rec_brand = _extract_brand_token(rid)
                if rec_brand and rec_brand != source_brand:
                    continue
                if _is_womens_product(rid) != _is_womens_product(source_product_id):
                    continue
                if _is_youth_product(rid) != _is_youth_product(source_product_id):
                    continue
                return rid, rec_type

    # Second pass: any brand
    for rec_type, candidates in _GLOBAL_REC_BY_TYPE.items():
        if rec_type in used_types:
            continue
        if rec_type in exclude_types:
            continue
        for rid in _candidates_for_type(rec_type, candidates):
            if rid in selected_ids or rid == source_product_id:
                continue
            if not _tier_ok(rid, rec_type):
                continue
            if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
                continue
            if _is_snow_gear(rid) and not _is_snow_gear(source_product_id):
                continue
            if source_type in {"hydration", "backpack", "luggage"} and rec_type == "helmet":
                continue
            if source_type in {"helmet_accessory", "care"} and rec_type not in HELMET_ACCESSORY_ALLOWED_TYPES:
                continue
            _rec_rt_b = _detect_riding_type(rid)
            if source_riding in {"street", "dirt"} and (_rec_rt_b == "unknown" or _rec_rt_b != source_riding):
                if not (source_is_suit and rec_type in {"gloves", "boots", "helmet"} and _rec_rt_b == "unknown"):
                    continue
            if source_riding == "street" and source_street_subtype == "race" and _detect_street_subtype(rid) == "touring":
                continue
            if source_riding == "dirt" and source_dirt_subtype == "mx" and _detect_dirt_subtype(rid) == "enduro":
                continue
            if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
                continue
            if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
                continue
            if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
                continue
            if source_type == "backpack" and rec_type == "backpack":
                continue
            if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
                rec_brand = _extract_brand_token(rid)
                if source_brand and rec_brand and source_brand != rec_brand:
                    continue
            if source_type == "helmet_accessory" and rec_type == "helmet_accessory":
                rec_brand = _extract_brand_token(rid)
                if source_brand and rec_brand and source_brand != rec_brand:
                    continue
            if _is_womens_product(rid) != _is_womens_product(source_product_id):
                continue
            if _is_youth_product(rid) != _is_youth_product(source_product_id):
                continue
            return rid, rec_type
    return "", ""


def _apply_recommendation_constraints(product_id: str, recommendations: list) -> list:
    """
    Runtime constraints:
    - For jacket/pants sources, jacket/pants recommendations must match source brand.
    - Return up to 3 recommendations with preference for distinct product types.
    - Price tier: when source has a tier and both source/rec are not tier-exempt, require matching tier.
    """
    # Race suits always get the fixed helmet/gloves/boots pool — no other logic needed.
    if _is_race_suit(product_id):
        return _pick_suit_recommendations(product_id)

    with _RULES_LOCK:
        rec_tier_map = _RULES_CACHE.get("rec_tier_map") or {}
        source_tier_map = _RULES_CACHE.get("source_tier_map") or {}
    source_tier = None
    for key in _source_lookup_candidates(product_id):
        if key in source_tier_map:
            source_tier = source_tier_map[key]
            break
    if source_tier is None:
        source_tier = _get_source_tier_from_catalog(product_id)

    source_type = _detect_product_type(product_id)
    source_brand = _extract_brand_token(product_id)
    source_riding = _detect_riding_type(product_id)
    # Helmets, boots, and apparel with unknown riding type default to street for filtering.
    if source_type in {"helmet", "boots", "jacket", "pants", "gloves"} and source_riding == "unknown":
        source_riding = "street"
    source_street_subtype = _detect_street_subtype(product_id)
    source_dirt_subtype = _detect_dirt_subtype(product_id)
    source_is_suit = _is_race_suit(product_id)
    source_is_race_helmet = _is_race_helmet(product_id)
    # If the slug doesn't contain "helmet" (e.g. agv-pista-gp-rr-soleluna-2023-limited-edition),
    # _detect_product_type returns "unknown". Override to "helmet" for race helmets.
    if source_is_race_helmet and source_type == "unknown":
        source_type = "helmet"
        if source_riding == "unknown":
            source_riding = "street"
    source_is_racing = _is_racing_source(product_id)
    ordered = _sort_by_priority(recommendations)

    filtered = []
    for rec in ordered:
        rid = (rec.get("id") or "").strip()
        if not rid:
            continue
        rec_type = _detect_product_type(rid)
        rec_riding = _detect_riding_type(rid)
        rec_street_subtype = _detect_street_subtype(rid)
        rec_dirt_subtype = _detect_dirt_subtype(rid)
        if not _is_vehicle_specific(product_id) and _is_vehicle_specific(rid):
            continue
        rec_brand = _extract_brand_token(rid)
        same_brand = source_brand and rec_brand and source_brand == rec_brand
        # Race suit: do not recommend pants, jacket, visor, or comm; only helmet/boots/gloves (brand-matched gloves).
        if source_is_suit and rec_type in {"pants", "jacket"}:
            continue
        if source_is_suit and rec_type in {"helmet_accessory", "communication"}:
            continue
        if source_is_suit and rec_type == "boots" and "smx" not in rid.lower():
            continue
        if source_is_suit and rec_type == "helmet" and not _helmet_allowed_for_suit(rid):
            continue
        if source_is_suit and rec_type == "gloves" and not _suit_glove_matches_brand(rid, source_brand):
            continue
        if not source_is_suit and _is_racing_source(product_id) and rec_type == "gloves" and not _is_racing_glove(rid):
            continue
        # Race helmet: jackets/pants must be race-grade (race suits, race jackets — no touring gear).
        if source_is_race_helmet and rec_type in {"jacket", "pants"} and not _is_race_grade_apparel(rid):
            continue
        # All recommendations must match street or dirt with the source (no cross-over, no same-brand exception).
        if source_riding in {"street", "dirt"} and (rec_riding == "unknown" or rec_riding != source_riding):
            continue
        if source_riding == "street" and source_street_subtype == "race" and rec_street_subtype == "touring" and not same_brand:
            continue
        if source_riding == "dirt" and source_dirt_subtype == "mx" and rec_dirt_subtype == "enduro" and not same_brand:
            continue

        # Communication systems (Sena, Cardo, etc.) only for street helmets.
        if rec_type == "communication":
            if source_type != "helmet" or source_riding == "dirt":
                continue

        # Snow gear only for snow gear (e.g. don't recommend snow boots for enduro jacket).
        if _is_snow_gear(rid) and not _is_snow_gear(product_id):
            continue

        # Don't recommend helmets for accessories (hydration, backpack, luggage).
        if source_type in {"hydration", "backpack", "luggage"} and rec_type == "helmet":
            continue

        if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
            continue
        if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
            continue
        if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
            continue
        if source_type == "backpack" and rec_type == "backpack":
            continue
        # T-shirts and hats only ever recommend other t-shirts and hats.
        if source_type in {"tshirt", "hat"} and rec_type not in {"tshirt", "hat"}:
            continue

        # Helmet accessories must always match helmet brand (fit-sensitive).
        if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        # Visors/shields only recommend other visors (same brand only), backpacks, gloves, and care.
        if source_type in {"helmet_accessory", "care"} and rec_type not in HELMET_ACCESSORY_ALLOWED_TYPES:
            continue
        # When source is a visor, recommended visors must be same brand; only one visor is suggested.
        if source_type == "helmet_accessory" and rec_type == "helmet_accessory":
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        # Do not recommend women's products for non-women's products (and vice versa).
        if _is_womens_product(rid) != _is_womens_product(product_id):
            continue
        # Do not recommend youth products for adult products (and vice versa).
        if _is_youth_product(rid) != _is_youth_product(product_id):
            continue
        # Price tier: only enforce when source has a tier and neither type is tier-exempt.
        if (source_tier and
                source_type not in TIER_EXEMPT_TYPES and
                rec_type not in TIER_EXEMPT_TYPES):
            rec_tier = rec.get("tier") or rec_tier_map.get(rid)
            if rec_tier != source_tier:
                continue
        filtered.append(rec)

    # For helmets, always reserve one slot for a price-tiered comm system (street only).
    # Dirt helmets don't use comm systems — recommend riding gear instead.
    selected = []
    selected_ids = set()
    seen_types = set()

    if source_type == "helmet" and source_riding != "dirt":
        comm_id = _pick_tiered_comm(product_id, selected_ids)
        if comm_id:
            selected.append({"id": comm_id, "label": "Pairs with your helmet", "priority": "Secondary"})
            selected_ids.add(comm_id)
            seen_types.add("communication")

    comm_only_brand = source_type == "communication"

    # For comm systems: Freecom gets audio kit + helmet accessory + gloves;
    # all others get helmet accessory(s) + gloves (no helmets).
    if comm_only_brand:
        if product_id in FREECOM_PRODUCTS and FREECOM_AUDIO_KIT != product_id:
            selected.append({"id": FREECOM_AUDIO_KIT, "label": "Second helmet kit", "priority": "Secondary"})
            selected_ids.add(FREECOM_AUDIO_KIT)
            seen_types.add("helmet_accessory")
        desired_types = ["helmet_accessory", "gloves"]
        if product_id not in FREECOM_PRODUCTS:
            desired_types.append("helmet_accessory")
        seen_brands_comm = set()
        offset = hash(product_id) % 50
        for desired_type in desired_types:
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                break
            candidates = _GLOBAL_REC_BY_TYPE.get(desired_type, [])
            viable = []
            for rid in candidates:
                if rid in selected_ids or rid == product_id:
                    continue
                if _is_vehicle_specific(rid):
                    continue
                if _is_womens_product(rid) != _is_womens_product(product_id):
                    continue
                if _is_youth_product(rid) != _is_youth_product(product_id):
                    continue
                rt = _detect_riding_type(rid)
                if source_riding in {"street", "dirt"} and (rt == "unknown" or rt != source_riding):
                    continue
                rid_type = _detect_product_type(rid)
                if (source_tier and
                        source_type not in TIER_EXEMPT_TYPES and
                        rid_type not in TIER_EXEMPT_TYPES):
                    if rec_tier_map.get(rid) != source_tier:
                        continue
                viable.append(rid)
            if not viable:
                continue
            rotated = viable[offset % len(viable):] + viable[:offset % len(viable)]
            for rid in rotated:
                rec_brand = _extract_brand_token(rid)
                if rec_brand in seen_brands_comm:
                    continue
                selected.append({"id": rid, "label": "Recommended item", "priority": "Tertiary"})
                selected_ids.add(rid)
                seen_types.add(desired_type)
                if rec_brand:
                    seen_brands_comm.add(rec_brand)
                break
        return selected

    # Pre-pass: for gear sources pick same-brand items from the GLOBAL pool first,
    # before any CSV-based filling. This ensures e.g. Klim jacket -> Klim pants
    # even when the CSV explicit recs list Fox pants as Primary.
    if source_type in GEAR_TYPES and source_brand:
        desired_pre = RUNTIME_COMPLEMENTARY_TYPES.get(source_type, [])
        for desired_type in desired_pre:
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                break
            if desired_type in seen_types:
                continue
            candidates = _GLOBAL_REC_BY_TYPE.get(desired_type, [])
            for rid in candidates:
                if rid in selected_ids or rid == product_id:
                    continue
                if _extract_brand_token(rid) != source_brand:
                    continue
                rec_rt = _detect_riding_type(rid)
                if source_riding in {"street", "dirt"} and rec_rt not in {"unknown", source_riding}:
                    continue
                if _is_vehicle_specific(rid):
                    continue
                if _is_womens_product(rid) != _is_womens_product(product_id):
                    continue
                if _is_youth_product(rid) != _is_youth_product(product_id):
                    continue
                if (source_tier and source_type not in TIER_EXEMPT_TYPES and
                        desired_type not in TIER_EXEMPT_TYPES):
                    if rec_tier_map.get(rid) != source_tier:
                        continue
                selected.append({"id": rid, "label": "Recommended item", "priority": "Primary"})
                selected_ids.add(rid)
                seen_types.add(desired_type)
                break

    # Fill remaining slots preferring distinct types.
    # For gear sources, prefer same-brand gear first (CSV filtered).
    if source_type in GEAR_TYPES and source_brand:
        for rec in filtered:
            rid = rec.get("id")
            if not rid or rid in selected_ids:
                continue
            rec_type = _detect_product_type(rid)
            if rec_type in seen_types:
                continue
            if rec_type in GEAR_TYPES:
                rec_brand = _extract_brand_token(rid)
                if rec_brand and rec_brand != source_brand:
                    continue
            selected.append(rec)
            selected_ids.add(rid)
            seen_types.add(rec_type)
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                return selected

    # Second pass: fill remaining with any brand, enforcing brand diversity.
    seen_brands = {_extract_brand_token(r["id"]) for r in selected if _extract_brand_token(r.get("id", ""))}
    for rec in filtered:
        rid = rec.get("id")
        if not rid or rid in selected_ids:
            continue
        rec_type = _detect_product_type(rid)
        if rec_type in seen_types:
            continue
        rec_brand = _extract_brand_token(rid)
        if comm_only_brand and rec_brand in seen_brands:
            continue
        selected.append(rec)
        selected_ids.add(rid)
        seen_types.add(rec_type)
        if rec_brand:
            seen_brands.add(rec_brand)
        if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
            return selected

    # Supplement from global candidates by complementary type.
    if len(selected) < PER_PRODUCT_RECOMMENDATION_LIMIT:
        if source_type == "helmet" and source_riding == "dirt":
            desired_types = ["jersey", "pants", "gloves"]
        elif source_is_suit:
            desired_types = ["gloves", "boots", "helmet"]
        elif source_is_race_helmet:
            # For race helmets, hardcode one of the two specific Alpinestars race suits.
            suit_slug = _RACE_HELMET_SUITS[hash(product_id) % len(_RACE_HELMET_SUITS)]
            if suit_slug not in selected_ids:
                selected.append({"id": suit_slug, "label": "Recommended item", "priority": "Tertiary"})
                selected_ids.add(suit_slug)
                seen_types.add("jacket")
            desired_types = []
        else:
            desired_types = RUNTIME_COMPLEMENTARY_TYPES.get(source_type, [])
        boots_filter = "smx" if source_is_suit else None
        helmet_filter = SUIT_ALLOWED_HELMET_KEYWORDS if source_is_suit else None
        for desired_type in desired_types:
            if desired_type in seen_types:
                continue
            rid = _pick_global_candidate(product_id, source_type, source_brand, source_riding, source_street_subtype, source_dirt_subtype, desired_type, selected_ids, source_tier=source_tier, rec_tier_map=rec_tier_map, boots_slug_must_contain=boots_filter, helmet_slug_any_of=helmet_filter, gloves_racing_only=source_is_racing, source_is_suit=source_is_suit, apparel_race_only=source_is_race_helmet)
            if not rid:
                continue
            selected.append({"id": rid, "label": "Recommended item", "priority": "Tertiary"})
            selected_ids.add(rid)
            seen_types.add(desired_type)
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                break

    # For helmets, fill remaining slots with same-brand helmet accessories.
    # helmet_accessory is tier-exempt so we never filter by tier here.
    if source_type == "helmet" and len(selected) < PER_PRODUCT_RECOMMENDATION_LIMIT:
        ha_candidates = _GLOBAL_REC_BY_TYPE.get("helmet_accessory", [])
        for rid in ha_candidates:
            if rid in selected_ids or rid == product_id:
                continue
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
            if _is_vehicle_specific(rid):
                continue
            selected.append({"id": rid, "label": "Complements your helmet", "priority": "Secondary"})
            selected_ids.add(rid)
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                break

    # Try any other unseen type if desired map didn't fill all slots.
    boots_filter = "smx" if source_is_suit else None
    helmet_filter = SUIT_ALLOWED_HELMET_KEYWORDS if source_is_suit else None
    if source_is_suit:
        exclude_types = {"pants", "jacket", "helmet_accessory", "communication"}
    elif source_type in {"tshirt", "hat"}:
        exclude_types = {t for t in _GLOBAL_REC_BY_TYPE if t not in {"tshirt", "hat"}}
    else:
        exclude_types = set()
    while len(selected) < PER_PRODUCT_RECOMMENDATION_LIMIT:
        rid, rec_type = _pick_global_candidate_any(product_id, source_type, source_brand, source_riding, source_street_subtype, source_dirt_subtype, selected_ids, seen_types, source_tier=source_tier, rec_tier_map=rec_tier_map, boots_slug_must_contain=boots_filter, helmet_slug_any_of=helmet_filter, gloves_racing_only=source_is_racing, exclude_types=exclude_types, source_is_suit=source_is_suit, apparel_race_only=source_is_race_helmet)
        if not rid:
            break
        selected.append({"id": rid, "label": "Recommended item", "priority": "Tertiary"})
        selected_ids.add(rid)
        seen_types.add(rec_type)

    return selected


def _build_rules_from_reader(reader):
    explicit_map = {}
    category_rules = {}
    rec_tier_map = {}
    source_tier_map = {}
    source_estimated_price_map = {}
    for row in reader:
        product_id = (row.get("Product ID") or "").strip()
        rec_id = (row.get("Recommended Product ID") or "").strip()
        label = (row.get("Label") or "").strip()
        row_type = (row.get("Type") or "Explicit").strip().lower()

        if not product_id or not rec_id:
            continue

        priority = (row.get("Priority") or "").strip()
        tier = (row.get("Price Tier") or "").strip().lower()
        rec = {"id": rec_id, "label": label, "priority": priority}
        if tier in VALID_TIERS:
            rec["tier"] = tier
            rec_tier_map[rec_id] = tier

        src_tier = (row.get("Source Tier") or "").strip().lower()
        if src_tier in VALID_TIERS:
            source_tier_map[product_id] = src_tier
        if rec_id not in source_tier_map and tier in VALID_TIERS:
            source_tier_map[rec_id] = tier

        src_est_price_raw = (row.get("Source Estimated Price") or "").strip()
        est_price_raw = (row.get("Estimated Price") or "").strip()
        try:
            src_est_price = float(src_est_price_raw) if src_est_price_raw else None
        except (TypeError, ValueError):
            src_est_price = None
        try:
            est_price = float(est_price_raw) if est_price_raw else None
        except (TypeError, ValueError):
            est_price = None
        if src_est_price is not None:
            source_estimated_price_map[product_id] = src_est_price
        if rec_id not in source_estimated_price_map and est_price is not None:
            source_estimated_price_map[rec_id] = est_price

        if row_type == "category":
            keywords = tuple(_parse_category_keywords(product_id))
            if not keywords:
                continue
            category_rules.setdefault(keywords, []).append(rec)
        else:
            explicit_map.setdefault(product_id, []).append(rec)

    category_rule_list = [(list(keywords), recs) for keywords, recs in category_rules.items()]
    return explicit_map, category_rule_list, rec_tier_map, source_tier_map, source_estimated_price_map


def _load_rules_from_local_csv():
    if not CSV_PATH.exists():
        return {}, [], {}, {}, {}
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        explicit_map, category_rule_list, rec_tier_map, source_tier_map, source_estimated_price_map = _build_rules_from_reader(csv.DictReader(f))
        _refresh_global_rec_pool(explicit_map, category_rule_list)
        return explicit_map, category_rule_list, rec_tier_map, source_tier_map, source_estimated_price_map


def _fetch_rules_from_remote_csv():
    response = requests.get(CSV_URL, timeout=CSV_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.text
    explicit_map, category_rule_list, rec_tier_map, source_tier_map, source_estimated_price_map = _build_rules_from_reader(csv.DictReader(io.StringIO(payload)))
    _refresh_global_rec_pool(explicit_map, category_rule_list)
    return explicit_map, category_rule_list, rec_tier_map, source_tier_map, source_estimated_price_map


def _load_rules_from_csv(force_refresh: bool = False):
    """
    Returns:
      explicit_map: {product_id: [{"id": "...", "label": "..."}]}
      category_rules: [(["keyword1", ...], [{"id": "...", "label": "..."}]), ...]
    """
    # Local-only mode: read local CSV every request (existing behavior).
    if not CSV_URL:
        explicit_map, category_rules, rec_tier_map, source_tier_map, source_estimated_price_map = _load_rules_from_local_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["rec_tier_map"] = rec_tier_map
            _RULES_CACHE["source_tier_map"] = source_tier_map
            _RULES_CACHE["source_estimated_price_map"] = source_estimated_price_map
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
        explicit_map, category_rules, rec_tier_map, source_tier_map, source_estimated_price_map = _fetch_rules_from_remote_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["rec_tier_map"] = rec_tier_map
            _RULES_CACHE["source_tier_map"] = source_tier_map
            _RULES_CACHE["source_estimated_price_map"] = source_estimated_price_map
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
        explicit_map, category_rules, rec_tier_map, source_tier_map, source_estimated_price_map = _load_rules_from_local_csv()
        with _RULES_LOCK:
            _RULES_CACHE["explicit_map"] = explicit_map
            _RULES_CACHE["category_rules"] = category_rules
            _RULES_CACHE["rec_tier_map"] = rec_tier_map
            _RULES_CACHE["source_tier_map"] = source_tier_map
            _RULES_CACHE["source_estimated_price_map"] = source_estimated_price_map
            _RULES_CACHE["fetched_at"] = time.time()
            _RULES_CACHE["source"] = "local-fallback"
        return explicit_map, category_rules


def get_recommendations(product_id: str, explicit_map: dict, category_rules: list) -> list:
    # 1) Exact or fallback product match from CSV (e.g. arai-corsair-x-bracket-helmet -> arai-corsair-x-helmet)
    if product_id in explicit_map:
        return _apply_recommendation_constraints(product_id, explicit_map[product_id])
    for key in _source_lookup_candidates(product_id):
        if key in explicit_map:
            return _apply_recommendation_constraints(product_id, explicit_map[key])

    # 2) Category fallback rows from CSV
    pid_lower = product_id.lower()
    for keywords, recs in category_rules:
        if any(kw in pid_lower for kw in keywords):
            return _apply_recommendation_constraints(product_id, recs)

    # 3) No CSV match: build from global pool by product type (same rules, no explicit recs)
    return _apply_recommendation_constraints(product_id, [])


def get_recommendations_debug(product_id: str, explicit_map: dict, category_rules: list) -> dict:
    """Return recommendations plus match metadata for debugging."""
    if product_id in explicit_map:
        constrained = _apply_recommendation_constraints(product_id, explicit_map[product_id])
        return {
            "match_type": "explicit",
            "matched_rule": product_id,
            "recommendations": constrained,
        }
    for key in _source_lookup_candidates(product_id):
        if key in explicit_map:
            constrained = _apply_recommendation_constraints(product_id, explicit_map[key])
            return {
                "match_type": "explicit",
                "matched_rule": key,
                "recommendations": constrained,
            }

    pid_lower = product_id.lower()
    for keywords, recs in category_rules:
        if any(kw in pid_lower for kw in keywords):
            constrained = _apply_recommendation_constraints(product_id, recs)
            return {
                "match_type": "category",
                "matched_rule": keywords,
                "recommendations": constrained,
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
        row = {}
        for key in _candidate_catalog_keys(slug):
            if key in catalog_map:
                row = dict(catalog_map.get(key, {}))
                break
        if not row:
            # Also try variant/shorter slug candidates before giving up.
            for candidate in _source_lookup_candidates(slug):
                for key in _candidate_catalog_keys(candidate):
                    if key in catalog_map:
                        row = dict(catalog_map.get(key, {}))
                        break
                if row:
                    break
        if not row:
            row = {"name": slug}
        if not row.get("url"):
            row["url"] = _build_storefront_url(slug)
        elif row.get("url", "").startswith("/") and STOREFRONT_BASE_URL:
            row["url"] = f"{STOREFRONT_BASE_URL}{row['url']}"
        # Always include price key so widget can display it (None when unknown).
        if "price" not in row:
            row["price"] = None
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
    # Prefer live BigCommerce catalog so simulator mirrors storefront data/images.
    catalog_map = _get_catalog_map()
    sample_catalog = {}
    if catalog_map:
        # Pick a broad sample: start with image-backed products sorted by price desc.
        rows = []
        for slug, item in catalog_map.items():
            price = float(item.get("price") or 0.0)
            rows.append((slug, price, item))
        rows.sort(key=lambda x: x[1], reverse=True)
        # Keep first N with images first, then fill with any.
        with_image = [r for r in rows if (r[2].get("image") or "").strip()]
        without_image = [r for r in rows if not (r[2].get("image") or "").strip()]
        picked = (with_image[:60] + without_image[:20])[:80]
        for slug, _, item in picked:
            sample_catalog[slug] = {
                "name": item.get("name") or slug,
                "price": item.get("price"),
                "url": item.get("url") or _build_storefront_url(slug),
                "image": item.get("image") or "",
            }
    else:
        # Local fallback if catalog auth is missing.
        sample_catalog = {
            # --- Race helmets (test race helmet recs) ---
            "agv-pista-gp-rr-soleluna-2023-limited-edition": {"name": "AGV Pista GP RR Soleluna 2023 Limited Edition", "price": 1929.95},
            "shoei-x-fifteen-escalate-helmet": {"name": "Shoei X-Fifteen Escalate Helmet", "price": 999.99},
            "alpinestars-supertech-r10-limited-edition-pedro-acosta-helmet": {"name": "Alpinestars Supertech R10 Acosta LE Helmet", "price": 1549.95},
            # --- Street helmets: premium ---
            "agv-pista-gp-rr-mono-carbon-helmet": {"name": "AGV Pista GP RR Mono Carbon Helmet", "price": 1679.99},
            "arai-corsair-x-bracket-helmet": {"name": "Arai Corsair-X Bracket Helmet", "price": 969.99},
            "shoei-rf-1400-arcane-helmet": {"name": "Shoei RF-1400 Arcane Helmet", "price": 649.99},
            "hjc-rpha-1-senin-helmet": {"name": "HJC RPHA 1 Senin Helmet", "price": 849.99},
            "shoei-neotec-3-satori-helmet": {"name": "Shoei Neotec 3 Satori Helmet", "price": 899.99},
            "schuberth-c5-eclipse-helmet": {"name": "Schuberth C5 Eclipse Helmet", "price": 749.99},
            # --- Street helmets: mid/entry ---
            "agv-k6-s-excite-helmet": {"name": "AGV K6 S Excite Helmet", "price": 499.99},
            "hjc-rpha-71-mapos-helmet": {"name": "HJC RPHA 71 Mapos Helmet", "price": 449.99},
            "scorpion-exo-r1-air-corpus-helmet": {"name": "Scorpion EXO-R1 Air Corpus Helmet", "price": 549.99},
            "icon-airflite-rubatone-helmet": {"name": "Icon Airflite Rubatone Helmet", "price": 250.00},
            "hjc-i10-robust-helmet": {"name": "HJC i10 Robust Helmet", "price": 179.99},
            "bell-qualifier-dlx-mips-helmet": {"name": "Bell Qualifier DLX MIPS Helmet", "price": 219.99},
            # --- Dirt helmets ---
            "fox-v3-rs-mips-motocross-helmet": {"name": "Fox V3 RS MIPS Motocross Helmet", "price": 549.99},
            "bell-moto-10-fasthouse-day-in-the-dirt-25-helmet": {"name": "Bell Moto-10 Fasthouse Helmet", "price": 919.95},
            "shoei-vfx-evo-pinnacle-offroad-helmet": {"name": "Shoei VFX-EVO Pinnacle Off-Road Helmet", "price": 679.99},
            "klim-f3-carbon-helmet-ecedot": {"name": "Klim F3 Carbon Helmet", "price": 499.99},
            "alpinestars-supertech-m10-deegan-monster-helmet": {"name": "Alpinestars Supertech M10 Deegan Helmet", "price": 919.95},
            "fly-racing-formula-s-carbon-protocol-helmet": {"name": "Fly Racing Formula S Carbon Helmet", "price": 1019.95},
            "100-percent-status-helmet": {"name": "100% Status Helmet", "price": 299.95},
            "bell-moto-9s-flex-helmet": {"name": "Bell Moto-9S Flex Helmet", "price": 519.95},
            "troy-lee-designs-se5-carbon-mips-helmet": {"name": "Troy Lee Designs SE5 Carbon MIPS Helmet", "price": 699.95},
            "oneal-sierra-mips-dirt-helmet": {"name": "O'Neal Sierra MIPS Helmet", "price": 149.99},
            # --- Helmet accessories ---
            "shoei-cwr-f2-pinlock-face-shield": {"name": "Shoei CWR-F2 Pinlock Face Shield", "price": 69.99},
            "agv-pista-gp-rr-visor-clear": {"name": "AGV Pista GP RR Visor Clear", "price": 149.99},
            "hjc-rpha-1-cheekpad-set": {"name": "HJC RPHA 1 Cheekpad Set", "price": 49.99},
            "shoei-neotec-3-pinlock-shield": {"name": "Shoei Neotec 3 Pinlock Shield", "price": 79.99},
            "arai-corsair-x-faceshield": {"name": "Arai Corsair-X Face Shield", "price": 109.99},
            # --- Race suits (test race suit recs) ---
            "alpinestars-fusion-1-piece-race-suit": {"name": "Alpinestars Fusion 1-Piece Race Suit", "price": 1734.95},
            "alpinestars-2025-missile-v2-1-piece-ignition-leather-suit": {"name": "Alpinestars 2025 Missile V2 Leather Suit", "price": 1359.95},
            "alpinestars-gp-tech-v4-race-suit": {"name": "Alpinestars GP Tech v4 Race Suit", "price": 1799.99},
            "dainese-laguna-seca-5-1pc-leather-suit": {"name": "Dainese Laguna Seca 5 1PC Leather Suit", "price": 1499.99},
            "rev-it-quantum-2-race-suit": {"name": "REV'IT! Quantum 2 Race Suit", "price": 649.99},
            # --- Street jackets ---
            "alpinestars-gp-tech-v4-leather-jacket": {"name": "Alpinestars GP Tech v4 Leather Jacket", "price": 1299.99},
            "alpinestars-gp-pro-r4-jacket": {"name": "Alpinestars GP Pro R4 Leather Jacket", "price": 749.99},
            "dainese-super-speed-4-leather-jacket": {"name": "Dainese Super Speed 4 Leather Jacket", "price": 649.99},
            "rev-it-eclipse-2-textile-jacket": {"name": "REV'IT! Eclipse 2 Textile Jacket", "price": 199.99},
            "icon-overlord3-mesh-jacket": {"name": "Icon Overlord3 Mesh Jacket", "price": 200.00},
            # --- Adventure / dual-sport jackets ---
            "klim-badlands-pro-jacket": {"name": "Klim Badlands Pro Jacket", "price": 1199.99},
            "firstgear-adventure-touring-jacket": {"name": "FirstGear Adventure Touring Jacket", "price": 349.99},
            # --- Dirt / MX jackets ---
            "fox-legion-off-road-jacket": {"name": "Fox Legion Off-Road Jacket", "price": 259.95},
            "alpinestars-racer-supermatic-jacket": {"name": "Alpinestars Racer Supermatic MX Jacket", "price": 249.95},
            "klim-xc-lite-jacket": {"name": "Klim XC Lite Jacket", "price": 349.99},
            "troy-lee-designs-se-ultra-jacket": {"name": "Troy Lee Designs SE Ultra Jacket", "price": 189.95},
            "100-percent-hydromatic-brisker-jacket": {"name": "100% Hydromatic Brisker Jacket", "price": 99.95},
            # --- Street pants ---
            "alpinestars-missile-v3-leather-pants": {"name": "Alpinestars Missile v3 Leather Pants", "price": 549.99},
            "alpinestars-track-v2-leather-pants": {"name": "Alpinestars Track v2 Leather Pants", "price": 349.99},
            "rev-it-tornado-3-textile-pants": {"name": "REV'IT! Tornado 3 Textile Pants", "price": 299.99},
            "dainese-delta-4-leather-pants": {"name": "Dainese Delta 4 Leather Pants", "price": 499.99},
            # --- Adventure / dirt pants ---
            "klim-badlands-pro-pants": {"name": "Klim Badlands Pro Pants", "price": 899.99},
            "fox-180-lux-motocross-pants": {"name": "Fox 180 Lux MX Pants", "price": 99.95},
            "alpinestars-racer-supermatic-pants": {"name": "Alpinestars Racer Supermatic MX Pants", "price": 199.95},
            "klim-xc-lite-pants": {"name": "Klim XC Lite Pants", "price": 299.99},
            "troy-lee-designs-se-ultra-pants": {"name": "Troy Lee Designs SE Ultra Pants", "price": 179.95},
            "oneal-element-motocross-pants": {"name": "O'Neal Element MX Pants", "price": 59.99},
            "100-percent-ridefit-pants": {"name": "100% Ridefit Pants", "price": 139.95},
            # --- MX jerseys ---
            "fox-racing-180-honda-jersey": {"name": "Fox 180 Honda Jersey", "price": 44.95},
            "alpinestars-racer-supermatic-jersey": {"name": "Alpinestars Racer Supermatic Jersey", "price": 69.95},
            "fasthouse-grindhouse-jersey": {"name": "Fasthouse Grindhouse Jersey", "price": 39.95},
            "troy-lee-designs-gp-pro-jersey": {"name": "Troy Lee Designs GP Pro Jersey", "price": 64.95},
            "100-percent-r-core-jersey": {"name": "100% R-Core Jersey", "price": 39.95},
            "oneal-element-jersey": {"name": "O'Neal Element Jersey", "price": 29.99},
            "klim-xc-jersey": {"name": "Klim XC Jersey", "price": 79.99},
            # --- Gloves: street / race ---
            "alpinestars-gp-pro-r4-gloves": {"name": "Alpinestars GP Pro R4 Gloves", "price": 299.99},
            "alpinestars-gp-tech-v2-gloves": {"name": "Alpinestars GP Tech v2 Gloves", "price": 199.95},
            "dainese-full-metal-7-gloves": {"name": "Dainese Full Metal 7 Gloves", "price": 599.99},
            "rev-it-control-2-gloves": {"name": "REV'IT! Control 2 Gloves", "price": 149.99},
            "rev-it-sand-4-adventure-gloves": {"name": "REV'IT! Sand 4 Adventure Gloves", "price": 109.99},
            # --- Dirt protection / armor ---
            "alpinestars-bionic-tech-v3-chest-protector": {"name": "Alpinestars Bionic Tech v3 Chest Protector", "price": 299.95},
            "fox-titan-sport-jacket-chest-protector": {"name": "Fox Titan Sport Jacket Chest Protector", "price": 119.95},
            "klim-dss-armor-chest-protector": {"name": "Klim D3O Body Armor Chest Protector", "price": 149.99},
            "100-percent-teratec-plus-elbow-guard": {"name": "100% Teratec+ Elbow Guard", "price": 69.95},
            "100-percent-teratec-plus-knee-guard": {"name": "100% Teratec+ Knee Guard", "price": 79.95},
            "leatt-3df-4-5-knee-shin-guard": {"name": "Leatt 3DF 4.5 Knee/Shin Guard", "price": 99.95},
            "alpinestars-nucleon-kr-1-back-protector": {"name": "Alpinestars Nucleon KR-1 Back Protector", "price": 149.99},
            "fox-rpc-chest-protector": {"name": "Fox RPc Chest Protector", "price": 89.95},
            # --- Gloves: dirt / MX ---
            "fox-dirtpaw-mx-gloves": {"name": "Fox Dirtpaw MX Gloves", "price": 29.95},
            "alpinestars-radar-tracking-gloves": {"name": "Alpinestars Radar MX Gloves", "price": 79.99},
            "klim-badlands-aero-pro-short-gloves": {"name": "Klim Badlands Aero Pro Short Gloves", "price": 89.99},
            "100-percent-brisker-gloves": {"name": "100% Brisker MX Gloves", "price": 34.50},
            "troy-lee-designs-air-gloves": {"name": "Troy Lee Designs Air Gloves", "price": 29.95},
            "oneal-matrix-gloves": {"name": "O'Neal Matrix Gloves", "price": 19.99},
            # --- Boots: street ---
            "alpinestars-supertech-r-boots": {"name": "Alpinestars Supertech R Boots", "price": 499.99},
            "alpinestars-smx-6-v2-vented-boots": {"name": "Alpinestars SMX-6 v2 Vented Boots", "price": 299.95},
            "dainese-torque-3-out-boots": {"name": "Dainese Torque 3 Out Boots", "price": 449.99},
            "tcx-rt-race-pro-air-boots": {"name": "TCX RT-Race Pro Air Boots", "price": 359.99},
            "sidi-crossfire-3-srs-boots": {"name": "Sidi Crossfire 3 SRS Boots", "price": 549.99},
            # --- Boots: dirt / MX ---
            "alpinestars-tech-10-supervented-boots-2025": {"name": "Alpinestars Tech-10 Supervented Boots", "price": 739.95},
            "fox-comp-boots": {"name": "Fox Comp Boots", "price": 149.95},
            "gaerne-sg-22-boots": {"name": "Gaerne SG-22 Boots", "price": 619.99},
            "oneal-rider-pro-boots": {"name": "O'Neal Rider Pro MX Boots", "price": 119.99},
            "sidi-crossfire-3-srs-boots": {"name": "Sidi Crossfire 3 SRS Boots", "price": 549.99},
            "leatt-4-5-enduro-boot": {"name": "Leatt 4.5 Enduro Boot", "price": 279.95},
            # --- Communication ---
            "cardo-packtalk-edge-jbl-single-bluetooth-unit": {"name": "Cardo Packtalk Edge JBL Single", "price": 349.99},
            "cardo-packtalk-neo-single-bluetooth-unit": {"name": "Cardo Packtalk Neo Single", "price": 249.99},
            "sena-50s-communication-system-with-harman-kardon-speakers-single-unit": {"name": "Sena 50S Harman Kardon Single", "price": 359.99},
            "cardo-freecom-4x-jbl-single-unit": {"name": "Cardo Freecom 4x JBL Single", "price": 199.99},
            "cardo-spirit-hd-single-unit": {"name": "Cardo Spirit HD Single", "price": 109.99},
            # --- Airbag / backpacks (test airbag vest fix) ---
            "klim-atlas-14-avalanche-airbag-vest": {"name": "Klim Atlas 14 Avalanche Airbag Vest", "price": 749.99},
            "klim-aspect-16-avalanche-airbag-backpack": {"name": "Klim Aspect 16 Avalanche Airbag Backpack", "price": 649.99},
            "kriega-r20-backpack": {"name": "Kriega R20 Backpack", "price": 179.99},
            "klim-nac-pak-backpack": {"name": "Klim NAC Pak Backpack", "price": 249.99},
            # --- Hydration ---
            "kriega-hydrapak-hydration-reservoir-3l": {"name": "Kriega Hydrapak Reservoir 3L", "price": 44.99},
            "klim-hydradri-hydration-pack": {"name": "Klim Hydradri Hydration Pack", "price": 69.99},
            # --- Luggage ---
            "kriega-os-12-adventure-tail-bag": {"name": "Kriega OS-12 Adventure Tail Bag", "price": 119.99},
            "kriega-us20-drypack": {"name": "Kriega US-20 Drypack", "price": 134.99},
            "nelson-rigg-commuter-lite-tank-bag": {"name": "Nelson-Rigg Commuter Lite Tank Bag", "price": 64.95},
            # --- T-shirts (test tshirt recs) ---
            "fasthouse-elevate-ss-t-shirt": {"name": "Fasthouse Elevate SS T-Shirt", "price": 32.00},
            "alpinestars-blaze-2-0-t-shirt": {"name": "Alpinestars Blaze 2.0 T-Shirt", "price": 28.95},
            "alpinestars-le-dirt-studios-t-shirt": {"name": "Alpinestars Le Dirt Studios T-Shirt", "price": 65.00},
            "fox-racing-honda-premium-t-shirt": {"name": "Fox Racing Honda Premium T-Shirt", "price": 34.95},
            # --- Hats (test hat recs) ---
            "fasthouse-elevate-snapback-hat": {"name": "Fasthouse Elevate Snapback Hat", "price": 30.00},
            "alpinestars-corp-trucker-hat": {"name": "Alpinestars Corp Trucker Hat", "price": 26.95},
            "fox-racing-absolute-flexfit-hat": {"name": "Fox Racing Absolute Flexfit Hat", "price": 34.95},
            "dbk-basics-4fifty-snapback-hat": {"name": "DBK Basics 4Fifty Snapback Hat", "price": 36.95},
            # --- Tires ---
            "dunlop-sportmax-q5-sportbike-tires": {"name": "Dunlop Sportmax Q5 Tires", "price": 354.99},
            "michelin-pilot-road-6-touring-tires": {"name": "Michelin Pilot Road 6 Tires", "price": 289.99},
            "pirelli-scorpion-trail-ii-adventure-tire": {"name": "Pirelli Scorpion Trail II Adventure Tire", "price": 199.99},
            "dunlop-geomax-mx34-motocross-tire": {"name": "Dunlop Geomax MX34 Motocross Tire", "price": 89.99},
            "maxxis-maxxcross-mx-tire": {"name": "Maxxis Maxxcross MX Tire", "price": 79.99},
            # --- Brakes ---
            "ebc-fa103-brake-pad": {"name": "EBC FA103 Brake Pad", "price": 40.95},
            "galfer-hh-sintered-brake-rotor": {"name": "Galfer HH Sintered Brake Rotor", "price": 189.99},
            "vesrah-rjl-race-brake-pad": {"name": "Vesrah RJL Race Brake Pad", "price": 59.95},
            # --- Chain / drivetrain ---
            "rk-520-max-x-gold-x-ring-chain": {"name": "RK 520 MAX-X Gold X-Ring Chain", "price": 159.99},
            "renthal-ultralight-rear-sprocket": {"name": "Renthal Ultralight Rear Sprocket", "price": 69.99},
            "motul-chain-lube-factory-line": {"name": "Motul Chain Lube Factory Line", "price": 15.99},
            "maxima-chain-wax": {"name": "Maxima Chain Wax", "price": 11.99},
            # --- Oil / fluids ---
            "motul-7100-10w40-synthetic-oil": {"name": "Motul 7100 10W40 Synthetic Oil", "price": 54.99},
            "motul-300v-factory-line-15w50-oil": {"name": "Motul 300V Factory Line 15W50 Oil", "price": 79.99},
            "maxima-castor-927-2-stroke-oil": {"name": "Maxima Castor 927 2-Stroke Oil", "price": 24.99},
            "maxima-premium-4-4t-motorcycle-oil": {"name": "Maxima Premium 4 Motorcycle Oil 10W40", "price": 14.99},
            "motorex-gear-oil-10w30": {"name": "Motorex Gear Oil 10W30", "price": 20.99},
            "bel-ray-fork-oil-10w": {"name": "Bel-Ray Fork Oil 10W", "price": 16.99},
            "maxima-premium-transmission-oil": {"name": "Maxima Premium Transmission Oil", "price": 12.99},
            "honda-hp4-4-stroke-engine-oil": {"name": "Honda HP4 4-Stroke Engine Oil", "price": 18.99},
            # --- Air filters ---
            "twin-air-air-filter-for-2024-kawasaki-kx450": {"name": "Twin Air Filter 2024 KX450", "price": 38.95},
            "k-and-n-air-filter-yamaha-yz250f": {"name": "K&N Air Filter Yamaha YZ250F", "price": 49.99},
            "bmc-air-filter-ducati-panigale-v4": {"name": "BMC Air Filter Ducati Panigale V4", "price": 99.99},
            # --- Parts / consumables ---
            "ngk-iridium-spark-plug": {"name": "NGK Iridium Spark Plug", "price": 12.99},
            "yuasa-ytx14-bs-battery": {"name": "Yuasa YTX14-BS Battery", "price": 129.99},
            "all-balls-racing-wheel-bearing-kit": {"name": "All Balls Racing Wheel Bearing Kit", "price": 39.99},
            "tusk-clutch-lever-assembly": {"name": "Tusk Clutch Lever Assembly", "price": 24.99},
            "cv4-performance-radiator-hose-kit": {"name": "CV4 Performance Radiator Hose Kit", "price": 89.99},
            # --- Misc ---
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

      .mini-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 9998; display: none; }
      .mini-overlay.open { display: block; }
      .mini-drawer {
        position: fixed; top: 0; right: 0; height: 100vh; width: min(430px, 95vw);
        background: #fff; z-index: 9999; transform: translateX(110%);
        transition: transform .2s ease; border-left: 1px solid #e5e5e5;
        display: flex; flex-direction: column;
      }
      .mini-drawer.open { transform: translateX(0); }
      .mini-head { padding: 14px 16px; border-bottom: 1px solid #e5e5e5; display: flex; align-items: center; justify-content: space-between; }
      .mini-body { padding: 14px 16px; overflow-y: auto; }
      .mini-cart-items { margin-bottom: 12px; }
      .mini-close { background: transparent; color: #111; border: 1px solid #d1d5db; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h2>Performance Cycle Recommendation Simulator</h2>
      <p class="muted">Simulates instant mini-cart popup recommendations after Add to Cart.</p>
      <div class="panel">
        <div class="row" style="margin-bottom:8px;">
          <h3 style="margin:0;">Catalog (click to add to cart)</h3>
          <button class="secondary" id="open-drawer">Open Mini Cart</button>
        </div>
        <div class="grid" id="catalog"></div>
      </div>
    </div>

    <div class="mini-overlay" id="mini-overlay"></div>
    <aside class="mini-drawer" id="mini-drawer">
      <div class="mini-head">
        <strong>Mini Cart</strong>
        <button class="mini-close" id="close-drawer">Close</button>
      </div>
      <div class="mini-body">
        <div class="row" style="margin-bottom:8px;">
          <span class="muted">Items in cart</span>
          <button class="secondary" id="clear-cart">Clear Cart</button>
        </div>
        <div class="mini-cart-items" id="cart-pills"></div>
        <div id="fbt-widget-drawer"></div>
      </div>
    </aside>
    <script>window.__CATALOG__ = {{ catalog | safe }};</script>
    <script>window.__STOREFRONT_BASE__ = {{ storefront_base | tojson }};</script>
    <script src="/widget/fbt-widget.js?v=6"></script>
    <script>
      const catalog = window.__CATALOG__;
      let cartIds = [];
      let widgetBooted = false;
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
      function openDrawer() {
        document.getElementById('mini-overlay').classList.add('open');
        document.getElementById('mini-drawer').classList.add('open');
      }

      function closeDrawer() {
        document.getElementById('mini-overlay').classList.remove('open');
        document.getElementById('mini-drawer').classList.remove('open');
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
        openDrawer();
        if (!window.FBTWidget) return;
        if (!widgetBooted) {
          FBTWidget.init({
            apiUrl: window.location.origin,
            cartProductIds: cartIds,
            productCatalog: catalog,
            productUrlBase: window.__STOREFRONT_BASE__ || '',
            containerId: 'fbt-widget-drawer',
            title: 'Frequently Bought Together',
            showAddButton: false,
            onAddToCart: null
          });
          widgetBooted = true;
        } else {
          FBTWidget.refresh(cartIds);
        }
      }
      document.getElementById('open-drawer').addEventListener('click', openDrawer);
      document.getElementById('close-drawer').addEventListener('click', closeDrawer);
      document.getElementById('mini-overlay').addEventListener('click', closeDrawer);
      document.getElementById('clear-cart').addEventListener('click', () => {
        cartIds = [];
        renderCart();
        if (widgetBooted && window.FBTWidget) FBTWidget.refresh(cartIds);
      });
      renderCatalog();
      renderCart();
    </script>
  </body>
</html>
"""
    storefront_base = STOREFRONT_BASE_URL or "https://www.performancecycle.com"
    return render_template_string(
        html,
        catalog=json.dumps(sample_catalog),
        storefront_base=storefront_base,
    )


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
                    or PRIORITY_RANK.get(incoming, 99) < PRIORITY_RANK.get(current, 99)
                ):
                    rec_info[rid]["priority"] = incoming

    cart_types = set()
    for pid in cart_product_ids:
        ptype = _detect_product_type(pid)
        cart_types.add(ptype)
        # Some helmet slugs (e.g. agv-pista-gp-rr-soleluna) don't contain "helmet";
        # detect them via race-helmet keywords so same-type filtering still works.
        if _is_race_helmet(pid):
            cart_types.add("helmet")
    recommendations = [
        {"id": rid, "label": info["label"] or None, "priority": info.get("priority") or None}
        for rid, info in sorted(
            rec_info.items(),
            key=lambda x: (-x[1]["count"], PRIORITY_RANK.get(x[1].get("priority", ""), 99)),
        )
        if _detect_product_type(rid) not in cart_types or _detect_product_type(rid) in MULTI_REC_TYPES
    ]

    return jsonify({
        "recommendations": recommendations,
        "cart_products": cart_product_ids,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

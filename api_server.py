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
    ("helmet_accessory", ["visor", "face-shield", "faceshield", "shield", "pinlock", "cheekpad", "cheek-pad", "cheek pad", "chin curtain", "curtain"]),
    ("helmet", ["helmet"]),
    ("jacket", ["jacket", "coat", "parka"]),
    ("pants", ["pant", "trouser", "bibs"]),
    ("gloves", ["glove", "gauntlet"]),
    ("boots", ["boot"]),
    ("hydration", ["hydration", "hydradri", "hydralite", "reservoir", "water-pack", "water pack", "bladder"]),
    ("luggage", ["tail-bag", "tail bag", "tank-bag", "tank bag", "drypack", "duffel", "fender-bag", "fender pack", "tool-pack", "tool pack", "toolbag", "fanny", "waist pack", "hip pack", "sling"]),
    ("backpack", ["backpack", "luggage"]),
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
    "pants": ["jacket", "gloves", "boots", "helmet"],
    "jacket": ["pants", "gloves", "boots", "helmet"],
    "helmet": ["helmet_accessory", "gloves", "jacket", "boots"],
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
    "communication": ["helmet", "gloves"],
    "protection": ["jacket", "pants", "gloves"],
}
GEAR_TYPES = {
    "helmet", "helmet_accessory", "jacket", "pants", "gloves", "boots",
    "backpack", "communication", "protection",
}
PARTS_TYPES = {"air_filter", "oil", "tire", "brake", "chain", "parts"}
BACKPACK_ALLOWED_TYPES = {"hydration", "luggage"}
VEHICLE_SPECIFIC_TERMS = {
    "harley", "davidson", "goldwing", "indian", "polaris", "can-am",
    "spyder", "ryker", "slingshot",
}

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
        "trail", "atv", "cross", "dualsport", "dual-sport", "adventure", "adv",
        "sx", "fx", "kawasaki kx", "yz", "crf", "rmz", "ktm exc", "husqvarna fe",
        "dirtpaw", "patrol", "kinetic", "f-16", "f 16",
        "moto-9", "moto 9", "formula-cc",
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
    ],
}
DIRT_ONLY_BRANDS = {
    "fly", "fox", "fasthouse", "troy", "seven", "shift", "thor", "one", "leatt",
}
STREET_ONLY_BRANDS = {
    "dainese", "cortech", "noru", "highway", "rst", "olympia", "firstgear",
    "tourmaster", "warm", "scorpion",
    "cardo", "sena", "schuberth", "boss",
}
STREET_RACE_KEYWORDS = [
    "race", "racing", "track", "pista", "gp", "supersport", "sportbike",
    "r10", "x 15", "x fifteen", "rf 1400", "corsair",
]
STREET_TOURING_KEYWORDS = [
    "tour", "touring", "adventure", "adv", "enduro",
    "dual-sport", "dualsport", "commuter", "cruiser",
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
    text = _normalize_slug_text(slug).replace("-", " ")
    dirt_hit = any(keyword in text for keyword in RIDING_TYPE_RULES["dirt"])
    street_hit = any(keyword in text for keyword in RIDING_TYPE_RULES["street"])
    if dirt_hit and not street_hit:
        return "dirt"
    if street_hit and not dirt_hit:
        return "street"
    brand = _extract_brand_token(slug)
    if brand in DIRT_ONLY_BRANDS:
        return "dirt"
    if brand in STREET_ONLY_BRANDS:
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


def _is_vehicle_specific(slug: str) -> bool:
    text = _normalize_slug_text(slug)
    return any(term in text for term in VEHICLE_SPECIFIC_TERMS)


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


def _pick_global_candidate(source_product_id: str, source_type: str, source_brand: str, source_riding: str, source_street_subtype: str, rec_type: str, selected_ids: set) -> str:
    candidates = _GLOBAL_REC_BY_TYPE.get(rec_type, [])
    # Special fallback preference:
    # For jacket/pants -> gloves, if same-brand gloves are unavailable,
    # prefer Alpinestars gloves.
    if source_type in {"jacket", "pants"} and rec_type == "gloves":
        for rid in candidates:
            if rid in selected_ids:
                continue
            if rid == source_product_id:
                continue
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand == source_brand:
                return rid
        for rid in candidates:
            if rid in selected_ids:
                continue
            if rid == source_product_id:
                continue
            rec_brand = _extract_brand_token(rid)
            if rec_brand == "alpinestars":
                return rid

    for rid in candidates:
        if rid in selected_ids:
            continue
        if rid == source_product_id:
            continue
        if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
            continue
        if source_riding in {"street", "dirt"} and _detect_riding_type(rid) != source_riding:
            continue
        if source_riding == "street" and source_street_subtype == "race" and _detect_street_subtype(rid) == "touring":
            continue
        if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
            continue
        if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
            continue
        if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
            continue
        if source_type == "backpack" and rec_type == "backpack":
            continue
        if source_type in {"jacket", "pants"} and rec_type in {"jacket", "pants", "gloves"}:
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        return rid
    return ""


def _pick_global_candidate_any(source_product_id: str, source_type: str, source_brand: str, source_riding: str, source_street_subtype: str, selected_ids: set, used_types: set) -> tuple:
    for rec_type, candidates in _GLOBAL_REC_BY_TYPE.items():
        if rec_type in used_types:
            continue
        for rid in candidates:
            if rid in selected_ids:
                continue
            if rid == source_product_id:
                continue
            if not _is_vehicle_specific(source_product_id) and _is_vehicle_specific(rid):
                continue
            if source_riding in {"street", "dirt"} and _detect_riding_type(rid) != source_riding:
                continue
            if source_riding == "street" and source_street_subtype == "race" and _detect_street_subtype(rid) == "touring":
                continue
            if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
                continue
            if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
                continue
            if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
                continue
            if source_type == "backpack" and rec_type == "backpack":
                continue
            if source_type in {"jacket", "pants"} and rec_type in {"jacket", "pants", "gloves"}:
                rec_brand = _extract_brand_token(rid)
                if source_brand and rec_brand and source_brand != rec_brand:
                    continue
            if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
                rec_brand = _extract_brand_token(rid)
                if source_brand and rec_brand and source_brand != rec_brand:
                    continue
            return rid, rec_type
    return "", ""


def _apply_recommendation_constraints(product_id: str, recommendations: list) -> list:
    """
    Runtime constraints:
    - For jacket/pants sources, jacket/pants recommendations must match source brand.
    - Return up to 3 recommendations with preference for distinct product types.
    """
    source_type = _detect_product_type(product_id)
    source_brand = _extract_brand_token(product_id)
    source_riding = _detect_riding_type(product_id)
    source_street_subtype = _detect_street_subtype(product_id)
    ordered = _sort_by_priority(recommendations)

    filtered = []
    for rec in ordered:
        rid = (rec.get("id") or "").strip()
        if not rid:
            continue
        rec_type = _detect_product_type(rid)
        rec_riding = _detect_riding_type(rid)
        rec_street_subtype = _detect_street_subtype(rid)
        if not _is_vehicle_specific(product_id) and _is_vehicle_specific(rid):
            continue
        if source_riding in {"street", "dirt"} and rec_riding != source_riding:
            continue
        if source_riding == "street" and source_street_subtype == "race" and rec_street_subtype == "touring":
            continue

        # Hard rule: parts/consumables should not recommend riding gear.
        if source_type in PARTS_TYPES and rec_type in GEAR_TYPES:
            continue
        # Symmetric safety: riding gear should not recommend parts/consumables.
        if source_type in GEAR_TYPES and rec_type in PARTS_TYPES:
            continue
        # Backpack should recommend backpack-adjacent items only.
        if source_type == "backpack" and rec_type not in BACKPACK_ALLOWED_TYPES:
            continue
        if source_type == "backpack" and rec_type == "backpack":
            continue

        # Brand consistency for apparel-to-apparel recommendations.
        if source_type in {"jacket", "pants"} and rec_type in {"jacket", "pants", "gloves"}:
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        # Brand consistency for helmets and fit-sensitive helmet products.
        if source_type == "helmet" and rec_type in {"helmet", "helmet_accessory"}:
            rec_brand = _extract_brand_token(rid)
            if source_brand and rec_brand and source_brand != rec_brand:
                continue
        filtered.append(rec)

    # For helmets, always reserve one slot for a price-tiered comm system.
    selected = []
    selected_ids = set()
    seen_types = set()

    if source_type == "helmet":
        comm_id = _pick_tiered_comm(product_id, selected_ids)
        if comm_id:
            selected.append({"id": comm_id, "label": "Pairs with your helmet", "priority": "Secondary"})
            selected_ids.add(comm_id)
            seen_types.add("communication")

    # Fill remaining slots preferring distinct types.
    for rec in filtered:
        rid = rec.get("id")
        if not rid or rid in selected_ids:
            continue
        rec_type = _detect_product_type(rid)
        if rec_type in seen_types:
            continue
        selected.append(rec)
        selected_ids.add(rid)
        seen_types.add(rec_type)
        if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
            return selected

    # Supplement from global candidates by complementary type.
    if len(selected) < PER_PRODUCT_RECOMMENDATION_LIMIT:
        desired_types = RUNTIME_COMPLEMENTARY_TYPES.get(source_type, [])
        for desired_type in desired_types:
            if desired_type in seen_types:
                continue
            rid = _pick_global_candidate(product_id, source_type, source_brand, source_riding, source_street_subtype, desired_type, selected_ids)
            if not rid:
                continue
            selected.append({"id": rid, "label": "Recommended item", "priority": "Tertiary"})
            selected_ids.add(rid)
            seen_types.add(desired_type)
            if len(selected) >= PER_PRODUCT_RECOMMENDATION_LIMIT:
                break

    # For helmets, fill remaining slots with same-brand helmet accessories.
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
    while len(selected) < PER_PRODUCT_RECOMMENDATION_LIMIT:
        rid, rec_type = _pick_global_candidate_any(product_id, source_type, source_brand, source_riding, source_street_subtype, selected_ids, seen_types)
        if not rid:
            break
        selected.append({"id": rid, "label": "Recommended item", "priority": "Tertiary"})
        selected_ids.add(rid)
        seen_types.add(rec_type)

    return selected


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
        explicit_map, category_rule_list = _build_rules_from_reader(csv.DictReader(f))
        _refresh_global_rec_pool(explicit_map, category_rule_list)
        return explicit_map, category_rule_list


def _fetch_rules_from_remote_csv():
    response = requests.get(CSV_URL, timeout=CSV_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.text
    explicit_map, category_rule_list = _build_rules_from_reader(csv.DictReader(io.StringIO(payload)))
    _refresh_global_rec_pool(explicit_map, category_rule_list)
    return explicit_map, category_rule_list


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
        return _apply_recommendation_constraints(product_id, explicit_map[product_id])

    # 2) Category fallback rows from CSV
    pid_lower = product_id.lower()
    for keywords, recs in category_rules:
        if any(kw in pid_lower for kw in keywords):
            return _apply_recommendation_constraints(product_id, recs)

    # 3) No match
    return []


def get_recommendations_debug(product_id: str, explicit_map: dict, category_rules: list) -> dict:
    """Return recommendations plus match metadata for debugging."""
    if product_id in explicit_map:
        constrained = _apply_recommendation_constraints(product_id, explicit_map[product_id])
        return {
            "match_type": "explicit",
            "matched_rule": product_id,
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
        picked = (with_image[:18] + without_image[:6])[:24]
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
            # --- Helmets: premium ---
            "agv-pista-gp-rr-mono-carbon-helmet": {"name": "AGV Pista GP RR Mono Carbon Helmet", "price": 1679.99},
            "shoei-x-fifteen-escalate-helmet": {"name": "Shoei X-Fifteen Escalate Helmet", "price": 999.99},
            "arai-corsair-x-bracket-helmet": {"name": "Arai Corsair-X Bracket Helmet", "price": 969.99},
            "shoei-rf-1400-arcane-helmet": {"name": "Shoei RF-1400 Arcane Helmet", "price": 649.99},
            "hjc-rpha-1-senin-helmet": {"name": "HJC RPHA 1 Senin Helmet", "price": 849.99},
            "shoei-neotec-3-satori-helmet": {"name": "Shoei Neotec 3 Satori Helmet", "price": 899.99},
            "schuberth-c5-eclipse-helmet": {"name": "Schuberth C5 Eclipse Helmet", "price": 749.99},
            # --- Helmets: mid ---
            "agv-k6-s-excite-helmet": {"name": "AGV K6 S Excite Helmet", "price": 499.99},
            "hjc-rpha-71-mapos-helmet": {"name": "HJC RPHA 71 Mapos Helmet", "price": 449.99},
            "scorpion-exo-r1-air-corpus-helmet": {"name": "Scorpion EXO-R1 Air Corpus Helmet", "price": 549.99},
            "icon-airflite-rubatone-helmet": {"name": "Icon Airflite Rubatone Helmet", "price": 250.00},
            "klim-f5-koroyd-helmet": {"name": "Klim F5 Koroyd Helmet", "price": 549.99},
            # --- Helmets: entry ---
            "hjc-i10-robust-helmet": {"name": "HJC i10 Robust Helmet", "price": 179.99},
            "ls2-stream-ii-lux-helmet": {"name": "LS2 Stream II Lux Helmet", "price": 159.99},
            "bell-qualifier-dlx-mips-helmet": {"name": "Bell Qualifier DLX MIPS Helmet", "price": 219.99},
            "icon-airform-conflux-helmet": {"name": "Icon Airform Conflux Helmet", "price": 200.00},
            # --- Helmets: dirt / off-road ---
            "fox-v3-rs-mips-motocross-helmet": {"name": "Fox V3 RS MIPS Motocross Helmet", "price": 549.99},
            "shoei-vfx-evo-pinnacle-offroad-helmet": {"name": "Shoei VFX-EVO Pinnacle Off-Road Helmet", "price": 679.99},
            "klim-f3-carbon-helmet-ecedot": {"name": "Klim F3 Carbon Helmet", "price": 499.99},
            # --- Helmet accessories ---
            "shoei-cwr-f2-pinlock-face-shield": {"name": "Shoei CWR-F2 Pinlock Face Shield", "price": 69.99},
            "agv-pista-gp-rr-visor-clear": {"name": "AGV Pista GP RR Visor Clear", "price": 149.99},
            "hjc-rpha-1-cheekpad-set": {"name": "HJC RPHA 1 Cheekpad Set", "price": 49.99},
            "shoei-neotec-3-pinlock-shield": {"name": "Shoei Neotec 3 Pinlock Shield", "price": 79.99},
            "arai-corsair-x-faceshield": {"name": "Arai Corsair-X Face Shield", "price": 109.99},
            "icon-airflite-face-shield-rst-silver": {"name": "Icon Airflite Face Shield RST Silver", "price": 45.00},
            # --- Jackets ---
            "klim-badlands-pro-jacket": {"name": "Klim Badlands Pro Jacket", "price": 1199.99},
            "alpinestars-gp-tech-v4-leather-jacket": {"name": "Alpinestars GP Tech v4 Leather Jacket", "price": 1299.99},
            "rev-it-eclipse-2-textile-jacket": {"name": "REV'IT! Eclipse 2 Textile Jacket", "price": 199.99},
            "dainese-super-speed-4-leather-jacket": {"name": "Dainese Super Speed 4 Leather Jacket", "price": 649.99},
            "icon-overlord3-mesh-jacket": {"name": "Icon Overlord3 Mesh Jacket", "price": 200.00},
            "firstgear-adventure-touring-jacket": {"name": "FirstGear Adventure Touring Jacket", "price": 349.99},
            "fox-legion-off-road-jacket": {"name": "Fox Legion Off-Road Jacket", "price": 259.95},
            # --- Pants ---
            "klim-badlands-pro-pants": {"name": "Klim Badlands Pro Pants", "price": 899.99},
            "alpinestars-missile-v3-leather-pants": {"name": "Alpinestars Missile v3 Leather Pants", "price": 549.99},
            "rev-it-tornado-3-textile-pants": {"name": "REV'IT! Tornado 3 Textile Pants", "price": 299.99},
            "dainese-delta-4-leather-pants": {"name": "Dainese Delta 4 Leather Pants", "price": 499.99},
            "icon-overlord-overpant": {"name": "Icon Overlord Overpant", "price": 175.00},
            # --- Gloves ---
            "alpinestars-gp-pro-r4-gloves": {"name": "Alpinestars GP Pro R4 Gloves", "price": 299.99},
            "dainese-full-metal-7-gloves": {"name": "Dainese Full Metal 7 Gloves", "price": 599.99},
            "rev-it-sand-4-adventure-gloves": {"name": "REV'IT! Sand 4 Adventure Gloves", "price": 109.99},
            "klim-badlands-aero-pro-short-gloves": {"name": "Klim Badlands Aero Pro Short Gloves", "price": 89.99},
            "icon-pursuit-classic-perforated-gloves": {"name": "Icon Pursuit Classic Perforated Gloves", "price": 75.00},
            "fox-dirtpaw-mx-gloves": {"name": "Fox Dirtpaw MX Gloves", "price": 29.95},
            # --- Boots ---
            "alpinestars-supertech-r-boots": {"name": "Alpinestars Supertech R Boots", "price": 499.99},
            "sidi-crossfire-3-srs-boots": {"name": "Sidi Crossfire 3 SRS Boots", "price": 549.99},
            "tcx-rt-race-pro-air-boots": {"name": "TCX RT-Race Pro Air Boots", "price": 359.99},
            "dainese-torque-3-out-boots": {"name": "Dainese Torque 3 Out Boots", "price": 449.99},
            "icon-el-bajo-boot": {"name": "Icon El Bajo Boot", "price": 200.00},
            "forma-adventure-low-waterproof-boot": {"name": "Forma Adventure Low WP Boot", "price": 219.99},
            # --- Communication ---
            "cardo-packtalk-edge-jbl-single-bluetooth-unit": {"name": "Cardo Packtalk Edge JBL Single", "price": 349.99},
            "cardo-packtalk-neo-single-bluetooth-unit": {"name": "Cardo Packtalk Neo Single", "price": 249.99},
            "sena-50s-communication-system-with-harman-kardon-speakers-single-unit": {"name": "Sena 50S Harman Kardon Single", "price": 359.99},
            "sena-30k-hd-communication-system-single-unit": {"name": "Sena 30K HD Communication", "price": 299.00},
            "cardo-freecom-4x-jbl-single-unit": {"name": "Cardo Freecom 4x JBL Single", "price": 199.99},
            "cardo-freecom-2x-jbl-single-unit": {"name": "Cardo Freecom 2x JBL Single", "price": 129.99},
            "cardo-spirit-hd-single-unit": {"name": "Cardo Spirit HD Single", "price": 109.99},
            "sena-20s-evo-hd-communication-system-single": {"name": "Sena 20S EVO HD Single", "price": 259.99},
            # --- Protection / armor ---
            "alpinestars-nucleon-kr-1-back-protector": {"name": "Alpinestars Nucleon KR-1 Back Protector", "price": 149.99},
            "dainese-pro-armor-chest-protector": {"name": "Dainese Pro-Armor Chest Protector", "price": 69.99},
            "forcefield-pro-l2k-evo-back-protector": {"name": "Forcefield Pro L2K Evo Back Protector", "price": 199.99},
            "rev-it-seeflex-rv12-knee-protector": {"name": "REV'IT! SEEFLEX RV12 Knee Protector", "price": 49.99},
            # --- Backpacks ---
            "kriega-r20-backpack": {"name": "Kriega R20 Backpack", "price": 179.99},
            "ogio-mach-5-backpack": {"name": "OGIO Mach 5 Backpack", "price": 259.99},
            "klim-nac-pak-backpack": {"name": "Klim NAC Pak Backpack", "price": 249.99},
            # --- Hydration ---
            "kriega-hydrapak-hydration-reservoir-3l": {"name": "Kriega Hydrapak Reservoir 3L", "price": 44.99},
            "klim-hydradri-hydration-pack": {"name": "Klim Hydradri Hydration Pack", "price": 69.99},
            # --- Luggage ---
            "kriega-os-12-adventure-tail-bag": {"name": "Kriega OS-12 Adventure Tail Bag", "price": 119.99},
            "nelson-rigg-commuter-lite-tank-bag": {"name": "Nelson-Rigg Commuter Lite Tank Bag", "price": 64.95},
            "kriega-us20-drypack": {"name": "Kriega US-20 Drypack", "price": 134.99},
            "mosko-moto-nomax-fender-bag": {"name": "Mosko Moto Nomax Fender Bag", "price": 89.00},
            # --- Tires ---
            "dunlop-sportmax-q5-sportbike-tires": {"name": "Dunlop Sportmax Q5 Tires", "price": 354.99},
            "michelin-pilot-road-6-touring-tires": {"name": "Michelin Pilot Road 6 Tires", "price": 289.99},
            "pirelli-scorpion-trail-ii-adventure-tire": {"name": "Pirelli Scorpion Trail II Adventure Tire", "price": 199.99},
            "dunlop-geomax-mx34-motocross-tire": {"name": "Dunlop Geomax MX34 Motocross Tire", "price": 89.99},
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
            "motorex-gear-oil-10w30": {"name": "Motorex Gear Oil 10W30", "price": 20.99},
            "motul-7100-10w40-synthetic-oil": {"name": "Motul 7100 10W40 Synthetic Oil", "price": 54.99},
            "bel-ray-fork-oil-10w": {"name": "Bel-Ray Fork Oil 10W", "price": 16.99},
            "maxima-premium-transmission-oil": {"name": "Maxima Premium Transmission Oil", "price": 12.99},
            # --- Air filters ---
            "twin-air-air-filter-for-2024-kawasaki-kx450": {"name": "Twin Air Filter 2024 KX450", "price": 38.95},
            "k-and-n-air-filter-yamaha-yz250f": {"name": "K&N Air Filter Yamaha YZ250F", "price": 49.99},
            "bmc-air-filter-ducati-panigale-v4": {"name": "BMC Air Filter Ducati Panigale V4", "price": 99.99},
            # --- Parts / consumables ---
            "ngk-iridium-spark-plug": {"name": "NGK Iridium Spark Plug", "price": 12.99},
            "yuasa-ytx14-bs-battery": {"name": "Yuasa YTX14-BS Battery", "price": 129.99},
            "all-balls-racing-wheel-bearing-kit": {"name": "All Balls Racing Wheel Bearing Kit", "price": 39.99},
            "moose-racing-stator": {"name": "Moose Racing Stator", "price": 159.99},
            "tusk-clutch-lever-assembly": {"name": "Tusk Clutch Lever Assembly", "price": 24.99},
            "cv4-performance-radiator-hose-kit": {"name": "CV4 Performance Radiator Hose Kit", "price": 89.99},
            # --- Misc / general ---
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

    recommendations = [
        {"id": rid, "label": info["label"] or None, "priority": info.get("priority") or None}
        for rid, info in sorted(
            rec_info.items(),
            key=lambda x: (-x[1]["count"], PRIORITY_RANK.get(x[1].get("priority", ""), 99)),
        )
    ]

    return jsonify({
        "recommendations": recommendations,
        "cart_products": cart_product_ids,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

"""
Sync recommendations from BigCommerce catalog.

Generates product_recommendations.csv using:
- Product identifier: slug (custom_url)
- Excludes out-of-stock products
- Exactly 3 recommendations per product:
  Primary (most expensive), Secondary, Tertiary

Required .env vars:
  BC_ACCESS_TOKEN=...
And either:
  BC_API_PATH=https://api.bigcommerce.com/stores/<store_hash>/v3
or:
  BC_STORE_HASH=<store_hash>
  BC_API_BASE=https://api.bigcommerce.com
"""

import csv
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

import requests
from dotenv import load_dotenv


PRIORITIES = ["Primary", "Secondary", "Tertiary"]

# Broad product type detection for apparel/parts/accessories.
# Order matters: more specific types should come first.
TYPE_RULES = [
    ("helmet_accessory", ["visor", "face shield", "faceshield", "shield", "pinlock", "cheek pad", "cheekpad"]),
    ("helmet", ["helmet"]),
    ("jacket", ["jacket", "coat", "parka"]),
    ("pants", ["pant", "trouser", "bibs"]),
    ("gloves", ["glove", "gauntlet"]),
    ("boots", ["boot", "shoe"]),
    ("backpack", ["backpack", "bag", "pack", "luggage"]),
    ("communication", ["communication", "intercom", "bluetooth", "headset", "sena", "cardo", "schuberth sc2"]),
    ("tire", ["tire", "tyre", "wheel"]),
    ("air_filter", ["air filter", "air-filter", "filter"]),
    ("oil", ["oil", "lubricant", "lube", "fork oil", "transmission oil"]),
    ("brake", ["brake", "pad", "rotor"]),
    ("chain", ["chain", "sprocket", "degreaser", "chain lube", "chain wax"]),
    ("protection", ["protector", "armor", "armour", "chest", "back protector"]),
]

# Complementary gear map (avoid same-type recommendations).
COMPLEMENTARY_TYPES = {
    "pants": ["jacket", "gloves", "boots", "protection", "backpack"],
    "jacket": ["pants", "gloves", "boots", "protection", "helmet"],
    "gloves": ["jacket", "pants", "boots", "helmet"],
    "boots": ["pants", "jacket", "gloves", "helmet"],
    "helmet": ["helmet_accessory", "communication", "backpack", "jacket", "gloves"],
    "helmet_accessory": ["helmet", "communication", "backpack"],
    "communication": ["helmet", "earplugs", "backpack"],
    "tire": ["brake", "chain", "oil"],
    "air_filter": ["oil", "chain", "brake"],
    "oil": ["air_filter", "chain", "brake"],
    "chain": ["oil", "brake", "air_filter"],
    "brake": ["tire", "chain", "oil"],
    "backpack": ["helmet", "jacket", "gloves"],
    "protection": ["jacket", "pants", "gloves", "boots"],
}


@dataclass
class Product:
    product_id: int
    slug: str
    name: str
    price: float
    brand_id: int
    categories: Set[int]
    category_names: List[str]


def normalize_text(s: str) -> str:
    return (s or "").lower().replace("-", " ")


def tokenize(s: str) -> List[str]:
    text = normalize_text(s)
    return [t for t in re.findall(r"[a-z0-9]+", text) if t]


TOKEN_STOPWORDS = {
    "helmet", "visor", "shield", "pinlock", "face", "clear", "dark", "smoke",
    "tinted", "replacement", "motorcycle", "racing", "race", "edition", "with",
    "for", "the", "and", "kit", "v2", "v3", "v4", "v5", "pro", "plus", "series",
    "single", "dual", "unit", "pack",
}


def parse_slug(custom_url: dict) -> str:
    if not custom_url:
        return ""
    url = (custom_url.get("url") or "").strip()
    if not url:
        return ""
    return url.strip("/")


def get_env() -> Tuple[str, str]:
    load_dotenv()
    store_hash = os.getenv("BC_STORE_HASH", "").strip()
    access_token = os.getenv("BC_ACCESS_TOKEN", "").strip()
    api_base = os.getenv("BC_API_BASE", "https://api.bigcommerce.com").strip()
    api_path = os.getenv("BC_API_PATH", "").strip().rstrip("/")
    if not access_token:
        raise RuntimeError("Missing BC_ACCESS_TOKEN in .env")
    if api_path:
        return access_token, api_path
    if not store_hash:
        raise RuntimeError("Set either BC_API_PATH or BC_STORE_HASH in .env")
    return access_token, f"{api_base}/stores/{store_hash}/v3"


def bc_get_all(session: requests.Session, base_path: str, endpoint: str, params: dict) -> List[dict]:
    out = []
    page = 1
    while True:
        req_params = dict(params)
        req_params["page"] = page
        req_params["limit"] = 250
        r = session.get(f"{base_path}{endpoint}", params=req_params, timeout=60)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("data", [])
        out.extend(rows)
        pagination = payload.get("meta", {}).get("pagination", {})
        total_pages = pagination.get("total_pages", page)
        if page >= total_pages:
            break
        page += 1
    return out


def is_in_stock(raw: dict) -> bool:
    # Visibility gate
    if not raw.get("is_visible", True):
        return False

    # Availability gate
    availability = (raw.get("availability") or "").lower()
    if availability and availability not in {"available", "preorder"}:
        return False

    # Inventory gate (when tracked at product level)
    tracking = (raw.get("inventory_tracking") or "none").lower()
    level = raw.get("inventory_level")
    if tracking != "none" and level is not None and level <= 0:
        return False

    return True


def read_existing_category_rows(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("Type") or "").strip().lower() == "category":
                rows.append(row)
    return rows


def rank_candidates(source: Product, candidates: List[Product]) -> List[Product]:
    # First rank by relevance, then price desc.
    def score(p: Product):
        shared = len(source.categories.intersection(p.categories))
        same_brand = 1 if (source.brand_id and source.brand_id == p.brand_id) else 0
        return (shared, same_brand, p.price)

    ranked = sorted(candidates, key=score, reverse=True)

    # Keep best relevant pool, but final output must be sorted by price desc for Primary/Secondary.
    top_pool = ranked[:30]
    top_pool = sorted(top_pool, key=lambda p: p.price, reverse=True)
    return top_pool


def detect_product_type(product: Product) -> str:
    # Prefer slug/name detection first (less noisy than category labels).
    hay_primary = " ".join([normalize_text(product.slug), normalize_text(product.name)])
    hay_categories = " ".join(normalize_text(cn) for cn in product.category_names)
    for ptype, kws in TYPE_RULES:
        if any(kw in hay_primary for kw in kws):
            return ptype
    for ptype, kws in TYPE_RULES:
        if any(kw in hay_categories for kw in kws):
            return ptype
    return "other"


def brand_token(product: Product) -> str:
    toks = tokenize(product.slug)
    return toks[0] if toks else ""


def model_tokens(product: Product) -> Set[str]:
    toks = set(tokenize(product.slug) + tokenize(product.name))
    # remove generic terms and short noise tokens
    return {t for t in toks if t not in TOKEN_STOPWORDS and len(t) >= 2}


def same_brand(source: Product, candidate: Product) -> bool:
    if source.brand_id and candidate.brand_id and source.brand_id == candidate.brand_id:
        return True
    # fallback: compare first slug token
    return brand_token(source) and brand_token(source) == brand_token(candidate)


def compatible_helmet_accessories(source: Product, candidates: List[Product]) -> List[Product]:
    """
    Score helmet accessories by fit quality:
    1) same brand
    2) model token overlap (e.g. rf1400, x15, pista, k3)
    3) price desc
    """
    src_tokens = model_tokens(source)
    scored = []
    for c in candidates:
        if c.slug == source.slug:
            continue
        overlap = len(src_tokens.intersection(model_tokens(c)))
        sb = 1 if same_brand(source, c) else 0
        # require at least weak compatibility signal
        if sb == 0 and overlap == 0:
            continue
        scored.append((sb, overlap, c.price, c))

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [x[3] for x in scored]


def choose_three(
    source: Product,
    source_type: str,
    by_slug: Dict[str, Product],
    by_category: Dict[int, List[str]],
    all_slugs_sorted_by_price: List[str],
    by_type: Dict[str, List[str]],
    product_type: Dict[str, str],
) -> List[Product]:
    seen = set([source.slug])
    picked: List[Product] = []

    # 0) Compatibility-first for helmets: prefer matching shields/visors/pinlocks
    if source_type == "helmet":
        helmet_acc_slugs = by_type.get("helmet_accessory", [])
        helmet_acc_candidates = [by_slug[s] for s in helmet_acc_slugs if s in by_slug and s not in seen]
        for p in compatible_helmet_accessories(source, helmet_acc_candidates):
            picked.append(p)
            seen.add(p.slug)
            if len(picked) == 3:
                return picked

    # 1) Complementary-type candidates (preferred)
    complementary = COMPLEMENTARY_TYPES.get(source_type, [])
    comp_slugs = []
    for t in complementary:
        comp_slugs.extend(by_type.get(t, []))
    comp_candidates = [by_slug[s] for s in comp_slugs if s in by_slug and s not in seen]
    ranked = rank_candidates(source, comp_candidates)
    for p in ranked:
        if p.slug not in seen:
            picked.append(p)
            seen.add(p.slug)
            if len(picked) == 3:
                return picked

    # 2) Same category but different product type
    category_candidate_slugs = set()
    for cid in source.categories:
        for slug in by_category.get(cid, []):
            category_candidate_slugs.add(slug)
    category_candidates = [
        by_slug[s]
        for s in category_candidate_slugs
        if s in by_slug
        and s not in seen
        and product_type.get(s, "other") != source_type
    ]
    ranked = rank_candidates(source, category_candidates)
    for p in ranked:
        picked.append(p)
        seen.add(p.slug)
        if len(picked) == 3:
            return picked

    # 3) Same brand fill but different type
    same_brand = [
        p
        for p in by_slug.values()
        if p.slug not in seen
        and source.brand_id
        and p.brand_id == source.brand_id
        and product_type.get(p.slug, "other") != source_type
    ]
    same_brand = sorted(same_brand, key=lambda p: p.price, reverse=True)
    for p in same_brand:
        picked.append(p)
        seen.add(p.slug)
        if len(picked) == 3:
            return picked

    # 4) Global expensive fill, still avoiding same type when possible
    for slug in all_slugs_sorted_by_price:
        if slug in seen:
            continue
        if product_type.get(slug, "other") == source_type:
            continue
        p = by_slug.get(slug)
        if not p:
            continue
        picked.append(p)
        seen.add(slug)
        if len(picked) == 3:
            return picked

    # 5) Absolute fallback only for unknown source type.
    # For known types we intentionally avoid same-type recommendations.
    if source_type == "other":
        for slug in all_slugs_sorted_by_price:
            if slug in seen:
                continue
            p = by_slug.get(slug)
            if not p:
                continue
            picked.append(p)
            seen.add(slug)
            if len(picked) == 3:
                return picked

    return picked


def main():
    access_token, base_path = get_env()

    session = requests.Session()
    session.headers.update({
        "X-Auth-Token": access_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    categories_raw = bc_get_all(
        session,
        base_path,
        "/catalog/categories",
        {"include_fields": "id,name,parent_id,is_visible"},
    )
    category_name = {int(c["id"]): c.get("name", "") for c in categories_raw}

    products_raw = bc_get_all(
        session,
        base_path,
        "/catalog/products",
        {
            "is_visible": "true",
            "include_fields": "id,name,price,brand_id,categories,custom_url,is_visible,availability,inventory_level,inventory_tracking",
        },
    )

    products: List[Product] = []
    for raw in products_raw:
        if not is_in_stock(raw):
            continue
        slug = parse_slug(raw.get("custom_url") or {})
        if not slug:
            continue
        categories = set(int(c) for c in (raw.get("categories") or []) if isinstance(c, int) or str(c).isdigit())
        products.append(
            Product(
                product_id=int(raw["id"]),
                slug=slug,
                name=(raw.get("name") or slug),
                price=float(raw.get("price") or 0.0),
                brand_id=int(raw.get("brand_id") or 0),
                categories=categories,
                category_names=[category_name.get(c, "") for c in categories if category_name.get(c)],
            )
        )

    by_slug = {p.slug: p for p in products}
    by_category = defaultdict(list)
    by_type = defaultdict(list)
    product_type = {}
    for p in products:
        for cid in p.categories:
            by_category[cid].append(p.slug)
        ptype = detect_product_type(p)
        product_type[p.slug] = ptype
        by_type[ptype].append(p.slug)

    all_slugs_sorted_by_price = [p.slug for p in sorted(products, key=lambda p: p.price, reverse=True)]

    out_rows = []
    for p in sorted(products, key=lambda x: x.slug):
        ptype = product_type.get(p.slug, "other")
        picks = choose_three(
            p,
            ptype,
            by_slug,
            by_category,
            all_slugs_sorted_by_price,
            by_type,
            product_type,
        )
        picks = sorted(picks, key=lambda x: x.price, reverse=True)[:3]
        for idx, rec in enumerate(picks):
            label = f"Complements your {ptype}" if ptype != "other" else "Recommended item"
            out_rows.append({
                "Product ID": p.slug,
                "Recommended Product ID": rec.slug,
                "Label": label,
                "Type": "Explicit",
                "Priority": PRIORITIES[idx] if idx < len(PRIORITIES) else "",
                "Estimated Price": f"{rec.price:.2f}",
            })

    # Preserve existing category rows for fallback behavior
    csv_path = "product_recommendations.csv"
    existing_category_rows = read_existing_category_rows(csv_path)
    for row in existing_category_rows:
        out_rows.append({
            "Product ID": row.get("Product ID", ""),
            "Recommended Product ID": row.get("Recommended Product ID", ""),
            "Label": row.get("Label", ""),
            "Type": "Category",
            "Priority": row.get("Priority", ""),
            "Estimated Price": row.get("Estimated Price", ""),
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Product ID", "Recommended Product ID", "Label", "Type", "Priority", "Estimated Price"],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    explicit_count = len(products)
    print(f"Synced {explicit_count} in-stock products from BigCommerce.")
    print(f"Wrote {len(out_rows)} rows to {csv_path}.")
    print("Primary/Secondary/Tertiary assigned by recommendation price descending.")


if __name__ == "__main__":
    main()

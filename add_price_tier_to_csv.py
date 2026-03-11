"""
add_price_tier_to_csv.py

Adds / updates four columns in product_recommendations.csv:
  - "Price Tier"            : tier for the Recommended Product ID
  - "Source Estimated Price": price for the Product ID (source/cart product)
  - "Source Tier"           : tier for the Product ID

Algorithm:
  1. Build a canonical slug → price map from every (Recommended Product ID, Estimated Price)
     pair in the CSV.  If the same slug appears with different prices, keep the FIRST seen.
  2. For Product IDs not yet in the canonical map (i.e. never appear as a rec),
     try to look up price from the BigCommerce catalog (if BC env vars are set).
     If still not found, Source Estimated Price and Source Tier are left blank.
  3. Normalise "Estimated Price" to use the canonical price for each rec slug.
  4. For every row set:
       Price Tier            = tier(rec_slug,  canonical[rec_slug])
       Source Estimated Price = canonical.get(product_id) or ""
       Source Tier           = tier(product_id, source_price) if source_price else ""

Missing or invalid Estimated Price → price = 0.0 → budget.
Unknown product type uses the "default" band.

Usage:
    python3 add_price_tier_to_csv.py
    python3 add_price_tier_to_csv.py --csv path/to/other.csv --no-catalog
"""

import csv
import os
import sys
import argparse
from pathlib import Path

# Allow importing api_server helpers.
sys.path.insert(0, str(Path(__file__).parent))
from api_server import _detect_product_type  # noqa: E402

# Per-type tier bands: (budget_max, mid_max, premium_max)
TIER_BANDS = {
    "helmet":           (150,  350,  600),
    "jacket":           (150,  300,  600),
    "pants":            (100,  200,  400),
    "boots":            (150,  300,  500),
    "gloves":           (50,   100,  200),
    "jersey":           (40,   80,   150),
    "tire":             (100,  180,  300),
    "luggage":          (100,  250,  500),
    "backpack":         (75,   150,  300),
    "hydration":        (50,   100,  200),
    "communication":    (100,  300,  600),
    "protection":       (75,   150,  300),
    "parts":            (50,   150,  350),
    "oil":              (25,   50,   100),
    "chain":            (80,   180,  350),
    "brake":            (80,   180,  400),
    "air_filter":       (40,   80,   150),
    "care":             (25,   50,   100),
    "helmet_accessory": (50,   120,  250),
    "default":          (75,   200,  500),
}


def get_tier(product_type: str, price: float) -> str:
    bands = TIER_BANDS.get(product_type, TIER_BANDS["default"])
    budget_max, mid_max, premium_max = bands
    if price < budget_max:
        return "budget"
    if price < mid_max:
        return "mid"
    if price < premium_max:
        return "premium"
    return "elite"


def _parse_price(raw) -> float:
    try:
        return float((raw or "").strip())
    except (ValueError, TypeError):
        return 0.0


def _fetch_catalog_prices() -> dict:
    """
    Fetch slug → price from BigCommerce catalog.
    Returns empty dict if env vars are not set or request fails.
    """
    import os, requests
    access_token = os.environ.get("BC_ACCESS_TOKEN", "").strip()
    bc_api_path = os.environ.get("BC_API_PATH", "").strip().rstrip("/")
    bc_store_hash = os.environ.get("BC_STORE_HASH", "").strip()
    bc_api_base = os.environ.get("BC_API_BASE", "https://api.bigcommerce.com").strip().rstrip("/")

    if not access_token:
        return {}

    if not bc_api_path:
        if bc_store_hash:
            bc_api_path = f"{bc_api_base}/stores/{bc_store_hash}/v3"
        else:
            return {}

    headers = {
        "X-Auth-Token": access_token,
        "Accept": "application/json",
    }
    prices = {}
    page = 1
    print("Fetching catalog prices from BigCommerce...")
    while True:
        try:
            resp = requests.get(
                f"{bc_api_path}/catalog/products",
                headers=headers,
                params={"page": page, "limit": 250, "is_visible": True},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"  Catalog fetch error (page {page}): {exc}", file=sys.stderr)
            break
        for row in payload.get("data", []):
            custom_url = (row.get("custom_url") or {}).get("url") or ""
            slug = custom_url.strip("/")
            price = row.get("price")
            if slug and price is not None:
                try:
                    prices[slug] = float(price)
                except (TypeError, ValueError):
                    pass
        meta = payload.get("meta", {}).get("pagination", {})
        if page >= meta.get("total_pages", page):
            break
        page += 1
    print(f"  Fetched prices for {len(prices)} catalog products.")
    return prices


def add_source_columns(csv_path: str, use_catalog: bool = True) -> None:
    path = Path(csv_path)
    if not path.exists():
        print(f"ERROR: file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        original_fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    # --- Pass 1: build canonical slug → price from (Recommended Product ID, Estimated Price) ---
    canonical: dict = {}
    for row in rows:
        rec_id = (row.get("Recommended Product ID") or "").strip()
        raw = (row.get("Estimated Price") or "").strip()
        if rec_id and raw:
            try:
                price = float(raw)
                if rec_id not in canonical:
                    canonical[rec_id] = price
            except (ValueError, TypeError):
                pass

    # --- Pass 2: fill Product IDs not yet in canonical ---
    missing_product_ids = set()
    for row in rows:
        pid = (row.get("Product ID") or "").strip()
        if pid and pid not in canonical:
            missing_product_ids.add(pid)

    if missing_product_ids:
        catalog_prices = _fetch_catalog_prices() if use_catalog else {}
        for slug in missing_product_ids:
            if slug in catalog_prices:
                canonical[slug] = catalog_prices[slug]
        still_missing = missing_product_ids - set(canonical)
        print(f"  {len(missing_product_ids)} Product IDs had no price from recs; "
              f"filled {len(missing_product_ids) - len(still_missing)} from catalog, "
              f"{len(still_missing)} still unknown (Source Estimated Price will be blank).")

    # --- Build new fieldnames ---
    new_fieldnames = list(original_fieldnames)

    def _ensure_after(field, after):
        if field not in new_fieldnames:
            if after in new_fieldnames:
                new_fieldnames.insert(new_fieldnames.index(after) + 1, field)
            else:
                new_fieldnames.append(field)

    _ensure_after("Price Tier", "Estimated Price")
    _ensure_after("Source Estimated Price", "Price Tier")
    _ensure_after("Source Tier", "Source Estimated Price")

    # --- Update all rows ---
    for row in rows:
        rec_id = (row.get("Recommended Product ID") or "").strip()
        pid = (row.get("Product ID") or "").strip()

        # Normalise Estimated Price to canonical value for the rec.
        rec_price = canonical.get(rec_id, _parse_price(row.get("Estimated Price")))
        row["Estimated Price"] = f"{rec_price:.2f}" if rec_price else (row.get("Estimated Price") or "")

        # Price Tier (rec).
        rec_type = _detect_product_type(rec_id) if rec_id else "unknown"
        row["Price Tier"] = get_tier(rec_type, rec_price)

        # Source Estimated Price and Source Tier.
        src_price = canonical.get(pid)
        if src_price is not None:
            row["Source Estimated Price"] = f"{src_price:.2f}"
            src_type = _detect_product_type(pid) if pid else "unknown"
            row["Source Tier"] = get_tier(src_type, src_price)
        else:
            row["Source Estimated Price"] = ""
            row["Source Tier"] = ""

    # --- Write back safely ---
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)

    # Stats
    source_tier_filled = sum(1 for r in rows if r.get("Source Tier"))
    source_tier_blank = sum(1 for r in rows if not r.get("Source Tier"))
    print(f"\nDone. {len(rows)} rows processed.")
    print(f"  Source Tier filled : {source_tier_filled}")
    print(f"  Source Tier blank  : {source_tier_blank} (Product ID had no price)")
    print(f"Saved to: {path}")

    # Spot-check
    print("\nSample rows (one per source product type):")
    seen_src_types = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pid = (row.get("Product ID") or "").strip()
            stype = _detect_product_type(pid)
            if stype not in seen_src_types:
                seen_src_types.add(stype)
                print(
                    f"  src={pid[:40]:40s}  src_price={row.get('Source Estimated Price','?'):>8s}"
                    f"  src_tier={row.get('Source Tier','?'):8s}"
                    f"  rec={row.get('Recommended Product ID','')[:30]:30s}"
                    f"  rec_price={row.get('Estimated Price','?'):>8s}"
                    f"  rec_tier={row.get('Price Tier','?')}"
                )
            if len(seen_src_types) >= 10:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add Source Estimated Price and Source Tier to recommendations CSV")
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "product_recommendations.csv"),
        help="Path to recommendations CSV (default: product_recommendations.csv)",
    )
    parser.add_argument(
        "--no-catalog",
        action="store_true",
        help="Skip BigCommerce catalog lookup (Source Estimated Price blank for source-only products)",
    )
    args = parser.parse_args()
    add_source_columns(args.csv, use_catalog=not args.no_catalog)

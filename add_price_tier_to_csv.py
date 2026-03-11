"""
add_price_tier_to_csv.py

Adds a "Price Tier" column to product_recommendations.csv.

For each row the tier is derived from:
  - Recommended Product ID (slug) → product type via _detect_product_type
  - Estimated Price + per-type tier bands → budget / mid / premium / elite

Tier bands ($ thresholds, exclusive upper bound):
  budget  : price < budget_max
  mid     : price < mid_max
  premium : price < premium_max
  elite   : price >= premium_max

Missing or invalid Estimated Price is treated as 0 → budget.
Unknown product type uses the "default" band.

Usage:
    python3 add_price_tier_to_csv.py
    python3 add_price_tier_to_csv.py --csv path/to/other.csv
"""

import csv
import os
import sys
import argparse
from pathlib import Path

# Import server's type detection so logic stays in sync.
sys.path.insert(0, str(Path(__file__).parent))
from api_server import _detect_product_type  # noqa: E402

# Per-type tier bands: (budget_max, mid_max, premium_max)
# price < budget_max → budget
# price < mid_max    → mid
# price < premium_max → premium
# else               → elite
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


def add_tier_column(csv_path: str) -> None:
    path = Path(csv_path)
    if not path.exists():
        print(f"ERROR: file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        original_fieldnames = reader.fieldnames or []
        rows = list(reader)

    # Build new fieldnames: insert "Price Tier" after "Estimated Price".
    new_fieldnames = list(original_fieldnames)
    if "Price Tier" not in new_fieldnames:
        if "Estimated Price" in new_fieldnames:
            idx = new_fieldnames.index("Estimated Price")
            new_fieldnames.insert(idx + 1, "Price Tier")
        else:
            new_fieldnames.append("Price Tier")

    updated = 0
    skipped_no_price = 0

    for row in rows:
        rec_id = (row.get("Recommended Product ID") or "").strip()
        raw_price = (row.get("Estimated Price") or "").strip()

        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = 0.0
            skipped_no_price += 1

        product_type = _detect_product_type(rec_id) if rec_id else "unknown"
        row["Price Tier"] = get_tier(product_type, price)
        updated += 1

    # Write back in-place (write to temp then replace for safety).
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    os.replace(tmp_path, path)

    print(f"Done. {updated} rows updated ({skipped_no_price} had no/invalid price → set to budget).")
    print(f"Saved to: {path}")

    # Spot-check a few rows
    print("\nSample rows:")
    sample_types = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ptype = _detect_product_type((row.get("Recommended Product ID") or "").strip())
            if ptype not in sample_types:
                sample_types.add(ptype)
                print(f"  {row.get('Recommended Product ID','')[:50]:50s}  "
                      f"type={ptype:18s}  price={row.get('Estimated Price','N/A'):>8s}  "
                      f"tier={row.get('Price Tier','')}")
            if len(sample_types) >= 12:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add Price Tier column to recommendations CSV")
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).parent / "product_recommendations.csv"),
        help="Path to recommendations CSV (default: product_recommendations.csv)",
    )
    args = parser.parse_args()
    add_tier_column(args.csv)

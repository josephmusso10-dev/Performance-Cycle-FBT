"""
Build a source-verification template for fit-sensitive helmet accessory pairs.

This creates/overwrites compatibility_proofs.csv with one row per
helmet -> fit-sensitive accessory recommendation pair.
"""

import argparse
import csv
from pathlib import Path
from urllib.parse import quote_plus

from validate_recommendations import detect_type, is_fit_sensitive_helmet_accessory


def build_template(recommendations_csv: Path, proofs_csv: Path) -> int:
    if not recommendations_csv.exists():
        print(f"ERROR: recommendations CSV not found: {recommendations_csv}")
        return 2

    rows = []
    seen = set()
    with recommendations_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            product_id = (row.get("Product ID") or "").strip()
            rec_id = (row.get("Recommended Product ID") or "").strip()
            if not product_id or not rec_id:
                continue
            if product_id.startswith("[") and "]" in product_id:
                continue

            if detect_type(product_id) == "helmet" and is_fit_sensitive_helmet_accessory(rec_id):
                key = (product_id, rec_id)
                if key in seen:
                    continue
                seen.add(key)
                query = f"{rec_id} compatible with {product_id}"
                rows.append(
                    {
                        "Product ID": product_id,
                        "Recommended Product ID": rec_id,
                        "Compatibility Verified": "",
                        "Compatibility Source": "",
                        "Compatibility Notes": "",
                        "Suggested Search URL": f"https://www.google.com/search?q={quote_plus(query)}",
                    }
                )

    with proofs_csv.open("w", newline="", encoding="utf-8") as out:
        fieldnames = [
            "Product ID",
            "Recommended Product ID",
            "Compatibility Verified",
            "Compatibility Source",
            "Compatibility Notes",
            "Suggested Search URL",
        ]
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} proof rows to {proofs_csv}")
    print("Fill Compatibility Verified + Compatibility Source for rows you confirm.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compatibility proofs template CSV.")
    parser.add_argument(
        "--csv",
        default="product_recommendations.csv",
        help="Path to recommendations CSV (default: product_recommendations.csv)",
    )
    parser.add_argument(
        "--out",
        default="compatibility_proofs.csv",
        help="Output compatibility proofs CSV (default: compatibility_proofs.csv)",
    )
    args = parser.parse_args()
    return build_template(Path(args.csv), Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())

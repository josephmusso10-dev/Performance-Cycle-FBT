"""
Build-time script: fetches the full BigCommerce catalog and writes
data/catalog.json (slug -> {id, name, price, url, image}).

Run before deploying so the API server can load product data without
making live BigCommerce requests on every cold start (critical on Vercel).

Usage:
    python3 scripts/fetch_catalog.py
    python3 scripts/fetch_catalog.py --output data/catalog.json

Requires env vars (from .env or Vercel environment variables):
    BC_ACCESS_TOKEN
    BC_STORE_HASH  (or BC_API_PATH)
    BC_API_BASE    (optional, defaults to https://api.bigcommerce.com)
"""

import json
import math
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env when running locally
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env.local", override=True)


def fetch_catalog() -> dict:
    access_token = os.environ.get("BC_ACCESS_TOKEN", "").strip()
    bc_api_path = os.environ.get("BC_API_PATH", "").strip().rstrip("/")
    bc_store_hash = os.environ.get("BC_STORE_HASH", "").strip()
    bc_api_base = os.environ.get("BC_API_BASE", "https://api.bigcommerce.com").strip().rstrip("/")

    if not access_token:
        print("ERROR: BC_ACCESS_TOKEN not set. Catalog will be empty.", file=sys.stderr)
        return {}

    if not bc_api_path:
        if bc_store_hash:
            bc_api_path = f"{bc_api_base}/stores/{bc_store_hash}/v3"
        else:
            print("ERROR: Set BC_API_PATH or BC_STORE_HASH. Catalog will be empty.", file=sys.stderr)
            return {}

    session = requests.Session()
    session.headers.update({
        "X-Auth-Token": access_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    limit = 250
    catalog = {}
    page = 1
    total_pages = None

    print("Fetching full BigCommerce catalog...")
    while True:
        try:
            resp = session.get(
                f"{bc_api_path}/catalog/products",
                params={
                    "page": page,
                    "limit": limit,
                    "include": "primary_image",
                    "include_fields": "id,name,price,custom_url",
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"  Catalog fetch error (page {page}): {exc}", file=sys.stderr)
            break

        rows = payload.get("data", [])
        for row in rows:
            custom_url = (row.get("custom_url") or {}).get("url") or ""
            slug = custom_url.strip("/")
            if not slug:
                continue
            catalog[slug] = {
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

        print(f"  Page {page}/{total_pages}: {len(rows)} products fetched (total so far: {len(catalog)})")

        if page >= total_pages or not rows:
            break
        page += 1

    print(f"Done. Total catalog entries: {len(catalog)}")
    return catalog


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch BigCommerce catalog and write data/catalog.json")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent.parent / "data" / "catalog.json"),
        help="Output JSON file path (default: data/catalog.json)",
    )
    args = parser.parse_args()

    catalog = fetch_catalog()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"Catalog written to: {output_path} ({len(catalog)} products)")


if __name__ == "__main__":
    main()

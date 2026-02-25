# Frequently Bought Together – Performance Cycle

CSV-driven recommendation service + embeddable widget + simulation page.

## Quick Start

```bash
pip install -r requirements.txt
python api_server.py
```

### Click-to-preview simulation

Open:

`http://localhost:5000/simulate`

This page lets you add sample products to cart and see exactly how recommendations appear.

## How recommendations are controlled

Recommendations are read from:

`product_recommendations.csv`

In local dev, edits saved to this CSV are picked up automatically by the API (no code edit required).

CSV columns:

- `Product ID`
- `Recommended Product ID`
- `Label`
- `Type` (`Explicit` or `Category`)

### No-redeploy CSV updates (Vercel runtime URL mode)

To update recommendations in production without redeploying every CSV edit:

1. Host your CSV at a stable public URL (for example: Google Sheets published CSV, S3 object URL, or other hosted file URL).
2. In Vercel Project Settings -> Environment Variables, set:
   - `RECOMMENDATIONS_CSV_URL` = your public CSV URL
   - `RECOMMENDATIONS_CSV_REFRESH_SECONDS` = `30` (or desired refresh cadence)
   - `RECOMMENDATIONS_CSV_TIMEOUT_SECONDS` = `8`
3. Redeploy once after adding env vars.

After that, the API fetches the CSV from URL at runtime and refreshes on interval, so CSV edits at that URL show up without code deploys.

### Product URL resolution for recommended items

To ensure recommendation cards link to real product pages without theme-side catalog wiring:

Set these env vars in Vercel:

- `STOREFRONT_BASE_URL` = your storefront domain (example: `https://performancecycle.com`)
- `STOREFRONT_PRODUCT_PATH_PATTERN` = product URL pattern (default fallback is `/products/{slug}/`)

Optional (for authoritative product URLs/images/prices via BigCommerce Catalog API):

- `BC_ACCESS_TOKEN`
- `BC_API_PATH` (or `BC_STORE_HASH` + `BC_API_BASE`)
- `CATALOG_REFRESH_SECONDS` (default `1800`)

With this enabled, widget calls `GET /api/catalog?ids=...` and hydrates recommended products with real URLs before render.

Health/debug:
- `GET /api/health` shows active source (`remote`, `local`, or `local-fallback`) and last error if remote fetch failed.
- `POST /api/reload` forces an immediate refresh attempt.

### Validate recommendation quality

Run:

```bash
./validate
```

Optional:

```bash
./validate --csv product_recommendations.csv --max-output 100
```

This validator checks complementary item pairing and flags likely helmet accessory compatibility mismatches.

### Source-backed strict compatibility (fit-sensitive accessories only)

Build the verification checklist:

```bash
./build-proofs-template
```

This creates `compatibility_proofs.csv` for helmet -> fit-sensitive accessory pairs (e.g., shields/pinlock/cheek pads), including a suggested Google search URL per pair.

After verifying each pair, fill:
- `Compatibility Verified` (yes/no)
- `Compatibility Source` (manufacturer/product URL)
- `Compatibility Notes` (optional)

Run strict validation:

```bash
./validate-strict
```

Optional strict mode with heuristic fallback (brand/model overlap only):

```bash
./validate-strict --allow-heuristic-fit
```

Note: strict proof is required only for fit-sensitive helmet accessories. General complementary pairs like jacket ↔ pants do not require source proof.

### Auto-fix definite mismatches

Auto-fix rows currently classified as `definite mismatch` (helmet brand conflict for fit-sensitive accessories):

```bash
./autofix-mismatches --dry-run
```

Write to a new file:

```bash
./autofix-mismatches --out product_recommendations.autofixed.csv
```

Overwrite in place (creates timestamped `.bak` backup automatically):

```bash
./autofix-mismatches --in-place
```

This only changes `definite mismatch` rows. It does not auto-fix `missing proof` rows.

### Auto-validate on every CSV update

Run this watcher in a terminal:

```bash
./validate-watch
```

Optional tuning:

```bash
./validate-watch --csv product_recommendations.csv --interval 1.0 --settle 0.75 --max-output 20
```

The watcher stays running and automatically re-validates after each CSV save. Press `Ctrl+C` to stop.

Strict watcher mode:

```bash
./validate-watch-strict
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/fbt` | GET | `?products=id1,id2` → recommended items |
| `/api/health` | GET | service + CSV path status |
| `/api/reload` | POST | validates CSV + returns rule counts |
| `/api/debug/product` | GET | `?id=product-slug` → show exact match source |
| `/simulate` | GET | browser simulation page |
| `/widget/fbt-widget.js` | GET | embeddable widget JS |

## BigCommerce Auto-Sync (All In-Stock Products)

You can auto-generate recommendations for all in-stock products from BigCommerce.

1) Create `.env` in project root:

```env
BC_ACCESS_TOKEN=your_access_token
BC_API_BASE=https://api.bigcommerce.com
# Prefer this if BigCommerce gave you an API path directly:
# BC_API_PATH=https://api.bigcommerce.com/stores/<store_hash>/v3
# Otherwise use:
# BC_STORE_HASH=7n1vmei
```

2) Install deps:

```bash
pip install -r requirements.txt
```

3) Generate CSV:

```bash
python sync_bigcommerce_recommendations.py
```

This writes `product_recommendations.csv` with:
- `Type=Explicit` for every in-stock product (using slug identifier)
- Exactly 3 recommendations per product
- `Priority`: Primary, Secondary, Tertiary
- `Primary/Secondary` sorted by highest recommendation price

## Deploy (Render)

This repo includes:

- `Procfile`
- `render.yaml`

Deploy steps:

1. Push this folder to GitHub
2. In Render, create a new Web Service from the repo
3. Render will use:
   - build: `pip install -r requirements.txt`
   - start: `gunicorn api_server:app`
4. Open your deployed URL + `/simulate`

Example:

`https://your-render-url.onrender.com/simulate`

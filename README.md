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

Any edits saved to this CSV are picked up automatically by the API (no code edit required).

CSV columns:

- `Product ID`
- `Recommended Product ID`
- `Label`
- `Type` (`Explicit` or `Category`)

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/fbt` | GET | `?products=id1,id2` → recommended items |
| `/api/health` | GET | service + CSV path status |
| `/api/reload` | POST | validates CSV + returns rule counts |
| `/api/debug/product` | GET | `?id=product-slug` → show exact match source |
| `/simulate` | GET | browser simulation page |
| `/widget/fbt-widget.js` | GET | embeddable widget JS |

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

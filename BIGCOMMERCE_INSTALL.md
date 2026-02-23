# BigCommerce Install (No Theme Code Needed)

Use this to install the recommendation widget on Performance Cycle cart pages.

## 1) Copy the install snippet

File: `bigcommerce-script-manager-snippet.js`

## 2) Add it in BigCommerce Script Manager

1. Go to **BigCommerce Admin**
2. Open **Storefront → Script Manager**
3. Click **Create a Script**
4. Set:
   - **Name**: `Frequently Bought Together Widget`
   - **Location on page**: `Footer`
   - **Select pages where script will be added**: `Store pages`
   - **Script category**: `Essential`
5. Paste full contents of `bigcommerce-script-manager-snippet.js`
6. Save

## 3) Verify on storefront

Open cart page and confirm widget appears:
- `/cart`
- or `/cart.php`

The snippet:
- fetches current cart items via `/api/storefront/carts`
- converts item URLs to slugs
- calls your deployed API `/api/fbt?products=...`
- renders recommendations in `#fbt-widget`

## 4) If widget does not appear

1. Ensure your deployment URL is correct in snippet:
   - `API_URL = "https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app"`
2. Confirm route works:
   - `https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app/widget/fbt-widget.js`
   - `https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app/api/health`
3. In browser dev tools Console, check for network/CORS errors.


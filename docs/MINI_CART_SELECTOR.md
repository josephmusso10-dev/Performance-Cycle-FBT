# FBT Widget Not Showing – Find Your Mini Cart Selector

If the Frequently Bought Together widget doesn’t appear in the right-side “Your Cart” panel, your theme’s mini cart likely uses different class names than the ones in the snippet. Use these steps to find the correct selector and add it.

## 1. Open your store and the mini cart

1. Go to your live store (e.g. performancecycle.com).
2. Add any product to the cart.
3. Open the **Your Cart** panel (slide-out or dropdown on the right).

## 2. Inspect the cart panel in the browser

1. **Right‑click** inside the cart panel (on the white area that shows the cart items, subtotal, and “CHECK OUT NOW”).
2. Choose **Inspect** (or **Inspect Element**).
3. In the DevTools **Elements** (or **Inspector**) tab, the HTML for the cart will be highlighted.

## 3. Find the best container to use

In the inspector, move **up** the HTML tree from the highlighted element. You’re looking for a **single parent element** that wraps:

- The whole visible cart content (cart items, subtotal, grand total, checkout button),

and that **does not** wrap the rest of the page (header, main content, etc.).

Often it’s a `<div>` with a **class** or **id**, for example:

- `class="cart-drawer"`
- `class="minicart"`
- `id="cart-preview-dropdown"`
- `data-cart-preview`
- `class="dropdown-pane"` (and it’s inside a cart-related parent)

Note the **exact** class or id of that wrapper (e.g. `cart-drawer`, `minicart`).

## 4. Add the selector to the snippet

1. In BigCommerce go to **Storefront → Script Manager** and open the script that contains the FBT snippet.
2. Find the line that starts with:  
   `var MINI_CART_SELECTORS = [`
3. Add your theme’s selector as the **first** item in the array so it’s tried first.

**If your wrapper has a class** (e.g. `my-theme-cart`):

```javascript
var MINI_CART_SELECTORS = [
  ".my-theme-cart",   // <-- add this line (use your class name with a dot)
  "[data-cart-preview]",
  // ... rest unchanged
];
```

**If your wrapper has an id** (e.g. `sidebar-cart`):

```javascript
var MINI_CART_SELECTORS = [
  "#sidebar-cart",   // <-- add this line (use your id with a hash)
  "[data-cart-preview]",
  // ... rest unchanged
];
```

4. **Save** the script and reload your store. Open the mini cart again and check if the FBT block appears below the checkout button.

## 5. Optional: confirm the script is loading

1. On the store page, open DevTools (**F12** or right‑click → Inspect).
2. Go to the **Console** tab.
3. Reload the page and open the mini cart.
4. If you see any **red** errors mentioning `FBT`, `fbt-widget`, or `Script Manager`, note the message—it may point to a script or API issue rather than the selector.

## Quick checklist

- [ ] Mini cart is open and you right‑clicked inside it and chose Inspect.
- [ ] You found the wrapper element (one div that contains all cart content).
- [ ] You added its selector (e.g. `.your-cart-class` or `#your-cart-id`) as the first item in `MINI_CART_SELECTORS`.
- [ ] You saved the script in Script Manager and reloaded the store.

After adding the correct selector, the widget should appear at the bottom of the “Your Cart” panel, below “CHECK OUT NOW”.

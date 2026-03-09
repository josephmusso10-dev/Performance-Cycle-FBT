/*
  BigCommerce Script Manager snippet for Performance Cycle FBT widget.
  Shows "Frequently Bought Together" in the mini cart (slide-out/dropdown on the right).

  Usage:
  1) In BigCommerce Admin -> Storefront -> Script Manager -> Create Script
  2) Location: Footer
  3) Pages: Store pages
  4) Script Category: Essential
  5) Paste this entire snippet
*/
(function () {
  var API_URL = "https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app";

  // Selectors for the mini cart ("Your Cart" slide-out on the right when you add to cart).
  // First match wins. Performance Cycle theme uses .openCartSidebar (may contain an iframe).
  var MINI_CART_SELECTORS = [
    ".openCartSidebar",
    "[data-cart-preview]",
    "[data-cart]",
    ".cart-preview",
    ".previewCart",
    ".preview-cart",
    ".minicart",
    ".mini-cart",
    ".cart-drawer",
    ".cart-drawer__content",
    ".drawer--right",
    ".drawer--cart",
    ".sidebar-cart",
    ".cart-sidebar",
    ".dropdown--cart .dropdown-pane",
    ".dropdown--cart .dropdown-menu",
    ".navUser-action--cart .dropdown-menu",
    ".header-cart .dropdown-pane",
    ".cart-dropdown .dropdown-pane",
    ".cart-dropdown__content",
    "#cart-preview-dropdown",
    ".modal-body[data-cart]",
    ".offcanvas-cart",
    ".js-cart-preview",
  ];

  function getMiniCartContainer() {
    for (var i = 0; i < MINI_CART_SELECTORS.length; i++) {
      var el = document.querySelector(MINI_CART_SELECTORS[i]);
      if (el) return el;
    }
    return null;
  }

  function ensureContainer() {
    var existing = document.getElementById("fbt-widget");
    if (existing) return existing;

    var miniCart = getMiniCartContainer();
    if (!miniCart) return null;

    var el = document.createElement("div");
    el.id = "fbt-widget";
    el.style.cssText = "pointer-events: none;";
    if (!document.getElementById("fbt-widget-pointer-events-style")) {
      var style = document.createElement("style");
      style.id = "fbt-widget-pointer-events-style";
      style.textContent = "#fbt-widget * { pointer-events: auto; }";
      document.head.appendChild(style);
    }
    miniCart.appendChild(el);
    return el;
  }

  function toSlug(url) {
    if (!url || typeof url !== "string") return "";
    return url.replace(/^https?:\/\/[^/]+/i, "").replace(/^\/+|\/+$/g, "");
  }

  function unique(arr) {
    var map = {};
    var out = [];
    for (var i = 0; i < arr.length; i++) {
      var v = arr[i];
      if (!v || map[v]) continue;
      map[v] = true;
      out.push(v);
    }
    return out;
  }

  function getCartSlugs() {
    // BigCommerce Storefront cart endpoint (same-origin)
    return fetch("/api/storefront/carts", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return [];
        return r.json();
      })
      .then(function (carts) {
        if (!Array.isArray(carts) || carts.length === 0) return [];
        var cart = carts[0];
        var lineItems = (cart.lineItems || {});
        var all = []
          .concat(lineItems.physicalItems || [])
          .concat(lineItems.digitalItems || [])
          .concat(lineItems.customItems || []);

        var slugs = all.map(function (item) {
          // item.url often has /product-slug/
          return toSlug(item.url || "");
        });
        return unique(slugs);
      })
      .catch(function () {
        return [];
      });
  }

  function loadWidgetScript() {
    return new Promise(function (resolve, reject) {
      if (window.FBTWidget) return resolve();
      var s = document.createElement("script");
      s.src = API_URL + "/widget/fbt-widget.js?v=5";
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function init() {
    var miniCart = getMiniCartContainer();
    if (!miniCart) return;

    var container = ensureContainer();
    if (!container) return;
    window._fbtInitialized = true;
    Promise.all([loadWidgetScript(), getCartSlugs()]).then(function (res) {
      var slugs = res[1] || [];
      if (!window.FBTWidget) return;
      window.FBTWidget.init({
        apiUrl: API_URL,
        cartProductIds: slugs,
        containerId: "fbt-widget",
        title: "Frequently Bought Together",
        showAddButton: false,
        onAddToCart: null,
        layout: "minicart",
        theme: {
          text: "#333",
          muted: "#6b7280",
          border: "#e5e7eb",
          accent: "#b91c1c"
        }
      });
      // When mini cart is visible, refresh recommendations (e.g. after add-to-cart)
      if (miniCart && window.IntersectionObserver) {
        var widget = document.getElementById("fbt-widget");
        if (widget) {
          var io = new IntersectionObserver(
            function (entries) {
              entries.forEach(function (entry) {
                if (entry.isIntersecting && window.FBTWidget) {
                  getCartSlugs().then(function (newSlugs) {
                    window.FBTWidget.refresh(newSlugs);
                  });
                }
              });
            },
            { root: null, threshold: 0.1 }
          );
          io.observe(widget);
        }
      }
    });
  }

  var retryCount = 0;
  var maxRetries = 5;

  function tryInit() {
    if (window._fbtInitialized) return;
    if (retryCount > maxRetries) return;
    init();
    if (!window._fbtInitialized && retryCount < maxRetries) {
      retryCount++;
      setTimeout(tryInit, 600);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      tryInit();
    });
  } else {
    tryInit();
  }
})();


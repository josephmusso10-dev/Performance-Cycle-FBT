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
  if (typeof console !== "undefined" && console.log) {
    console.log("FBT: Product Recommendations script loaded");
  }
  var API_URL = "https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app";

  // Selectors for the mini cart ("Your Cart" slide-out). First match wins.
  // If the widget doesn't appear: right-click inside the cart panel -> Inspect, find the wrapper
  // div that contains the cart items + "CHECK OUT NOW", and add its class or id here (e.g. ".your-cart-class").
  var MINI_CART_SELECTORS = [
    "#halo-cart-sidebar",
    ".halo-cart-sidebar",
    ".openCartSidebar",
    ".modal-dialog",
    ".drawer",
    "[data-cart-drawer]",
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

  function findCartByText() {
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    var node;
    while ((node = walker.nextNode())) {
      if (node.textContent && node.textContent.trim() === "Your Cart") {
        var el = node.parentElement;
        while (el && el !== document.body) {
          if (el.innerText && (el.innerText.indexOf("CHECK OUT") >= 0 || el.innerText.indexOf("CHECKOUT") >= 0)) {
            return el;
          }
          el = el.parentElement;
        }
      }
    }
    return null;
  }

  function getMiniCartContainer() {
    for (var i = 0; i < MINI_CART_SELECTORS.length; i++) {
      var el = document.querySelector(MINI_CART_SELECTORS[i]);
      if (el) {
        if (typeof console !== "undefined" && console.log) {
          console.log("FBT: Injected into " + MINI_CART_SELECTORS[i]);
        }
        return el;
      }
    }
    var fallback = findCartByText();
    if (fallback) {
      if (typeof console !== "undefined" && console.log) {
        console.log("FBT: Injected via fallback (found 'Your Cart' + CHECK OUT)");
      }
      return fallback;
    }
    if (typeof console !== "undefined" && console.log) {
      console.log("FBT: No mini cart container found. Widget will not show.");
    }
    return null;
  }

  function ensureContainer(cb) {
    var miniCart = getMiniCartContainer();
    if (!miniCart) return cb(null);
    var existing = document.getElementById("fbt-widget");
    if (existing) return cb(existing);
    var el = document.createElement("div");
    el.id = "fbt-widget";
    el.style.cssText = "pointer-events: none; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e5e7eb;";
    if (!document.getElementById("fbt-widget-pointer-events-style")) {
      var style = document.createElement("style");
      style.id = "fbt-widget-pointer-events-style";
      style.textContent = "#fbt-widget * { pointer-events: auto; }";
      document.head.appendChild(style);
    }
    miniCart.appendChild(el);
    cb(el);
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

    ensureContainer(function (container) {
      if (!container) return;
      window._fbtInitialized = true;
      Promise.all([loadWidgetScript(), getCartSlugs()]).then(function (res) {
        var slugs = res[1] || [];
        if (!window.FBTWidget) return;
        var containerId = "fbt-widget";
        window.FBTWidget.init({
          apiUrl: API_URL,
          cartProductIds: slugs,
          containerId: containerId,
          title: "Product Recommendations",
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
        var widget = document.getElementById(containerId);
        if (!widget && container && container.ownerDocument) {
          widget = container.ownerDocument.getElementById(containerId);
        }
        if (miniCart && widget && window.IntersectionObserver) {
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
      });
    });
  }

  var retryCount = 0;
  var maxRetries = 25;

  function tryInit() {
    if (window._fbtInitialized) return;
    if (retryCount > maxRetries) return;
    init();
    if (!window._fbtInitialized && retryCount < maxRetries) {
      retryCount++;
      setTimeout(tryInit, 800);
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


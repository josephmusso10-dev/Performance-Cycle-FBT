/*
  BigCommerce Script Manager snippet for Performance Cycle FBT widget.
  Usage:
  1) In BigCommerce Admin -> Storefront -> Script Manager -> Create Script
  2) Location: Footer
  3) Pages: Store pages
  4) Script Category: Essential
  5) Paste this entire snippet
*/
(function () {
  var API_URL = "https://performance-cycle-mb1rd1mcs-josephmusso10-devs-projects.vercel.app";

  function isCartPage() {
    var p = window.location.pathname.toLowerCase();
    return p.indexOf("/cart") === 0 || p.indexOf("/cart.php") === 0;
  }

  function ensureContainer() {
    var existing = document.getElementById("fbt-widget");
    if (existing) return existing;

    var el = document.createElement("div");
    el.id = "fbt-widget";

    // Best-effort placement across Stencil variants
    var targets = [
      ".cart-content",
      ".page-content",
      ".cart",
      "main",
      "body",
    ];
    for (var i = 0; i < targets.length; i++) {
      var t = document.querySelector(targets[i]);
      if (t) {
        t.appendChild(el);
        return el;
      }
    }
    document.body.appendChild(el);
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
      s.src = API_URL + "/widget/fbt-widget.js";
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function init() {
    if (!isCartPage()) return;
    ensureContainer();
    Promise.all([loadWidgetScript(), getCartSlugs()]).then(function (res) {
      var slugs = res[1] || [];
      if (!window.FBTWidget) return;
      window.FBTWidget.init({
        apiUrl: API_URL,
        cartProductIds: slugs,
        containerId: "fbt-widget",
        title: "Frequently Bought Together",
        // If no catalog is passed, widget falls back to slug IDs.
        onAddToCart: function (slug) {
          // Default behavior: send user to product page.
          window.location.href = "/" + slug + "/";
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();


/**
 * Frequently Bought Together Widget - Performance Cycle (Englewood, CO)
 *
 * Shows accessory recommendations based on cart contents.
 * E.g., helmet in cart → recommend visor, pinlock, chin curtain.
 *
 * Usage:
 * 1. Include: <script src="/path/to/fbt-widget.js"></script>
 * 2. Add container: <div id="fbt-widget"></div>
 * 3. Initialize:
 *    FBTWidget.init({
 *      apiUrl: 'https://your-api.com',
 *      cartProductIds: ['helmet-001'],  // From your cart
 *      productCatalog: { ... }  // id -> {name, image, url, price}
 *    });
 */

(function() {
  'use strict';

  const defaultConfig = {
    apiUrl: 'http://localhost:5000',
    cartProductIds: [],
    productCatalog: {},
    containerId: 'fbt-widget',
    maxRecommendations: 6,
    title: 'Frequently Bought Together',
    onAddToCart: null,  // Optional: (productId) => {} - called when user clicks add
    emptyMessage: 'Add items to your cart to see recommendations.',
    loadingMessage: 'Loading recommendations...',
  };

  function renderProduct(rec, catalog) {
    const id = rec.id || rec;
    const label = rec.label || '';
    const p = catalog[id] || {};
    const name = p.name || id;
    const image = p.image || '';
    const url = p.url || '#';
    const price = p.price ? `$${parseFloat(p.price).toFixed(2)}` : '';

    return `
      <div class="fbt-product" data-id="${id}">
        <a href="${url}" class="fbt-product-link">
          ${image ? `<img src="${image}" alt="${name}" class="fbt-product-img">` : ''}
          <div class="fbt-product-info">
            <span class="fbt-product-name">${escapeHtml(name)}</span>
            ${label ? `<span class="fbt-product-label">${escapeHtml(label)}</span>` : ''}
            ${price ? `<span class="fbt-product-price">${price}</span>` : ''}
          </div>
        </a>
        <button type="button" class="fbt-add-btn button button--small" data-id="${id}">Add to Cart</button>
      </div>
    `;
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function injectStyles() {
    if (document.getElementById('fbt-widget-styles')) return;
    const style = document.createElement('style');
    style.id = 'fbt-widget-styles';
    style.textContent = `
      .fbt-widget {
        --fbt-border: #e5e5e5;
        --fbt-text: #222;
        --fbt-muted: #6b7280;
        --fbt-bg: #fff;
        --fbt-btn-bg: #111;
        --fbt-btn-hover: #333;
        font-family: inherit;
        color: var(--fbt-text);
        padding: 1.25rem 0;
        border-top: 1px solid var(--fbt-border);
      }
      .fbt-title {
        font-size: 1.15rem;
        font-weight: 600;
        margin: 0 0 0.85rem;
        color: var(--fbt-text);
        letter-spacing: 0.01em;
      }
      .fbt-products { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.85rem; }
      .fbt-product { background: var(--fbt-bg); border: 1px solid var(--fbt-border); border-radius: 3px; overflow: hidden; }
      .fbt-product-link { display: block; text-decoration: none; color: inherit; }
      .fbt-product-img { width: 100%; aspect-ratio: 1; object-fit: cover; }
      .fbt-product-info { padding: 0.65rem 0.75rem 0.35rem; min-height: 78px; }
      .fbt-product-name { display: block; font-size: 0.87rem; font-weight: 600; line-height: 1.35; }
      .fbt-product-label { display: block; font-size: 0.78rem; color: var(--fbt-muted); margin-top: 0.15rem; line-height: 1.35; }
      .fbt-product-price { display: block; font-size: 0.87rem; color: var(--fbt-text); margin-top: 0.35rem; font-weight: 600; }
      .fbt-add-btn {
        width: calc(100% - 1rem);
        margin: 0.3rem 0.5rem 0.6rem;
        padding: 0.5rem 0.65rem;
        background: var(--fbt-btn-bg);
        color: #fff;
        border: 1px solid var(--fbt-btn-bg);
        border-radius: 3px;
        cursor: pointer;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }
      .fbt-add-btn:hover { background: var(--fbt-btn-hover); border-color: var(--fbt-btn-hover); }
      .fbt-empty, .fbt-loading { color: var(--fbt-muted); font-size: 0.92rem; }
      @media (max-width: 640px) {
        .fbt-products { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.65rem; }
      }
    `;
    document.head.appendChild(style);
  }

  function FBTWidget() {
    let config = { ...defaultConfig };

    function fetchRecommendations() {
      const container = document.getElementById(config.containerId);
      if (!container) return;

      if (!config.cartProductIds || config.cartProductIds.length === 0) {
        container.innerHTML = `<div class="fbt-widget"><div class="fbt-empty">${config.emptyMessage}</div></div>`;
        return;
      }

      container.innerHTML = `<div class="fbt-widget"><div class="fbt-loading">${config.loadingMessage}</div></div>`;

      const url = `${config.apiUrl.replace(/\/$/, '')}/api/fbt?products=${encodeURIComponent(config.cartProductIds.join(','))}`;

      fetch(url)
        .then(r => r.json())
        .then(data => {
          const recs = (data.recommendations || []).slice(0, config.maxRecommendations);
          if (recs.length === 0) {
            container.innerHTML = `<div class="fbt-widget"><div class="fbt-empty">No recommendations at this time.</div></div>`;
            return;
          }

          const toRec = r => (typeof r === 'object' && r.id ? r : { id: r, label: '' });
          const html = `
            <div class="fbt-widget">
              <h3 class="fbt-title">${config.title}</h3>
              <div class="fbt-products">
                ${recs.map(r => renderProduct(toRec(r), config.productCatalog)).join('')}
              </div>
            </div>
          `;
          container.innerHTML = html;

          container.querySelectorAll('.fbt-add-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
              e.preventDefault();
              const id = btn.dataset.id;
              if (typeof config.onAddToCart === 'function') {
                config.onAddToCart(id);
              } else {
                window.location.href = (config.productCatalog[id] || {}).url || '#';
              }
            });
          });
        })
        .catch(err => {
          container.innerHTML = `<div class="fbt-widget"><div class="fbt-empty">Could not load recommendations.</div></div>`;
          console.error('FBT Widget error:', err);
        });
    }

    return {
      init(opts) {
        config = { ...defaultConfig, ...opts };
        injectStyles();
        fetchRecommendations();
      },
      refresh(cartProductIds) {
        config.cartProductIds = cartProductIds || config.cartProductIds;
        fetchRecommendations();
      }
    };
  }

  window.FBTWidget = FBTWidget();
})();

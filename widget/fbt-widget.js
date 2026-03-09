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
    apiUrl: 'http://localhost:5050',
    cartProductIds: [],
    productCatalog: {},
    containerId: 'fbt-widget',
    maxRecommendations: 6,
    title: 'Frequently Bought Together',
    showAddButton: true,
    layout: '', // 'minicart' = compact list for right-side cart drawer
    productUrlBase: '',
    productUrlPattern: '/{slug}/',
    theme: {
      border: '#e5e5e5',
      text: '#222',
      muted: '#6b7280',
      bg: '#fff',
      buttonBg: '#111',
      buttonHover: '#333',
      radius: '3px',
      headingSize: '1.15rem',
      cardNameSize: '0.87rem',
      buttonTextColor: '#fff',
      accent: '#b91c1c' // Performance Cycle red accent for links
    },
    onAddToCart: null,
    emptyMessage: 'Add items to your cart to see recommendations.',
    loadingMessage: 'Loading recommendations...',
  };

  function getProductUrl(id, catalog, cfg) {
    const p = catalog[id] || {};
    if (p.url && typeof p.url === 'string' && p.url.trim()) {
      const rawUrl = p.url.trim();
      if (/^https?:\/\//i.test(rawUrl)) return rawUrl;
      if (rawUrl.startsWith('/')) {
        const base = (((cfg && cfg.productUrlBase) || '').trim()).replace(/\/$/, '');
        return base ? `${base}${rawUrl}` : rawUrl;
      }
      return rawUrl;
    }
    // Fallback assumes recommendation IDs are storefront slugs.
    const slug = encodeURIComponent(id);
    const pattern = ((cfg && cfg.productUrlPattern) || '/{slug}/').replace('{slug}', slug);
    const base = (((cfg && cfg.productUrlBase) || '').trim()).replace(/\/$/, '');
    return `${base}${pattern.startsWith('/') ? pattern : `/${pattern}`}`;
  }

  function renderProduct(rec, catalog, cfg) {
    const id = rec.id || rec;
    const label = rec.label || '';
    const p = catalog[id] || {};
    const name = p.name || id;
    const image = p.image || '';
    const url = getProductUrl(id, catalog, cfg);
    const price = p.price ? `$${parseFloat(p.price).toFixed(2)}` : '';
    const isMinicart = cfg.layout === 'minicart';

    if (isMinicart) {
      return `
        <div class="fbt-product fbt-product--minicart" data-id="${id}">
          <a href="${url}" class="fbt-product-link">
            <div class="fbt-product-img-wrap">
              ${image ? `<img src="${image}" alt="${name}" class="fbt-product-img">` : '<span class="fbt-product-img fbt-product-img--placeholder"></span>'}
            </div>
            <div class="fbt-product-info">
              <span class="fbt-product-name">${escapeHtml(name)}</span>
              ${price ? `<span class="fbt-product-price">${price}</span>` : ''}
            </div>
          </a>
          <a href="${url}" class="fbt-view-link">View Product</a>
        </div>
      `;
    }

    const ctaHtml = cfg.showAddButton
      ? `<button type="button" class="fbt-add-btn" data-id="${id}">Add to Cart</button>`
      : `<a href="${url}" class="fbt-view-link">View Product</a>`;

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
        ${ctaHtml}
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
        --fbt-btn-text: #fff;
        --fbt-radius: 3px;
        --fbt-heading-size: 1.15rem;
        --fbt-card-name-size: 0.87rem;
        font-family: inherit;
        color: var(--fbt-text);
        padding: 1.25rem 0;
        border-top: 1px solid var(--fbt-border);
      }
      .fbt-title {
        font-size: var(--fbt-heading-size);
        font-weight: 600;
        margin: 0 0 0.85rem;
        color: var(--fbt-text);
        letter-spacing: 0.01em;
      }
      .fbt-products { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.85rem; }
      .fbt-product { background: var(--fbt-bg); border: 1px solid var(--fbt-border); border-radius: var(--fbt-radius); overflow: hidden; }
      .fbt-product-link { display: block; text-decoration: none; color: inherit; }
      .fbt-product-img { width: 100%; aspect-ratio: 1; object-fit: cover; }
      .fbt-product-info { padding: 0.65rem 0.75rem 0.35rem; min-height: 78px; }
      .fbt-product-name { display: block; font-size: var(--fbt-card-name-size); font-weight: 600; line-height: 1.35; }
      .fbt-product-label { display: block; font-size: 0.78rem; color: var(--fbt-muted); margin-top: 0.15rem; line-height: 1.35; }
      .fbt-product-price { display: block; font-size: 0.87rem; color: var(--fbt-text); margin-top: 0.35rem; font-weight: 600; }
      .fbt-add-btn {
        width: calc(100% - 1rem);
        margin: 0.3rem 0.5rem 0.6rem;
        padding: 0.5rem 0.65rem;
        background: var(--fbt-btn-bg);
        color: var(--fbt-btn-text);
        border: 1px solid var(--fbt-btn-bg);
        border-radius: var(--fbt-radius);
        cursor: pointer;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.02em;
      }
      .fbt-add-btn:hover { background: var(--fbt-btn-hover); border-color: var(--fbt-btn-hover); }
      .fbt-view-link {
        display: block;
        width: calc(100% - 1rem);
        margin: 0.3rem 0.5rem 0.6rem;
        padding: 0.5rem 0.65rem;
        border: 1px solid var(--fbt-border);
        border-radius: var(--fbt-radius);
        text-align: center;
        text-decoration: none;
        color: var(--fbt-text);
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.02em;
        background: #fff;
      }
      .fbt-view-link:hover { background: #f9fafb; }
      .fbt-empty, .fbt-loading { color: var(--fbt-muted); font-size: 0.92rem; }
      @media (max-width: 640px) {
        .fbt-products { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.65rem; }
      }
      /* Minicart layout: Related Products–style vertical cards */
      .fbt-widget--minicart { padding: 1rem 0 0.5rem; border-top: 1px solid var(--fbt-border); }
      .fbt-widget--minicart .fbt-title { font-size: 1rem; margin: 0 0 0.75rem; font-weight: 700; color: var(--fbt-text); letter-spacing: 0; }
      .fbt-widget--minicart .fbt-products { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
      .fbt-product--minicart { display: flex; flex-direction: column; background: var(--fbt-bg); }
      .fbt-product--minicart .fbt-product-link { display: flex; flex-direction: column; text-decoration: none; color: inherit; }
      .fbt-product--minicart .fbt-product-img-wrap { width: 100%; aspect-ratio: 1; overflow: hidden; background: #f5f5f5; display: flex; align-items: center; justify-content: center; margin-bottom: 0.5rem; }
      .fbt-product--minicart .fbt-product-img { width: 100%; height: 100%; object-fit: contain; }
      .fbt-product--minicart .fbt-product-img--placeholder { width: 100%; height: 100%; background: var(--fbt-border); }
      .fbt-product--minicart .fbt-product-info { padding: 0; min-height: 0; }
      .fbt-product--minicart .fbt-product-name { display: block; font-size: 0.82rem; font-weight: 700; line-height: 1.3; color: var(--fbt-text); margin-bottom: 0.25rem; }
      .fbt-product--minicart .fbt-product-price { display: block; font-size: 0.82rem; font-weight: 700; color: var(--fbt-text); margin-bottom: 0.5rem; }
      .fbt-product--minicart .fbt-view-link { display: block; text-align: center; padding: 0.4rem 0.5rem; border: 1px solid var(--fbt-border); border-radius: var(--fbt-radius); font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; text-decoration: none; color: var(--fbt-text); background: #fff; margin-top: auto; }
      .fbt-product--minicart .fbt-view-link:hover { background: #f5f5f5; }
    `;
    document.head.appendChild(style);
  }

  function FBTWidget() {
    let config = { ...defaultConfig };

    function applyTheme(container) {
      const root = container && container.querySelector ? container.querySelector('.fbt-widget') : null;
      if (!root) return;
      const theme = config.theme || {};
      const setVar = (name, value) => {
        if (value === undefined || value === null || value === '') return;
        root.style.setProperty(name, String(value));
      };
      setVar('--fbt-border', theme.border);
      setVar('--fbt-text', theme.text);
      setVar('--fbt-muted', theme.muted);
      setVar('--fbt-bg', theme.bg);
      setVar('--fbt-btn-bg', theme.buttonBg);
      setVar('--fbt-btn-hover', theme.buttonHover);
      setVar('--fbt-btn-text', theme.buttonTextColor);
      setVar('--fbt-radius', theme.radius);
      setVar('--fbt-heading-size', theme.headingSize);
      setVar('--fbt-card-name-size', theme.cardNameSize);
      setVar('--fbt-accent', theme.accent);
    }

    function hydrateCatalogForRecommendations(recs) {
      const ids = recs
        .map(r => (typeof r === 'object' && r.id ? r.id : r))
        .filter(Boolean)
        .filter(id => {
          const p = config.productCatalog[id] || {};
          return !p.url;
        });
      if (ids.length === 0) return Promise.resolve();

      const uniqueIds = Array.from(new Set(ids));
      const url = `${config.apiUrl.replace(/\/$/, '')}/api/catalog?ids=${encodeURIComponent(uniqueIds.join(','))}`;
      return fetch(url)
        .then(r => r.json())
        .then(data => {
          const items = (data && data.items) || {};
          Object.keys(items).forEach(id => {
            config.productCatalog[id] = { ...(config.productCatalog[id] || {}), ...items[id] };
          });
        })
        .catch(() => {});
    }

    function fetchRecommendations() {
      const container = document.getElementById(config.containerId);
      if (!container) return;

      if (!config.cartProductIds || config.cartProductIds.length === 0) {
        container.innerHTML = `<div class="fbt-widget"><div class="fbt-empty">${config.emptyMessage}</div></div>`;
        applyTheme(container);
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
            applyTheme(container);
            return;
          }
          return hydrateCatalogForRecommendations(recs).then(() => recs);
        })
        .then(recs => {
          if (!recs) return;

          const toRec = r => (typeof r === 'object' && r.id ? r : { id: r, label: '' });
          const layoutClass = config.layout === 'minicart' ? ' fbt-widget--minicart' : '';
          const html = `
            <div class="fbt-widget${layoutClass}">
              <h3 class="fbt-title">${config.title}</h3>
              <div class="fbt-products">
                ${recs.map(r => renderProduct(toRec(r), config.productCatalog, config)).join('')}
              </div>
            </div>
          `;
          container.innerHTML = html;
          applyTheme(container);

          if (config.showAddButton) {
            container.querySelectorAll('.fbt-add-btn').forEach(btn => {
              btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const id = btn.dataset.id;
                if (typeof config.onAddToCart === 'function') {
                  config.onAddToCart(id);
                } else {
                  window.location.href = getProductUrl(id, config.productCatalog, config);
                }
              });
            });
          }
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

// Mini App UI helpers. TZ section 30 (components.js).
// Vanilla, no bundler: everything hangs off the global `UI`. Loaded via <script>.

const UI = (() => {
  // Escape user/content strings before injecting into innerHTML.
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const money = (v) => {
    if (v == null || isNaN(v)) return '—';
    return Math.round(v).toLocaleString('ru-RU') + ' \u20BD';
  };

  const spinner = () => '<div class="spinner">Загрузка…</div>';
  const empty = (text) => `<div class="empty">${esc(text || 'Нет данных')}</div>`;
  const error = (text) => `<div class="empty err">${esc(text || 'Ошибка загрузки')}</div>`;

  const urgencyBadge = (u) => {
    if (!u) return '';
    const label = { hot: 'горячий', warm: 'тёплый', cold: 'холодный' }[u] || u;
    return `<span class="badge ${esc(u)}">${esc(label)}</span>`;
  };

  const card = (inner) => `<div class="card">${inner}</div>`;

  // Render an array with a template fn, or an empty state.
  const list = (items, tmpl, emptyText) =>
    (items && items.length) ? items.map(tmpl).join('') : empty(emptyText);

  // Mount HTML into #view and run an optional wiring callback.
  const render = (html, wire) => {
    const view = document.getElementById('view');
    if (view) view.innerHTML = html;
    if (typeof wire === 'function') wire();
  };

  const setHeader = (title, sub) => {
    const h = document.getElementById('header-title');
    const s = document.getElementById('header-sub');
    if (h) h.textContent = title || '';
    if (s) s.textContent = sub || '';
  };

  const toast = (msg) => {
    try {
      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.showPopup) {
        window.Telegram.WebApp.showPopup({ message: msg });
        return;
      }
    } catch (e) { /* ignore */ }
    // eslint-disable-next-line no-alert
    alert(msg);
  };

  return { esc, money, spinner, empty, error, urgencyBadge, card, list, render, setHeader, toast };
})();

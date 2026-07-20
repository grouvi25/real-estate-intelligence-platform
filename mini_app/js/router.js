// Mini App SPA router (hash-based). TZ section 30 (router.js).
// Routes are registered as { pattern: handler }. Patterns support :params,
// e.g. "leads/:id". No bundler: exposed as global `Router`.

const Router = (() => {
  const routes = [];
  let notFound = () => UI.render(UI.empty('Экран не найден'));

  const add = (pattern, handler) => {
    const parts = pattern.split('/').filter(Boolean);
    routes.push({ parts, handler });
  };

  const setNotFound = (fn) => { notFound = fn; };

  const parse = () => {
    const hash = (location.hash || '#/').replace(/^#\/?/, '');
    return hash.split('/').filter(Boolean);
  };

  const match = (segments) => {
    for (const r of routes) {
      if (r.parts.length !== segments.length) continue;
      const params = {};
      let ok = true;
      for (let i = 0; i < r.parts.length; i++) {
        const p = r.parts[i];
        if (p.startsWith(':')) params[p.slice(1)] = decodeURIComponent(segments[i]);
        else if (p !== segments[i]) { ok = false; break; }
      }
      if (ok) return { handler: r.handler, params };
    }
    return null;
  };

  const resolve = () => {
    const segments = parse();
    const m = match(segments);
    // Sync bottom-nav active state to the top-level route.
    const top = segments[0] || 'dashboard';
    document.querySelectorAll('.nav a').forEach((a) => {
      a.classList.toggle('active', a.getAttribute('data-route') === top);
    });
    // Telegram back button on non-root screens.
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg && tg.BackButton) {
        if (segments.length > 1) { tg.BackButton.show(); }
        else { tg.BackButton.hide(); }
      }
    } catch (e) { /* ignore */ }

    if (m) {
      Promise.resolve(m.handler(m.params)).catch((err) => {
        UI.render(UI.error('Ошибка: ' + (err && err.message ? err.message : err)));
      });
    } else {
      notFound();
    }
  };

  const go = (path) => { location.hash = '#/' + path.replace(/^\/?#?\/?/, ''); };

  const start = () => {
    window.addEventListener('hashchange', resolve);
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg && tg.BackButton) tg.BackButton.onClick(() => history.back());
    } catch (e) { /* ignore */ }
    resolve();
  };

  return { add, setNotFound, start, go, resolve };
})();

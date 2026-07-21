// Mini App hash router. Global `Router`. Patterns support :params ("leads/:id").
const Router = (() => {
  const routes = [];
  let notFound = () => UI.render(UI.empty({ title: 'Экран не найден' }));

  const add = (pattern, handler) => {
    routes.push({ parts: pattern.split('/').filter(Boolean), handler });
  };
  const setNotFound = (fn) => { notFound = fn; };

  const parse = () => (location.hash || '#/').replace(/^#\/?/, '').split('/').filter(Boolean);

  const match = (segs) => {
    for (const r of routes) {
      if (r.parts.length !== segs.length) continue;
      const params = {}; let ok = true;
      for (let i = 0; i < r.parts.length; i++) {
        const p = r.parts[i];
        if (p[0] === ':') params[p.slice(1)] = decodeURIComponent(segs[i]);
        else if (p !== segs[i]) { ok = false; break; }
      }
      if (ok) return { handler: r.handler, params };
    }
    return null;
  };

  const resolve = () => {
    const segs = parse();
    const top = segs[0] || 'dashboard';
    document.querySelectorAll('.nav__item').forEach((a) =>
      a.classList.toggle('nav__item--active', a.getAttribute('data-route') === top));
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg && tg.BackButton) { segs.length > 1 ? tg.BackButton.show() : tg.BackButton.hide(); }
    } catch (e) { /* ignore */ }

    const m = match(segs);
    if (m) {
      Promise.resolve(m.handler(m.params)).catch((err) =>
        UI.render(UI.errorState(err && err.message ? err.message : String(err))));
    } else { notFound(); }
  };

  const go = (path) => { location.hash = '#/' + String(path).replace(/^#?\/?/, ''); };

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

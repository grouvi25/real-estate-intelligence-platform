// Mini App SPA bootstrap. TZ section 30 (app.js).
// Registers routes, authenticates, renders the shell (header + bottom nav), and
// starts the hash router.

(function () {
  const ROUTES = [
    ['dashboard', Screens.dashboard],
    ['signals', Screens.signals],
    ['signals/:id', Screens.signalDetail],
    ['queue', Screens.queue],
    ['leads', Screens.leads],
    ['leads/:id', Screens.leadDetail],
    ['properties', Screens.properties],
    ['properties/:id', Screens.propertyDetail],
    ['analytics', Screens.analytics],
    ['settings', Screens.settings],
  ];

  const NAV = [
    ['dashboard', '🏠', 'Дом'],
    ['queue', '💬', 'Ответы'],
    ['leads', '👤', 'Лиды'],
    ['properties', '🏢', 'Объекты'],
    ['analytics', '📊', 'Аналитика'],
    ['settings', '⚙️', 'Профиль'],
  ];

  function renderShell() {
    document.body.innerHTML = `
      <header class="app-header">
        <h1 id="header-title">Real Estate Intelligence</h1>
        <div class="sub" id="header-sub"></div>
      </header>
      <main id="view"><div class="spinner">Загрузка…</div></main>
      <nav class="nav">
        ${NAV.map(([r, ico, label]) =>
          `<a data-route="${r}" href="#/${r}"><span class="ico">${ico}</span>${label}</a>`).join('')}
      </nav>
    `;
  }

  async function boot() {
    try {
      await authenticate();
    } catch (e) {
      document.body.innerHTML =
        '<div class="empty err">Не удалось авторизоваться. Откройте приложение через бота.</div>';
      // eslint-disable-next-line no-console
      console.error('Auth failed:', e);
      return;
    }
    renderShell();
    ROUTES.forEach(([pattern, handler]) => Router.add(pattern, handler));
    Router.setNotFound(() => UI.render(UI.empty('Экран не найден')));
    if (!location.hash) location.hash = '#/dashboard';
    Router.start();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();

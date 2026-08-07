// Mini App bootstrap: auth, shell (header + nav), routes, router start.
(function () {
  // The server explains refusals in Russian ("нужна ссылка-приглашение"); the
  // Telegram SDK throws things like "WebAppMethodUnsupported", which means
  // nothing to a person and only happens outside Telegram anyway.
  function authHint(e) {
    const msg = String((e && e.message) || '');
    return /[а-яё]/i.test(msg) ? msg : 'Откройте кабинет кнопкой в боте.';
  }

  const ROUTES = [
    ['dashboard', () => Screens.dashboard()],
    ['signals', () => Screens.signals()],
    ['signals/:id', (p) => Screens.signalDetail(p)],
    ['queue', () => Screens.queue()],
    ['leads', () => Screens.leads()],
    ['leads/new', () => Screens.leadNew()],
    ['leads/:id', (p) => Screens.leadDetail(p)],
    ['properties', () => Screens.properties()],
    ['properties/import', () => Screens.propertyImport()],
    ['properties/:id', (p) => Screens.propertyDetail(p)],
    ['analytics', () => Screens.analytics()],
    ['settings', () => Screens.settings()],
    ['partners/:id', (p) => Screens.partnerDetail(p)],
    ['referrals', () => Screens.referrals()],
    ['tasks', () => Screens.tasks()],
    ['sources', () => Screens.sources()],
  ];

  const NAV = [
    ['dashboard', 'dashboard', 'Обзор'],
    ['signals', 'signals', 'Сигналы'],
    ['leads', 'leads', 'Лиды'],
    ['properties', 'properties', 'Объекты'],
    ['analytics', 'analytics', 'Аналитика'],
  ];

  function shell() {
    document.body.innerHTML =
      '<header class="header" id="hdr"></header>' +
      '<main id="view"></main>' +
      '<nav class="nav">' + NAV.map(([r, ic, l]) =>
        `<a class="nav__item" data-route="${r}" href="#/${r}">${Icons.svg(ic, 'nav__ico')}<span>${l}</span></a>`
      ).join('') + '</nav>';
  }

  async function boot() {
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
    } catch (e) { /* ignore */ }

    try {
      await authenticate();
    } catch (e) {
      document.body.innerHTML =
        '<div class="empty" style="padding-top:80px">' + Icons.svg('close') +
        '<div class="empty__t">Не удалось войти</div>' +
        '<div class="empty__s">' + UI.esc(authHint(e)) + '</div></div>';
      return;
    }

    shell();
    ROUTES.forEach(([p, h]) => Router.add(p, h));
    Router.setNotFound(() => UI.render(UI.empty({ title: 'Экран не найден' })));
    if (!location.hash) location.hash = '#/dashboard';
    Router.start();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();

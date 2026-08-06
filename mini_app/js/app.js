// Mini App bootstrap: auth, shell (header + nav), routes, router start.
(function () {
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
        '<div class="empty__t">Не удалось авторизоваться</div>' +
        '<div class="empty__s">Откройте приложение через кнопку в боте.</div></div>';
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

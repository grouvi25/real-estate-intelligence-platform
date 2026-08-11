// Mini App bootstrap: auth, shell (header + nav), routes, router start.
(function () {
  // What the person in front of the screen can actually do about it.
  //
  // This used to answer "Откройте кабинет кнопкой в боте" to everything,
  // because the API client threw "API 403" and the check below found no
  // Cyrillic in it. So a manager who had simply never been invited was told to
  // do the one thing that could not help -- and the complaint that reached us
  // was "Telegram won't let me in", which sent the search in the wrong
  // direction entirely.
  function authHint(e) {
    const code = e && e.code;
    if (code === 'INVITE_REQUIRED') {
      return 'Вас ещё нет в агентстве. Попросите владельца прислать ссылку-приглашение и войдите по ней — один раз, дальше кабинет открывается кнопкой в боте.';
    }
    if (code === 'INVITE_INVALID') {
      return 'Ссылка-приглашение больше не действует. Попросите владельца прислать новую.';
    }
    if (e && e.status === 401) {
      return 'Telegram не подтвердил вход. Закройте приложение и откройте заново кнопкой в боте.';
    }
    if (!PlatformSDK.inTelegram) return 'Откройте кабинет в Telegram — кнопкой в боте.';
    const msg = String((e && e.message) || '');
    if (/[а-яё]/i.test(msg)) return msg;
    // Everything left is the network: the SDK's own failures read like
    // "WebAppMethodUnsupported" and mean nothing to anybody.
    return 'Не удалось связаться с сервером. Попробуйте ещё раз через минуту.';
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
        '<div class="empty__s">' + UI.esc(authHint(e)) + '</div>' +
        '<button class="btn" id="retry" style="margin-top:16px">Попробовать снова</button></div>';
      const retry = document.getElementById('retry');
      if (retry) retry.onclick = () => location.reload();
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

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
    ['sources/discovery', () => Screens.discovery()],
    ['collection', () => Screens.collection()],
    ['admin', () => Screens.admin()],
    ['admin/geo', () => Screens.adminGeo()],
    ['admin/geo/new', () => Screens.adminGeoNew()],
    ['admin/sources', () => Screens.adminSources()],
    ['admin/bot', () => Screens.adminBot()],
  ];

  const NAV = [
    ['dashboard', 'dashboard', 'Обзор'],
    ['signals', 'signals', 'Сигналы'],
    ['leads', 'leads', 'Лиды'],
    ['properties', 'properties', 'Объекты'],
    ['analytics', 'analytics', 'Аналитика'],
  ];

  // Routes a demo visitor may open: the allowed tabs and one level below them
  // (ТЗ «Сигналы» 7.1, D-02/D-03). Anything else says what it would take.
  const DEMO_ROUTES = { dashboard: ['dashboard'], signals: ['signals', 'signals/:id', 'queue'],
    leads: ['leads', 'leads/:id'], analytics: ['analytics'] };

  function demoBar() {
    const d = window._demo;
    return `<div class="demo-bar" role="status">
      <div>⚡ ${UI.esc(d.headline || 'Демо-режим — данные синтетические')}. Хотите реальные?
        <button class="demo-bar__cta" data-demo-request>Оставьте заявку</button></div>
      <div class="demo-bar__row">
        <label class="demo-bar__city">Город
          <select id="demo-city">${(d.cities || []).map((c) =>
            `<option${c === d.city ? ' selected' : ''}>${UI.esc(c)}</option>`).join('')}</select></label>
        <button class="btn btn--sm" data-demo-request>Подключить для ${UI.esc(d.city)}</button>
      </div>
    </div>`;
  }

  // «Оставьте заявку» (ТЗ «Сигналы» 7.5): the request goes to the platform's
  // operators, who call back -- no Telegram needed.
  function openDemoRequest() {
    const d = window._demo;
    UI.sheet('Подключить REIP', `
      <div class="item__sub" style="margin-top:0">Оставьте контакты — покажем систему на данных
        вашего города и расскажем про подключение.</div>
      <div class="field mt-3"><label for="dr-city">Город</label><input id="dr-city" value="${UI.esc(d.city)}"></div>
      <div class="field"><label for="dr-agency">Агентство</label><input id="dr-agency" placeholder="Название агентства"></div>
      <div class="field"><label for="dr-name">Как к вам обращаться</label><input id="dr-name"></div>
      <div class="field"><label for="dr-phone">Телефон</label>
        <input id="dr-phone" type="tel" inputmode="tel" placeholder="+7 900 123-45-67"></div>
      <label class="row" style="gap:10px;align-items:flex-start">
        <input type="checkbox" id="dr-consent">
        <span class="item__sub" style="margin-top:0">Согласен на обработку персональных данных для связи по заявке</span>
      </label>
      <button class="btn btn--block mt-3" id="dr-send">${UI.icon('send')} Отправить заявку</button>
      ${d.cta_url ? `<a class="btn btn--ghost btn--block mt-2" href="${UI.esc(d.cta_url)}" target="_blank"
         rel="noopener">${UI.icon('link')} Или напишите нам в Telegram</a>` : ''}`, (close) => {
      const btn = document.getElementById('dr-send');
      btn.onclick = () => UI.busy(btn, async () => {
        const val = (id) => document.getElementById(id).value.trim();
        if (!document.getElementById('dr-consent').checked) { UI.toast('Нужно согласие на обработку данных'); return; }
        if (!val('dr-agency') || !val('dr-phone')) { UI.toast('Укажите агентство и телефон'); return; }
        try {
          const r = await api.request('/demo/request', 'POST', {
            city: val('dr-city'), agency_name: val('dr-agency'), name: val('dr-name'),
            phone: val('dr-phone'), consent: true,
          });
          close();
          UI.toast(r.message || 'Заявка отправлена');
        } catch (e) { UI.toast(e.message); }
      });
    });
  }

  function wireDemoBar() {
    document.querySelectorAll('[data-demo-request]').forEach((b) => { b.onclick = openDemoRequest; });
    const sel = document.getElementById('demo-city');
    if (!sel) return;
    sel.onchange = async () => {
      sel.disabled = true;
      try {
        const r = await api.request('/demo/session', 'PATCH', { city: sel.value });
        window._demo.city = r.city;
        window._agency = { id: 'demo', name: 'Демо-агентство · ' + r.city, city: r.city };
        try { sessionStorage.setItem('demo_city', r.city); } catch (e) { /* ignore */ }
        document.getElementById('demobar').innerHTML = demoBar();
        wireDemoBar();
        Router.resolve();
      } catch (e) { UI.toast('Не удалось: ' + e.message); sel.disabled = false; }
    };
  }

  function shell() {
    let nav = [...NAV];
    if (window._manager && window._manager.role === 'owner') {
      nav.push(['admin', 'settings', 'Управление']);
    }
    if (window._demo) {
      const tabs = window._demo.allowed_tabs || Object.keys(DEMO_ROUTES);
      nav = nav.filter(([r]) => tabs.includes(r));
    }
    document.body.innerHTML =
      '<header class="header" id="hdr"></header>' +
      '<div class="subnotice" id="subnotice" role="alert" hidden></div>' +
      (window._demo ? '<div id="demobar">' + demoBar() + '</div>' : '') +
      '<main id="view"></main>' +
      '<nav class="nav">' + nav.map(([r, ic, l]) =>
        `<a class="nav__item" data-route="${r}" href="#/${r}">${Icons.svg(ic, 'nav__ico')}<span>${l}</span></a>`
      ).join('') + '</nav>';
  }

  // One standing notice for an unpaid subscription (ТЗ «SaaS-слой» 3.3), raised
  // by any 402 in platform_init.js. It stays until reload: the state it reports
  // does not change while the cabinet is open.
  window.addEventListener('reip:subscription', (e) => {
    const box = document.getElementById('subnotice');
    if (!box || !e.detail) return;
    box.textContent = e.detail.message || 'Подписка неактивна';
    box.hidden = false;
  });

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
    if (window._demo) {
      wireDemoBar();
      const tabs = window._demo.allowed_tabs || Object.keys(DEMO_ROUTES);
      const open = new Set(tabs.flatMap((t) => DEMO_ROUTES[t] || []));
      const locked = () => {
        UI.setHeader('Демо-режим', '', { back: true });
        UI.render(UI.empty({ icon: 'shield', title: 'Доступно после подключения',
          sub: 'В демо открыты обзор, сигналы, лиды и аналитика — на синтетических данных.' }));
      };
      ROUTES.forEach(([p, h]) => Router.add(p, open.has(p) ? h : locked));
    } else {
      ROUTES.forEach(([p, h]) => Router.add(p, h));
    }
    Router.setNotFound(() => UI.render(UI.empty({ title: 'Экран не найден' })));
    if (!location.hash) location.hash = '#/dashboard';
    Router.start();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();

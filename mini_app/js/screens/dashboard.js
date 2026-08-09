// Screen: Dashboard — what the agency looks like this morning.
//
// The four numbers used to occupy two thirds of the screen and the actions were
// three identical slabs underneath. Numbers are compact now, money is the one
// figure that gets size, and the actions say what they are for.
window.Screens = window.Screens || {};

Screens.dashboard = async function () {
  UI.setHeader('Обзор', 'Агентство сегодня', {
    actionIcon: 'settings', actionLabel: 'Профиль', onAction: () => Router.go('settings'),
  });

  const skeleton = UI.skelStats() + '<div class="mt-3">' + UI.skelCard() + '</div>' +
    '<div class="section-title">Быстрые действия</div>' + UI.skelTiles();

  UI.load(skeleton, () => Promise.all([API.overview(), API.tasksSummary().catch(() => null)]), ([o, t]) => {
    const stat = (ic, n, l, tone) =>
      `<div class="stat"><div class="stat__ico${tone ? ` stat__ico--${tone}` : ''}">${UI.icon(ic)}</div>` +
      `<div class="grow"><div class="stat__n">${n ?? 0}</div><div class="stat__l">${l}</div></div></div>`;

    const urgent = (t && t.urgent) || o.urgent_tasks || 0;
    const overdue = (t && t.overdue) || 0;

    UI.render(
      `<div class="stats">
         ${stat('leads', o.total_leads, 'Лиды')}
         ${stat('properties', o.active_properties, 'Объекты')}
         ${stat('handshake', o.deals_won, 'Сделки', 'success')}
         ${stat('flame', urgent, 'Срочные', urgent ? 'hot' : '')}
       </div>

       <div class="hero mt-3">
         <div class="between">
           <div>
             <div class="hero__l">Комиссия за сделки</div>
             <div class="hero__v">${UI.money(o.total_commission)}</div>
           </div>
           <div class="stat__ico stat__ico--success">${UI.icon('ruble')}</div>
         </div>
       </div>

       ${overdue ? `<div class="card mt-3">
         <div class="row"><span class="chip chip--hot">${UI.icon('clock')}просрочено ${overdue}</span></div>
         <div class="item__sub mt-2">Задачи с истёкшим сроком — лид ждёт ответа дольше обещанного.</div>
         <button class="btn btn--secondary btn--block mt-3" id="q-overdue">${UI.icon('check')} Разобрать</button>
       </div>` : ''}

       <div class="section-title">Быстрые действия</div>
       <div class="tiles">
         <button class="tile" id="q-queue">
           <div class="tile__ico">${UI.icon('queue')}</div>
           <div class="tile__t">Очередь ответов</div>
           <div class="tile__s">Написать первым</div>
         </button>
         <button class="tile" id="q-tasks">
           <div class="tile__ico">${UI.icon('check')}</div>
           <div class="tile__t">Мои задачи</div>
           <div class="tile__s">${urgent ? UI.count(urgent, ['срочная', 'срочные', 'срочных']) : 'На сегодня'}</div>
         </button>
         <button class="tile" id="q-an">
           <div class="tile__ico">${UI.icon('analytics')}</div>
           <div class="tile__t">Аналитика</div>
           <div class="tile__s">Воронка, ROI</div>
         </button>
         <button class="tile" id="q-src">
           <div class="tile__ico">${UI.icon('signals')}</div>
           <div class="tile__t">Источники</div>
           <div class="tile__s">Чаты и группы</div>
         </button>
       </div>`,
      () => {
        const go = (id, route) => {
          const el = document.getElementById(id);
          if (el) el.onclick = () => Router.go(route);
        };
        go('q-queue', 'queue'); go('q-tasks', 'tasks');
        go('q-an', 'analytics'); go('q-src', 'sources'); go('q-overdue', 'tasks');
      });
  });
};

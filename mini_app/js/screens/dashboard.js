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

  UI.load(skeleton, () => Promise.all([
    API.overview(),
    API.tasksSummary().catch(() => null),
    // Background decoration must never be the reason a screen fails to load.
    API.timeline().catch(() => ({ months: [] })),
  ]), ([o, t, tl]) => {
    // Each counter goes to the screen it counts — a number you cannot act on is
    // just wallpaper.
    const stat = (ic, n, l, route, tone) =>
      `<button class="stat" data-go="${route}"><div class="stat__ico${tone ? ` stat__ico--${tone}` : ''}">${UI.icon(ic)}</div>` +
      `<div class="grow"><div class="stat__n">${n ?? 0}</div><div class="stat__l">${l}</div></div></button>`;

    const urgent = (t && t.urgent) || o.urgent_tasks || 0;
    const overdue = (t && t.overdue) || 0;

    // The first day. An owner who signs in to four zeroes has no way of knowing
    // that the catalogue is what makes matching possible, or that the robot
    // reads only the cities it has been given. The card names the four things
    // in the order they have to happen, and disappears the moment they are done
    // -- an onboarding that outstays its welcome is just clutter.
    const s = o.setup;
    const setup = (s && s.done < s.total) ? `
      <div class="card mt-3">
        <div class="between">
          <span class="card__title">С чего начать</span>
          <span class="chip">${s.done} из ${s.total}</span>
        </div>
        ${s.steps.map((x) => `
          <button class="item mt-3" data-go="${x.route}"${x.done ? ' disabled' : ''}
                  style="width:100%;text-align:left;background:none;border:0;padding:0">
            <div class="stat__ico${x.done ? ' stat__ico--success' : ''}">
              ${UI.icon(x.done ? 'check' : 'plus')}</div>
            <div class="grow">
              <div class="item__title"${x.done ? ' style="opacity:.55"' : ''}>${UI.esc(x.title)}</div>
              <div class="item__meta">${UI.esc(x.hint)}</div>
            </div>
          </button>`).join('')}
      </div>` : '';

    const months = (tl && tl.months) || [];
    const topMonth = Math.max(...months.map((m) => m.commission), 0);
    const spark = topMonth > 0
      ? `<div class="hero__spark" aria-hidden="true">${months.map((m) =>
          `<i style="height:${Math.max(4, Math.round((m.commission / topMonth) * 100))}%"
              title="${UI.esc(UI.moneyShort(m.commission))}"></i>`).join('')}</div>`
      : '';

    UI.render(
      `<div class="stats">
         ${stat('leads', o.total_leads, 'Лиды', 'leads')}
         ${stat('properties', o.active_properties, 'Объекты', 'properties')}
         ${stat('handshake', o.deals_won, 'Сделки', 'analytics', 'success')}
         ${stat('flame', urgent, 'Срочные', 'tasks', urgent ? 'hot' : '')}
       </div>

       <div class="hero mt-3${spark ? ' hero--spark' : ''}">
         ${spark}
         <div class="between">
           <div>
             <div class="hero__l">Комиссия за сделки</div>
             <div class="hero__v">${UI.money(o.total_commission)}</div>
             ${months.length && topMonth > 0
               ? '<div class="item__meta mt-1">за последние 6 месяцев</div>' : ''}
           </div>
           <div class="stat__ico stat__ico--success">${UI.icon('ruble')}</div>
         </div>
       </div>

       ${overdue ? `<div class="card mt-3">
         <div class="row"><span class="chip chip--hot">${UI.icon('clock')}просрочено ${overdue}</span></div>
         <div class="item__sub mt-2">Задачи с истёкшим сроком — лид ждёт ответа дольше обещанного.</div>
         <button class="btn btn--secondary btn--block mt-3" id="q-overdue">${UI.icon('check')} Разобрать</button>
       </div>` : ''}

       ${setup}

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
        Router.bindGo();   // counters carry data-go
        const go = (id, route) => {
          const el = document.getElementById(id);
          if (el) el.onclick = () => Router.go(route);
        };
        go('q-queue', 'queue'); go('q-tasks', 'tasks');
        go('q-an', 'analytics'); go('q-src', 'sources'); go('q-overdue', 'tasks');
      });
  });
};

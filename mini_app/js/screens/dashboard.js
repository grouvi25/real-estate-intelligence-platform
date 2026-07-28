// Screen: Dashboard.
window.Screens = window.Screens || {};

Screens.dashboard = async function () {
  UI.setHeader('Дашборд', 'Обзор агентства', { actionIcon: 'settings', onAction: () => Router.go('settings') });
  UI.render(UI.skelStats() + '<div style="height:10px"></div>' + UI.skelCard());

  const o = await API.overview();
  const stat = (ic, n, l) =>
    `<div class="stat"><div class="stat__ico">${UI.icon(ic)}</div>` +
    `<div class="stat__n">${n}</div><div class="stat__l">${l}</div></div>`;

  UI.render(
    `<div class="stats">
       ${stat('leads', o.total_leads, 'Лиды')}
       ${stat('properties', o.active_properties, 'Объекты')}
       ${stat('handshake', o.deals_won, 'Сделки')}
       ${stat('flame', o.urgent_tasks, 'Срочные')}
     </div>
     <div class="card" style="margin-top:12px">
       <div class="between"><span class="muted">Комиссия за сделки</span>
         <span class="price" style="font-size:18px">${UI.money(o.total_commission)}</span></div>
     </div>
     <div class="section-title">Быстрые действия</div>
     <button class="btn btn--block" id="q-queue">${UI.icon('queue')} Очередь ответов на сигналы</button>
     <div style="height:8px"></div>
     <div style="height:8px"></div>
     <button class="btn btn--secondary btn--block" id="q-tasks">${UI.icon('check')} Мои задачи</button>
     <div style="height:8px"></div>
     <button class="btn btn--secondary btn--block" id="q-an">${UI.icon('analytics')} Открыть аналитику</button>`,
    () => {
      document.getElementById('q-queue').onclick = () => Router.go('queue');
      document.getElementById('q-tasks').onclick = () => Router.go('tasks');
      document.getElementById('q-an').onclick = () => Router.go('analytics');
    }
  );
};

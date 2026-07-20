// Screen: Dashboard (agency overview). TZ section 30.
window.Screens = window.Screens || {};

Screens.dashboard = async function () {
  UI.setHeader('Дашборд', 'Обзор агентства');
  UI.render(UI.spinner());
  const o = await API.overview();
  const html = `
    <div class="stats">
      <div class="stat"><div class="n">${o.total_leads}</div><div class="l">Лиды</div></div>
      <div class="stat"><div class="n">${o.active_properties}</div><div class="l">Объекты</div></div>
      <div class="stat"><div class="n">${o.deals_won}</div><div class="l">Сделки</div></div>
      <div class="stat"><div class="n">${o.urgent_tasks}</div><div class="l">Срочные задачи</div></div>
    </div>
    <div class="card">
      <div class="row"><span class="muted">Комиссия (всего)</span>
        <span class="price">${UI.money(o.total_commission)}</span></div>
    </div>
    <button class="btn block" onclick="Router.go('queue')">Очередь ответов на сигналы</button>
    <button class="btn secondary block" onclick="Router.go('analytics')">Аналитика</button>
  `;
  UI.render(html);
};

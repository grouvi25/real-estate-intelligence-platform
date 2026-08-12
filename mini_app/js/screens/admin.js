// Owner-only administration: sales geographies and monitoring sources.
window.Screens = window.Screens || {};

function ownerOnly() {
  if (window._manager && window._manager.role === 'owner') return true;
  Router.go('dashboard');
  return false;
}

Screens.admin = async function () {
  if (!ownerOnly()) return;
  UI.setHeader('Управление', 'Кабинет владельца');
  UI.render(`
    <div class="card"><div class="between"><div><div class="card__title">${UI.esc((window._agency && window._agency.name) || 'Агентство')}</div>
      <div class="item__sub">Вы вошли как владелец</div></div><span class="chip chip--success">owner</span></div></div>
    <div class="section-title">Система</div>
    <div class="tiles">
      <button class="tile" data-go="admin/geo"><span class="tile__ico">${UI.icon('location')}</span><span class="tile__t">Города</span><span class="tile__s">Гео и поиск источников</span></button>
      <button class="tile" data-go="admin/sources"><span class="tile__ico">${UI.icon('signals')}</span><span class="tile__t">Источники</span><span class="tile__s">Мониторинг и активность</span></button>
      <button class="tile" data-go="tasks"><span class="tile__ico">${UI.icon('check')}</span><span class="tile__t">Задачи</span><span class="tile__s">Работа команды</span></button>
      <button class="tile" data-go="analytics"><span class="tile__ico">${UI.icon('analytics')}</span><span class="tile__t">Аналитика</span><span class="tile__s">Воронка и ROI</span></button>
    </div>
    <div class="section-title">Команда</div><div id="admin-team">${UI.skelList(2)}</div>
    <div class="section-title">Настройки владельца</div>
    <button class="btn btn--secondary btn--block" data-go="settings">${UI.icon('settings')} Агентство, приглашения, CRM и AI</button>
  `, () => { Router.bindGo(); loadAdminTeam(); });
};

async function loadAdminTeam() {
  const box = document.getElementById('admin-team');
  if (!box) return;
  try {
    const data = await API.adminManagers();
    box.innerHTML = UI.list(data.managers || [], (m) => `
      <div class="card"><div class="between"><div><div class="item__title">${UI.esc(m.name)}</div>
        <div class="item__sub">${UI.esc(m.role)}</div></div>
        <span class="chip ${m.is_active ? 'chip--success' : ''}">${m.is_active ? 'активен' : 'отключён'}</span></div>
        ${m.id !== (window._manager && window._manager.id) ? `<button class="btn btn--secondary btn--sm mt-3" data-manager-toggle="${m.id}" data-active="${m.is_active}">${m.is_active ? 'Отключить' : 'Активировать'}</button>` : ''}
      </div>`, {icon: 'user', title: 'Менеджеров пока нет'});
    box.querySelectorAll('[data-manager-toggle]').forEach((button) => {
      button.onclick = async () => {
        await API.updateAdminManager(button.dataset.managerToggle, {is_active: button.dataset.active !== 'true'});
        loadAdminTeam();
      };
    });
  } catch (e) {
    box.innerHTML = UI.errorState(e.message);
  }
}

Screens.adminGeo = async function () {
  if (!ownerOnly()) return;
  UI.setHeader('Управление', 'Города продаж и источники', {
    actionIcon: 'plus', actionLabel: 'Город', onAction: () => Router.go('admin/geo/new'),
  });
  UI.load(UI.skelList(3), () => API.geoLocations(), (data) => {
    const items = data.geo || [];
    const tools = `<button class="btn btn--secondary btn--block" id="admin-sources">
      ${UI.icon('settings')} Управлять источниками</button>`;
    const list = UI.list(items, (g) => `
      <div class="card">
        <div class="between gap-2">
          <strong>${UI.esc(g.city_name)}</strong>
          <span class="chip ${g.is_active ? 'chip--success' : ''}">${g.is_active ? 'активен' : 'пауза'}</span>
        </div>
        <div class="item__meta mt-2">${UI.esc(g.region || '')}</div>
        <div class="item__meta mt-1">Источников: <span class="num">${g.source_count || 0}</span></div>
        <div class="item__meta mt-1">Последний сигнал: ${g.last_signal_at ? UI.esc(UI.ago(g.last_signal_at)) : 'никогда'}</div>
      </div>`, {
      icon: 'map', title: 'Городов пока нет', sub: 'Добавьте первый город продаж',
      actionLabel: 'Добавить город', actionIcon: 'plus', actionId: 'admin-add-geo',
    });
    UI.render(tools + `<div class="mt-3">${list}</div>`, () => {
      document.getElementById('admin-sources').onclick = () => Router.go('admin/sources');
      const add = document.getElementById('admin-add-geo');
      if (add) add.onclick = () => Router.go('admin/geo/new');
    });
  });
};

Screens.adminGeoNew = async function () {
  if (!ownerOnly()) return;
  UI.setHeader('Добавить город', 'Новая территория продаж', { back: true });
  UI.render(`
    <form id="geo-form" class="card">
      <div class="field"><label>Город *</label><input id="city-name" placeholder="Геленджик" required></div>
      <div class="field"><label>Регион *</label><input id="region" placeholder="Краснодарский край" required></div>
      <div class="field"><label>Тип рынка</label><select id="market-type">
        <option value="resort">Курортный</option><option value="urban">Городской</option>
        <option value="suburban">Пригород</option></select></div>
      <button type="submit" class="btn btn--block mt-3">Добавить город</button>
    </form>`, () => {
    document.getElementById('geo-form').onsubmit = async (event) => {
      event.preventDefault();
      const city = document.getElementById('city-name').value.trim();
      const region = document.getElementById('region').value.trim();
      const marketType = document.getElementById('market-type').value;
      if (!city || !region) return;
      try {
        const result = await API.addGeoLocation({ city_name: city, region, market_type: marketType });
        if (result.status === 'partner_offer') {
          UI.toast(`Регион занят партнёром: ${result.message}`);
          return;
        }
        UI.toast(`${city} добавлен, поиск источников запущен`);
        Router.go('admin/geo');
      } catch (e) { UI.toast('Не удалось добавить город: ' + e.message); }
    };
  });
};

Screens.adminSources = async function () {
  if (!ownerOnly()) return;
  return Screens.sources();
};

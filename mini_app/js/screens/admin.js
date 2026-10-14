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
      <button class="tile" data-go="admin/bot"><span class="tile__ico">${UI.icon('sparkles')}</span><span class="tile__t">ИИ-бот</span><span class="tile__s">Ответы в чатах и диалоги</span></button>
      <button class="tile" data-go="admin/lead-magnets"><span class="tile__ico">${UI.icon('target')}</span><span class="tile__t">Лид-магниты</span><span class="tile__s">Калькуляторы для клиентов</span></button>
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

// === ИИ-бот продажник (ТЗ «AI-бот продажник», раздел 8) ===
const BOT_MODES = [
  ['disabled', 'Выключен', 'Бот не отвечает и не пишет.'],
  ['assist', 'Помощник', 'Бот пишет черновик ответа в очередь, отправляет менеджер.'],
  ['semi_auto', 'Полуавтомат', 'Бот отправит ответ сам через N минут, если его не отклонить.'],
  ['auto', 'Автомат', 'Бот отвечает сразу и сам зовёт менеджера, когда нужно.'],
];
const BOT_TONES = [['expert', 'Эксперт'], ['friendly', 'Дружелюбный'], ['concise', 'Коротко'],
  ['rotating', 'A/B: по очереди']];
const REPLY_STATUS_RU = { draft: 'черновик', scheduled: 'ждёт отправки', sent: 'отправлен',
  failed: 'не отправлен', rejected: 'отклонён' };

Screens.adminBot = async function () {
  if (!ownerOnly()) return;
  UI.setHeader('ИИ-бот', 'Ответы в чатах и диалоги', { back: true });
  UI.render(`<div id="bot-settings">${UI.skelCard()}</div>
    <div class="section-title">Статистика за 30 дней</div><div id="bot-perf">${UI.skelCard()}</div>
    <div class="section-title">Последние ответы</div><div id="bot-replies">${UI.skelList(2)}</div>`,
    () => { drawBotSettings(); drawBotPerf(); drawBotReplies(); });
};

async function drawBotSettings() {
  const box = document.getElementById('bot-settings');
  if (!box) return;
  let s;
  try { s = await API.botSettings(); } catch (e) { box.innerHTML = UI.errorState(e.message); return; }
  const order = BOT_MODES.map((m) => m[0]);
  const allowed = (mode) => order.indexOf(mode) <= order.indexOf(s.max_mode);
  box.innerHTML = `
    <div class="card">
      <div class="field"><label for="bm-mode">Режим</label>
        <select id="bm-mode">${BOT_MODES.map(([v, l]) => `<option value="${v}" ${v === s.bot_mode ? 'selected' : ''}
          ${allowed(v) ? '' : 'disabled'}>${l}${allowed(v) ? '' : ' — не входит в тариф'}</option>`).join('')}</select>
        <div class="field__hint" id="bm-hint"></div></div>
      <div class="field"><label for="bm-thr">Минимальная оценка сигнала для ответа</label>
        <input id="bm-thr" type="number" min="0" max="100" value="${s.bot_reply_threshold}"></div>
      <div class="field"><label for="bm-lim">Ответов в чаты в сутки, не больше</label>
        <input id="bm-lim" type="number" min="1" max="500" value="${s.bot_daily_reply_limit}"></div>
      <div class="field" id="bm-delay-box"><label for="bm-delay">Задержка полуавтомата, минут</label>
        <input id="bm-delay" type="number" min="1" max="60" value="${s.bot_semi_auto_delay}"></div>
      <div class="field"><label for="bm-tone">Тон ответов</label>
        <select id="bm-tone">${BOT_TONES.map(([v, l]) => `<option value="${v}" ${v === s.bot_tone_ab_test ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
      <div class="item__sub">В чат бот может ответить, только если он там участник. Если нет —
        ответ останется в очереди с пометкой «не отправлен», и его можно переслать вручную.</div>
      <button class="btn btn--block mt-3" id="bm-save">${UI.icon('check')} Сохранить</button>
    </div>`;
  const mode = document.getElementById('bm-mode');
  const sync = () => {
    const m = BOT_MODES.find((x) => x[0] === mode.value);
    document.getElementById('bm-hint').textContent = m ? m[2] : '';
    document.getElementById('bm-delay-box').hidden = mode.value !== 'semi_auto';
  };
  mode.onchange = sync; sync();
  const save = document.getElementById('bm-save');
  save.onclick = () => UI.busy(save, async () => {
    const num = (id) => parseInt(document.getElementById(id).value, 10);
    try {
      await API.updateBotSettings({ bot_mode: mode.value, bot_reply_threshold: num('bm-thr'),
        bot_daily_reply_limit: num('bm-lim'), bot_semi_auto_delay: num('bm-delay'),
        bot_tone_ab_test: document.getElementById('bm-tone').value });
      UI.toast('Сохранено');
    } catch (e) { UI.toast(e.message); }
  });
}

async function drawBotPerf() {
  const box = document.getElementById('bot-perf');
  if (!box) return;
  try {
    const p = await API.botPerformance();
    const row = (l, v) => `<div class="between mt-1"><span class="muted">${l}</span><span class="item__meta">${v}</span></div>`;
    box.innerHTML = `<div class="card">
      ${row('Ответов в чаты', `${p.public_replies_sent} (не отправлено: ${p.public_replies_failed})`)}
      ${row('Написали боту после ответа', `${p.got_response_count} · ${p.response_rate_pct}%`)}
      ${row('Диалогов в личке', p.dm_conversations_started)}
      ${row('Лидов от бота', `${p.leads_created_by_bot} · ${p.dm_to_lead_conversion_pct}%`)}</div>`;
  } catch (e) { box.innerHTML = UI.errorState(e.message); }
}

async function drawBotReplies() {
  const box = document.getElementById('bot-replies');
  if (!box) return;
  try {
    const d = await API.botReplies();
    box.innerHTML = UI.list(d.replies || [], (r) => `
      <div class="card"><div class="between"><span class="item__meta">${UI.ago(r.created_at)}</span>
        <span class="chip ${r.status === 'sent' ? 'chip--success' : ''}">${UI.esc(REPLY_STATUS_RU[r.status] || r.status)}</span></div>
        <div class="item__sub" style="margin-top:6px">${UI.esc(r.text)}</div>
        ${r.fail_reason ? `<div class="item__sub muted mt-1">${UI.esc(r.fail_reason)}</div>` : ''}
        <button class="btn btn--ghost btn--sm mt-2" data-go="signals/${UI.esc(r.signal_id)}">К сигналу</button></div>`,
      { icon: 'sparkles', title: 'Бот ещё не отвечал', sub: 'Черновики появятся в очереди ответов' });
    Router.bindGo();
  } catch (e) { box.innerHTML = UI.errorState(e.message); }
}

// Lead magnets: the public pages for clients (/lm/<agency>/<tool>), which are
// on, their links, requests they brought, the agency's own rates.
Screens.adminLeadMagnets = async function () {
  if (!ownerOnly()) return;
  UI.setHeader('Лид-магниты', 'Калькуляторы и подборки для клиентов', { back: true });
  UI.render(`<div id="lm-box">${UI.skelList(3)}</div>`, drawLeadMagnets);
};

const lmNum = (v) => String(v).replace('.', ',');

async function lmCopy(text) {
  try { await navigator.clipboard.writeText(text); UI.toast('Ссылка скопирована'); }
  catch (e) { UI.toast('Скопируйте вручную'); }
}

async function drawLeadMagnets() {
  const box = document.getElementById('lm-box');
  if (!box) return;
  let d;
  try { d = await API.leadMagnets(); } catch (e) { box.innerHTML = UI.errorState(e.message); return; }
  const r = d.rental;
  box.innerHTML = `
    ${d.available ? '' : `<div class="card"><div class="item__sub">Кабинет заблокирован — страницы для клиентов сейчас не открываются.</div></div>`}
    <div class="card">
      <div class="item__title">Все инструменты на одной странице</div>
      <div class="item__sub">Ссылка для сайта, бота и рассылок: клиент видит только включённые инструменты.
        Заявки приходят в «Лиды» с источником «Лид-магнит» и задачей менеджеру.</div>
      <div class="copyfield mt-2">${UI.esc(d.overview_url)}</div>
      <div class="row row--wrap mt-2">
        <button class="btn btn--sm" data-lm-copy="${UI.esc(d.overview_url)}">${UI.icon('copy')} Скопировать</button>
        <a class="btn btn--sm btn--secondary" href="${UI.esc(d.overview_url)}" target="_blank" rel="noopener">${UI.icon('link')} Открыть</a>
      </div>
    </div>
    <div class="section-title">Инструменты</div>
    ${d.tools.map((t) => `<div class="card">
      <div class="between"><div class="item__title">${UI.esc(t.title)}</div>
        <span class="chip ${t.enabled ? 'chip--success' : ''}">${t.enabled ? 'включён' : 'выключен'}</span></div>
      <div class="item__sub">${UI.esc(t.description)}</div>
      <div class="item__meta mt-1">Заявок за 30 дней: ${t.leads_30d}</div>
      <div class="row row--wrap mt-2">
        <button class="btn btn--sm ${t.enabled ? 'btn--secondary' : ''}" data-lm-toggle="${t.slug}">${t.enabled ? 'Выключить' : 'Включить'}</button>
        ${t.enabled ? `<button class="btn btn--sm btn--secondary" data-lm-copy="${UI.esc(t.url)}">${UI.icon('copy')} Ссылка</button>
        <a class="btn btn--sm btn--ghost" href="${UI.esc(t.url)}" target="_blank" rel="noopener">Открыть</a>` : ''}
      </div>
    </div>`).join('')}
    <div class="section-title">Ставки ипотеки, % годовых</div>
    <div class="card">
      ${d.mortgage_programs.map((p) => `<div class="field"><label for="lm-r-${p.key}">${UI.esc(p.name)}</label>
        <input id="lm-r-${p.key}" type="number" inputmode="decimal" step="0.01" min="0" max="50" value="${p.rate_percent}">
        ${p.rate_percent !== p.default_rate_percent ? `<div class="field__hint">По умолчанию ${lmNum(p.default_rate_percent)} %</div>` : ''}</div>`).join('')}
      <button class="btn btn--block" id="lm-rates-save">${UI.icon('check')} Сохранить ставки</button>
    </div>
    <div class="section-title">Аренда в калькуляторе доходности · ${UI.esc(r.city)}</div>
    <div class="card">
      <div class="field"><label for="lm-season">Сезон, месяцев в году</label>
        <input id="lm-season" type="number" inputmode="decimal" step="0.5" min="0.5" max="12" value="${r.season_months}"></div>
      <div class="field"><label for="lm-rent">Аренда в месяц сезона, % от цены квартиры</label>
        <input id="lm-rent" type="number" inputmode="decimal" step="0.01" min="0.05" max="5" value="${r.monthly_rent_percent}">
        <div class="field__hint">Например, 0,7 % от квартиры за 8 млн — 56 000 ₽ в месяц</div></div>
      <div class="field"><label for="lm-occ">Загрузка в сезон, %</label>
        <input id="lm-occ" type="number" inputmode="decimal" step="1" min="5" max="100" value="${r.occupancy_percent}"></div>
      <button class="btn btn--block" id="lm-rent-save">${UI.icon('check')} Сохранить</button>
    </div>`;

  box.querySelectorAll('[data-lm-copy]').forEach((b) => { b.onclick = () => lmCopy(b.dataset.lmCopy); });
  box.querySelectorAll('[data-lm-toggle]').forEach((b) => {
    b.onclick = () => UI.busy(b, async () => {
      const slug = b.dataset.lmToggle;
      const enabled = d.tools.filter((t) => (t.slug === slug ? !t.enabled : t.enabled)).map((t) => t.slug);
      try { await API.updateLeadMagnets({ enabled }); UI.toast('Сохранено'); drawLeadMagnets(); }
      catch (e) { UI.toast(e.message); }
    });
  });
  const val = (id) => parseFloat(String(document.getElementById(id).value).replace(',', '.'));
  const rates = document.getElementById('lm-rates-save');
  rates.onclick = () => UI.busy(rates, async () => {
    const body = {};
    d.mortgage_programs.forEach((p) => { body[p.key] = val(`lm-r-${p.key}`); });
    if (Object.values(body).some((v) => isNaN(v))) { UI.toast('Заполните все ставки'); return; }
    try { await API.updateLeadMagnets({ mortgage_rates_percent: body }); UI.toast('Ставки сохранены'); drawLeadMagnets(); }
    catch (e) { UI.toast(e.message); }
  });
  const rent = document.getElementById('lm-rent-save');
  rent.onclick = () => UI.busy(rent, async () => {
    const body = { season_months: val('lm-season'), monthly_rent_percent: val('lm-rent'), occupancy_percent: val('lm-occ') };
    if (Object.values(body).some((v) => isNaN(v))) { UI.toast('Заполните все поля'); return; }
    try { await API.updateLeadMagnets({ rental: body }); UI.toast('Сохранено'); drawLeadMagnets(); }
    catch (e) { UI.toast(e.message); }
  });
}

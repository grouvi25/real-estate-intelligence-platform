// Screens: Analytics + Settings/Owner area.
window.Screens = window.Screens || {};

Screens.analytics = async function () {
  UI.setHeader('Аналитика', 'Воронка и источники');
  UI.render(UI.skelCard() + UI.skelList(3));
  let funnel, roi;
  try {
    [funnel, roi] = await Promise.all([API.funnel(), API.sourceRoi()]);
  } catch (e) {
    UI.render(UI.errorState(e.message), () => {
      document.getElementById('retry').onclick = () => Screens.analytics();
    });
    return;
  }

  const total = funnel.total || 1;
  const bar = (label, n) => {
    const pct = total ? Math.max(3, Math.round((n / total) * 100)) : 0;
    return `<div class="funnel__row"><div class="funnel__lbl"><span>${label}</span><b>${n}</b></div>
      <div class="funnel__track"><div class="funnel__bar" style="width:${pct}%"></div></div></div>`;
  };
  const st = funnel.stages || {};
  const conv = (funnel.conversion && funnel.conversion.overall) || 0;

  const sources = UI.list(roi.sources, (s) => `
    <div class="card">
      <div class="between gap-2">
        <span class="item__title ellipsis">${UI.esc(UI.utmSource(s.source))}</span>
        <span class="chip chip--accent">${UI.count(s.leads, ['лид', 'лида', 'лидов'])}</span>
      </div>
      <div class="between mt-2">
        <span class="muted">${UI.count(s.deals_won, ['сделка', 'сделки', 'сделок'])} · конверсия ${s.conversion_pct}%</span>
        <span class="price">${UI.moneyShort(s.commission)}</span>
      </div>
    </div>`, { icon: 'analytics', title: 'Нет данных по источникам',
               sub: 'Появятся, когда лиды начнут приходить по меткам' });

  UI.render(`
    <div class="card">
      <div class="between"><span class="card__title">Воронка</span>
        <span class="chip chip--success">Конверсия ${conv}%</span></div>
      <div style="margin-top:10px">
        ${bar('Новые', st.new || 0)}${bar('В работе', st.in_progress || 0)}
        ${bar('Квалифицированы', st.qualified || 0)}${bar('Сделки', st.deal || 0)}
      </div>
    </div>
    <div class="section-title">Источники · ROI</div>
    ${sources}
    <button class="btn btn--secondary btn--block" id="mkt" style="margin-top:14px">${UI.icon('sparkles')} Анализ рыночного события</button>`,
    () => { document.getElementById('mkt').onclick = marketEventSheet; });
};

function marketEventSheet() {
  UI.sheet('Анализ рыночного события', `
    <div class="field"><label>Город</label><input id="me-city" placeholder="напр. Геленджик"></div>
    <div class="field"><label>Тип события</label>
      <select id="me-type">
        <option value="price_change">Изменение цен</option>
        <option value="new_development">Новая застройка</option>
        <option value="infrastructure">Инфраструктура</option>
        <option value="regulation">Регулирование / законы</option>
        <option value="mortgage_rate">Ипотечные ставки</option>
      </select></div>
    <div class="field"><label>Описание / данные</label>
      <textarea id="me-data" rows="4" placeholder="Опишите событие: цифры, источник, детали"></textarea></div>
    <button class="btn btn--block" id="me-go">${UI.icon('sparkles')} Проанализировать</button>
    <div id="me-out" style="margin-top:12px"></div>`,
    () => {
      document.getElementById('me-go').onclick = async () => {
        const city = document.getElementById('me-city').value.trim();
        const data = document.getElementById('me-data').value.trim();
        if (!city || !data) { UI.toast('Заполните город и описание'); return; }
        const out = document.getElementById('me-out');
        out.innerHTML = '<div class="skel skel-line lg"></div><div class="skel skel-line md"></div><div class="skel skel-line sm"></div>';
        try {
          const r = await API.marketEvent({
            city, event_type: document.getElementById('me-type').value, event_data: data,
          });
          const a = r.analysis || {};
          const sig = a.significance || '—';
          const sigChip = sig === 'high' ? 'chip--hot' : sig === 'medium' ? 'chip--warm' : 'chip--accent';
          out.innerHTML = `
            <div class="card">
              <div class="between"><span class="card__title">Значимость</span>
                <span class="chip ${sigChip}">${UI.esc(sig)}</span></div>
              ${a.summary ? `<div class="item__sub" style="margin-top:8px">${UI.esc(a.summary)}</div>` : ''}
              ${a.impact_on_agency ? `<hr class="divider"><div class="item__sub"><b>Влияние:</b> ${UI.esc(a.impact_on_agency)}</div>` : ''}
              ${a.recommended_action ? `<div class="item__sub" style="margin-top:6px"><b>Действие:</b> ${UI.esc(a.recommended_action)}</div>` : ''}
              ${(a.affected_segments && a.affected_segments.length) ? `<div class="row" style="margin-top:8px">${a.affected_segments.map((s) => `<span class="chip">${UI.esc(UI.seg(s) || s)}</span>`).join('')}</div>` : ''}
            </div>`;
        } catch (e) { out.innerHTML = UI.errorState(e.message); }
      };
    });
}

// What still stands between the agency and a working system. /health/deep says
// the dependencies are up; this says whether a buyer could actually be served.
async function loadReadiness() {
  const box = document.getElementById('readiness');
  if (!box) return;
  try {
    const r = await API.readiness();
    const items = Object.entries(r.findings || {});
    if (!items.length) {
      box.innerHTML = `<div class="card"><div class="row" style="gap:10px">${UI.icon('check')}
        <span>Всё настроено — система готова к работе</span></div></div>`;
      return;
    }
    box.innerHTML = `<div class="card">
      <div class="row row--wrap gap-1">
        ${r.blockers ? `<span class="chip chip--hot">${UI.icon('flame')}мешает работе ${r.blockers}</span>` : ''}
        ${r.warnings ? `<span class="chip chip--warm">внимание ${r.warnings}</span>` : ''}
      </div>
      ${items.map(([, f]) => `
        <div class="mt-3">
          <div class="meta-row">${UI.icon(f.severity === 'blocker' ? 'flame' : 'clock')}
            <span style="color:${f.severity === 'blocker' ? 'var(--hot)' : 'var(--warm)'}">
              ${f.severity === 'blocker' ? 'блокирует' : 'внимание'}</span></div>
          <div class="item__sub mt-1" style="color:var(--fg);font-size:var(--t-md)">${UI.esc(f.detail)}</div>
          <div class="item__sub">${UI.esc(f.action)}</div>
        </div>`).join('<hr class="divider">')}
    </div>`;
  } catch (e) {
    box.innerHTML = UI.errorState(e.message);
  }
}

Screens.settings = async function () {
  UI.setHeader('Профиль', '', { back: true });
  const platform = (window.PlatformSDK && PlatformSDK.platform) || 'web';
  const user = (window.PlatformSDK && PlatformSDK.user) || {};

  UI.render(`
    <div class="card">
      <div class="item">
        <div class="avatar">${UI.esc(UI.initials(user.first_name || 'M'))}</div>
        <div class="grow"><div class="card__title">${UI.esc(user.first_name || 'Менеджер')}</div>
          <div class="item__sub">Платформа: ${UI.esc(platform)}</div></div>
      </div>
      <hr class="divider">
      <div class="between"><span class="muted">Агентство</span>
        <span class="item__title ellipsis" id="ag-name">${UI.esc((window._agency && window._agency.name) || '—')}</span></div>
      ${(window._agency && window._agency.city)
        ? `<div class="between mt-1"><span class="muted">Город</span>
             <span class="item__meta" id="ag-city">${UI.esc(window._agency.city)}</span></div>` : ''}
      <button class="btn btn--secondary btn--block mt-3" id="ag-edit">${UI.icon('edit')} Настройки агентства</button>
    </div>

    <div class="section-title" style="margin:18px 2px 8px">Готовность к работе</div>
    <div id="readiness">${UI.skelCard()}</div>

    <div class="section-title" style="margin:18px 2px 8px">Менеджеры</div>
    <div id="invite">${UI.skelCard()}</div>

    <div class="section-title" style="margin:18px 2px 8px">AI-провайдер</div>
    <div id="aiprov">${UI.skelCard()}</div>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Города (гео)</span>
      <button class="btn btn--ghost btn--sm" id="add-geo">${UI.icon('plus')} Город</button></div>
    <div id="geos">${UI.skelList(2)}</div>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Партнёры</span>
      <button class="btn btn--ghost btn--sm" id="add-partner">${UI.icon('plus')} Партнёр</button></div>
    <div id="partners">${UI.skelList(2)}</div>
    <button class="btn btn--ghost btn--block" id="go-refs" style="margin-top:8px">${UI.icon('handshake')} Все рефералы</button>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Мониторинг</span></div>
    <button class="btn btn--ghost btn--block" id="go-sources">${UI.icon('settings')} Источники сигналов</button>
    <div style="height:8px"></div>
    <button class="btn btn--ghost btn--block" id="go-tasks">${UI.icon('check')} Задачи команды</button>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Команда</span></div>
    <div id="mgrs">${UI.skelList(2)}</div>

    <button class="btn btn--danger btn--block" id="logout" style="margin-top:16px">${UI.icon('logout')} Выйти</button>`,
    () => {
      loadReadiness();
      document.getElementById('logout').onclick = async () => {
        await StorageAdapter.remove('jwt_token');
        api.token = null;
        location.reload();
      };
      document.getElementById('add-geo').onclick = geoSheet;
      document.getElementById('add-partner').onclick = partnerSheet;
      document.getElementById('go-refs').onclick = () => Router.go('referrals');
      document.getElementById('go-sources').onclick = () => Router.go('sources');
      document.getElementById('go-tasks').onclick = () => Router.go('tasks');
      const edit = document.getElementById('ag-edit');
      if (edit) edit.onclick = agencySheet;
      loadGeos(); loadPartners(); loadMgrs(); loadInvite(); loadAiProvider();
    });
};

async function loadInvite() {
  // The link IS the invitation: anyone holding it joins this agency, and nobody
  // without it can. Owners only -- a manager gets a 403 and sees nothing here.
  const box = document.getElementById('invite');
  let data;
  try {
    data = await API.invite();
  } catch (e) {
    box.innerHTML = `<div class="card"><div class="item__sub">Ссылку-приглашение выдаёт владелец агентства.</div></div>`;
    return;
  }
  const draw = (link) => {
    box.innerHTML = `
      <div class="card">
        <div class="item__sub">Отправьте менеджеру эту ссылку — по ней он попадёт в ваше агентство.
          Без неё вход в кабинет закрыт.</div>
        <div class="copyfield mt-3">${UI.esc(link)}</div>
        <div class="btn-row btn-row--equal mt-3">
          <button class="btn btn--sm" id="inv-copy">${UI.icon('copy')} Скопировать</button>
          <button class="btn btn--secondary btn--sm" id="inv-rot">${UI.icon('refresh')} Сменить</button>
        </div>
      </div>`;
    document.getElementById('inv-copy').onclick = async () => {
      try { await navigator.clipboard.writeText(link); UI.toast('Ссылка скопирована'); }
      catch (e) { UI.toast('Скопируйте вручную'); }
    };
    document.getElementById('inv-rot').onclick = async () => {
      if (!confirm('Старая ссылка перестанет работать. Сменить?')) return;
      try { const r = await API.rotateInvite(); draw(r.link); UI.toast('Ссылка обновлена'); }
      catch (e) { UI.toast('Не удалось: ' + e.message); }
    };
  };
  draw(data.link);
}

const CRM_RU = {
  '': 'Обычный вебхук', topnlab: 'Topnlab', amocrm: 'amoCRM',
  bitrix24: 'Bitrix24', yucrm: 'YUcrm',
};

// Name, city and where qualified leads are exported. All three used to be
// editable only with an UPDATE against the database.
async function agencySheet() {
  let a;
  try { a = await API.agency(); } catch (e) { UI.toast('Не удалось: ' + e.message); return; }
  const crmType = (a.crm && a.crm.type) || '';

  UI.sheet('Настройки агентства', `
    <div class="field"><label for="ag-n">Название</label>
      <input id="ag-n" value="${UI.esc(a.name || '')}"></div>
    <div class="field"><label for="ag-c">Основной город</label>
      <input id="ag-c" value="${UI.esc(a.city || '')}"></div>

    <div class="section-title">Выгрузка лидов в CRM</div>
    <div class="field"><label for="ag-crm">Система</label>
      <select id="ag-crm">${Object.entries(CRM_RU).map(([v, l]) =>
        `<option value="${v}" ${v === crmType ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
    <div class="field"><label for="ag-url">Адрес API</label>
      <input id="ag-url" placeholder="https://crm.example" value="${UI.esc((a.crm && a.crm.base_url) || '')}"></div>
    <div class="field"><label for="ag-key">Ключ доступа</label>
      <input id="ag-key" type="password" placeholder="${a.crm && a.crm.has_key ? 'сохранён — введите новый, чтобы заменить' : 'не задан'}">
      <div class="field__hint">Ключ хранится в зашифрованном виде и не показывается обратно.</div></div>

    <button class="btn btn--block mt-3" id="ag-save">${UI.icon('check')} Сохранить</button>`,
    (close) => {
      const save = document.getElementById('ag-save');
      save.onclick = () => UI.busy(save, async () => {
        const val = (id) => document.getElementById(id).value.trim();
        if (!val('ag-n')) { UI.toast('Название не может быть пустым'); return; }
        try {
          const updated = await API.updateAgency({
            name: val('ag-n'), city: val('ag-c'),
            crm_type: document.getElementById('ag-crm').value,
            crm_base_url: val('ag-url'),
            crm_api_key: val('ag-key') || null,
          });
          window._agency = { id: updated.id, name: updated.name, city: updated.city };
          try { sessionStorage.setItem('agency', JSON.stringify(window._agency)); } catch (e) { /* ignore */ }
          close();
          UI.toast('Сохранено');
          Router.resolve();
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
    });
}

const PROVIDER_RU = {
  yandexgpt: 'YandexGPT', gigachat: 'GigaChat', openai: 'OpenAI', anthropic: 'Anthropic',
};

async function loadAiProvider() {
  const box = document.getElementById('aiprov');
  let d;
  try {
    d = await API.aiProvider();
  } catch (e) {
    box.innerHTML = `<div class="card"><div class="item__sub">Провайдера выбирает владелец агентства.</div></div>`;
    return;
  }
  const opts = (d.options || []).map((o) => `
    <option value="${o.value}" ${o.value === d.provider ? 'selected' : ''} ${o.configured ? '' : 'disabled'}>
      ${UI.esc(PROVIDER_RU[o.value] || o.value)}${o.data_stays_in_russia ? ' · данные в РФ' : ' · через прокси, обезличенно'}${o.configured ? '' : ' — нет ключей'}
    </option>`).join('');
  box.innerHTML = `
    <div class="card">
      <div class="item__sub">Кто отвечает на запросы системы. Смена действует со следующего
        запроса, перезапуск не нужен.</div>
      <div class="field" style="margin-top:8px"><select id="ai-sel">${opts}</select></div>
      <div class="item__sub">Сейчас: <b>${UI.esc(PROVIDER_RU[d.provider] || d.provider)}</b>
        · ${d.source === 'admin' ? 'выбран здесь' : 'из настроек сервера'}
        ${d.configured ? '' : ' · <b>ключей нет, вызовы не пройдут</b>'}</div>
    </div>`;
  document.getElementById('ai-sel').onchange = async (ev) => {
    try {
      await API.setAiProvider(ev.target.value);
      UI.toast('Провайдер переключён');
      loadAiProvider();
    } catch (e) { UI.toast('Не удалось: ' + e.message); loadAiProvider(); }
  };
}

async function loadMgrs() {
  try {
    const m = await API.managers();
    document.getElementById('mgrs').innerHTML = UI.list(m.managers, (x) => `
      <div class="card"><div class="between"><span class="item__title">${UI.esc(x.name)}</span>
        <span class="chip chip--accent">${UI.count(x.deals_won, ['сделка', 'сделки', 'сделок'])}</span></div>
        <div class="item__sub" style="margin-top:4px">Комиссия: ${UI.money(x.commission)}</div></div>`,
      { icon: 'leads', title: 'Нет менеджеров' });
  } catch (e) { document.getElementById('mgrs').innerHTML = UI.errorState(e.message); }
}

async function loadGeos() {
  try {
    const d = await API.geoList();
    document.getElementById('geos').innerHTML = UI.list(d.geo, (g) => `
      <div class="card"><div class="between">
        <span class="item__title">${UI.icon('location')} ${UI.esc(g.city_name)}</span>
        <span class="chip ${g.geo_type === 'base' ? 'chip--accent' : ''}">${UI.esc(UI.geoType(g.geo_type))}</span></div>
        <div class="item__sub" style="margin-top:4px">${UI.esc(g.region || '')}
          ${g.has_keywords ? '· ключевые слова готовы' : '· keywords генерируются'}</div></div>`,
      { icon: 'location', title: 'Городов нет' });
  } catch (e) { document.getElementById('geos').innerHTML = UI.errorState(e.message); }
}

async function loadPartners() {
  try {
    const d = await API.partners({ active_only: false });
    document.getElementById('partners').innerHTML = UI.list(d.partners, (p) => `
      <div class="card card--tap" data-go="partners/${p.id}">
        <div class="between">
          <span class="item__title">${UI.esc(p.partner_name)}</span>
          <span class="chip ${p.is_active ? 'chip--success' : ''}">${p.is_active ? 'активен' : 'выкл'}</span></div>
        <div class="item__sub" style="margin-top:4px">${UI.esc(p.partner_city)}
          ${p.commission_percent ? '· ' + p.commission_percent + '%' : ''}
          ${p.deals_count ? '· сделок: ' + p.deals_count : ''}</div>
      </div>`,
      { icon: 'handshake', title: 'Партнёров нет', sub: 'Добавьте, чтобы передавать защищённые лиды' });
    Router.bindGo();
  } catch (e) { document.getElementById('partners').innerHTML = UI.errorState(e.message); }
}

function geoSheet() {
  UI.sheet('Добавить город',
    `<div class="field"><label>Город</label><input id="g-city" placeholder="напр. Сочи"></div>
     <div class="field"><label>Регион</label><input id="g-region" placeholder="напр. Краснодарский край"></div>
     <div class="field"><label>Тип рынка</label><select id="g-type">
       <option value="urban">Город</option><option value="resort">Курорт</option><option value="suburban">Пригород</option></select></div>
     <button class="btn btn--block" id="g-save">${UI.icon('check')} Добавить</button>`,
    (close) => {
      document.getElementById('g-save').onclick = async () => {
        const city = document.getElementById('g-city').value.trim();
        const region = document.getElementById('g-region').value.trim();
        if (!city || !region) { UI.toast('Заполните город и регион'); return; }
        const marketType = document.getElementById('g-type').value;
        try {
          const res = await API.createGeo({ city_name: city, region, market_type: marketType });
          close();
          // 202 partner_offer: the city belongs to a partner's territory, so it
          // was NOT created. Saying "Город добавлен" here was a lie, and the
          // offer itself had no way to be accepted.
          if (res && res.status === 'partner_offer') {
            partnerOfferSheet({ city, region, marketType, res });
            return;
          }
          UI.toast('Город добавлен'); loadGeos();
        } catch (e) {
          UI.toast(e.message.indexOf('409') >= 0 ? 'Город защищён другим агентством' : 'Ошибка: ' + e.message);
        }
      };
    });
}

// The city is covered by a partner: the agency may open it in referral mode,
// collecting signals there and handing deals to that partner.
function partnerOfferSheet({ city, region, marketType, res }) {
  UI.sheet('Город закреплён за партнёром',
    `<p>${UI.esc(res.message || 'Этот город обслуживает партнёр.')}</p>
     <p class="muted">Можно работать через партнёра: сигналы собираем мы,
       сделки передаются ему по реферальной схеме.</p>
     <button class="btn btn--block" id="po-accept">${UI.icon('handshake')} Работать через партнёра</button>
     <button class="btn btn--secondary btn--block" id="po-skip" style="margin-top:8px">Не добавлять</button>`,
    (close) => {
      document.getElementById('po-skip').onclick = close;
      document.getElementById('po-accept').onclick = async () => {
        const btn = document.getElementById('po-accept');
        btn.disabled = true;
        try {
          await API.acceptPartnerGeo({
            partner_id: res.partner_id, city_name: city,
            region: region || null, market_type: marketType,
          });
          close(); UI.toast('Город открыт через партнёра'); loadGeos();
        } catch (e) {
          UI.toast('Ошибка: ' + e.message); btn.disabled = false;
        }
      };
    });
}

function partnerSheet() {
  UI.sheet('Добавить партнёра',
    `<div class="field"><label>Название</label><input id="p-name" placeholder="Агентство-партнёр"></div>
     <div class="field"><label>Город</label><input id="p-city" placeholder="напр. Краснодар"></div>
     <div class="field"><label>Telegram (chat id или @)</label><input id="p-tg" placeholder="напр. 123456789"></div>
     <div class="field"><label>Комиссия, %</label><input id="p-com" type="number" inputmode="decimal" placeholder="напр. 30"></div>
     <button class="btn btn--block" id="p-save">${UI.icon('check')} Добавить</button>`,
    (close) => {
      document.getElementById('p-save').onclick = async () => {
        const name = document.getElementById('p-name').value.trim();
        const city = document.getElementById('p-city').value.trim();
        if (!name || !city) { UI.toast('Заполните название и город'); return; }
        const com = parseFloat(document.getElementById('p-com').value);
        try {
          await API.createPartner({
            partner_name: name, partner_city: city,
            contact_telegram: document.getElementById('p-tg').value.trim() || null,
            commission_percent: isNaN(com) ? null : com,
          });
          close(); UI.toast('Партнёр добавлен'); loadPartners();
        } catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
    });
}

function REF_RU(s) {
  return ({ pending: 'Ожидает', sent_to_partner: 'Отправлен', accepted: 'Принят',
    in_progress: 'В работе', rejected: 'Отклонён', expired: 'Истёк',
    deal_done: 'Сделка', dispute: 'Спор' })[s] || s || '—';
}
function REF_CHIP(s) {
  return s === 'deal_done' ? 'chip--success' : (s === 'accepted' || s === 'in_progress') ? 'chip--accent'
    : (s === 'rejected' || s === 'expired' || s === 'dispute') ? '' : 'chip--warm';
}

const PARTNER_TRUST = { standard: 'Базовый', verified: 'Проверенный', premium: 'Премиум' };

Screens.partnerDetail = async function (params) {
  UI.setHeader('Партнёр', '', { back: true });
  UI.render(UI.skelCard() + UI.skelList(2));
  let p;
  try { p = await API.partner(params.id); }
  catch (e) {
    UI.render(UI.errorState(e.message), () => {
      document.getElementById('retry').onclick = () => Screens.referrals();
    });
    return;
  }

  const s = p.stats || {};
  const refs = UI.list(p.referrals, (r) => `
    <div class="card">
      <div class="between"><span class="item__title ellipsis">${UI.esc(r.lead_name || 'Лид')}</span>
        <span class="chip ${REF_CHIP(r.status)}">${REF_RU(r.status)}</span></div>
      <div class="item__sub" style="margin-top:4px">
        ${r.commission_amount ? 'комиссия ' + UI.money(r.commission_amount)
          : (r.commission_agreed_percent ? r.commission_agreed_percent + '%' : '')}</div>
    </div>`, { icon: 'handshake', title: 'Рефералов пока нет' });

  UI.render(`
    <div class="card">
      <div class="between gap-2">
        <span class="card__title ellipsis">${UI.esc(p.partner_name || 'Партнёр')}</span>
        <span class="chip ${p.is_active ? 'chip--success' : ''}">${p.is_active ? 'активен' : 'выключен'}</span></div>
      ${(p.partner_city || p.partner_region)
        ? `<div class="meta-row mt-1">${UI.icon('location')}${UI.esc([p.partner_city, p.partner_region].filter(Boolean).join(', '))}</div>` : ''}
      <hr class="divider">
      <div class="between"><span class="muted">Комиссия</span>
        <span class="price">${p.commission_percent != null ? p.commission_percent + '%'
          : (p.commission_fixed ? UI.money(p.commission_fixed) : '—')}</span></div>
      ${p.trust_level ? `<div class="between mt-2"><span class="muted">Доверие</span>
        <span class="chip chip--accent">${PARTNER_TRUST[p.trust_level] || UI.esc(p.trust_level)}</span></div>` : ''}
      ${p.contact_telegram ? `<div class="between mt-2"><span class="muted">Telegram</span>
        <a href="https://t.me/${UI.esc(String(p.contact_telegram).replace(/^@/, ''))}" target="_blank" rel="noopener">${UI.esc(p.contact_telegram)}</a></div>` : ''}
      ${p.contact_phone ? `<div class="between mt-2"><span class="muted">Телефон</span>
        <a href="tel:${UI.esc(p.contact_phone)}">${UI.esc(p.contact_phone)}</a></div>` : ''}
      ${p.notes ? `<div class="item__sub" style="margin-top:4px">${UI.esc(p.notes)}</div>` : ''}
    </div>
    <div class="stats" style="margin-top:12px">
      <div class="stat"><div class="grow"><div class="stat__n">${s.total || 0}</div><div class="stat__l">Рефералов</div></div></div>
      <div class="stat"><div class="grow"><div class="stat__n">${p.deals_count || 0}</div><div class="stat__l">Сделок</div></div></div>
      <div class="stat"><div class="grow"><div class="stat__n">${s.pending || 0}</div><div class="stat__l">В ожидании</div></div></div>
      <div class="stat"><div class="grow"><div class="stat__n">${s.accepted || 0}</div><div class="stat__l">Принято</div></div></div>
    </div>
    <div class="card" style="margin-top:12px"><div class="between">
      <span class="muted">Заработано комиссии</span>
      <span class="price">${UI.money(p.total_commission_earned)}</span></div></div>
    <div class="btn-row" style="margin-top:12px">
      <button class="btn btn--secondary btn--sm" id="p-edit">${UI.icon('edit')} Изменить</button>
      <button class="btn btn--secondary btn--sm" id="p-toggle">${p.is_active ? 'Отключить' : 'Включить'}</button>
      <button class="btn btn--danger btn--sm" id="p-del">Удалить</button>
    </div>
    <div class="section-title">Рефералы партнёру</div>
    ${refs}`,
    () => {
      document.getElementById('p-edit').onclick = () => editPartnerSheet(p);
      document.getElementById('p-toggle').onclick = async () => {
        try { await API.updatePartner(p.id, { is_active: !p.is_active }); UI.toast('Готово'); Router.resolve(); }
        catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
      document.getElementById('p-del').onclick = async () => {
        try { await API.deletePartner(p.id); UI.toast('Партнёр удалён'); Router.go('settings'); }
        catch (e) { UI.toast(e.message.indexOf('409') >= 0 ? 'Есть рефералы — только отключение' : 'Ошибка: ' + e.message); }
      };
    });
};

function editPartnerSheet(p) {
  UI.sheet('Изменить партнёра', `
    <div class="field"><label>Название</label><input id="e-name" value="${UI.esc(p.partner_name)}"></div>
    <div class="field"><label>Город</label><input id="e-city" value="${UI.esc(p.partner_city)}"></div>
    <div class="field"><label>Регион</label><input id="e-region" value="${UI.esc(p.partner_region || '')}"></div>
    <div class="field"><label>Контакт (имя)</label><input id="e-cname" value="${UI.esc(p.contact_name || '')}"></div>
    <div class="field"><label>Telegram (chat id или @)</label><input id="e-tg" value="${UI.esc(p.contact_telegram || '')}"></div>
    <div class="field"><label>Телефон</label><input id="e-phone" value="${UI.esc(p.contact_phone || '')}"></div>
    <div class="field"><label>Комиссия, %</label><input id="e-com" type="number" inputmode="decimal" value="${p.commission_percent != null ? p.commission_percent : ''}"></div>
    <div class="field"><label>Тип комиссии</label><select id="e-ctype">
      <option value="percent">Процент</option><option value="fixed">Фиксированная</option><option value="hybrid">Гибрид</option></select></div>
    <div class="field"><label>Уровень доверия</label><select id="e-trust">
      <option value="standard">Базовый</option><option value="verified">Проверенный</option><option value="premium">Премиум</option></select></div>
    <div class="field"><label>Заметки</label><textarea id="e-notes" rows="2">${UI.esc(p.notes || '')}</textarea></div>
    <button class="btn btn--block" id="e-save">${UI.icon('check')} Сохранить</button>`,
    (close) => {
      document.getElementById('e-ctype').value = p.commission_type || 'percent';
      document.getElementById('e-trust').value = p.trust_level || 'standard';
      document.getElementById('e-save').onclick = async () => {
        const name = document.getElementById('e-name').value.trim();
        const city = document.getElementById('e-city').value.trim();
        if (!name || !city) { UI.toast('Название и город обязательны'); return; }
        const com = parseFloat(document.getElementById('e-com').value);
        const body = {
          partner_name: name,
          partner_city: city,
          partner_region: document.getElementById('e-region').value.trim() || null,
          contact_name: document.getElementById('e-cname').value.trim() || null,
          contact_telegram: document.getElementById('e-tg').value.trim() || null,
          contact_phone: document.getElementById('e-phone').value.trim() || null,
          commission_percent: isNaN(com) ? null : com,
          commission_type: document.getElementById('e-ctype').value,
          trust_level: document.getElementById('e-trust').value,
          notes: document.getElementById('e-notes').value.trim() || null,
        };
        try { await API.updatePartner(p.id, body); close(); UI.toast('Сохранено'); Router.resolve(); }
        catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
    });
}

Screens.referrals = async function () {
  UI.setHeader('Рефералы', 'Переданные лиды', { back: true });
  UI.render(UI.skelList(3));
  let data;
  try { data = await API.referralsList({ limit: 100 }); }
  catch (e) {
    UI.render(UI.errorState(e.message), () => {
      document.getElementById('retry').onclick = () => Screens.referrals();
    });
    return;
  }
  UI.render(UI.list(data.referrals, (r) => `
    <div class="card">
      <div class="between"><span class="item__title ellipsis">${UI.esc(r.lead_name || 'Лид')}</span>
        <span class="chip ${REF_CHIP(r.status)}">${REF_RU(r.status)}</span></div>
      <div class="meta-row mt-1">${UI.icon('handshake')}${UI.esc(r.partner_name || 'партнёр не указан')}
        ${r.commission_amount ? `<span class="dot"></span>комиссия ${UI.moneyShort(r.commission_amount)}`
          : (r.commission_agreed_percent ? `<span class="dot"></span>${r.commission_agreed_percent}%` : '')}</div>
      ${r.created_at ? `<div class="item__meta mt-1">${UI.esc(UI.ago(r.created_at))}</div>` : ''}
      ${(r.status === 'pending' || r.status === 'accepted' || r.status === 'in_progress')
        ? `<button class="btn btn--block mt-3" data-deal="${r.id}">${UI.icon('handshake')} Записать сделку</button>` : ''}
    </div>`, { icon: 'handshake', title: 'Рефералов нет', sub: 'Передавайте лиды партнёрам из карточки лида' }),
    () => {
      document.querySelectorAll('[data-deal]').forEach((b) =>
        b.onclick = () => refDealSheet(b.getAttribute('data-deal')));
    });
};

function refDealSheet(id) {
  UI.sheet('Сделка по рефералу', `
    <div class="field"><label>Сумма сделки, ₽</label><input id="rd-amount" type="number" inputmode="numeric" placeholder="напр. 8500000"></div>
    <div class="field"><label>Наша комиссия, ₽</label><input id="rd-com" type="number" inputmode="numeric" placeholder="напр. 150000"></div>
    <button class="btn btn--block" id="rd-save">${UI.icon('check')} Записать</button>`,
    (close) => {
      document.getElementById('rd-save').onclick = async () => {
        const amount = parseInt(document.getElementById('rd-amount').value, 10);
        const com = parseInt(document.getElementById('rd-com').value, 10);
        const body = { commission_amount: isNaN(com) ? 0 : com };
        if (!isNaN(amount)) body.deal_amount = amount;
        try { await API.recordReferralDeal(id, body); close(); UI.toast('Сделка записана'); Router.resolve(); }
        catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
    });
}

// Screens: Analytics + Settings/Owner area.
window.Screens = window.Screens || {};

Screens.analytics = async function () {
  UI.setHeader('Аналитика', 'Воронка и источники');
  UI.render(UI.skelCard() + UI.skelList(3));
  const [funnel, roi] = await Promise.all([API.funnel(), API.sourceRoi()]);

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
      <div class="between"><span class="item__title">${UI.esc(s.source)}</span>
        <span class="chip chip--accent">${s.leads} лид.</span></div>
      <div class="between" style="margin-top:8px">
        <span class="muted">Сделки: <b style="color:var(--fg)">${s.deals_won}</b> · конв. ${s.conversion_pct}%</span>
        <span class="price">${UI.money(s.commission)}</span></div>
    </div>`, { icon: 'analytics', title: 'Нет данных по источникам' });

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
      <div class="item__sub">Агентство: <span class="muted">${UI.esc(api.agencyId || '—')}</span></div>
    </div>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Города (гео)</span>
      <button class="btn btn--ghost btn--sm" id="add-geo">${UI.icon('plus')} Город</button></div>
    <div id="geos">${UI.skelList(2)}</div>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Партнёры</span>
      <button class="btn btn--ghost btn--sm" id="add-partner">${UI.icon('plus')} Партнёр</button></div>
    <div id="partners">${UI.skelList(2)}</div>

    <div class="between" style="margin:18px 2px 8px">
      <span class="section-title" style="margin:0">Команда</span></div>
    <div id="mgrs">${UI.skelList(2)}</div>

    <button class="btn btn--danger btn--block" id="logout" style="margin-top:16px">${UI.icon('logout')} Выйти</button>`,
    () => {
      document.getElementById('logout').onclick = () => {
        try { localStorage.removeItem('jwt_token'); } catch (e) { /* ignore */ }
        location.reload();
      };
      document.getElementById('add-geo').onclick = geoSheet;
      document.getElementById('add-partner').onclick = partnerSheet;
      loadGeos(); loadPartners(); loadMgrs();
    });
};

async function loadMgrs() {
  try {
    const m = await API.managers();
    document.getElementById('mgrs').innerHTML = UI.list(m.managers, (x) => `
      <div class="card"><div class="between"><span class="item__title">${UI.esc(x.name)}</span>
        <span class="chip chip--accent">${x.deals_won} сделок</span></div>
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
        <span class="chip ${g.geo_type === 'base' ? 'chip--accent' : ''}">${UI.esc(g.geo_type)}</span></div>
        <div class="item__sub" style="margin-top:4px">${UI.esc(g.region || '')}
          ${g.has_keywords ? '· ключевые слова готовы' : '· keywords генерируются'}</div></div>`,
      { icon: 'location', title: 'Городов нет' });
  } catch (e) { document.getElementById('geos').innerHTML = UI.errorState(e.message); }
}

async function loadPartners() {
  try {
    const d = await API.partners({ active_only: false });
    document.getElementById('partners').innerHTML = UI.list(d.partners, (p) => `
      <div class="card"><div class="between">
        <span class="item__title">${UI.esc(p.partner_name)}</span>
        <span class="chip ${p.is_active ? 'chip--success' : ''}">${p.is_active ? 'активен' : 'выкл'}</span></div>
        <div class="item__sub" style="margin-top:4px">${UI.esc(p.partner_city)}
          ${p.commission_percent ? '· ' + p.commission_percent + '%' : ''}</div></div>`,
      { icon: 'handshake', title: 'Партнёров нет', sub: 'Добавьте, чтобы передавать защищённые лиды' });
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
        try {
          await API.createGeo({ city_name: city, region, market_type: document.getElementById('g-type').value });
          close(); UI.toast('Город добавлен'); loadGeos();
        } catch (e) {
          UI.toast(e.message.indexOf('409') >= 0 ? 'Город защищён другим агентством' : 'Ошибка: ' + e.message);
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

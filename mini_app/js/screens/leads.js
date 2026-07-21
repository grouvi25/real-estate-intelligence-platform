// Screens: Leads list + detail (feedback, deal outcome, commercial offer).
window.Screens = window.Screens || {};

const LEAD_TABS = [['', 'Все'], ['new', 'Новые'], ['in_progress', 'В работе'],
  ['qualified', 'Квалиф.'], ['deal', 'Сделки']];

Screens.leads = async function () {
  UI.setHeader('Лиды', '');
  let cur = Screens._leadTab || '';
  const seg = () => `<div class="segmented" style="margin-bottom:12px">${LEAD_TABS.map(([v, l]) =>
    `<div class="segmented__opt ${v === cur ? 'segmented__opt--active' : ''}" data-tab="${v}">${l}</div>`).join('')}</div>`;

  async function load() {
    document.getElementById('lead-list').innerHTML = UI.skelList();
    const data = await API.leads({ limit: 50, status: cur || undefined });
    document.getElementById('lead-list').innerHTML = UI.list(data.leads, (l) => `
      <div class="card card--tap" data-go="leads/${l.id}">
        <div class="item">
          <div class="avatar">${UI.esc(UI.initials(l.name))}</div>
          <div class="grow">
            <div class="between"><span class="item__title ellipsis">${UI.esc(l.name || 'Без имени')}</span>
              ${UI.urgencyChip(l.urgency)}</div>
            <div class="item__sub">${l.segment ? UI.esc(UI.seg(l.segment)) + ' · ' : ''}${UI.statusChip(l.status)}
              &nbsp;${UI.money(l.budget_max)}</div>
          </div>
          <span class="item__chev">${UI.icon('chevron')}</span>
        </div>
      </div>`, { icon: 'leads', title: 'Лидов нет', sub: 'Квалифицируйте сигнал, чтобы создать лид' });
    bindGo();
  }

  UI.render(seg() + '<div id="lead-list">' + UI.skelList() + '</div>', () => {
    document.querySelectorAll('[data-tab]').forEach((t) => t.onclick = () => {
      cur = t.getAttribute('data-tab'); Screens._leadTab = cur;
      document.querySelectorAll('[data-tab]').forEach((x) =>
        x.classList.toggle('segmented__opt--active', x === t));
      load();
    });
    load();
  });
};

Screens.leadDetail = async function (params) {
  UI.setHeader('Лид', '', { back: true });
  UI.render(UI.skelCard() + UI.skelList(2));
  const l = await API.lead(params.id);

  const matches = UI.list(l.matches, (m) => `
    <div class="card">
      <div class="between"><span class="card__title ellipsis">${UI.esc(m.title)}</span>
        ${UI.scoreEl(m.match_score)}</div>
      <div class="price" style="margin:6px 0">${UI.money(m.price)}</div>
      ${m.pitch ? `<div class="item__sub">${UI.esc(m.pitch)}</div>` : ''}
      <div class="btn-row" style="margin-top:10px">
        <button class="btn btn--secondary btn--sm" data-acc="${m.property_id}">${UI.icon('check')} Подходит</button>
        <button class="btn btn--danger btn--sm" data-rej="${m.property_id}">${UI.icon('close')} Отклонить</button>
      </div>
    </div>`, { icon: 'properties', title: 'Нет подобранных объектов' });

  const alt = l.lead_type === 'alternative'
    ? `<button class="btn btn--secondary btn--block" id="alt" style="margin-top:8px">${UI.icon('refresh')} Обработать альтернативу</button>` : '';

  UI.render(`
    <div class="card">
      <div class="item">
        <div class="avatar">${UI.esc(UI.initials(l.name))}</div>
        <div class="grow"><div class="card__title ellipsis">${UI.esc(l.name || 'Без имени')}</div>
          <div class="item__sub">${l.segment ? UI.esc(UI.seg(l.segment)) + ' · ' : ''}${UI.esc(l.purchase_goal || '')}</div></div>
        ${UI.urgencyChip(l.urgency)}
      </div>
      <hr class="divider">
      ${l.phone ? `<div class="row" style="margin:6px 0">${UI.icon('phone')}<a href="tel:${UI.esc(l.phone)}">${UI.esc(l.phone)}</a></div>` : ''}
      <div class="row" style="margin:6px 0">${UI.icon('ruble')}<span>${UI.money(l.budget_min)} – ${UI.money(l.budget_max)}</span></div>
      <div class="row" style="margin:6px 0">${UI.icon('tag')}${UI.statusChip(l.status)}</div>
    </div>
    <div class="btn-row" style="margin-top:12px">
      <button class="btn btn--sm" id="qual">${UI.icon('check')} Квалиф.</button>
      <button class="btn btn--secondary btn--sm" id="deal">${UI.icon('handshake')} Исход</button>
      <button class="btn btn--secondary btn--sm" id="kp">${UI.icon('file')} КП</button>
    </div>
    <button class="btn btn--danger btn--block" id="arch" style="margin-top:8px">Отправить в архив</button>
    ${alt}
    <div class="section-title">Подборка объектов</div>
    ${matches}`,
    () => wire(l));
};

function wire(l) {
  const doStatus = async (status, toastMsg, goBack) => {
    await API.setLeadStatus(l.id, { status });
    UI.toast(toastMsg);
    goBack ? Router.go('leads') : Router.resolve();
  };
  document.getElementById('qual').onclick = () => doStatus('qualified', 'Квалифицирован', false);
  document.getElementById('arch').onclick = () => doStatus('archived', 'В архиве', true);
  const altBtn = document.getElementById('alt');
  if (altBtn) altBtn.onclick = async () => {
    try { const r = await API.processAlternative(l.id); UI.toast(`Создано задач: ${r.tasks_created}`); }
    catch (e) { UI.toast('Ошибка: ' + e.message); }
  };

  document.getElementById('deal').onclick = () => dealSheet(l);
  document.getElementById('kp').onclick = () => docSheet(l);

  document.querySelectorAll('[data-acc]').forEach((b) => b.onclick = async () => {
    try { await API.matchFeedback(l.id, b.getAttribute('data-acc'), { status: 'accepted' }); UI.toast('Отмечено «подходит»'); }
    catch (e) { UI.toast('Ошибка: ' + e.message); }
  });
  document.querySelectorAll('[data-rej]').forEach((b) => b.onclick = () => rejectSheet(l, b.getAttribute('data-rej')));
}

const REJECT_CATS = [['price_too_high', 'Дорого'], ['wrong_location', 'Локация'],
  ['wrong_size', 'Размер'], ['wrong_type', 'Тип'], ['client_changed_mind', 'Передумал'], ['other', 'Другое']];

function rejectSheet(l, propId) {
  UI.sheet('Причина отказа',
    `<div class="stack" style="gap:8px">${REJECT_CATS.map(([v, t]) =>
      `<button class="btn btn--secondary btn--block" data-cat="${v}">${t}</button>`).join('')}</div>`,
    (close) => {
      document.querySelectorAll('[data-cat]').forEach((b) => b.onclick = async () => {
        try {
          await API.matchFeedback(l.id, propId, { status: 'rejected', rejection_category: b.getAttribute('data-cat') });
          close(); UI.toast('Отклонено'); Router.resolve();
        } catch (e) { UI.toast('Ошибка: ' + e.message); }
      });
    });
}

const OUTCOMES = [['deal_done', 'Сделка закрыта'], ['rejected', 'Отказ клиента'],
  ['lost_to_competitor', 'Ушёл к конкуренту'], ['expired', 'Протух']];

function dealSheet(l) {
  UI.sheet('Записать исход',
    `<div class="field"><label>Сумма сделки, ₽</label><input id="da" type="number" inputmode="numeric" placeholder="напр. 8500000"></div>
     <div class="field"><label>Комиссия, ₽</label><input id="ca" type="number" inputmode="numeric" placeholder="напр. 300000"></div>
     <div class="stack" style="gap:8px">${OUTCOMES.map(([v, t]) =>
      `<button class="btn ${v === 'deal_done' ? '' : 'btn--secondary'} btn--block" data-out="${v}">${t}</button>`).join('')}</div>`,
    (close) => {
      document.querySelectorAll('[data-out]').forEach((b) => b.onclick = async () => {
        const body = { outcome: b.getAttribute('data-out') };
        const da = parseInt(document.getElementById('da').value, 10);
        const ca = parseInt(document.getElementById('ca').value, 10);
        if (!isNaN(da)) body.deal_amount = da;
        if (!isNaN(ca)) body.commission_amount = ca;
        try { await API.recordOutcome(l.id, body); close(); UI.toast('Исход записан'); Router.resolve(); }
        catch (e) { UI.toast('Ошибка: ' + e.message); }
      });
    });
}

async function docSheet(l) {
  UI.sheet('Коммерческое предложение', '<div class="skel skel-line lg"></div><div class="skel skel-line md"></div>',
    async () => {
      try {
        const html = await API.leadDocumentHtml(l.id);
        const body = document.querySelector('.sheet__body');
        const iframe = document.createElement('iframe');
        iframe.setAttribute('sandbox', 'allow-same-origin');
        body.innerHTML = '';
        body.appendChild(iframe);
        iframe.srcdoc = html;
      } catch (e) {
        document.querySelector('.sheet__body').innerHTML = UI.errorState(e.message);
      }
    });
}

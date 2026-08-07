// Screens: Leads list + detail (feedback, deal outcome, commercial offer).
//
// The list answers the manager's three questions in one glance: who, how much,
// and how long they have been waiting. The budget is the figure that decides
// what to show them, so it is the figure that gets the weight.
window.Screens = window.Screens || {};

const LEAD_TABS = [['', 'Все'], ['new', 'Новые'], ['in_progress', 'В работе'],
  ['qualified', 'Квалиф.'], ['deal', 'Сделки']];

function leadName(l) {
  return l.name || (l.telegram_username ? '@' + l.telegram_username : 'Лид #' + String(l.id).slice(0, 6));
}

function leadCard(l) {
  const tone = l.urgency === 'hot' ? ' card--hot' : l.urgency === 'warm' ? ' card--warm' : '';
  const budget = l.budget_max ? UI.moneyShort(l.budget_max) : '';
  return `
    <div class="card card--tap${tone}" data-go="leads/${l.id}">
      <div class="item">
        <div class="avatar">${UI.esc(UI.initials(l.name || l.telegram_username || '?'))}</div>
        <div class="grow">
          <div class="between">
            <span class="item__title ellipsis">${UI.esc(leadName(l))}</span>
            ${budget ? `<span class="price">${budget}</span>` : ''}
          </div>
          <div class="row row--wrap gap-1 mt-1">
            ${UI.urgencyChip(l.urgency)}
            ${UI.statusChip(l.status)}
            ${l.segment ? `<span class="chip">${UI.esc(UI.seg(l.segment))}</span>` : ''}
          </div>
          <div class="item__meta mt-2">
            ${l.created_at ? UI.esc(UI.ago(l.created_at)) : ''}
            ${l.intent_score != null ? `<span class="dot"></span>интерес ${l.intent_score}` : ''}
          </div>
        </div>
        <span class="item__chev">${UI.icon('chevron')}</span>
      </div>
    </div>`;
}

Screens.leads = async function () {
  UI.setHeader('Лиды', 'Кому продаём', {
    actionIcon: 'plus', actionLabel: 'Новый лид', onAction: () => Router.go('leads/new'),
  });
  let cur = Screens._leadTab || '';

  const bar = () => `<div class="segmented" role="tablist">${LEAD_TABS.map(([v, l]) =>
    `<button class="segmented__opt${v === cur ? ' segmented__opt--active' : ''}" role="tab"
       aria-selected="${v === cur}" data-tab="${v}">${l}</button>`).join('')}</div>`;

  function draw() {
    UI.load(bar() + UI.skelList(4),
      () => API.leads({ limit: 50, status: cur || undefined }),
      (data) => {
        UI.render(bar() + UI.list(data.leads, leadCard, {
          icon: 'leads',
          title: cur ? 'В этом статусе пусто' : 'Лидов пока нет',
          sub: cur ? 'Посмотрите другие вкладки'
            : 'Квалифицируйте сигнал или заведите лида вручную',
          actionLabel: cur ? null : 'Новый лид', actionIcon: 'plus', actionId: 'new-lead',
        }), () => {
          Router.bindGo();
          document.querySelectorAll('[data-tab]').forEach((t) => {
            t.onclick = () => { cur = t.getAttribute('data-tab'); Screens._leadTab = cur; draw(); };
          });
          const n = document.getElementById('new-lead');
          if (n) n.onclick = () => Router.go('leads/new');
        });
      });
  }

  draw();
};

// TZ 30 screen /leads/new. Until this existed a lead could only arrive from a
// Telegram signal or a lead magnet, so a manager who took a phone call had
// nowhere to put that person.
const LEAD_SOURCES = [['incoming_call', 'Входящий звонок'], ['manual', 'Вручную'],
  ['referral', 'По рекомендации']];
const LEAD_SEGMENTS = [['', 'Не указан'], ['family', 'Семья'], ['investor', 'Инвестор'],
  ['relocant', 'Переезжающий'], ['remote_worker', 'Удалёнщик'], ['senior', 'Пенсионер'],
  ['alternative', 'Альтернатива'], ['student_parent', 'Родитель студента']];
const LEAD_GOALS = [['', 'Не указана'], ['own', 'Для себя'], ['invest', 'Инвестиция'],
  ['rent_out', 'Под сдачу'], ['relocate', 'Переезд'], ['children', 'Детям']];
const LEAD_URGENCY = [['hot', 'Горячий'], ['warm', 'Тёплый'], ['cold', 'Холодный']];

const opts = (list, sel) => list.map(([v, l]) =>
  `<option value="${v}"${v === sel ? ' selected' : ''}>${l}</option>`).join('');

Screens.leadNew = async function () {
  UI.setHeader('Новый лид', 'Звонок, встреча, рекомендация', { back: true });
  UI.render(`
    <div class="card">
      <div class="field"><label>Имя *</label><input id="ln-name" placeholder="Как зовут"></div>
      <div class="field"><label>Телефон</label><input id="ln-phone" type="tel" placeholder="+7 ..."></div>
      <div class="field"><label>Telegram</label><input id="ln-tg" placeholder="@username"></div>
      <div class="item__sub">Нужен телефон или Telegram — иначе с лидом не связаться.</div>
    </div>

    <div class="card" style="margin-top:12px">
      <div class="field"><label>Откуда</label><select id="ln-src">${opts(LEAD_SOURCES, 'incoming_call')}</select></div>
      <div class="field"><label>Сегмент</label><select id="ln-seg">${opts(LEAD_SEGMENTS, '')}</select></div>
      <div class="field"><label>Цель покупки</label><select id="ln-goal">${opts(LEAD_GOALS, '')}</select></div>
      <div class="field"><label>Срочность</label><select id="ln-urg">${opts(LEAD_URGENCY, 'warm')}</select></div>
      <div class="row" style="gap:8px">
        <div class="field grow"><label>Бюджет от, ₽</label><input id="ln-bmin" type="number" inputmode="numeric"></div>
        <div class="field grow"><label>до, ₽</label><input id="ln-bmax" type="number" inputmode="numeric"></div>
      </div>
      <div class="field"><label>Заметка</label><input id="ln-note" placeholder="Что важно помнить"></div>
    </div>

    <div class="card" style="margin-top:12px">
      <label class="row" style="gap:10px;align-items:flex-start">
        <input type="checkbox" id="ln-consent">
        <span>Клиент дал согласие на обработку персональных данных (152-ФЗ)</span>
      </label>
    </div>

    <button class="btn btn--block" id="ln-save" style="margin-top:14px">${UI.icon('check')} Создать лид</button>`,
    () => {
      document.getElementById('ln-save').onclick = async () => {
        const val = (id) => document.getElementById(id).value.trim();
        const num = (id) => { const n = parseInt(val(id), 10); return isNaN(n) ? null : n; };

        if (!val('ln-name')) { UI.toast('Укажите имя'); return; }
        if (!val('ln-phone') && !val('ln-tg')) { UI.toast('Нужен телефон или Telegram'); return; }
        if (!document.getElementById('ln-consent').checked) {
          UI.toast('Без согласия клиента лид создать нельзя'); return;
        }
        const bmin = num('ln-bmin'), bmax = num('ln-bmax');
        if (bmin && bmax && bmin > bmax) { UI.toast('Бюджет «от» больше «до»'); return; }

        const btn = document.getElementById('ln-save');
        btn.disabled = true;
        try {
          const r = await API.createLeadManual({
            name: val('ln-name'),
            phone: val('ln-phone') || null,
            telegram_username: val('ln-tg') || null,
            source_type: val('ln-src'),
            segment: val('ln-seg') || null,
            purchase_goal: val('ln-goal') || null,
            urgency: val('ln-urg'),
            budget_min: bmin, budget_max: bmax,
            note: val('ln-note') || null,
            consent_text: 'Согласие получено менеджером при контакте (152-ФЗ)',
          });
          UI.toast(r.is_duplicate ? 'Такой лид уже был — открываю его' : 'Лид создан');
          Router.go('leads/' + r.lead_id);
        } catch (e) {
          UI.toast('Ошибка: ' + e.message); btn.disabled = false;
        }
      };
    });
};

Screens.leadDetail = async function (params) {
  UI.setHeader('Лид', '', { back: true });

  UI.load(UI.skelCard() + `<div class="mt-3">${UI.skelList(2)}</div>`,
    () => API.lead(params.id), (l) => {
      const matches = UI.list(l.matches, (m) => `
        <div class="card">
          <div class="between">
            <span class="card__title ellipsis">${UI.esc(m.title)}</span>
            ${UI.scoreEl(m.match_score)}
          </div>
          <div class="price mt-1" style="font-size:var(--t-lg)">${UI.money(m.price)}</div>
          ${m.pitch ? `<div class="item__sub mt-2">${UI.esc(m.pitch)}</div>` : ''}
          <div class="btn-row btn-row--equal mt-3">
            <button class="btn btn--secondary btn--sm" data-acc="${m.property_id}">${UI.icon('check')} Подходит</button>
            <button class="btn btn--danger btn--sm" data-rej="${m.property_id}">${UI.icon('close')} Не то</button>
          </div>
        </div>`, { icon: 'properties', title: 'Объекты ещё не подобраны',
                   sub: 'Подбор запускается после квалификации лида' });

      const contact = [
        l.phone ? `<a class="btn btn--secondary btn--sm" href="tel:${UI.esc(l.phone)}">${UI.icon('phone')} Позвонить</a>` : '',
        l.telegram_username ? `<a class="btn btn--secondary btn--sm" target="_blank" rel="noopener"
           href="https://t.me/${UI.esc(String(l.telegram_username).replace(/^@/, ''))}">${UI.icon('send')} Написать</a>` : '',
      ].filter(Boolean).join('');

      UI.render(`
        <div class="card${l.urgency === 'hot' ? ' card--hot' : ''}">
          <div class="item">
            <div class="avatar">${UI.esc(UI.initials(l.name || l.telegram_username || '?'))}</div>
            <div class="grow">
              <div class="card__title ellipsis">${UI.esc(leadName(l))}</div>
              <div class="item__sub">${l.segment ? UI.esc(UI.seg(l.segment)) : 'Сегмент не определён'}</div>
            </div>
            ${UI.urgencyChip(l.urgency)}
          </div>
          ${contact ? `<div class="btn-row btn-row--equal mt-3">${contact}</div>` : ''}
          <hr class="divider">
          <div class="between"><span class="muted">Бюджет</span>
            <span class="price">${l.budget_min ? UI.moneyShort(l.budget_min) + ' – ' : 'до '}${UI.moneyShort(l.budget_max)}</span></div>
          <div class="between mt-2"><span class="muted">Статус</span>${UI.statusChip(l.status)}</div>
          <div class="between mt-2"><span class="muted">Создан</span>
            <span class="item__meta">${UI.esc(UI.dateTime(l.created_at))}</span></div>
        </div>

        <div class="section-title">Действия</div>
        <button class="btn btn--block" id="qual">${UI.icon('check')} Квалифицировать</button>
        <div class="btn-row btn-row--equal mt-2">
          <button class="btn btn--secondary btn--sm" id="deal">${UI.icon('handshake')} Исход</button>
          <button class="btn btn--secondary btn--sm" id="kp">${UI.icon('file')} КП</button>
          <button class="btn btn--secondary btn--sm" id="contract">${UI.icon('file')} Договор</button>
        </div>
        <button class="btn btn--secondary btn--block mt-2" id="refer">${UI.icon('handshake')} Передать партнёру</button>
        ${l.lead_type === 'alternative'
          ? `<button class="btn btn--secondary btn--block mt-2" id="alt">${UI.icon('refresh')} Обработать альтернативу</button>` : ''}
        <button class="btn btn--danger btn--block mt-2" id="arch">${UI.icon('trash')} В архив</button>

        <div class="section-title">Персональные данные · 152-ФЗ</div>
        <div class="btn-row btn-row--equal">
          <button class="btn btn--secondary btn--sm" id="pd-export">${UI.icon('file')} Выгрузить</button>
          <button class="btn btn--danger btn--sm" id="pd-erase">${UI.icon('trash')} Удалить ПД</button>
        </div>
        <div class="item__meta mt-2">По требованию клиента: выгрузка — что о нём хранится,
          удаление — стираются имя, телефон, почта и текст обращения. Статистика сделки
          остаётся обезличенной.</div>

        <div class="section-head">
          <span class="section-title">Подборка объектов</span>
          <span class="item__meta">${(l.matches || []).length}</span>
        </div>
        ${matches}`,
        () => wire(l));
    });
};

function wire(l) {
  const doStatus = async (status, toastMsg, goBack) => {
    await API.setLeadStatus(l.id, { status });
    UI.toast(toastMsg);
    goBack ? Router.go('leads') : Router.resolve();
  };
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on('qual', (e) => UI.busy(e.currentTarget, () => doStatus('qualified', 'Квалифицирован', false)));
  on('arch', (e) => UI.busy(e.currentTarget, () => doStatus('archived', 'В архиве', true)));
  const altBtn = document.getElementById('alt');
  if (altBtn) altBtn.onclick = async () => {
    try { const r = await API.processAlternative(l.id); UI.toast(`Создано задач: ${r.tasks_created}`); }
    catch (e) { UI.toast('Ошибка: ' + e.message); }
  };

  on('pd-export', (e) => UI.busy(e.currentTarget, () => pdExportSheet(l)));
  on('pd-erase', () => pdEraseSheet(l));
  on('deal', () => dealSheet(l));
  on('kp', () => docSheet(l));
  on('contract', () => contractSheet(l));
  on('refer', () => referralSheet(l));

  document.querySelectorAll('[data-acc]').forEach((b) => b.onclick = async () => {
    try { await API.matchFeedback(l.id, b.getAttribute('data-acc'), { status: 'accepted' }); UI.toast('Отмечено «подходит»'); }
    catch (e) { UI.toast('Ошибка: ' + e.message); }
  });
  document.querySelectorAll('[data-rej]').forEach((b) => b.onclick = () => rejectSheet(l, b.getAttribute('data-rej')));
}

// 152-ФЗ §14: the subject may ask what is stored about them.
async function pdExportSheet(l) {
  UI.sheet('Персональные данные', UI.skelCard(), async () => {
    const body = document.querySelector('.sheet__body');
    try {
      const data = await API.personalData(l.id);
      const json = JSON.stringify(data, null, 2);
      body.innerHTML = `
        <div class="item__sub">Всё, что система хранит об этом человеке. Можно отправить
          ему по запросу.</div>
        <div class="copyfield mt-3" style="max-height:40vh;overflow:auto;white-space:pre-wrap">${UI.esc(json)}</div>
        <button class="btn btn--block mt-3" id="pd-copy">${UI.icon('copy')} Скопировать</button>`;
      document.getElementById('pd-copy').onclick = async () => {
        try { await navigator.clipboard.writeText(json); UI.toast('Скопировано'); }
        catch (e) { UI.toast('Выделите текст и скопируйте вручную'); }
      };
    } catch (e) {
      body.innerHTML = UI.errorState(e.message);
    }
  });
}

// 152-ФЗ §21: erasure on request. Irreversible, so it asks twice.
function pdEraseSheet(l) {
  UI.sheet('Удалить персональные данные', `
    <div class="item__sub">Будут стёрты имя, телефон, почта, Telegram и текст исходного
      обращения. Отменить нельзя.</div>
    <div class="item__sub mt-2">Останется обезличенная запись: источник, статус, сумма
      сделки — она нужна для отчётности агентства и никого не идентифицирует.</div>
    <div class="field mt-3"><label for="pd-reason">Основание</label>
      <input id="pd-reason" value="Запрос субъекта ПД"></div>
    <button class="btn btn--danger btn--block" id="pd-go">${UI.icon('trash')} Удалить безвозвратно</button>`,
    (close) => {
      const go = document.getElementById('pd-go');
      go.onclick = () => UI.busy(go, async () => {
        try {
          await API.erasePersonalData(l.id, document.getElementById('pd-reason').value.trim());
          close();
          UI.toast('Персональные данные удалены');
          Router.go('leads');
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
    });
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

function contractSheet(l) {
  const opts = (l.matches || []).map((m) =>
    `<option value="${m.property_id}">${UI.esc(m.title || m.property_id)}</option>`).join('');
  if (!opts) { UI.toast('Сначала нужен подобранный объект'); return; }

  const plus = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
  UI.sheet('Предварительный договор',
    `<div class="field"><label>Объект</label><select id="cp">${opts}</select></div>
     <div class="field"><label>Задаток, ₽</label><input id="cd" type="number" inputmode="numeric" placeholder="напр. 300000"></div>
     <div class="field"><label>Срок задатка, дней</label><input id="cdays" type="number" inputmode="numeric" value="7"></div>
     <div class="field"><label>Дата основной сделки</label><input id="cfd" type="date" value="${plus}"></div>
     <button class="btn btn--block" id="cgo">${UI.icon('file')} Сформировать</button>`,
    (close) => {
      document.getElementById('cgo').onclick = async () => {
        const amount = parseInt(document.getElementById('cd').value, 10);
        const days = parseInt(document.getElementById('cdays').value, 10);
        const finalDate = document.getElementById('cfd').value;
        if (isNaN(amount) || amount <= 0) { UI.toast('Укажите сумму задатка'); return; }
        if (isNaN(days) || days <= 0) { UI.toast('Укажите срок задатка'); return; }
        if (!finalDate) { UI.toast('Укажите дату сделки'); return; }

        const btn = document.getElementById('cgo');
        btn.disabled = true;
        try {
          const doc = await API.createContract({
            lead_id: l.id,
            property_id: document.getElementById('cp').value,
            deposit_amount: amount, deposit_days: days, final_date: finalDate,
          });
          close();
          UI.docLinkSheet('Договор готов', doc, `Формат: ${UI.esc(doc.format.toUpperCase())}`);
        } catch (e) {
          UI.toast('Ошибка: ' + e.message); btn.disabled = false;
        }
      };
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

async function referralSheet(l) {
  UI.sheet('Передать партнёру', UI.skelList(2), async (close) => {
    let data;
    try { data = await API.partners({ active_only: true }); }
    catch (e) { document.querySelector('.sheet__body').innerHTML = UI.errorState(e.message); return; }
    if (!data.partners.length) {
      document.querySelector('.sheet__body').innerHTML =
        UI.empty({ icon: 'handshake', title: 'Нет партнёров', sub: 'Добавьте партнёра в разделе Профиль' });
      return;
    }
    document.querySelector('.sheet__body').innerHTML = data.partners.map((p) => `
      <button class="btn btn--secondary btn--block" data-p="${p.id}" style="margin-bottom:8px">
        ${UI.esc(p.partner_name)} · ${UI.esc(p.partner_city)}${p.commission_percent ? ' · ' + p.commission_percent + '%' : ''}
      </button>`).join('');
    document.querySelectorAll('[data-p]').forEach((b) => b.onclick = async () => {
      try {
        await API.createReferral({ lead_id: l.id, partner_agency_id: b.getAttribute('data-p') });
        close(); UI.toast('Лид передан партнёру'); Router.go('leads');
      } catch (e) { UI.toast('Ошибка: ' + e.message); }
    });
  });
}

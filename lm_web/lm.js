// Public lead magnet pages of an agency: /lm/<agency_id> lists the tools,
// /lm/<agency_id>/<tool> opens one. Everything comes from /api/lm.
(function () {
  'use strict';

  const parts = location.pathname.split('/').filter(Boolean); // ['lm', agency, tool?]
  const AGENCY = parts[1] || '';
  const TOOL = parts[2] || '';
  const app = document.getElementById('app');
  const CONSENT = 'Я согласен на обработку персональных данных в соответствии с политикой конфиденциальности';
  let cfg = null;

  // ---------------------------------------------------------------- helpers
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const rub = (n) => (n == null || isNaN(n) ? '—' : Math.round(n).toLocaleString('ru-RU') + ' ₽');
  const num = (v) => { const d = String(v || '').replace(/\D/g, ''); return d ? parseInt(d, 10) : null; };
  const $ = (id) => document.getElementById(id);

  function utm() {
    const q = new URLSearchParams(location.search);
    const out = {};
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'].forEach((k) => {
      if (q.get(k)) out[k] = q.get(k).slice(0, 200);
    });
    if (document.referrer) out.referrer = document.referrer.slice(0, 500);
    return out;
  }

  function errorText(data, status) {
    if (data && data.error) return data.error;
    if (data && Array.isArray(data.detail) && data.detail[0]) {
      const field = (data.detail[0].loc || []).slice(-1)[0];
      const names = { property_price: 'стоимость', down_payment: 'взнос', budget_max: 'бюджет',
        contact_phone: 'телефон', contact_name: 'имя', city: 'город' };
      return 'Проверьте поле «' + (names[field] || field || 'форма') + '»';
    }
    if (data && typeof data.detail === 'string') return data.detail;
    if (status === 429) return 'Слишком много запросов — попробуйте через минуту';
    return 'Не получилось. Попробуйте ещё раз';
  }

  async function api(path, body) {
    const res = await fetch('/api/lm' + path, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(errorText(data, res.status)); e.status = res.status; throw e; }
    return data;
  }

  // A button keeps its size while busy: the label is swapped for a spinner of the same height.
  async function busy(btn, fn) {
    if (btn.getAttribute('aria-busy') === 'true') return;
    const label = btn.innerHTML;
    btn.style.width = btn.offsetWidth + 'px';
    btn.setAttribute('aria-busy', 'true');
    btn.disabled = true;
    btn.innerHTML = '<span class="spin" aria-hidden="true"></span><span class="sr">Подождите…</span>';
    try { return await fn(); } finally {
      btn.disabled = false; btn.removeAttribute('aria-busy'); btn.innerHTML = label; btn.style.width = '';
    }
  }

  function showError(box, message) {
    box.innerHTML = '<div class="msg msg--bad" role="alert">' + esc(message) + '</div>';
  }

  function moneyInput(id, label, opts) {
    const o = opts || {};
    return '<div class="field"><label for="' + id + '">' + label + '</label>' +
      '<input type="text" inputmode="numeric" autocomplete="off" id="' + id + '" placeholder="' + (o.placeholder || '') + '"' +
      (o.value != null ? ' value="' + Number(o.value).toLocaleString('ru-RU') + '"' : '') + '>' +
      (o.hint ? '<div class="hint">' + o.hint + '</div>' : '') + '</div>';
  }

  // digits only, grouped as the person types
  function bindMoney(root) {
    root.querySelectorAll('input[inputmode=numeric]').forEach((el) => {
      el.addEventListener('input', () => {
        const n = num(el.value);
        el.value = n == null ? '' : n.toLocaleString('ru-RU');
        el.removeAttribute('aria-invalid');
      });
    });
  }

  function select(id, label, options, value) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><select id="' + id + '">' +
      options.map(([v, l]) => '<option value="' + esc(v) + '"' + (String(v) === String(value) ? ' selected' : '') + '>' + esc(l) + '</option>').join('') +
      '</select></div>';
  }

  function contactFields(prefix) {
    return '<div class="row2">' +
      '<div class="field"><label for="' + prefix + '-name">Имя</label><input type="text" id="' + prefix + '-name" autocomplete="name"></div>' +
      '<div class="field"><label for="' + prefix + '-phone">Телефон</label><input type="tel" id="' + prefix + '-phone" autocomplete="tel" placeholder="+7 900 000-00-00"></div>' +
      '</div>' +
      '<label class="check"><input type="checkbox" id="' + prefix + '-consent">' +
      '<span>Я согласен на обработку персональных данных в соответствии с <a href="' + esc(cfg.privacy_url) + '" target="_blank" rel="noopener">политикой конфиденциальности</a></span></label>';
  }

  // the contact block's values, or a message for what is missing
  function readContacts(prefix) {
    const name = $(prefix + '-name').value.trim();
    const phone = $(prefix + '-phone').value.trim();
    if (name.length < 2) { $(prefix + '-name').setAttribute('aria-invalid', 'true'); return { error: 'Напишите, как к вам обращаться' }; }
    if (String(phone).replace(/\D/g, '').length < 10) { $(prefix + '-phone').setAttribute('aria-invalid', 'true'); return { error: 'Нужен телефон, чтобы менеджер мог связаться' }; }
    if (!$(prefix + '-consent').checked) return { error: 'Отметьте согласие на обработку данных' };
    return { contact_name: name, contact_phone: phone, consent_given: true, consent_text: CONSENT };
  }

  // After a result: offer a manager's help; ``send`` posts the subscribe request.
  function cta(box, title, text, send) {
    const div = document.createElement('div');
    div.className = 'card cta';
    div.innerHTML = '<div class="cta__t">' + esc(title) + '</div><div class="cta__d">' + esc(text) + '</div>' +
      contactFields('c') + '<div id="c-msg"></div><button class="btn" id="c-send" type="button">Отправить</button>';
    box.appendChild(div);
    const btn = $('c-send');
    btn.onclick = () => busy(btn, async () => {
      const contacts = readContacts('c');
      if (contacts.error) { showError($('c-msg'), contacts.error); return; }
      try {
        const res = await send(Object.assign({ agency_id: AGENCY }, contacts, utm()));
        div.innerHTML = thanks(res);
      } catch (e) { showError($('c-msg'), e.message); }
    });
  }

  function thanks(res) {
    return '<div class="msg msg--ok" role="status">' + (res && res.is_duplicate
      ? 'Ваша заявка у нас уже есть — менеджер свяжется с вами.'
      : 'Спасибо! Менеджер агентства «' + esc(cfg.agency.name) + '» свяжется с вами.') + '</div>';
  }

  function list(title, items) {
    if (!items || !items.length) return '';
    return '<div class="sub">' + esc(title) + '</div><ul class="list">' + items.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul>';
  }

  // ---------------------------------------------------------------- pages
  function page(title, lead, form) {
    const back = cfg.tools.length > 1 ? '<a class="back" href="/lm/' + esc(AGENCY) + location.search + '">← Все инструменты</a>' : '';
    app.innerHTML = back + '<h1>' + esc(title) + '</h1><p class="lead">' + esc(lead) + '</p>' +
      '<form class="card" id="f" novalidate>' + form + '<div id="f-msg"></div>' +
      '<button class="btn" id="f-go" type="submit">Рассчитать</button></form><div id="out"></div>';
    bindMoney(app);
    return { form: $('f'), btn: $('f-go'), msg: $('f-msg'), out: $('out') };
  }

  function onSubmit(p, fn) {
    p.form.onsubmit = (ev) => {
      ev.preventDefault();
      p.msg.innerHTML = '';
      busy(p.btn, async () => {
        try {
          await fn();
          // on a phone the result lands below the fold: bring it up
          if (p.out.firstElementChild) p.out.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) { showError(p.msg, e.message); }
      });
    };
  }

  const TOOLS = {};

  TOOLS.mortgage = function () {
    const progs = cfg.mortgage_programs.map((p) => [p.key, p.name + ' — ' + String(p.rate_percent).replace('.', ',') + ' %']);
    const p = page('Ипотечный калькулятор', 'Платёж и переплата по пяти программам — считаем по ставкам агентства.',
      moneyInput('m-price', 'Стоимость квартиры', { placeholder: '7 500 000' }) +
      moneyInput('m-down', 'Первоначальный взнос', { placeholder: '1 500 000' }) +
      '<div class="row2">' +
      select('m-term', 'Срок, лет', [5, 10, 15, 20, 25, 30].map((y) => [y, y]), 20) +
      select('m-prog', 'Программа', progs, 'standard') + '</div>' +
      moneyInput('m-income', 'Доход семьи в месяц', { hint: 'Необязательно — покажем, хватает ли дохода' }) +
      '<label class="check"><input type="checkbox" id="m-mat"><span>Есть материнский капитал (' + rub(cfg.matkapital) + ')</span></label>');
    p.btn.textContent = 'Рассчитать платёж';
    onSubmit(p, async () => {
      const price = num($('m-price').value);
      const down = num($('m-down').value) || 0;
      if (!price || price < 500000) { $('m-price').setAttribute('aria-invalid', 'true'); throw new Error('Укажите стоимость — от 500 000 ₽'); }
      const body = { property_price: price, down_payment: down, term_years: parseInt($('m-term').value, 10),
        program: $('m-prog').value, use_matkapital: $('m-mat').checked, monthly_income: num($('m-income').value), agency_id: AGENCY };
      const r = await api('/lm2/calculate', body);
      const s = r.selected_program;
      if (s.error) throw new Error('Взнос не может быть больше стоимости квартиры');
      let income = '';
      if (s.income_sufficient === true) income = '<span class="chip chip--ok">Дохода хватает</span>';
      if (s.income_sufficient === false) income = '<span class="chip chip--warn">Банк может попросить созаёмщика</span>';
      p.out.innerHTML = '<h2>Результат</h2><div class="card">' +
        '<div class="note" style="margin-top:0">Платёж в месяц · ' + esc(s.program) + ', ' + String(s.rate_percent).replace('.', ',') + ' %</div>' +
        '<div class="big">' + rub(s.monthly_payment) + '</div>' + (income ? '<div style="margin-top:8px">' + income + '</div>' : '') +
        '<div style="margin-top:12px">' +
        '<div class="kv"><span>Сумма кредита</span><span>' + rub(s.loan_amount) + '</span></div>' +
        '<div class="kv"><span>Срок</span><span>' + s.term_years + ' лет</span></div>' +
        '<div class="kv"><span>Переплата</span><span>' + rub(s.overpayment) + ' (' + String(s.overpayment_percent).replace('.', ',') + ' %)</span></div>' +
        '<div class="kv"><span>Рекомендуемый доход</span><span>от ' + rub(s.recommended_min_income) + '</span></div>' +
        (s.matkapital_used ? '<div class="kv"><span>Маткапитал в взносе</span><span>' + rub(s.matkapital_used) + '</span></div>' : '') +
        '</div><div class="note">Условия программы: ' + esc(s.conditions) + '</div></div>' +
        '<h2>Все программы</h2><div class="card"><table class="cmp"><tr><th>Программа</th><th>Ставка</th><th>В месяц</th></tr>' +
        r.all_programs.filter((x) => !x.error).map((x) => '<tr' + (x.program_key === body.program ? ' class="on"' : '') + '><td>' + esc(x.program) +
          '</td><td>' + String(x.rate_percent).replace('.', ',') + ' %</td><td>' + rub(x.monthly_payment) + '</td></tr>').join('') +
        '</table><div class="note">Расчёт ориентировочный: точную ставку назовёт банк.</div></div>';
      cta(p.out, 'Подобрать квартиру под этот платёж', 'Менеджер пришлёт варианты, которые укладываются в бюджет, и поможет с одобрением ипотеки.',
        (c) => api('/lm2/subscribe', Object.assign({ calc_data: body }, c)));
    });
  };

  TOOLS.roi = function () {
    const p = page('Доходность для инвестора', 'Сезонная аренда в городе ' + cfg.agency.city + ' против банковского вклада.',
      moneyInput('r-price', 'Стоимость квартиры', { placeholder: '8 000 000' }) +
      '<div class="row2">' + moneyInput('r-down', 'Свои деньги', { hint: 'Если в ипотеку — сколько вкладываете' }) +
      moneyInput('r-renov', 'Ремонт и мебель', { value: 0 }) + '</div>' +
      moneyInput('r-exp', 'Расходы в месяц', { value: 5000, hint: 'Коммуналка, уборка, обслуживание' }));
    p.btn.textContent = 'Посчитать доходность';
    onSubmit(p, async () => {
      const price = num($('r-price').value);
      if (!price || price < 1000000) { $('r-price').setAttribute('aria-invalid', 'true'); throw new Error('Укажите стоимость — от 1 000 000 ₽'); }
      const body = { property_price: price, city: cfg.agency.city, down_payment: num($('r-down').value),
        renovation_budget: num($('r-renov').value) || 0, monthly_expenses: num($('r-exp').value) || 0, agency_id: AGENCY };
      const r = await api('/lm6/calculate', body);
      const better = r.vs_deposit.real_estate_advantage > 0;
      p.out.innerHTML = '<h2>Результат</h2><div class="card">' +
        '<div class="note" style="margin-top:0">Доходность от аренды в год</div><div class="big">' + String(r.roi_rental_only_pct).replace('.', ',') + ' %</div>' +
        '<div style="margin-top:8px"><span class="chip ' + (better ? 'chip--ok' : 'chip--warn') + '">' + esc(r.vs_deposit.verdict) + '</span></div>' +
        '<div style="margin-top:12px">' +
        '<div class="kv"><span>С ростом цены квартиры</span><span>' + String(r.roi_with_appreciation_pct).replace('.', ',') + ' % в год</span></div>' +
        '<div class="kv"><span>Чистый доход от аренды</span><span>' + rub(r.rental_income.annual_net) + ' в год</span></div>' +
        '<div class="kv"><span>Окупаемость</span><span>' + (r.payback_years >= 999 ? 'не окупается' : String(r.payback_years).replace('.', ',') + ' лет') + '</span></div>' +
        '<div class="kv"><span>Аренда в месяц сезона</span><span>' + rub(r.assumptions.monthly_rental_estimate) + '</span></div>' +
        '<div class="kv"><span>Сезон и загрузка</span><span>' + String(r.assumptions.season_months).replace('.', ',') + ' мес., ' + r.assumptions.occupancy_pct + ' %</span></div>' +
        '<div class="kv"><span>Вклад под ' + String(r.vs_deposit.deposit_rate_pct).replace('.', ',') + ' %</span><span>' + rub(r.vs_deposit.deposit_annual_income) + ' в год</span></div>' +
        '</div><div class="note">' + esc(r.note) + '</div></div>';
      cta(p.out, 'Найти объект с такой доходностью', 'Менеджер подберёт квартиры под сдачу и посчитает доход по конкретным вариантам.',
        (c) => api('/lm6/subscribe', Object.assign({ calc_data: body }, c)));
    });
  };

  TOOLS.districts = function () {
    const p = page('Район под образ жизни', 'Три района ' + cfg.agency.city + ', которые подходят именно вам.',
      select('d-scn', 'Для чего квартира', cfg.scenarios.map((s) => [s.key, s.label]), 'family') +
      moneyInput('d-budget', 'Бюджет', { hint: 'Необязательно' }));
    p.btn.textContent = 'Подобрать районы';
    onSubmit(p, async () => {
      const body = { city: cfg.agency.city, scenario: $('d-scn').value, budget_max: num($('d-budget').value), agency_id: AGENCY };
      const r = await api('/lm4/districts', body);
      const ds = r.districts || [];
      p.out.innerHTML = '<h2>Подходящие районы</h2>' + (r.city_overview ? '<p class="lead">' + esc(r.city_overview) + '</p>' : '') +
        (ds.length ? ds.map((d) => '<div class="card"><div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">' +
          '<strong>' + esc(d.name) + '</strong>' + (d.price_range ? '<span class="chip">' + esc(d.price_range) + '</span>' : '') + '</div>' +
          (d.why_fits ? '<div style="margin-top:6px">' + esc(d.why_fits) + '</div>' : '') +
          list('Плюсы', d.pros) + list('Минусы', d.cons) + '</div>').join('')
          : '<div class="msg msg--info">По этому городу данных о районах пока нет — менеджер расскажет лично.</div>') +
        (r.recommendation ? '<div class="note">' + esc(r.recommendation) + '</div>' : '');
      cta(p.out, 'Показать квартиры в этих районах', 'Менеджер пришлёт варианты в подходящих районах под ваш бюджет.',
        (c) => api('/lm4/subscribe', Object.assign({ city: body.city, scenario: body.scenario, budget_max: body.budget_max }, c)));
    });
  };

  TOOLS.checker = function () {
    const p = page('Проверка объявления', 'Разберём чужое объявление: сильные стороны, слабые места и риски сделки.',
      '<div class="field"><label for="k-url">Ссылка на объявление</label><input type="url" id="k-url" placeholder="https://"></div>' +
      '<div class="field"><label for="k-text">Или текст объявления</label><textarea id="k-text" placeholder="Скопируйте описание целиком"></textarea>' +
      '<div class="hint">С ЦИАН, Авито и ДомКлик ссылку открыть нельзя — вставьте текст.</div></div>');
    p.btn.textContent = 'Проверить';
    onSubmit(p, async () => {
      const body = { listing_url: $('k-url').value.trim() || null, listing_text: $('k-text').value.trim() || null, city: cfg.agency.city, agency_id: AGENCY };
      if (!body.listing_url && !body.listing_text) throw new Error('Вставьте ссылку или текст объявления');
      if (body.listing_text && body.listing_text.length < 50) throw new Error('Текст слишком короткий — нужно описание целиком');
      const r = await api('/lm3/analyze', body);
      if (r.needs_manual_text) {
        p.out.innerHTML = '<div class="msg msg--info">' + esc(r.message || 'Этот сайт не даёт открыть объявление. Скопируйте текст в поле выше.') + '</div>';
        $('k-text').focus();
        return;
      }
      const a = r.analysis || {};
      const price = { fair: ['chip--ok', 'Цена в рынке'], overpriced: ['chip--warn', 'Цена выше рынка'], underpriced: ['chip--warn', 'Цена ниже рынка — стоит выяснить почему'] }[a.market_price_assessment];
      p.out.innerHTML = '<h2>Что мы видим</h2><div class="card">' +
        (price ? '<span class="chip ' + price[0] + '">' + price[1] + '</span>' : '') +
        list('Сильные стороны', a.strengths) + list('Слабые места', a.weaknesses) + list('Риски', a.risks) +
        (!(a.strengths || []).length && !(a.risks || []).length ? '<div class="msg msg--info">Подробный разбор сделает менеджер.</div>' : '') +
        '<div class="note">Это автоматический разбор по тексту объявления, не юридическая проверка.</div></div>';
      cta(p.out, 'Проверить объект по документам', 'Менеджер проверит собственника, обременения и историю объекта.',
        (c) => api('/lm3/subscribe', Object.assign({ listing_url: body.listing_url, listing_text: body.listing_text, city: body.city }, c)));
    });
  };

  // The report and the selection come together with the request: they are the reward.
  TOOLS.market = function () {
    const segs = [['family', 'Семья'], ['investor', 'Инвестиция'], ['relocant', 'Переезд на ПМЖ'], ['remote_worker', 'Удалённая работа'], ['senior', 'Жизнь на пенсии']];
    const p = page('Отчёт по рынку', 'Цены, спрос и подводные камни ' + cfg.agency.city + ' под ваш бюджет и цель.',
      select('k-seg', 'Для чего покупаете', segs, 'family') +
      '<div class="row2">' + moneyInput('k-min', 'Бюджет от') + moneyInput('k-max', 'Бюджет до') + '</div>' +
      '<div class="sub" style="margin:4px 0 10px">Куда прислать отчёт</div>' + contactFields('mk'));
    p.btn.textContent = 'Получить отчёт';
    onSubmit(p, async () => {
      const contacts = readContacts('mk');
      if (contacts.error) throw new Error(contacts.error);
      const body = Object.assign({ agency_id: AGENCY, city: cfg.agency.city, segment: $('k-seg').value,
        budget_min: num($('k-min').value), budget_max: num($('k-max').value), goal: $('k-seg').value === 'investor' ? 'invest' : 'own' }, contacts, utm());
      const r = await api('/lm5/subscribe', body);
      const rep = r.report || {};
      const trend = { growing: ['chip--ok', 'Цены растут'], rising: ['chip--ok', 'Цены растут'], stable: ['', 'Цены стабильны'], falling: ['chip--warn', 'Цены снижаются'], declining: ['chip--warn', 'Цены снижаются'] }[rep.market_trend];
      const demand = { high: ['chip--ok', 'Спрос высокий'], medium: ['', 'Спрос средний'], low: ['chip--warn', 'Спрос низкий'] }[rep.demand_level];
      p.form.outerHTML = '<div class="card">' + thanks(r) + '</div>';
      p.out.innerHTML = '<h2>Ваш отчёт</h2><div class="card">' +
        (trend ? '<span class="chip ' + trend[0] + '">' + trend[1] + '</span> ' : '') + (demand ? '<span class="chip ' + demand[0] + '">' + demand[1] + '</span>' : '') +
        (rep.summary ? '<p>' + esc(rep.summary) + '</p>' : '') +
        (rep.price_range_max ? '<div class="kv"><span>Цены в сегменте</span><span>' + rub(rep.price_range_min) + ' – ' + rub(rep.price_range_max) + '</span></div>' : '') +
        list('Что сейчас продаётся', rep.typical_objects) + list('Возможности', rep.opportunities) + list('Риски', rep.risks) +
        (rep.recommended_action ? '<div class="sub">Что делать</div><div>' + esc(rep.recommended_action) + '</div>' : '') +
        '<div class="note">Оценки — ориентир, актуальные варианты пришлёт менеджер.</div></div>';
    });
  };

  TOOLS.finder = function () {
    const goals = [['own', 'Жить самим'], ['invest', 'Вложить деньги'], ['rent_out', 'Сдавать'], ['relocate', 'Переезд на ПМЖ'], ['children', 'Для детей']];
    const p = page('Подбор квартиры', 'Скажите бюджет и цель — покажем подходящие варианты из каталога агентства.',
      select('q-goal', 'Для чего квартира', goals, 'own') + moneyInput('q-budget', 'Бюджет до', { placeholder: '8 000 000' }) +
      '<div class="sub" style="margin:4px 0 10px">Ваши контакты</div>' + contactFields('fd'));
    p.btn.textContent = 'Подобрать варианты';
    onSubmit(p, async () => {
      const budget = num($('q-budget').value);
      if (!budget) { $('q-budget').setAttribute('aria-invalid', 'true'); throw new Error('Укажите бюджет'); }
      const contacts = readContacts('fd');
      if (contacts.error) throw new Error(contacts.error);
      p.out.innerHTML = '<div class="msg msg--info">Подбираем варианты, это займёт до минуты…</div>';
      const r = await api('/lm1/result', Object.assign({ agency_id: AGENCY, goal: $('q-goal').value, budget_max: budget }, contacts, utm()));
      p.form.outerHTML = '<div class="card">' + thanks(r) + '</div>';
      const ms = r.matches || [];
      p.out.innerHTML = ms.length ? '<h2>Подходящие варианты</h2>' + ms.map((m) => '<div class="card">' +
          '<strong>' + esc(m.title) + '</strong>' + (m.price ? '<div class="big" style="font-size:22px;margin-top:4px">' + rub(m.price) + '</div>' : '') +
          (m.pitch ? '<div style="margin-top:6px">' + esc(m.pitch) + '</div>' : '') + list('Почему подходит', m.highlights) + '</div>').join('')
        : (r.is_duplicate ? '' : '<div class="msg msg--info">Готовых вариантов в каталоге под этот бюджет сейчас нет — менеджер подберёт вручную.</div>');
    });
  };

  function index() {
    app.innerHTML = '<h1>Инструменты для покупателя</h1><p class="lead">Посчитайте, сравните и получите подборку от агентства «' + esc(cfg.agency.name) + '».</p>' +
      (cfg.tools.length ? '<div class="tools">' + cfg.tools.map((t) => '<a class="tool" href="/lm/' + esc(AGENCY) + '/' + t.slug + location.search + '">' +
        '<div class="tool__t">' + esc(t.title) + '</div><div class="tool__d">' + esc(t.description) + '</div></a>').join('') + '</div>'
        : '<div class="msg msg--info">Сейчас инструменты недоступны.</div>');
  }

  async function boot() {
    try {
      cfg = await api('/config/' + encodeURIComponent(AGENCY));
    } catch (e) {
      app.innerHTML = '<h1>Страница не найдена</h1><p class="lead">Проверьте ссылку или спросите её у агентства.</p>';
      $('brand').textContent = 'REIP';
      return;
    }
    $('brand').textContent = cfg.agency.name;
    $('brand').href = '/lm/' + AGENCY + location.search;
    $('city').textContent = cfg.agency.city;
    $('foot').innerHTML = '© ' + esc(cfg.agency.name) + ' · <a href="' + esc(cfg.privacy_url) + '" target="_blank" rel="noopener">Политика конфиденциальности</a>';
    const tool = cfg.tools.find((t) => t.slug === TOOL);
    if (TOOL && tool && TOOLS[TOOL]) {
      document.title = tool.title + ' — ' + cfg.agency.name;
      TOOLS[TOOL]();
    } else if (TOOL) {
      app.innerHTML = '<h1>Инструмент недоступен</h1><p class="lead">Агентство его сейчас не показывает.</p>' +
        (cfg.tools.length ? '<a class="btn btn--ghost" href="/lm/' + esc(AGENCY) + location.search + '">Другие инструменты</a>' : '');
    } else {
      document.title = 'Инструменты — ' + cfg.agency.name;
      index();
    }
  }

  boot();
})();

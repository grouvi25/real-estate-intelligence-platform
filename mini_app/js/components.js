// Mini App UI helpers + primitives. Global `UI`. No bundler.
//
// Two rules the screens rely on:
//   * a skeleton has the shape of the thing it stands in for, so the layout
//     does not jump when the data lands;
//   * anything that can fail renders a state that says what to do next —
//     an empty with an action, an error with «Повторить».
const UI = (() => {
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const money = (v) => (v == null || isNaN(v))
    ? '—' : Math.round(v).toLocaleString('ru-RU') + ' ₽';

  // 7 900 000 ₽ is hard to scan in a list; 7,9 млн is not.
  const moneyShort = (v) => {
    if (v == null || isNaN(v)) return '—';
    if (v >= 1e6) {
      const m = v / 1e6;
      return (m >= 10 ? Math.round(m) : Number(m.toFixed(1))).toLocaleString('ru-RU') + ' млн ₽';
    }
    if (v >= 1e3) return Math.round(v / 1e3).toLocaleString('ru-RU') + ' тыс ₽';
    return money(v);
  };

  const initials = (name) => {
    const p = String(name || '?').trim().split(/\s+/);
    return ((p[0] || '?')[0] + (p[1] ? p[1][0] : '')).toUpperCase();
  };

  // «2 часа назад» beats an ISO timestamp when you are scanning a feed.
  const ago = (iso) => {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return 'только что';
    if (m < 60) return `${m} мин назад`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h} ч назад`;
    const d = Math.round(h / 24);
    if (d < 8) return `${d} дн назад`;
    return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
  };

  const dateTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  };

  // "1 срочная", "2 срочные", "5 срочных" — the app writes Russian, so it
  // declines. plural(n, ['срочная', 'срочные', 'срочных'])
  const plural = (n, forms) => {
    const a = Math.abs(n) % 100;
    const b = a % 10;
    if (a > 10 && a < 20) return forms[2];
    if (b > 1 && b < 5) return forms[1];
    if (b === 1) return forms[0];
    return forms[2];
  };
  const count = (n, forms) => `${n} ${plural(n, forms)}`;

  const icon = (n, cls) => Icons.svg(n, cls);

  // Skeletons ----------------------------------------------------------------
  const sk = (cls, style) => `<div class="skel ${cls || ''}"${style ? ` style="${style}"` : ''}></div>`;
  const skelCard = () =>
    `<div class="card">${sk('skel-line lg')}${sk('skel-line md')}${sk('skel-line sm')}</div>`;
  const skelList = (n = 5) => Array.from({ length: n }, () =>
    `<div class="card"><div class="row">${sk('skel-sq')}` +
    `<div class="grow">${sk('skel-line md')}${sk('skel-line sm')}</div></div></div>`
  ).join('');
  // A signal card: chips on top, three lines of text.
  const skelFeed = (n = 4) => Array.from({ length: n }, () =>
    `<div class="card"><div class="row gap-2">${sk('skel-chip', 'width:58px')}${sk('skel-chip')}</div>` +
    `<div class="mt-3">${sk('skel-line lg')}${sk('skel-line lg')}${sk('skel-line md')}</div></div>`
  ).join('');
  const skelStats = () =>
    `<div class="stats">${Array.from({ length: 4 }, () =>
      `<div class="stat">${sk('skel-sq', 'width:36px;height:36px')}` +
      `<div class="grow">${sk('skel-line md')}${sk('skel-line sm')}</div></div>`
    ).join('')}</div>`;
  const skelTiles = (n = 4) =>
    `<div class="tiles">${Array.from({ length: n }, () =>
      `<div class="tile">${sk('skel-sq', 'width:34px;height:34px')}${sk('skel-line md')}${sk('skel-line sm')}</div>`
    ).join('')}</div>`;
  const skelForm = (n = 3) =>
    `<div class="card">${Array.from({ length: n }, () =>
      `<div class="field">${sk('skel-line sm')}${sk('', 'height:44px;border-radius:12px')}</div>`
    ).join('')}${sk('skel-btn', 'margin-top:12px')}</div>`;

  // Chips --------------------------------------------------------------------
  const URG = { hot: ['hot', 'flame', 'Горячий'], warm: ['warm', 'clock', 'Тёплый'], cold: ['cold', 'clock', 'Холодный'] };
  const urgencyChip = (u) => {
    const d = URG[u]; if (!d) return '';
    return `<span class="chip chip--${d[0]}">${icon(d[1])}${d[2]}</span>`;
  };
  const STATUS_RU = {
    new: 'Новый', in_progress: 'В работе', qualified: 'Квалифицирован', deal: 'Сделка',
    rejected: 'Отклонён', archived: 'Архив', referred: 'Передан',
    active: 'Активен', reserved: 'Бронь', sold: 'Продан', draft: 'Черновик',
    // Reply states. 'none' used to render as "—": a freshly collected signal has
    // no reply state, and since that is exactly what the triage queue is full
    // of, the most common chip on the busiest screen was a dash.
    none: 'Без ответа', draft_reply: 'Черновик', pending: 'В очереди', sent: 'Отправлен',
    replied: 'Отвечен', escalated: 'Старшему', dismissed: 'Не наш',
    failed: 'Ошибка', skipped: 'Пропущен', suggested: 'Предложен', accepted: 'Принят', presented: 'Показан',
    sandbox: 'Песочница', paused: 'Остановлен', blocked: 'Заблокирован', dead: 'Мёртвый',
  };
  const SEG_RU = {
    family: 'Семья', investor: 'Инвестор', relocant: 'Переезд', remote_worker: 'Удалёнка',
    senior: 'Взрослые', alternative: 'Альтернатива', student_parent: 'Студ.+родители', not_buyer: 'Не покупатель',
  };
  const TASK_RU = {
    call: 'Звонок', document: 'Документы', showing: 'Показ', follow_up: 'Напоминание',
    escalation: 'Эскалация', meeting: 'Встреча', reply: 'Ответ', other: 'Задача',
  };
  const CHANNEL_RU = { telegram: 'Telegram', vk: 'ВКонтакте', max: 'MAX', forum: 'Форум' };
  const GEO_RU = { base: 'основной', sales: 'продажи', partner: 'партнёрский', watch: 'наблюдение' };
  // utm_source values as they are stored, in words a manager recognises.
  const UTM_RU = {
    telegram_bot: 'Телеграм-бот', bot_deeplink: 'Ссылка из бота', vk: 'ВКонтакте',
    telegram: 'Telegram', max: 'MAX', manual: 'Вручную', incoming_call: 'Входящий звонок',
    referral: 'Рекомендация', lm2_mortgage: 'Ипотечный калькулятор', lm6_roi: 'ROI-калькулятор',
  };
  const STATUS_TONE = {
    deal: 'success', qualified: 'accent', active: 'success', sent: 'success', accepted: 'success',
    rejected: 'danger', failed: 'danger', blocked: 'danger', dead: 'danger',
  };
  const statusChip = (s) => {
    const tone = STATUS_TONE[s];
    return `<span class="chip${tone ? ` chip--${tone}` : ''}">${esc(STATUS_RU[s] || s || '—')}</span>`;
  };
  const seg = (s) => SEG_RU[s] || s || '';
  const taskType = (t) => TASK_RU[t] || t || 'Задача';
  const channel = (c) => CHANNEL_RU[c] || c || '';
  const geoType = (t) => GEO_RU[t] || t || '';
  const utmSource = (u) => UTM_RU[u] || u || 'Без метки';
  const channelChip = (c) => c
    ? `<span class="chip">${icon(c === 'vk' ? 'signals' : 'send')}${esc(channel(c))}</span>` : '';

  const scoreEl = (v) => {
    if (v == null) return '<span class="score score--lo"><b>—</b></span>';
    const k = v >= 70 ? 'hi' : v >= 45 ? 'mid' : 'lo';
    return `<span class="score score--${k}"><b>${v}</b><span>/100</span></span>`;
  };

  const list = (items, tmpl, emptyOpts) =>
    (items && items.length) ? items.map(tmpl).join('') : empty(emptyOpts);

  // An empty screen should say what to do about it, not just that it is empty.
  const empty = (o) => {
    o = o || {};
    const action = o.actionLabel
      ? `<button class="btn" id="${o.actionId || 'empty-action'}">${o.actionIcon ? icon(o.actionIcon) : ''}${esc(o.actionLabel)}</button>`
      : '';
    return `<div class="empty">${icon(o.icon || 'file')}<div class="empty__t">${esc(o.title || 'Пусто')}</div>` +
      (o.sub ? `<div class="empty__s">${esc(o.sub)}</div>` : '') + action + '</div>';
  };
  const errorState = (msg, retryId) =>
    `<div class="empty">${icon('close')}<div class="empty__t err-text">Не удалось загрузить</div>` +
    `<div class="empty__s">${esc(msg || 'Проверьте соединение')}</div>` +
    `<button class="btn btn--secondary" id="${retryId || 'retry'}">${icon('refresh')} Повторить</button></div>`;

  // Wraps a screen body: renders skeleton, awaits, renders, and turns a failure
  // into a retry instead of a blank screen.
  const load = async (skeleton, fetcher, renderer) => {
    render(skeleton);
    try {
      const data = await fetcher();
      renderer(data);
    } catch (e) {
      render(errorState(e && e.message), () => {
        const b = document.getElementById('retry');
        if (b) b.onclick = () => load(skeleton, fetcher, renderer);
      });
    }
  };

  // A city field that suggests instead of trusting the typing. Every screen that
  // wanted a city asked for it as free text, so the same town arrived as
  // «Геленджик», «геленжик» and «г. Геленджик» — three places as far as the
  // database was concerned. Picking from a list makes the name canonical.
  //
  // The list appears under the field rather than in a <datalist>: native
  // datalists are unreliable inside Telegram's webview, and this way the region
  // can be shown beside the name — there is more than one Красноармейск.
  const cityField = (id, { label = 'Город', value = '', hint = '' } = {}) => `
    <div class="field cityfield">
      <label for="${id}">${esc(label)}</label>
      <input id="${id}" autocomplete="off" value="${esc(value || '')}"
             placeholder="начните вводить название">
      <div class="cityfield__list hidden" id="${id}-list"></div>
      ${hint ? `<div class="field__hint">${esc(hint)}</div>` : ''}
    </div>`;

  // Wires a field built by `cityField`. Returns nothing; the input's value is
  // the answer, exactly as before, so callers read it the way they always did.
  const bindCityField = (id) => {
    const input = document.getElementById(id);
    const list = document.getElementById(`${id}-list`);
    if (!input || !list) return;
    let timer = null;
    let last = '';

    const hide = () => { list.classList.add('hidden'); list.innerHTML = ''; };

    const show = (cities) => {
      if (!cities.length) { hide(); return; }
      list.innerHTML = cities.map((c) => `
        <button type="button" class="cityfield__opt" data-city="${esc(c.name)}">
          ${esc(c.name)}${c.region ? `<span class="cityfield__where">${esc(c.region)}</span>` : ''}
        </button>`).join('');
      list.classList.remove('hidden');
      list.querySelectorAll('[data-city]').forEach((b) => {
        b.onclick = () => { input.value = b.getAttribute('data-city'); hide(); };
      });
    };

    const ask = async () => {
      const q = input.value.trim();
      if (q.length < 2 || q === last) { if (q.length < 2) hide(); return; }
      last = q;
      try {
        const r = await API.suggestCities(q);
        // The answer may arrive after more typing; only draw it if it still fits.
        if (input.value.trim() === q) show((r && r.cities) || []);
      } catch (e) { hide(); }
    };

    // Typing is faster than the network; asking on every keystroke would send a
    // billed request per letter.
    input.oninput = () => { clearTimeout(timer); timer = setTimeout(ask, 350); };
    input.onblur = () => setTimeout(hide, 150);   // let a click on an option land
  };

  const render = (html, wire) => {
    const v = document.getElementById('view');
    if (v) { v.innerHTML = html; v.scrollTop = 0; }
    if (typeof wire === 'function') wire();
  };

  // Disables a button for the duration of an action, so a double tap cannot
  // send two requests, and restores it on failure.
  const busy = async (btn, fn) => {
    if (!btn) return fn();
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    try {
      return await fn();
    } finally {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.innerHTML = label;
    }
  };

  const setHeader = (title, sub, opts) => {
    opts = opts || {};
    const h = document.getElementById('hdr');
    if (!h) return;
    const back = opts.back
      ? `<button class="header__btn" id="hdr-back" aria-label="Назад">${icon('back')}</button>` : '';
    const action = opts.actionIcon
      ? `<button class="header__btn" id="hdr-action" aria-label="${esc(opts.actionLabel || 'Действие')}">${icon(opts.actionIcon)}</button>` : '';
    h.innerHTML = `${back}<div class="header__l"><h1 class="header__title ellipsis">${esc(title)}</h1>` +
      (sub ? `<div class="header__sub ellipsis">${esc(sub)}</div>` : '') + `</div>${action}`;
    const b = document.getElementById('hdr-back');
    if (b) b.onclick = () => history.back();
    const a = document.getElementById('hdr-action');
    if (a && opts.onAction) a.onclick = opts.onAction;
  };

  let toastT = null;
  const toast = (msg) => {
    let t = document.getElementById('toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; document.body.appendChild(t); }
    t.textContent = msg;
    t.setAttribute('role', 'status');
    t.classList.remove('hidden');
    // Re-run the entrance so a second toast is visibly a second toast.
    t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.add('hidden'), 2400);
  };

  // Overlay sheet ------------------------------------------------------------
  const sheet = (title, bodyHtml, wire) => {
    let o = document.getElementById('overlay');
    if (!o) { o = document.createElement('div'); o.id = 'overlay'; o.className = 'overlay'; document.body.appendChild(o); }
    o.innerHTML =
      `<div class="sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">` +
      `<div class="sheet__grab"></div>` +
      `<div class="sheet__head"><div class="sheet__title">${esc(title)}</div>` +
      `<button class="header__btn" id="sheet-close" aria-label="Закрыть">${icon('close')}</button></div>` +
      `<div class="sheet__body">${bodyHtml}</div></div>`;
    o.classList.remove('hidden');
    const close = () => { o.classList.add('hidden'); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    document.getElementById('sheet-close').onclick = close;
    o.onclick = (e) => { if (e.target === o) close(); };
    if (typeof wire === 'function') wire(close);
    return close;
  };

  return {
    esc, money, moneyShort, initials, ago, dateTime, icon, plural, count,
    skelCard, skelList, skelFeed, skelStats, skelTiles, skelForm,
    urgencyChip, statusChip, seg, taskType, channel, channelChip, geoType, utmSource, scoreEl,
    list, empty, errorState, load, busy,
    render, setHeader, toast, sheet, cityField, bindCityField,
  };
})();

UI.docLinkSheet = function (title, doc, subtitle) {
  // The stored document needs the JWT, so fetch it and hand the browser a blob
  // URL; a bare href to pdf_url would open a 401.
  UI.sheet(title, `<p class="muted">${UI.esc(subtitle)}</p>${UI.skelCard()}`,
    async () => {
      const body = document.querySelector('.sheet__body');
      try {
        const url = await API.documentBlob(doc.key);
        body.innerHTML =
          `<p class="muted">${UI.esc(subtitle)}</p>
           <a class="btn btn--block" href="${url}" target="_blank" rel="noopener"
              download="${UI.esc(doc.key.split('/').pop())}">${UI.icon('file')} Открыть документ</a>`;
      } catch (e) {
        body.innerHTML = UI.errorState(e.message);
      }
    });
};

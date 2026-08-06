// Mini App UI helpers + primitives. Global `UI`. No bundler.
const UI = (() => {
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const money = (v) => (v == null || isNaN(v))
    ? '—' : Math.round(v).toLocaleString('ru-RU') + ' ₽';

  const initials = (name) => {
    const p = String(name || '?').trim().split(/\s+/);
    return ((p[0] || '?')[0] + (p[1] ? p[1][0] : '')).toUpperCase();
  };

  const icon = (n, cls) => Icons.svg(n, cls);

  // Skeletons ----------------------------------------------------------------
  const skelCard = () =>
    `<div class="card"><div class="skel skel-line lg"></div><div class="skel skel-line md"></div>` +
    `<div class="skel skel-line sm"></div></div>`;
  const skelList = (n = 5) => Array.from({ length: n }, () =>
    `<div class="card"><div class="row"><div class="skel" style="width:40px;height:40px;border-radius:12px"></div>` +
    `<div class="grow"><div class="skel skel-line md"></div><div class="skel skel-line sm"></div></div></div></div>`
  ).join('');
  const skelStats = () =>
    `<div class="stats">${Array.from({ length: 4 }, () =>
      `<div class="stat"><div class="skel" style="width:34px;height:34px;border-radius:10px"></div>` +
      `<div class="skel skel-line md" style="margin-top:10px"></div><div class="skel skel-line sm"></div></div>`
    ).join('')}</div>`;

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
    none: '—', draft_reply: 'Черновик', pending: 'В очереди', sent: 'Отправлен',
    failed: 'Ошибка', skipped: 'Пропущен', suggested: 'Предложен', accepted: 'Принят', presented: 'Показан',
  };
  const SEG_RU = {
    family: 'Семья', investor: 'Инвестор', relocant: 'Переезд', remote_worker: 'Удалёнка',
    senior: 'Взрослые', alternative: 'Альтернатива', student_parent: 'Студ.+родители', not_buyer: 'Не покупатель',
  };
  const statusChip = (s) => `<span class="chip">${esc(STATUS_RU[s] || s || '—')}</span>`;
  const seg = (s) => SEG_RU[s] || s || '';
  const scoreEl = (v) => {
    if (v == null) return '<span class="score score--lo"><b>—</b></span>';
    const k = v >= 70 ? 'hi' : v >= 45 ? 'mid' : 'lo';
    return `<span class="score score--${k}"><b>${v}</b><span>/100</span></span>`;
  };

  const list = (items, tmpl, emptyOpts) =>
    (items && items.length) ? items.map(tmpl).join('') : empty(emptyOpts);

  const empty = (o) => {
    o = o || {};
    return `<div class="empty">${icon(o.icon || 'file')}<div class="empty__t">${esc(o.title || 'Пусто')}</div>` +
      (o.sub ? `<div class="empty__s">${esc(o.sub)}</div>` : '') + '</div>';
  };
  const errorState = (msg) =>
    `<div class="empty">${icon('close')}<div class="empty__t err-text">Ошибка</div>` +
    `<div class="empty__s">${esc(msg || 'Не удалось загрузить')}</div></div>`;

  const render = (html, wire) => {
    const v = document.getElementById('view');
    if (v) { v.innerHTML = html; v.scrollTop = 0; }
    if (typeof wire === 'function') wire();
  };

  const setHeader = (title, sub, opts) => {
    opts = opts || {};
    const h = document.getElementById('hdr');
    if (!h) return;
    const back = opts.back ? `<button class="header__btn" id="hdr-back">${icon('back')}</button>` : '';
    const action = opts.actionIcon
      ? `<button class="header__btn" id="hdr-action" aria-label="action">${icon(opts.actionIcon)}</button>` : '';
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
    t.textContent = msg; t.classList.remove('hidden');
    clearTimeout(toastT); toastT = setTimeout(() => t.classList.add('hidden'), 2200);
  };

  // Overlay sheet ------------------------------------------------------------
  const sheet = (title, bodyHtml, wire) => {
    let o = document.getElementById('overlay');
    if (!o) { o = document.createElement('div'); o.id = 'overlay'; o.className = 'overlay'; document.body.appendChild(o); }
    o.innerHTML =
      `<div class="sheet"><div class="sheet__head"><div class="sheet__title">${esc(title)}</div>` +
      `<button class="header__btn" id="sheet-close">${icon('close')}</button></div>` +
      `<div class="sheet__body">${bodyHtml}</div></div>`;
    o.classList.remove('hidden');
    const close = () => o.classList.add('hidden');
    document.getElementById('sheet-close').onclick = close;
    o.onclick = (e) => { if (e.target === o) close(); };
    if (typeof wire === 'function') wire(close);
    return close;
  };

  return {
    esc, money, initials, icon, skelCard, skelList, skelStats,
    urgencyChip, statusChip, seg, scoreEl, list, empty, errorState,
    render, setHeader, toast, sheet,
  };
})();

UI.docLinkSheet = function (title, doc, subtitle) {
  // The stored document needs the JWT, so fetch it and hand the browser a blob
  // URL; a bare href to pdf_url would open a 401.
  UI.sheet(title, `<p class="muted">${subtitle}</p><div class="skel skel-line md"></div>`,
    async () => {
      const body = document.querySelector('.sheet__body');
      try {
        const url = await API.documentBlob(doc.key);
        body.innerHTML =
          `<p class="muted">${subtitle}</p>
           <a class="btn btn--block" href="${url}" target="_blank" rel="noopener"
              download="${UI.esc(doc.key.split('/').pop())}">Открыть документ</a>`;
      } catch (e) {
        body.innerHTML = UI.errorState(e.message);
      }
    });
};

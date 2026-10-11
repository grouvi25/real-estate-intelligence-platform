// Screens: Signals list + detail.
//
// A signal is a stranger's message, so the two questions a manager asks first
// are "how hot" and "how long has it been sitting". Both are on the card now,
// along with where it came from — an answer in VK is written differently from
// an answer in Telegram.
window.Screens = window.Screens || {};

const SIGNAL_FILTERS = [
  ['', 'Все'],
  ['hot', 'Горячие'],
  ['new', 'Новые'],
];

// ТЗ «Сигналы» v1.0, апгрейд B: категория по словам сообщения.
const SIGNAL_CATEGORIES = [['purchase', 'Покупка'], ['rental', 'Аренда'], ['news', 'Новости'],
  ['competitor', 'Конкуренты'], ['other', 'Прочее']];
const ALL_CATS = SIGNAL_CATEGORIES.map(([k]) => k);
const categoryLabel = (k) => (SIGNAL_CATEGORIES.find(([c]) => c === k) || [k, 'Прочее'])[1];

Screens.signals = async function () {
  let filter = '';
  // Which categories the list opens with is the agency's setting; the chips
  // change it for this visit only (the owner can save a new default).
  let prefs = { enabled_cats: ALL_CATS, competitor_names: [], competitors_found: [] };
  try { prefs = await API.signalFilter(); } catch (e) { /* defaults */ }
  let cats = [...prefs.enabled_cats];
  const isOwner = window._manager && window._manager.role === 'owner';

  function card(s) {
      return `
      <div class="card card--tap" data-go="signals/${s.id}">
        <div class="row row--wrap gap-2">
          ${UI.scoreEl(s.intent_score)}
          ${UI.urgencyChip(s.urgency)}
          ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}
          <span class="chip">${UI.esc(s.signal_category_label || categoryLabel(s.signal_category))}</span>
        </div>
        <div class="item__sub clamp-3 mt-3" style="font-size:var(--t-md);color:var(--fg)">
          ${UI.esc(s.raw_text || '')}
        </div>
        <div class="between mt-3">
          <span class="item__meta">
            ${UI.esc(UI.channel(s.origin_system || s.reply_channel))}
            ${s.created_at ? `<span class="dot"></span>${UI.esc(UI.ago(s.created_at))}` : ''}
          </span>
          <span class="item__chev">${UI.icon('chevron')}</span>
        </div>
      </div>`;
  }

  function draw() {
    const bar = `<div class="segmented" role="tablist">${SIGNAL_FILTERS.map(([v, l]) =>
      `<button class="segmented__opt${filter === v ? ' segmented__opt--active' : ''}" role="tab"
         aria-selected="${filter === v}" data-f="${v}">${l}</button>`).join('')}</div>`;

    const all = cats.length === ALL_CATS.length;
    const catBar = `<div class="chips mt-2" role="group" aria-label="Категории">
      <button class="chip chip--btn${all ? ' chip--accent' : ''}" data-cat="" aria-pressed="${all}">Все</button>
      ${SIGNAL_CATEGORIES.map(([k, l]) => {
        const on = !all && cats.includes(k);
        return `<button class="chip chip--btn${on ? ' chip--accent' : ''}" data-cat="${k}" aria-pressed="${on}">${l}</button>`;
      }).join('')}
      ${isOwner ? `<button class="chip chip--btn" id="cat-setup" aria-label="Настроить категории">${UI.icon('settings')}</button>` : ''}
    </div>`;
    const head = bar + catBar;
    const query = { limit: 50, ...(all ? {} : { category: cats.join(',') }) };

    UI.load(head + UI.skelFeed(), () => API.signals(query), (data) => {
      let items = data.signals || [];
      if (filter === 'hot') items = items.filter((s) => s.urgency === 'hot');
      if (filter === 'new') items = items.filter((s) => s.status === 'new');

      UI.render(head + UI.list(items, card, {
        icon: 'signals',
        title: filter || !all ? 'В этом фильтре пусто' : 'Пока нет сигналов',
        // An empty list looks the same whether the collector is off, or working
        // and finding nobody. Send the person where that question is answered
        // instead of to the source list, which shows neither.
        sub: filter || !all ? 'Снимите фильтр, чтобы увидеть остальные'
          : 'Робот читает чаты и оставляет только тех, кто похож на покупателя. '
            + 'Посмотрите, сколько он прочитал и что отсеял.',
        actionLabel: filter || !all ? null : 'Как идёт сбор',
        actionIcon: 'signals', actionId: 'to-sources',
      }), () => {
        Router.bindGo();
        document.querySelectorAll('[data-f]').forEach((b) => {
          b.onclick = () => { filter = b.getAttribute('data-f'); draw(); };
        });
        document.querySelectorAll('[data-cat]').forEach((b) => {
          b.onclick = () => {
            const k = b.getAttribute('data-cat');
            if (!k) cats = [...ALL_CATS];
            else if (cats.length === ALL_CATS.length) cats = [k];
            else if (cats.includes(k)) cats = cats.filter((c) => c !== k);
            else cats = [...cats, k];
            if (!cats.length) cats = [...ALL_CATS];
            draw();
          };
        });
        const setup = document.getElementById('cat-setup');
        if (setup) setup.onclick = openSetup;
        const a = document.getElementById('to-sources');
        if (a) a.onclick = () => Router.go('collection');
      });
    });
  }

  function openSetup() {
    UI.sheet('Категории сигналов', `
      <div class="item__sub" style="margin-top:0">Какие категории показывать при входе в «Сигналы»:</div>
      ${SIGNAL_CATEGORIES.map(([k, l]) => `
        <label class="row mt-2" style="gap:10px"><input type="checkbox" data-def="${k}"
          ${prefs.enabled_cats.includes(k) ? 'checked' : ''}><span>${l}</span></label>`).join('')}
      <div class="field mt-3"><label for="cat-comp">Конкуренты — по одному в строке</label>
        <textarea id="cat-comp" rows="4" placeholder="Этажи">${UI.esc((prefs.competitor_names || []).join('\n'))}</textarea></div>
      ${(prefs.competitors_found || []).length ? `<div class="item__meta">Ещё автопоиск нашёл на Яндекс.Картах:
        ${prefs.competitors_found.map(UI.esc).join(', ')}</div>` : ''}
      <div class="item__meta mt-2">Сообщение с названием конкурента попадает в «Конкуренты».</div>
      <button class="btn btn--block mt-3" id="cat-save">${UI.icon('check')} Сохранить</button>`, (close) => {
      const save = document.getElementById('cat-save');
      save.onclick = () => UI.busy(save, async () => {
        const chosen = [...document.querySelectorAll('[data-def]')].filter((x) => x.checked)
          .map((x) => x.getAttribute('data-def'));
        if (!chosen.length) { UI.toast('Выберите хотя бы одну категорию'); return; }
        const names = document.getElementById('cat-comp').value.split('\n')
          .map((x) => x.trim()).filter(Boolean);
        try {
          prefs = await API.updateSignalFilter({ enabled_cats: chosen, competitor_names: names });
          cats = [...prefs.enabled_cats];
          close();
          UI.toast('Сохранено');
          draw();
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
    });
  }

  UI.setHeader('Сигналы', 'Входящие намерения', {
    actionIcon: 'queue', actionLabel: 'Очередь ответов', onAction: () => Router.go('queue'),
  });
  draw();
};

Screens.signalDetail = async function (params) {
  UI.setHeader('Сигнал', '', { back: true });

  UI.load(UI.skelCard() + `<div class="mt-3">${UI.skelCard()}</div>`,
    () => API.signal(params.id), (s) => {
      const qualified = s.status === 'qualified';
      UI.render(`
        <div class="card">
          <div class="row row--wrap gap-2">
            ${UI.scoreEl(s.intent_score)}
            ${UI.urgencyChip(s.urgency)}
            ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}
            ${UI.statusChip(s.status)}
          </div>
          <p class="mt-3" style="margin-bottom:0;white-space:pre-wrap">${UI.esc(s.raw_text)}</p>
          <div class="field mt-3" style="margin-bottom:0"><label for="sig-cat">Категория</label>
            <select id="sig-cat">${SIGNAL_CATEGORIES.map(([k, l]) =>
              `<option value="${k}"${k === (s.signal_category || 'other') ? ' selected' : ''}>${l}</option>`).join('')}</select>
            <div class="field__hint">Определяется по словам сообщения; если ошиблась — поправьте.</div></div>
          <hr class="divider">
          <div class="between">
            <span class="item__meta">${UI.esc(s.source_name || UI.channel(s.source_type || s.reply_channel || s.origin_system))}
              ${s.created_at ? `<span class="dot"></span>${UI.esc(UI.dateTime(s.created_at))}` : ''}</span>
            ${s.signal_url ? `<a class="btn btn--ghost btn--sm" href="${UI.esc(s.signal_url)}"
               target="_blank" rel="noopener">${UI.icon('link')} Источник</a>` : ''}
          </div>
        </div>

        ${s.status === 'rejected' ? `
        <div class="card mt-3"><div class="item__sub">Отсеян фильтром${s.triage_reason ? ': ' + UI.esc(s.triage_reason) : ''}.
          Это не покупатель, поэтому сигнала нет ни в списке, ни в очереди ответов.</div></div>` : `
        <button class="btn btn--block mt-3" id="mk">
          ${UI.icon('leads')} ${qualified ? 'Лид создан — открыть' : 'Квалифицировать в лид'}
        </button>
        <button class="btn btn--secondary btn--block mt-2" id="toq">
          ${UI.icon('queue')} Ответить в очереди
        </button>`}`,
        () => {
          const sel = document.getElementById('sig-cat');
          sel.onchange = async () => {
            sel.disabled = true;
            try {
              await API.setSignalCategory(s.id, sel.value);
              s.signal_category = sel.value;
              UI.toast('Категория: ' + categoryLabel(sel.value));
            } catch (e) { UI.toast('Не удалось: ' + e.message); sel.value = s.signal_category || 'other'; }
            finally { sel.disabled = false; }
          };
          const toq = document.getElementById('toq');
          if (!toq) return;  // rejected: nothing to act on
          toq.onclick = () => Router.go('queue');
          const b = document.getElementById('mk');
          if (qualified) { b.onclick = () => Router.go(s.lead_id ? 'leads/' + s.lead_id : 'leads'); return; }
          b.onclick = () => UI.leadFromSignal(s.id);
        });
    });
};

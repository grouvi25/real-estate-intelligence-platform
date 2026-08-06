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

Screens.signals = async function () {
  let filter = '';

  function card(s) {
    const tone = s.urgency === 'hot' ? ' card--hot' : s.urgency === 'warm' ? ' card--warm' : '';
    return `
      <div class="card card--tap${tone}" data-go="signals/${s.id}">
        <div class="row row--wrap gap-2">
          ${UI.scoreEl(s.intent_score)}
          ${UI.urgencyChip(s.urgency)}
          ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}
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

    UI.load(bar + UI.skelFeed(), () => API.signals({ limit: 50 }), (data) => {
      let items = data.signals || [];
      if (filter === 'hot') items = items.filter((s) => s.urgency === 'hot');
      if (filter === 'new') items = items.filter((s) => s.status === 'new');

      UI.render(bar + UI.list(items, card, {
        icon: 'signals',
        title: filter ? 'В этом фильтре пусто' : 'Пока нет сигналов',
        sub: filter ? 'Снимите фильтр, чтобы увидеть остальные'
          : 'Появятся, когда источники начнут собирать',
        actionLabel: filter ? null : 'Настроить источники',
        actionIcon: 'settings', actionId: 'to-sources',
      }), () => {
        Router.bindGo();
        document.querySelectorAll('[data-f]').forEach((b) => {
          b.onclick = () => { filter = b.getAttribute('data-f'); draw(); };
        });
        const a = document.getElementById('to-sources');
        if (a) a.onclick = () => Router.go('sources');
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
        <div class="card${s.urgency === 'hot' ? ' card--hot' : ''}">
          <div class="row row--wrap gap-2">
            ${UI.scoreEl(s.intent_score)}
            ${UI.urgencyChip(s.urgency)}
            ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}
            ${UI.statusChip(s.status)}
          </div>
          <p class="mt-3" style="margin-bottom:0;white-space:pre-wrap">${UI.esc(s.raw_text)}</p>
          <hr class="divider">
          <div class="between">
            <span class="item__meta">${UI.esc(UI.channel(s.origin_system || s.reply_channel))}
              ${s.created_at ? `<span class="dot"></span>${UI.esc(UI.dateTime(s.created_at))}` : ''}</span>
            ${s.signal_url ? `<a class="btn btn--ghost btn--sm" href="${UI.esc(s.signal_url)}"
               target="_blank" rel="noopener">${UI.icon('link')} Источник</a>` : ''}
          </div>
        </div>

        <button class="btn btn--block mt-3" id="mk">
          ${UI.icon('leads')} ${qualified ? 'Лид создан — открыть' : 'Квалифицировать в лид'}
        </button>
        <button class="btn btn--secondary btn--block mt-2" id="toq">
          ${UI.icon('queue')} Ответить в очереди
        </button>`,
        () => {
          document.getElementById('toq').onclick = () => Router.go('queue');
          const b = document.getElementById('mk');
          if (qualified) { b.onclick = () => Router.go('leads'); return; }
          b.onclick = () => UI.busy(b, async () => {
            try {
              const r = await API.createLead(s.id, { consent_text: 'Согласие получено в чате (152-ФЗ)' });
              UI.toast(r && r.already_exists ? 'Лид уже был создан' : 'Лид создан');
              Router.go('leads');
            } catch (e) { UI.toast('Не удалось: ' + e.message); }
          });
        });
    });
};

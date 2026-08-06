// Screens: Signals list + detail.
window.Screens = window.Screens || {};

Screens.signals = async function () {
  UI.setHeader('Сигналы', 'Входящие намерения',
    { actionIcon: 'queue', onAction: () => Router.go('queue') });
  UI.render(UI.skelList());
  const data = await API.signals({ limit: 50 });
  UI.render(UI.list(data.signals, (s) => `
    <div class="card card--tap" data-go="signals/${s.id}">
      <div class="item">
        <div class="grow">
          <div class="row" style="gap:10px">${UI.scoreEl(s.intent_score)}${UI.urgencyChip(s.urgency)}
            ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}</div>
          <div class="item__sub" style="margin-top:8px">${UI.esc((s.raw_text || '').slice(0, 130))}</div>
        </div>
        <span class="item__chev">${UI.icon('chevron')}</span>
      </div>
    </div>`, { icon: 'signals', title: 'Пока нет сигналов', sub: 'Появятся после подключения источников' }),
    Router.bindGo);
};

Screens.signalDetail = async function (params) {
  UI.setHeader('Сигнал', '', { back: true });
  UI.render(UI.skelCard());
  let s;
  try { s = await API.signal(params.id); }
  catch (e) { UI.render(UI.empty({ icon: 'signals', title: 'Сигнал не найден' })); return; }

  UI.render(`
    <div class="card">
      <div class="row" style="gap:10px">${UI.scoreEl(s.intent_score)}${UI.urgencyChip(s.urgency)}
        ${s.segment ? `<span class="chip chip--accent">${UI.esc(UI.seg(s.segment))}</span>` : ''}
        ${UI.statusChip(s.status)}</div>
      <p style="margin:12px 0 0">${UI.esc(s.raw_text)}</p>
    </div>
    <button class="btn btn--block" id="mk" style="margin-top:12px">${UI.icon('leads')} ${s.status === 'qualified' ? 'Лид создан — открыть' : 'Квалифицировать в лид'}</button>
    <button class="btn btn--secondary btn--block" id="toq" style="margin-top:8px">${UI.icon('queue')} К очереди ответов</button>`,
    () => {
      document.getElementById('toq').onclick = () => Router.go('queue');
      const b = document.getElementById('mk');
      if (s.status === 'qualified') {
        b.onclick = () => Router.go('leads');
        return;
      }
      b.onclick = async () => {
        b.disabled = true;
        try {
          const r = await API.createLead(s.id, { consent_text: 'Согласие получено в чате (152-ФЗ)' });
          UI.toast(r && r.already_exists ? 'Лид уже был создан' : 'Лид создан'); Router.go('leads');
        } catch (e) { UI.toast('Ошибка: ' + e.message); b.disabled = false; }
      };
    });
};


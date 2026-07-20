// Screens: Signals list + detail. TZ section 30.
window.Screens = window.Screens || {};

Screens.signals = async function () {
  UI.setHeader('Сигналы', 'Входящие намерения');
  UI.render(UI.spinner());
  const data = await API.signals({ limit: 50 });
  const body = UI.list(data.signals, (s) => `
    <div class="card" onclick="Router.go('signals/${s.id}')">
      <div class="row">
        <span class="score">${s.intent_score == null ? '—' : s.intent_score}</span>
        ${UI.urgencyBadge(s.urgency)}
      </div>
      <div class="stack">
        <div>${UI.esc((s.raw_text || '').slice(0, 120))}</div>
        <div class="muted">${UI.esc(s.segment || '')} · ${UI.esc(s.status)}</div>
      </div>
    </div>`, 'Пока нет сигналов');
  UI.render(body);
};

Screens.signalDetail = async function (params) {
  UI.setHeader('Сигнал', '');
  UI.render(UI.spinner());
  // No single-signal GET; fetch the list and find it (small volumes in-app).
  const data = await API.signals({ limit: 200 });
  const s = (data.signals || []).find((x) => x.id === params.id);
  if (!s) { UI.render(UI.empty('Сигнал не найден')); return; }
  const html = `
    <div class="card">
      <div class="row"><span class="score">Интент: ${s.intent_score == null ? '—' : s.intent_score}</span>
        ${UI.urgencyBadge(s.urgency)}</div>
      <p>${UI.esc(s.raw_text)}</p>
      <div class="muted">${UI.esc(s.segment || '')} · ${UI.esc(s.status)}</div>
    </div>
    <button class="btn block" id="mk-lead">Квалифицировать в лид</button>
    <button class="btn secondary block" onclick="Router.go('queue')">К очереди ответов</button>
  `;
  UI.render(html, () => {
    const btn = document.getElementById('mk-lead');
    if (btn) btn.onclick = async () => {
      btn.disabled = true;
      try {
        await API.createLead(s.id, { consent_text: 'Согласие получено в чате (152-ФЗ)' });
        UI.toast('Лид создан');
        Router.go('leads');
      } catch (e) { UI.toast('Ошибка: ' + e.message); btn.disabled = false; }
    };
  });
};

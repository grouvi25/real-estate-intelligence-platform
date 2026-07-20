// Screens: Leads list + detail (with matches & feedback). TZ section 30.
window.Screens = window.Screens || {};

Screens.leads = async function () {
  UI.setHeader('Лиды', '');
  UI.render(UI.spinner());
  const data = await API.leads({ limit: 50 });
  const body = UI.list(data.leads, (l) => `
    <div class="card" onclick="Router.go('leads/${l.id}')">
      <div class="row">
        <strong>${UI.esc(l.name || 'Без имени')}</strong>
        ${UI.urgencyBadge(l.urgency)}
      </div>
      <div class="muted">${UI.esc(l.segment || '')} · ${UI.esc(l.status)} ·
        ${UI.money(l.budget_max)}</div>
    </div>`, 'Пока нет лидов');
  UI.render(body);
};

Screens.leadDetail = async function (params) {
  UI.setHeader('Лид', '');
  UI.render(UI.spinner());
  const l = await API.lead(params.id);
  const matches = UI.list(l.matches, (m) => `
    <div class="card">
      <div class="row"><strong>${UI.esc(m.title)}</strong><span class="score">${m.match_score}%</span></div>
      <div class="price">${UI.money(m.price)}</div>
      <div class="muted">${UI.esc(m.pitch || '')}</div>
      <div class="row" style="margin-top:8px">
        <button class="btn secondary" data-acc="${m.property_id}">Подходит</button>
        <button class="btn secondary" data-rej="${m.property_id}">Отклонить</button>
      </div>
    </div>`, 'Нет подобранных объектов');
  const html = `
    <div class="card">
      <h3>${UI.esc(l.name || 'Без имени')}</h3>
      <div class="stack">
        <div>${UI.esc(l.phone || '')}</div>
        <div class="muted">${UI.esc(l.segment || '')} · ${UI.esc(l.purchase_goal || '')}</div>
        <div class="muted">Бюджет: ${UI.money(l.budget_min)} – ${UI.money(l.budget_max)}</div>
        <div class="muted">Статус: ${UI.esc(l.status)}</div>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn" data-qual>Квалифицирован</button>
        <button class="btn secondary" data-arch>В архив</button>
      </div>
    </div>
    <h3 style="margin:12px 0 6px">Подборка</h3>
    ${matches}
  `;
  UI.render(html, () => {
    const q = document.querySelector('[data-qual]');
    if (q) q.onclick = async () => {
      await API.setLeadStatus(l.id, { status: 'qualified' });
      UI.toast('Статус обновлён'); Router.resolve();
    };
    const a = document.querySelector('[data-arch]');
    if (a) a.onclick = async () => {
      await API.setLeadStatus(l.id, { status: 'archived' });
      UI.toast('В архиве'); Router.go('leads');
    };
    document.querySelectorAll('[data-acc]').forEach((b) => {
      b.onclick = async () => {
        await API.matchFeedback(l.id, b.getAttribute('data-acc'), { status: 'accepted' });
        UI.toast('Отмечено как подходит');
      };
    });
    document.querySelectorAll('[data-rej]').forEach((b) => {
      b.onclick = async () => {
        await API.matchFeedback(l.id, b.getAttribute('data-rej'),
          { status: 'rejected', rejection_category: 'other' });
        UI.toast('Отклонено'); Router.resolve();
      };
    });
  });
};

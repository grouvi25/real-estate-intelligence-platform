// Screens: Analytics (funnel + source ROI + managers) & Settings. TZ section 30.
window.Screens = window.Screens || {};

Screens.analytics = async function () {
  UI.setHeader('Аналитика', 'Воронка и источники');
  UI.render(UI.spinner());
  const [funnel, roi] = await Promise.all([API.funnel(), API.sourceRoi()]);
  const stages = funnel.stages || {};
  const total = funnel.total || 1;
  const bar = (label, n) => {
    const pct = Math.max(4, Math.round((n / total) * 100));
    return `<div class="lbl"><span>${label}</span><span>${n}</span></div>
            <div class="bar" style="width:${pct}%"></div>`;
  };
  const sources = UI.list(roi.sources, (s) => `
    <div class="card">
      <div class="row"><strong>${UI.esc(s.source)}</strong><span class="muted">${s.leads} лид.</span></div>
      <div class="row"><span class="muted">Сделки: ${s.deals_won}</span>
        <span class="price">${UI.money(s.commission)}</span></div>
      <div class="muted">Конверсия: ${s.conversion_pct}%</div>
    </div>`, 'Нет данных по источникам');
  const html = `
    <div class="card funnel">
      <h3>Воронка</h3>
      ${bar('Новые', stages.new || 0)}
      ${bar('В работе', stages.in_progress || 0)}
      ${bar('Квалифиц.', stages.qualified || 0)}
      ${bar('Сделки', stages.deal || 0)}
      <div class="muted" style="margin-top:6px">Общая конверсия:
        ${(funnel.conversion && funnel.conversion.overall) || 0}%</div>
    </div>
    <h3 style="margin:12px 0 6px">Источники (ROI)</h3>
    ${sources}
  `;
  UI.render(html);
};

Screens.settings = async function () {
  UI.setHeader('Профиль', '');
  const platform = (window.PlatformSDK && PlatformSDK.platform) || 'web';
  const user = (window.PlatformSDK && PlatformSDK.user) || {};
  const html = `
    <div class="card">
      <h3>${UI.esc(user.first_name || 'Менеджер')}</h3>
      <div class="muted">Платформа: ${UI.esc(platform)}</div>
      <div class="muted">Агентство: ${UI.esc(api.agencyId || '—')}</div>
    </div>
    <button class="btn secondary block" id="logout">Выйти</button>
  `;
  UI.render(html, () => {
    document.getElementById('logout').onclick = () => {
      try { localStorage.removeItem('jwt_token'); } catch (e) { /* ignore */ }
      location.reload();
    };
  });
};

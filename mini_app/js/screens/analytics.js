// Screens: Analytics + Settings/Owner area.
window.Screens = window.Screens || {};

Screens.analytics = async function () {
  UI.setHeader('Аналитика', 'Воронка и источники');
  UI.render(UI.skelCard() + UI.skelList(3));
  const [funnel, roi] = await Promise.all([API.funnel(), API.sourceRoi()]);

  const total = funnel.total || 1;
  const bar = (label, n) => {
    const pct = total ? Math.max(3, Math.round((n / total) * 100)) : 0;
    return `<div class="funnel__row"><div class="funnel__lbl"><span>${label}</span><b>${n}</b></div>
      <div class="funnel__track"><div class="funnel__bar" style="width:${pct}%"></div></div></div>`;
  };
  const st = funnel.stages || {};
  const conv = (funnel.conversion && funnel.conversion.overall) || 0;

  const sources = UI.list(roi.sources, (s) => `
    <div class="card">
      <div class="between"><span class="item__title">${UI.esc(s.source)}</span>
        <span class="chip chip--accent">${s.leads} лид.</span></div>
      <div class="between" style="margin-top:8px">
        <span class="muted">Сделки: <b style="color:var(--fg)">${s.deals_won}</b> · конв. ${s.conversion_pct}%</span>
        <span class="price">${UI.money(s.commission)}</span></div>
    </div>`, { icon: 'analytics', title: 'Нет данных по источникам' });

  UI.render(`
    <div class="card">
      <div class="between"><span class="card__title">Воронка</span>
        <span class="chip chip--success">Конверсия ${conv}%</span></div>
      <div style="margin-top:10px">
        ${bar('Новые', st.new || 0)}${bar('В работе', st.in_progress || 0)}
        ${bar('Квалифицированы', st.qualified || 0)}${bar('Сделки', st.deal || 0)}
      </div>
    </div>
    <div class="section-title">Источники · ROI</div>
    ${sources}`);
};

Screens.settings = async function () {
  UI.setHeader('Профиль', '', { back: true });
  const platform = (window.PlatformSDK && PlatformSDK.platform) || 'web';
  const user = (window.PlatformSDK && PlatformSDK.user) || {};
  const isOwner = true; // owner-only extras are safe; endpoint is agency-scoped

  UI.render(`
    <div class="card">
      <div class="item">
        <div class="avatar">${UI.esc(UI.initials(user.first_name || 'M'))}</div>
        <div class="grow"><div class="card__title">${UI.esc(user.first_name || 'Менеджер')}</div>
          <div class="item__sub">Платформа: ${UI.esc(platform)}</div></div>
      </div>
      <hr class="divider">
      <div class="item__sub">Агентство: <span class="muted">${UI.esc(api.agencyId || '—')}</span></div>
    </div>
    <div class="section-title">Команда</div>
    <div id="mgrs">${UI.skelList(2)}</div>
    <button class="btn btn--danger btn--block" id="logout" style="margin-top:16px">${UI.icon('logout')} Выйти</button>`,
    async () => {
      document.getElementById('logout').onclick = () => {
        try { localStorage.removeItem('jwt_token'); } catch (e) { /* ignore */ }
        location.reload();
      };
      try {
        const m = await API.managers();
        document.getElementById('mgrs').innerHTML = UI.list(m.managers, (x) => `
          <div class="card"><div class="between">
            <span class="item__title">${UI.esc(x.name)}</span>
            <span class="chip chip--accent">${x.deals_won} сделок</span></div>
            <div class="item__sub" style="margin-top:4px">Комиссия: ${UI.money(x.commission)}</div></div>`,
          { icon: 'leads', title: 'Нет менеджеров' });
      } catch (e) {
        document.getElementById('mgrs').innerHTML = UI.errorState(e.message);
      }
    });
};

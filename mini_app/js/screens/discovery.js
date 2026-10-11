// Screen: автопоиск источников (ТЗ «Сигналы» v1.0, апгрейд A). Owner only.
// What the hourly search found, what it plugged in, what it threw out and why,
// and which platforms it can reach at all. A finding can be overruled by hand.
window.Screens = window.Screens || {};

const DISCOVERY_PLATFORM_RU = {
  telegram: 'Telegram', tg_catalog: 'Каталог Telegram', vk: 'ВКонтакте', youtube: 'YouTube',
  rss: 'Новостная лента', forum: 'Форум', yandex_maps: 'Яндекс.Карты',
  classifieds: 'Доски объявлений', otzovik: 'Отзовики', wordstat: 'Wordstat',
};
const PLATFORM_STATE = {
  active: ['работает', ' chip--success'],
  needs_key: ['нужен ключ', ' chip--warm'],
  stub: ['недоступно', ''],
  disabled: ['выключено', ''],
  error: ['ошибка', ' chip--hot'],
};
const VERDICT_TABS = [['ACTIVATE', 'Подключены'], ['SANDBOX', 'Песочница'], ['REJECT', 'Отклонены']];

Screens.discovery = async function () {
  UI.setHeader('Автопоиск', 'Новые источники каждый час', { back: true });
  let verdict = 'ACTIVATE';

  async function draw() {
    UI.render(UI.skelStats() + '<div class="mt-3">' + UI.skelList(3) + '</div>');
    let cfg, log, cands;
    try {
      [cfg, log, cands] = await Promise.all([
        API.discoveryConfig(), API.discoveryLog(10), API.discoveryCandidates({ verdict }),
      ]);
    } catch (e) {
      UI.render(UI.errorState(e.message), () => { document.getElementById('retry').onclick = draw; });
      return;
    }
    const conf = cfg.config;
    const budgets = conf.platform_budgets || {};

    const head = `
      <div class="card">
        <div class="between gap-2">
          <span class="item__title">Автопоиск</span>
          <div class="segmented" role="tablist">
            <button class="segmented__opt${conf.enabled ? ' segmented__opt--active' : ''}" data-on="1">Включён</button>
            <button class="segmented__opt${!conf.enabled ? ' segmented__opt--active' : ''}" data-on="0">Выключен</button>
          </div>
        </div>
        <div class="item__sub mt-1">Раз в час ищет чаты, группы, каналы и ленты о вашем городе,
          читает последние ${20} публикаций каждой находки и оценивает, встречаются ли там
          покупатели. Не больше ${conf.max_new_sources_per_run} находок за раз.
          От ${conf.sandbox_score_activate} баллов — сразу в работу, от ${conf.sandbox_score_sandbox} —
          в песочницу с повторной проверкой через ${conf.sandbox_retry_days} дн.</div>
      </div>`;

    const platform = (p) => {
      const enabled = (budgets[p.platform] || {}).enabled !== false;
      const state = p.state === 'active' && !enabled ? 'disabled' : p.state;
      const [label, cls] = PLATFORM_STATE[state] || [state, ''];
      const toggle = p.state !== 'stub'
        ? `<button class="btn btn--ghost btn--sm" data-pl="${UI.esc(p.platform)}" data-en="${enabled ? 0 : 1}">
             ${enabled ? 'Выключить' : 'Включить'}</button>` : '';
      // .item is a flex row; everything below the title goes into one column
      return `
        <div class="item"><div class="grow">
          <div class="between gap-2">
            <span class="item__title">${UI.esc(p.title)}</span>
            <span class="chip${cls}">${label}</span>
          </div>
          ${p.why ? `<div class="item__meta mt-1">${UI.esc(p.why)}</div>` : ''}
          ${toggle ? `<div class="btn-row mt-2">${toggle}</div>` : ''}
        </div></div>`;
    };

    const tabs = `
      <div class="segmented mt-3" role="tablist">${VERDICT_TABS.map(([v, l]) =>
        `<button class="segmented__opt${v === verdict ? ' segmented__opt--active' : ''}" role="tab"
           aria-selected="${v === verdict}" data-v="${v}">${l}</button>`).join('')}</div>`;

    const candidate = (c) => `
      <div class="card">
        <div class="between gap-2">
          <span class="item__title clamp-2">${UI.esc(c.name || c.external_id)}</span>
          ${c.sandbox_score !== null && c.sandbox_score !== undefined
            ? `<span class="chip">оценка <span class="num">${Math.round(c.sandbox_score)}</span></span>` : ''}
        </div>
        <div class="meta-row mt-1">${UI.esc(DISCOVERY_PLATFORM_RU[c.platform] || c.platform)}
          ${c.audience ? `<span class="dot"></span>${UI.esc(String(c.audience))} подписчиков` : ''}
          ${c.decided_by === 'manager' ? '<span class="dot"></span>решили вы' : ''}</div>
        ${c.reason ? `<div class="item__meta mt-1">${UI.esc(c.reason)}</div>` : ''}
        <div class="item__meta mt-1">Проверен ${c.tested_at ? UI.esc(UI.ago(c.tested_at)) : '—'}${
          c.retry_after ? ' · повторно ' + UI.esc(new Date(c.retry_after).toLocaleDateString('ru-RU')) : ''}</div>
        <div class="btn-row mt-3">
          ${c.url ? `<a class="btn btn--ghost btn--sm" href="${UI.esc(c.url)}" target="_blank" rel="noopener">${UI.icon('link')} Открыть</a>` : ''}
          ${c.verdict !== 'ACTIVATE' ? `<button class="btn btn--sm" data-act="${c.id}">${UI.icon('check')} Подключить</button>` : ''}
          ${c.verdict !== 'REJECT' ? `<button class="btn btn--secondary btn--sm" data-rej="${c.id}">${UI.icon('close')} Отклонить</button>` : ''}
        </div>
      </div>`;

    const run = (r) => `
      <div class="item"><div class="grow">
        <div class="between gap-2">
          <span class="item__title">${UI.esc(r.city || '')}</span>
          <span class="item__meta">${UI.esc(UI.ago(r.run_at))}</span>
        </div>
        <div class="item__meta mt-1">найдено ${r.found} · новых ${r.passed_dup} · проверено ${r.tested}
          · подключено ${r.activated} · в песочнице ${r.sandboxed} · отклонено ${r.rejected}</div>
        ${Object.keys(r.errors || {}).length ? `<div class="item__meta mt-1 text--warning">ошибки:
          ${UI.esc(Object.entries(r.errors).map(([k, v]) => (DISCOVERY_PLATFORM_RU[k] || k) + ' — ' + v).join('; '))}</div>` : ''}
      </div></div>`;

    const competitors = (cfg.competitors_found || []).length ? `
      <div class="section-title">Конкуренты с Яндекс.Карт</div>
      <div class="card"><div class="item__sub">${cfg.competitors_found.map(UI.esc).join(', ')}</div>
        <div class="item__meta mt-2">Сообщения с этими названиями попадают в категорию «Конкуренты».</div></div>` : '';

    UI.render(
      head + tabs
      + UI.list(cands.candidates, candidate, {
        icon: 'signals', title: 'Пока пусто',
        sub: verdict === 'ACTIVATE' ? 'Подключённые находки появятся после первых запусков'
          : 'Здесь будут находки с этим решением',
      })
      + '<div class="section-title">Площадки</div><div class="card">'
      + cfg.platforms.map(platform).join('') + '</div>'
      + competitors
      + '<div class="section-title">Журнал запусков</div><div class="card">'
      + ((log.runs || []).length ? log.runs.map(run).join('')
        : '<div class="item__meta">Запусков ещё не было</div>') + '</div>',
      () => {
        document.querySelectorAll('[data-on]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
          const on = b.getAttribute('data-on') === '1';
          if (on === conf.enabled) return;
          try { await API.updateDiscoveryConfig({ enabled: on }); UI.toast(on ? 'Автопоиск включён' : 'Автопоиск выключен'); await draw(); }
          catch (e) { UI.toast('Не удалось: ' + e.message); }
        }));
        document.querySelectorAll('[data-v]').forEach((b) => b.onclick = () => {
          verdict = b.getAttribute('data-v'); draw();
        });
        document.querySelectorAll('[data-pl]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
          const pl = b.getAttribute('data-pl');
          const en = b.getAttribute('data-en') === '1';
          try {
            await API.updateDiscoveryConfig({ platform_budgets: { [pl]: { enabled: en } } });
            UI.toast((DISCOVERY_PLATFORM_RU[pl] || pl) + (en ? ': включено' : ': выключено'));
            await draw();
          } catch (e) { UI.toast('Не удалось: ' + e.message); }
        }));
        document.querySelectorAll('[data-act]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
          try { await API.activateCandidate(b.getAttribute('data-act')); UI.toast('Источник подключён'); await draw(); }
          catch (e) { UI.toast('Не удалось: ' + e.message); }
        }));
        document.querySelectorAll('[data-rej]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
          try { await API.rejectCandidate(b.getAttribute('data-rej')); UI.toast('Отклонено, источник остановлен'); await draw(); }
          catch (e) { UI.toast('Не удалось: ' + e.message); }
        }));
      });
  }

  await draw();
};

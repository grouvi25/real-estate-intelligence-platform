// Screen: monitoring sources (TZ 30 `/admin/sources`).
// Shows what Source Discovery picked and lets the owner promote, pause or drop
// a chat. Before this screen the only way to stop a bad source was raw SQL.
window.Screens = window.Screens || {};

const SOURCE_STATUS_RU = {
  active: 'в работе',
  sandbox: 'песочница',
  paused: 'остановлен',
  blocked: 'заблокирован',
  dead: 'мёртвый',
};

function sourceStatusChip(s) {
  const mod = s === 'active' ? ' chip--accent' : (s === 'paused' || s === 'dead' ? ' chip--hot' : '');
  return `<span class="chip${mod}">${UI.esc(SOURCE_STATUS_RU[s] || s)}</span>`;
}

Screens.sources = async function () {
  let filter = {};

  async function draw() {
    UI.render(UI.skelList(3));
    let data;
    try {
      data = await API.sources(filter);
    } catch (e) {
      UI.render(UI.errorState(e.message), () => { document.getElementById('retry').onclick = draw; });
      return;
    }

    const tabs = `
      <div class="chips">
        <button class="chip chip--btn ${!filter.status ? 'chip--accent' : ''}" data-s="">Все <span class="num">${data.count}</span></button>
        <button class="chip chip--btn ${filter.status === 'active' ? 'chip--accent' : ''}" data-s="active">В работе</button>
        <button class="chip chip--btn ${filter.status === 'sandbox' ? 'chip--accent' : ''}" data-s="sandbox">Песочница</button>
        <button class="chip chip--btn ${filter.status === 'paused' ? 'chip--accent' : ''}" data-s="paused">Остановлены</button>
      </div>
      <button class="btn btn--secondary btn--block mt-3" id="add">${UI.icon('plus')} Добавить чат или группу</button>`;

    const body = UI.list(data.sources, (s) => {
      const isVk = String(s.source_type || '').startsWith('vk');
      const dead = s.status === 'active' && !s.signals_total;
      return `
      <div class="card${s.status === 'active' ? '' : s.status === 'paused' || s.status === 'dead' ? ' card--warm' : ''}">
        <div class="between gap-2">
          <span class="item__title clamp-2">${UI.esc(s.source_name || s.source_url)}</span>
          ${sourceStatusChip(s.status)}
        </div>
        <div class="meta-row mt-1">${UI.icon(isVk ? 'globe' : 'send')}${isVk ? 'ВКонтакте' : 'Telegram'}
          ${s.external_id ? `<span class="dot"></span>${UI.esc(isVk ? s.external_id : '@' + s.external_id)}` : ''}
          ${s.city_name ? `<span class="dot"></span>${UI.esc(s.city_name)}` : ''}</div>
        <div class="row row--wrap gap-1 mt-3">
          <span class="chip">оценка <span class="num">${s.score}</span></span>
          <span class="chip${dead ? ' chip--warm' : s.signals_total ? ' chip--success' : ''}">
            сигналов <span class="num">${s.signals_total}</span></span>
          ${s.signals_per_day ? `<span class="chip"><span class="num">${s.signals_per_day}</span> в день</span>` : ''}
          ${s.auto_found ? '<span class="chip">нашёл робот</span>' : ''}
        </div>
        ${dead ? '<div class="item__meta mt-2">В работе, но пока ничего не принёс.</div>' : ''}
        <div class="btn-row mt-3">
          ${s.status !== 'active' ? `<button class="btn btn--sm" data-act="active" data-id="${s.id}">${UI.icon('check')} В работу</button>` : ''}
          ${s.status !== 'paused' ? `<button class="btn btn--secondary btn--sm" data-act="paused" data-id="${s.id}">${UI.icon('pause')} Остановить</button>` : ''}
          <button class="btn btn--danger btn--sm" data-del="${s.id}">${UI.icon('trash')} Удалить</button>
        </div>
      </div>`;
    }, {
      icon: 'settings',
      title: filter.status ? 'В этом статусе пусто' : 'Источников нет',
      sub: filter.status ? 'Посмотрите другие фильтры'
        : 'Робот ищет чаты сам раз в неделю — или добавьте свой',
      actionLabel: filter.status ? null : 'Добавить источник', actionIcon: 'plus', actionId: 'add-empty',
    });

    UI.render(tabs + body, () => {
      document.querySelectorAll('[data-s]').forEach((b) => {
        b.onclick = () => {
          const v = b.getAttribute('data-s');
          filter = v ? { status: v } : {};
          draw();
        };
      });

      document.querySelectorAll('[data-act]').forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try {
            await API.updateSource(b.getAttribute('data-id'), { status: b.getAttribute('data-act') });
            UI.toast('Статус обновлён');
            await draw();
          } catch (e) { b.disabled = false; UI.toast('Не удалось: ' + e.message); }
        };
      });

      document.querySelectorAll('[data-del]').forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try { await API.deleteSource(b.getAttribute('data-del')); UI.toast('Источник удалён'); await draw(); }
          catch (e) {
            b.disabled = false;
            // 409 when signals reference it — deleting would break attribution.
            UI.toast('Нельзя удалить: у источника есть сигналы. Остановите его.');
          }
        };
      });

      const openAdd = async () => {
        // The city is where the collector gets its keywords: a source without
        // one reads messages and discards every single one of them.
        const geos = (await API.geoList().catch(() => ({}))).geo || [];
        const cityField = geos.length > 1 ? `
          <div class="field"><label>Город</label>
            <select id="src-geo">${geos.map((g) => `<option value="${g.id}">${UI.esc(g.city_name)}</option>`).join('')}</select></div>` : '';

        UI.sheet('Добавить источник', `
          <div class="field"><label>Ссылка на чат или группу</label>
            <input id="src-url" placeholder="@gelendzhik_chat или vk.com/gel_realty"></div>
          <div class="item__sub">Telegram и ВКонтакте — канал определяется по ссылке.</div>
          <div class="field"><label>Название (необязательно)</label>
            <input id="src-name" placeholder="Барахолка Геленджик"></div>
          ${cityField}
          <button class="btn btn--block" id="src-save" style="margin-top:12px">Добавить</button>`,
          (close) => {
            document.getElementById('src-save').onclick = async () => {
              const url = document.getElementById('src-url').value.trim();
              if (!url) { UI.toast('Укажите ссылку или @имя'); return; }
              const geoEl = document.getElementById('src-geo');
              try {
                await API.createSource({
                  source_url: url,
                  source_name: document.getElementById('src-name').value.trim() || null,
                  geo_location_id: geoEl ? geoEl.value : null,
                });
                UI.toast('Источник добавлен в песочницу');
                close();
                await draw();
              } catch (e) { UI.toast('Не удалось: ' + e.message); }
            };
          });
      };

      const addBtn = document.getElementById('add');
      if (addBtn) addBtn.onclick = openAdd;
      const addEmpty = document.getElementById('add-empty');
      if (addEmpty) addEmpty.onclick = openAdd;
    });
  }

  UI.setHeader('Источники', 'Откуда берутся сигналы', { back: true });
  await draw();
};

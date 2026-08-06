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
    UI.render(UI.skelList());
    const data = await API.sources(filter);

    const tabs = `
      <div class="row" style="gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <button class="chip ${!filter.status ? 'chip--accent' : ''}" data-s="">Все ${data.count}</button>
        <button class="chip ${filter.status === 'active' ? 'chip--accent' : ''}" data-s="active">В работе</button>
        <button class="chip ${filter.status === 'sandbox' ? 'chip--accent' : ''}" data-s="sandbox">Песочница</button>
        <button class="chip ${filter.status === 'paused' ? 'chip--accent' : ''}" data-s="paused">Остановлены</button>
      </div>
      <button class="btn btn--block" id="add" style="margin-bottom:12px">${UI.icon('plus')} Добавить чат вручную</button>`;

    const body = UI.list(data.sources, (s) => `
      <div class="card">
        <div class="row" style="gap:8px;flex-wrap:wrap">
          ${sourceStatusChip(s.status)}
          <span class="chip">оценка ${s.score}</span>
          <span class="chip">сигналов: ${s.signals_total}</span>
          ${s.auto_found ? '<span class="chip">найден роботом</span>' : ''}
          ${s.city_name ? `<span class="chip">${UI.icon('location')} ${UI.esc(s.city_name)}</span>` : ''}
        </div>
        <div class="item__title" style="margin-top:10px">${UI.esc(s.source_name || s.source_url)}</div>
        <div class="item__sub" style="margin-top:4px">${UI.esc(s.source_url)}</div>
        <div class="btn-row" style="margin-top:12px">
          ${s.status !== 'active' ? `<button class="btn" data-act="active" data-id="${s.id}">${UI.icon('check')} В работу</button>` : ''}
          ${s.status !== 'paused' ? `<button class="btn btn--secondary" data-act="paused" data-id="${s.id}">${UI.icon('close')} Остановить</button>` : ''}
          <button class="btn btn--secondary" data-del="${s.id}">${UI.icon('close')} Удалить</button>
        </div>
      </div>`, {
      icon: 'settings',
      title: 'Источников нет',
      sub: 'Робот ищет чаты сам раз в неделю — или добавьте чат вручную',
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

      document.getElementById('add').onclick = async () => {
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
    });
  }

  UI.setHeader('Источники', 'Откуда система берёт сигналы', { back: true });
  await draw();
};

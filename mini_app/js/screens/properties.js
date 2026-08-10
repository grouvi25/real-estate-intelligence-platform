// Screens: Properties list + detail (price edit -> rematch, object report).
//
// Title and price used to share a line, so a long title pushed the price into a
// wrap: "11 800 000" on one line and "₽" alone on the next. Price now sits on
// its own row and never wraps.
window.Screens = window.Screens || {};

const PROPERTY_TABS = [['', 'Все'], ['active', 'В продаже'], ['reserved', 'Бронь'], ['sold', 'Проданы']];

function propertyCard(p) {
  const meta = [
    p.district,
    p.rooms ? `${p.rooms}-комн.` : null,
    p.area_total ? `${p.area_total} м²` : null,
    (p.floor && p.floors_total) ? `${p.floor}/${p.floors_total} эт.` : null,
  ].filter(Boolean).join(' · ');
  return `
    <div class="card card--tap" data-go="properties/${p.id}">
      <div class="between gap-2">
        <span class="item__title clamp-2">${UI.esc(p.title)}</span>
        <span class="item__chev">${UI.icon('chevron')}</span>
      </div>
      <div class="between mt-2">
        <span class="price" style="font-size:var(--t-lg)">${UI.money(p.price)}</span>
        ${UI.statusChip(p.status)}
      </div>
      ${meta ? `<div class="item__sub mt-1">${UI.esc(meta)}</div>` : ''}
      ${p.price_per_sqm ? `<div class="item__meta mt-1">${UI.money(p.price_per_sqm)} за м²</div>` : ''}
    </div>`;
}

Screens.properties = async function () {
  UI.setHeader('Объекты', 'Каталог агентства', {
    actionIcon: 'upload', actionLabel: 'Загрузить каталог',
    onAction: () => Router.go('properties/import'),
  });
  let cur = Screens._propTab || '';

  const bar = () => `<div class="segmented" role="tablist">${PROPERTY_TABS.map(([v, l]) =>
    `<button class="segmented__opt${v === cur ? ' segmented__opt--active' : ''}" role="tab"
       aria-selected="${v === cur}" data-tab="${v}">${l}</button>`).join('')}</div>`;

  function draw() {
    UI.load(bar() + UI.skelList(3), () => API.properties({ limit: 50 }), (data) => {
      const items = cur ? (data.properties || []).filter((p) => p.status === cur) : (data.properties || []);
      UI.render(bar() + UI.list(items, propertyCard, {
        icon: 'properties',
        title: cur ? 'В этом статусе пусто' : 'Каталог пуст',
        sub: cur ? 'Посмотрите другие вкладки'
          : 'Система находит покупателей — предложить им нужно ваши объекты',
        actionLabel: cur ? null : 'Загрузить каталог', actionIcon: 'upload', actionId: 'to-import',
      }), () => {
        Router.bindGo();
        document.querySelectorAll('[data-tab]').forEach((t) => {
          t.onclick = () => { cur = t.getAttribute('data-tab'); Screens._propTab = cur; draw(); };
        });
        const i = document.getElementById('to-import');
        if (i) i.onclick = () => Router.go('properties/import');
      });
    });
  }

  draw();
};

Screens.propertyDetail = async function (params) {
  UI.setHeader('Объект', '', { back: true });
  UI.render(UI.skelCard() + `<div class="mt-3">${UI.skelForm(1)}</div>`);
  let p;
  try { p = await API.property(params.id); }
  catch (e) {
    UI.render(UI.empty({ icon: 'properties', title: 'Объект не найден',
      sub: 'Возможно, он удалён из каталога' }));
    return;
  }

  const meta = [
    p.district,
    p.rooms ? `${p.rooms}-комн.` : null,
    p.area_total ? `${p.area_total} м²` : null,
    (p.floor && p.floors_total) ? `${p.floor}/${p.floors_total} эт.` : null,
  ].filter(Boolean).join(' · ');

  // Coordinates come with the property: the server found them once and kept
  // them, so nothing is looked up while a person waits. Not every catalogue row
  // has a street address -- a row with only a district still has a point, and
  // tying the block to the address text hid the map for exactly those.
  const map = Maps.block(p.lat, p.lon, { height: 180 });

  UI.render(`
    <div class="card">
      <div class="between gap-2">
        <span class="card__title">${UI.esc(p.title)}</span>
        ${UI.statusChip(p.status)}
      </div>
      ${meta ? `<div class="item__sub mt-1">${UI.esc(meta)}</div>` : ''}
      <div class="hero__v mt-3">${UI.money(p.price)}</div>
      ${p.price_per_sqm ? `<div class="item__meta">${UI.money(p.price_per_sqm)} за м²</div>` : ''}
    </div>

    ${(p.address || map) ? `<div class="card mt-3">
      <div class="meta-row">${UI.icon('location')}${UI.esc(p.address || p.district || 'Место на карте')}</div>
      ${map ? map.html : ''}
    </div>` : ''}

    <div class="card mt-3">
      <div class="field"><label for="price">Цена, ₽</label>
        <input id="price" type="number" inputmode="numeric" value="${p.price || ''}">
        <div class="field__hint">Снижение на 5% и больше запускает переподбор для подходящих лидов.</div>
      </div>
      <button class="btn btn--block" id="save">${UI.icon('check')} Сохранить цену</button>
    </div>

    <div class="section-title">Документы и продвижение</div>
    <button class="btn btn--secondary btn--block" id="report">${UI.icon('file')} Отчёт по объекту</button>
    <button class="btn btn--secondary btn--block mt-2" id="listing">${UI.icon('sparkles')} Сгенерировать объявление</button>
    <button class="btn btn--secondary btn--block mt-2" id="checklist">${UI.icon('check')} Чек-лист документов</button>`,
    () => {
      Maps.paint(map);
      const saveBtn = document.getElementById('save');
      saveBtn.onclick = () => UI.busy(saveBtn, async () => {
        const price = parseInt(document.getElementById('price').value, 10);
        if (isNaN(price) || price <= 0) { UI.toast('Введите цену числом'); return; }
        try {
          const r = await API.updateProperty(p.id, { price });
          UI.toast(r.price_changed ? 'Цена снижена — переподбор запущен' : 'Цена сохранена');
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
      document.getElementById('report').onclick = () => {
        UI.sheet('Отчёт по объекту', UI.skelCard(),
          async () => {
            try {
              const html = await API.propertyReportHtml(p.id);
              const body = document.querySelector('.sheet__body');
              const iframe = document.createElement('iframe');
              iframe.setAttribute('sandbox', 'allow-same-origin');
              body.innerHTML = ''; body.appendChild(iframe); iframe.srcdoc = html;
            } catch (e) { document.querySelector('.sheet__body').innerHTML = UI.errorState(e.message); }
          });
      };
      const checklistBtn = document.getElementById('checklist');
      checklistBtn.onclick = () => UI.busy(checklistBtn, async () => {
        try {
          const doc = await API.createChecklist(p.id);
          UI.docLinkSheet('Чек-лист готов', doc,
            `${p.is_new_build ? 'Новостройка' : 'Вторичка'} · ${String(doc.format).toUpperCase()}`);
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
      document.getElementById('listing').onclick = () => {
        UI.sheet('Генерация объявления', `
          <div class="field"><label>Площадка</label>
            <select id="lg-platform">
              <option value="avito">Avito</option>
              <option value="cian">Циан</option>
              <option value="domclick">Домклик</option>
              <option value="telegram">Telegram</option>
            </select></div>
          <div class="field"><label>Тон</label>
            <select id="lg-tone">
              <option value="professional">Профессиональный</option>
              <option value="friendly">Дружелюбный</option>
              <option value="premium">Премиальный</option>
            </select></div>
          <button class="btn btn--block" id="lg-go">${UI.icon('sparkles')} Сгенерировать</button>
          <div id="lg-out" style="margin-top:12px"></div>`,
          () => {
            document.getElementById('lg-go').onclick = async () => {
              const out = document.getElementById('lg-out');
              out.innerHTML = '<div class="skel skel-line lg"></div><div class="skel skel-line md"></div><div class="skel skel-line sm"></div>';
              try {
                const r = await API.generateListing(p.id, {
                  platform: document.getElementById('lg-platform').value,
                  tone: document.getElementById('lg-tone').value,
                });
                const l = r.listing || {};
                // The prompt asks for the ad split into parts plus `full_text`,
                // the finished thing to post. The screen used to look for
                // `text`/`body`/`description`, found none of them and printed the
                // raw JSON — a manager was shown the machine's notes instead of
                // an advert. Parts are only assembled when full_text is missing.
                const assembled = [l.lead_paragraph, l.key_facts, l.infrastructure, l.closing]
                  .filter(Boolean).join('\n\n');
                const text = l.full_text || assembled || l.text || l.body || l.description
                  || (typeof l === 'string' ? l : '');
                const title = l.headline || l.title || '';
                const tags = Array.isArray(l.tags) ? l.tags.filter(Boolean) : [];
                out.innerHTML =
                  (title ? `<div class="field"><label for="lg-title">Заголовок</label>
                     <input id="lg-title" value="${UI.esc(title)}"></div>` : '') +
                  `<div class="field"><label for="lg-text">Текст объявления</label>
                     <textarea id="lg-text" rows="10">${UI.esc(text)}</textarea></div>` +
                  (tags.length ? `<div class="row row--wrap gap-1">${tags.map((t) =>
                     `<span class="chip">${UI.esc(t)}</span>`).join('')}</div>` : '') +
                  `<button class="btn btn--secondary btn--block mt-3" id="lg-copy">${UI.icon('file')} Копировать</button>`;
                document.getElementById('lg-copy').onclick = () => {
                  // A listing is a headline plus a body; copying only the body
                  // means retyping the headline on the other side.
                  const head = document.getElementById('lg-title');
                  const ta = document.getElementById('lg-text');
                  const whole = [head && head.value.trim(), ta.value].filter(Boolean).join('\n\n');
                  try { navigator.clipboard.writeText(whole); UI.toast('Скопировано'); }
                  catch (e) { ta.select(); document.execCommand('copy'); UI.toast('Скопировано'); }
                };
              } catch (e) { out.innerHTML = UI.errorState(e.message); }
            };
          });
      };
    });
};

// Catalogue import. Matching, pitches and offers all read from properties, so
// an agency that cannot load its inventory gets nothing out of the system --
// and until now loading it meant asking a developer to run INSERTs.
Screens.propertyImport = async function () {
  UI.setHeader('Загрузка каталога', 'CSV или Excel', { back: true });

  UI.render(`
    <div class="card">
      <p class="muted" style="margin:0 0 10px">
        Выгрузите каталог из CRM или Excel. Заголовки понимаются русские:
        «Название», «Цена», «Общая площадь», «Комнат», «Район», «Новостройка».
      </p>
      <div class="field">
        <label>Файл</label>
        <input type="file" id="imp-file" accept=".csv,.xlsx,.xlsm">
      </div>
      <button class="btn btn--block" id="imp-check">${UI.icon('file')} Проверить файл</button>
      <p class="muted" style="margin:10px 0 0;font-size:13px">
        Сначала проверка — она ничего не записывает и показывает, что получится.
      </p>
    </div>
    <div id="imp-report"></div>`);

  const fileInput = document.getElementById('imp-file');
  const report = document.getElementById('imp-report');

  const renderReport = (res, checked) => {
    const errors = res.errors || [];
    const unmapped = res.unmapped_columns || [];
    report.innerHTML = `
      <div class="card" style="margin-top:12px">
        <div class="between"><b>${checked ? 'Результат проверки' : 'Загружено'}</b></div>
        <div class="item__sub" style="margin-top:8px">
          Новых: <b>${res.created}</b> · Обновится: <b>${res.updated}</b> ·
          Пропущено: <b>${res.skipped}</b>
        </div>
        ${unmapped.length ? `<p class="muted" style="margin:10px 0 0">
          Не распознаны колонки: ${unmapped.map(UI.esc).join(', ')}. Данные из них не загрузятся.
        </p>` : ''}
        ${errors.length ? `<div style="margin-top:10px">
          <div class="muted" style="margin-bottom:6px">Проблемные строки:</div>
          ${errors.slice(0, 15).map((e) =>
            `<div class="item__sub">строка ${e.row}: ${UI.esc(e.message)}</div>`).join('')}
          ${errors.length > 15 ? `<div class="muted">…и ещё ${errors.length - 15}</div>` : ''}
        </div>` : ''}
        ${checked && (res.created + res.updated) > 0
          ? `<button class="btn btn--block" id="imp-go" style="margin-top:14px">
               ${UI.icon('check')} Загрузить ${res.created + res.updated} объектов</button>`
          : ''}
      </div>`;

    const go = document.getElementById('imp-go');
    if (go) go.onclick = () => run(false);
  };

  const run = async (dryRun) => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) { UI.toast('Выберите файл'); return; }

    const button = document.getElementById(dryRun ? 'imp-check' : 'imp-go');
    if (button) { button.disabled = true; button.textContent = 'Обработка…'; }
    try {
      const res = await API.importProperties(file, dryRun);
      renderReport(res, dryRun);
      if (!dryRun) UI.toast(`Готово: ${res.created} новых, ${res.updated} обновлено`);
    } catch (e) {
      UI.toast(e.message || 'Не удалось обработать файл');
      if (button) { button.disabled = false; button.textContent = 'Проверить файл'; }
    }
  };

  document.getElementById('imp-check').onclick = () => run(true);
};

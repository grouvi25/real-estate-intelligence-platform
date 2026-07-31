// Screens: Properties list + detail (price edit -> rematch, object report).
window.Screens = window.Screens || {};

Screens.properties = async function () {
  UI.setHeader('Объекты', 'Каталог агентства');
  UI.render(UI.skelList());
  const data = await API.properties({ limit: 50 });
  UI.render(UI.list(data.properties, (p) => `
    <div class="card card--tap" data-go="properties/${p.id}">
      <div class="item">
        <div class="grow">
          <div class="between"><span class="item__title ellipsis">${UI.esc(p.title)}</span>
            <span class="price">${UI.money(p.price)}</span></div>
          <div class="item__sub">${p.district ? UI.esc(p.district) + ' · ' : ''}${p.rooms || '—'}-комн. · ${UI.statusChip(p.status)}</div>
        </div>
        <span class="item__chev">${UI.icon('chevron')}</span>
      </div>
    </div>`, { icon: 'properties', title: 'Объектов нет', sub: 'Загрузите каталог агентства' })
    + `<button class="btn btn--ghost btn--block" data-go="properties/import" style="margin-top:12px">
         ${UI.icon('plus')} Загрузить каталог</button>`, bindGo);
};

Screens.propertyDetail = async function (params) {
  UI.setHeader('Объект', '', { back: true });
  UI.render(UI.skelCard());
  let p;
  try { p = await API.property(params.id); }
  catch (e) { UI.render(UI.empty({ icon: 'properties', title: 'Объект не найден' })); return; }

  UI.render(`
    <div class="card">
      <div class="card__title">${UI.esc(p.title)}</div>
      <div class="item__sub" style="margin-top:4px">${p.district ? UI.esc(p.district) + ' · ' : ''}${p.rooms || '—'}-комн.
        ${p.area_total ? ' · ' + p.area_total + ' м²' : ''}</div>
      <div class="row" style="margin-top:8px">${UI.statusChip(p.status)}</div>
      <hr class="divider">
      <div class="field"><label>Цена, ₽</label><input id="price" type="number" inputmode="numeric" value="${p.price || ''}"></div>
      <button class="btn btn--block" id="save">${UI.icon('check')} Сохранить цену</button>
      <div class="item__sub" style="margin-top:8px">Снижение цены ≥ 5% запускает переподбор для подходящих лидов.</div>
    </div>
    <button class="btn btn--secondary btn--block" id="report" style="margin-top:12px">${UI.icon('file')} Отчёт по объекту</button>
    <button class="btn btn--secondary btn--block" id="listing" style="margin-top:8px">${UI.icon('sparkles')} Сгенерировать объявление</button>`,
    () => {
      document.getElementById('save').onclick = async () => {
        const price = parseInt(document.getElementById('price').value, 10);
        if (isNaN(price)) { UI.toast('Введите число'); return; }
        try {
          const r = await API.updateProperty(p.id, { price });
          UI.toast(r.price_changed ? 'Цена обновлена, переподбор запущен' : 'Цена сохранена');
        } catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
      document.getElementById('report').onclick = () => {
        UI.sheet('Отчёт по объекту', '<div class="skel skel-line lg"></div><div class="skel skel-line md"></div>',
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
                const text = l.text || l.body || l.description || (typeof l === 'string' ? l : JSON.stringify(l, null, 2));
                const title = l.title || l.headline || '';
                out.innerHTML =
                  (title ? `<div class="card__title" style="margin-bottom:6px">${UI.esc(title)}</div>` : '') +
                  `<textarea id="lg-text" rows="10" style="width:100%">${UI.esc(text)}</textarea>` +
                  `<button class="btn btn--secondary btn--block" id="lg-copy" style="margin-top:8px">${UI.icon('file')} Копировать</button>`;
                document.getElementById('lg-copy').onclick = () => {
                  const ta = document.getElementById('lg-text');
                  ta.select();
                  try { navigator.clipboard.writeText(ta.value); UI.toast('Скопировано'); }
                  catch (e) { document.execCommand('copy'); UI.toast('Скопировано'); }
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

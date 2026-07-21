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
    </div>`, { icon: 'properties', title: 'Объектов нет' }), bindGo);
};

Screens.propertyDetail = async function (params) {
  UI.setHeader('Объект', '', { back: true });
  UI.render(UI.skelCard());
  const data = await API.properties({ limit: 200 });
  const p = (data.properties || []).find((x) => x.id === params.id);
  if (!p) { UI.render(UI.empty({ icon: 'properties', title: 'Объект не найден' })); return; }

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

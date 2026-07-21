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
    <button class="btn btn--secondary btn--block" id="report" style="margin-top:12px">${UI.icon('file')} Отчёт по объекту</button>`,
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
    });
};

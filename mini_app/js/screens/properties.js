// Screens: Properties list + detail (with price edit -> rematch). TZ section 30.
window.Screens = window.Screens || {};

Screens.properties = async function () {
  UI.setHeader('Объекты', '');
  UI.render(UI.spinner());
  const data = await API.properties({ limit: 50 });
  const body = UI.list(data.properties, (p) => `
    <div class="card" onclick="Router.go('properties/${p.id}')">
      <div class="row"><strong>${UI.esc(p.title)}</strong><span class="price">${UI.money(p.price)}</span></div>
      <div class="muted">${UI.esc(p.district || '')} · ${p.rooms || '—'} комн. ·
        ${UI.esc(p.status)}</div>
    </div>`, 'Пока нет объектов');
  UI.render(body);
};

Screens.propertyDetail = async function (params) {
  UI.setHeader('Объект', '');
  UI.render(UI.spinner());
  const data = await API.properties({ limit: 200 });
  const p = (data.properties || []).find((x) => x.id === params.id);
  if (!p) { UI.render(UI.empty('Объект не найден')); return; }
  const html = `
    <div class="card">
      <h3>${UI.esc(p.title)}</h3>
      <div class="muted">${UI.esc(p.district || '')} · ${p.rooms || '—'} комн. · ${UI.esc(p.status)}</div>
      <label>Цена, ₽</label>
      <input id="price" type="number" value="${p.price || ''}" />
      <button class="btn block" id="save-price">Сохранить цену</button>
      <div class="muted" style="margin-top:6px">Изменение цены запускает переподбор для лидов.</div>
    </div>
  `;
  UI.render(html, () => {
    document.getElementById('save-price').onclick = async () => {
      const price = parseInt(document.getElementById('price').value, 10);
      if (isNaN(price)) { UI.toast('Введите число'); return; }
      const r = await API.updateProperty(p.id, { price });
      UI.toast(r.price_changed ? 'Цена обновлена, переподбор запущен' : 'Цена без изменений');
    };
  });
};

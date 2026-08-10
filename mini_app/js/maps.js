// Yandex Maps JS API. Global `Maps`. TZ 2.3.
//
// Credential-gated like every other integration: without YANDEX_MAPS_API_KEY the
// backend sends no key, `Maps.available()` is false, and screens leave the block
// out entirely rather than drawing an empty grey square.
//
// The API is loaded on demand — the first screen that asks for a map pays for it,
// and a manager who only ever looks at the queue never downloads it at all.
//
// There are no coordinates in the catalogue, so a placemark is found by geocoding
// the address. That is one request per card, cached for the session, and it fails
// quietly: a card without a findable address shows everything else as before.
window.Maps = (() => {
  const KEY_STORE = 'maps_key';
  let key = null;
  let loading = null;
  const found = new Map();

  const setKey = (k) => { key = k || null; };
  const available = () => Boolean(key);

  function load() {
    if (window.ymaps) return Promise.resolve(window.ymaps);
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(key)}&lang=ru_RU`;
      s.onload = () => window.ymaps.ready(() => resolve(window.ymaps));
      s.onerror = () => reject(new Error('Карты не загрузились'));
      document.head.appendChild(s);
    });
    return loading;
  }

  async function geocode(ymaps, query) {
    if (found.has(query)) return found.get(query);
    const res = await ymaps.geocode(query, { results: 1 });
    const first = res.geoObjects.get(0);
    const at = first ? first.geometry.getCoordinates() : null;
    found.set(query, at);
    return at;
  }

  /** Container HTML. Returns null when there is no key or nothing to look up. */
  function block(query, { height = 180 } = {}) {
    if (!available() || !query) return null;
    const id = `map-${Math.random().toString(36).slice(2, 9)}`;
    return {
      id,
      query,
      html: `<div class="map" id="${id}" style="height:${height}px"></div>`,
    };
  }

  /** Draw a block returned by `block`. Silent on failure — a map is never the
   *  reason a card fails to show what it knows. */
  async function paint(spec) {
    if (!spec) return;
    const el = document.getElementById(spec.id);
    if (!el) return;
    try {
      const ymaps = await load();
      const at = await geocode(ymaps, spec.query);
      if (!at) { el.remove(); return; }
      const map = new ymaps.Map(el, {
        center: at, zoom: 15, controls: ['zoomControl'],
      }, { suppressMapOpenBlock: true });
      map.behaviors.disable('scrollZoom');   // the page must still scroll
      map.geoObjects.add(new ymaps.Placemark(at, {}, { preset: 'islands#blueDotIcon' }));
    } catch (e) {
      el.remove();
    }
  }

  return { setKey, available, block, paint, KEY_STORE };
})();

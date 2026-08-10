// Yandex Maps JS API. Global `Maps`. TZ 2.3.
//
// Credential-gated like every other integration: without YANDEX_MAPS_API_KEY the
// backend sends no key, `Maps.available()` is false, and screens leave the block
// out entirely rather than drawing an empty grey square.
//
// The API is loaded on demand — the first screen that asks for a map pays for it,
// and a manager who only ever opens the queue never downloads it at all.
//
// Nothing here geocodes. Coordinates arrive with the property, found once on the
// server and kept: the geocoder is a separate, billed product whose key has no
// business in a page anyone can open, and Telegram's webview does not reliably
// send the Referer that Yandex checks.
window.Maps = (() => {
  const KEY_STORE = 'maps_key';
  let key = null;
  let loading = null;

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

  /** Container HTML, or null when there is no key or no point to show. */
  function block(lat, lon, { height = 180 } = {}) {
    if (!available() || typeof lat !== 'number' || typeof lon !== 'number') return null;
    const id = `map-${Math.random().toString(36).slice(2, 9)}`;
    return { id, at: [lat, lon], html: `<div class="map" id="${id}" style="height:${height}px"></div>` };
  }

  /** Draw a block returned by `block`. Silent on failure — a map is never the
   *  reason a card fails to show what it knows. */
  async function paint(spec) {
    if (!spec) return;
    const el = document.getElementById(spec.id);
    if (!el) return;
    try {
      const ymaps = await load();
      const map = new ymaps.Map(el, {
        center: spec.at, zoom: 15, controls: ['zoomControl'],
      }, { suppressMapOpenBlock: true });
      map.behaviors.disable('scrollZoom');   // the page must still scroll
      map.geoObjects.add(new ymaps.Placemark(spec.at, {}, { preset: 'islands#blueDotIcon' }));
    } catch (e) {
      el.remove();
    }
  }

  return { setKey, available, block, paint, KEY_STORE };
})();

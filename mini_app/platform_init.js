// Mini App platform abstraction (Telegram + MAX) + API client. TZ section 18.1.
// Static-file friendly: the API base comes from window.REIP_CONFIG (no bundler),
// replacing the TZ's Vite `import.meta.env.VITE_API_URL`.

const PlatformSDK = (() => {
  const tgApp = () => (window.Telegram && window.Telegram.WebApp) || null;
  // MAX Bridge кладёт мост прямо в window.WebApp (dev.max.ru/docs/webapps).
  // Раньше здесь ждали window.MAX.WebApp — такого объекта MAX не создаёт
  // никогда, поэтому в MAX приложение считало себя обычным браузером,
  // подписи не получало и упиралось в отказ авторизации.
  const maxApp = () => window.WebApp || (window.MAX && window.MAX.WebApp) || null;

  // Telegram hands the signed launch payload to the page in the URL fragment
  // (#tgWebAppData=...); telegram-web-app.js is what turns it into
  // WebApp.initData. That script is fetched from telegram.org, so when the
  // request does not arrive -- a blocked resolver, a captive network, an ad
  // blocker -- no bridge appears and the app declares itself "not in Telegram"
  // while the signature is sitting in the address bar, untouched.
  //
  // Read once, at load: the router rewrites the hash to #/dashboard as soon as
  // it starts, and a token that expires an hour later must still be able to
  // re-authenticate.
  const LAUNCH = (() => {
    const out = {};
    const take = (source) => {
      try {
        new URLSearchParams(source).forEach((value, key) => {
          // URLSearchParams decodes once, which is exactly right: the value is
          // the initData string, percent-encoded. Decoding a second time turns
          // a name that legitimately contains "%" into an exception.
          if (!(key in out) && (key.indexOf('tgWebApp') === 0 || key === 'WebAppData')) {
            out[key] = value;
          }
        });
      } catch (e) { /* malformed URL; nothing to take */ }
    };
    const hash = location.hash || '';
    take(hash.startsWith('#') ? hash.slice(1) : hash);
    take(location.search || '');
    return out;
  })();

  // Whoever is asking, the answer must not be a value captured before the
  // bridge existed: on Desktop it can be injected a moment after the page runs.
  const personFrom = (initData) => {
    try {
      const raw = new URLSearchParams(initData).get('user');
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  };

  const telegram = {
    platform: 'telegram',
    get inTelegram() { return true; },
    get initData() {
      const tg = tgApp();
      return (tg && tg.initData) || LAUNCH.tgWebAppData || '';
    },
    get user() {
      const tg = tgApp();
      return (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) || personFrom(this.initData);
    },
    get theme() { const tg = tgApp(); return (tg && tg.colorScheme) || 'light'; },
    showMainButton: (text, cb) => {
      const tg = tgApp();
      if (!tg || !tg.MainButton) return;
      tg.MainButton.setText(text);
      tg.MainButton.show();
      tg.MainButton.onClick(cb);
    },
    close: () => { const tg = tgApp(); if (tg) tg.close(); },
  };

  if (tgApp()) {
    try { tgApp().ready(); tgApp().expand(); } catch (e) { /* older client */ }
    return telegram;
  }
  // No bridge, but Telegram's own launch parameters are in the URL. This is
  // still Telegram, and the signature it left is enough to sign in.
  if (LAUNCH.tgWebAppData || LAUNCH.tgWebAppPlatform) return telegram;

  if (maxApp()) {
    const max = maxApp();
    max.ready();
    return {
      platform: 'max',
      inTelegram: false,
      user: max.initDataUnsafe && max.initDataUnsafe.user,
      get initData() { return max.initData || LAUNCH.WebAppData || ''; },
      theme: max.theme || 'light',
      showMainButton: (text, cb) => {
        if (max.MainButton) {
          max.MainButton.setText(text);
          max.MainButton.show();
          max.MainButton.onClick(cb);
        }
      },
      close: () => max.close()
    };
  }
  // Browser fallback for local dev.
  return {
    platform: 'web',
    inTelegram: false,
    user: { id: 0, first_name: 'TestDev' },
    initData: 'mock',
    theme: 'light',
    showMainButton: () => {},
    close: () => {}
  };
})();

const API_BASE = (window.REIP_CONFIG && window.REIP_CONFIG.apiUrl) || '';

// TZ 33.1 / 35.8: the JWT must live in Telegram CloudStorage, falling back to
// sessionStorage — not localStorage, which persists the token on the device
// indefinitely and survives closing the app. Async because CloudStorage is
// callback-based.
const StorageAdapter = (() => {
  const cloud = () => {
    const tg = window.Telegram && window.Telegram.WebApp;
    return tg && tg.CloudStorage && typeof tg.CloudStorage.getItem === 'function'
      ? tg.CloudStorage : null;
  };
  return {
    async get(key) {
      const cs = cloud();
      if (cs) return new Promise((r) => cs.getItem(key, (e, v) => r(e ? null : (v || null))));
      try { return sessionStorage.getItem(key); } catch (e) { return null; }
    },
    async set(key, value) {
      const cs = cloud();
      if (cs) return new Promise((r) => cs.setItem(key, value, () => r()));
      try { sessionStorage.setItem(key, value); } catch (e) { /* ignore */ }
    },
    async remove(key) {
      const cs = cloud();
      if (cs && typeof cs.removeItem === 'function') {
        return new Promise((r) => cs.removeItem(key, () => r()));
      }
      try { sessionStorage.removeItem(key); } catch (e) { /* ignore */ }
    },
  };
})();

// One-off cleanup: earlier builds kept the JWT in localStorage, so it is still
// sitting on devices that opened the app before this change. Drop it.
try { localStorage.removeItem('jwt_token'); } catch (e) { /* ignore */ }

// TZ 32.6: attribution for a session opened through a bot deeplink
// (t.me/<bot>?start=<campaign>). Explicit query params win; otherwise the
// presence of start_param marks the session as coming from the bot.
window._utm = (() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  const sp = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || '';
  let qp;
  try { qp = new URLSearchParams(location.search); } catch (e) { qp = new URLSearchParams(); }
  return {
    utm_source: qp.get('utm_source') || (sp ? 'telegram_bot' : null),
    utm_medium: qp.get('utm_medium') || (sp ? 'bot_deeplink' : null),
    utm_campaign: qp.get('utm_campaign') || sp || null,
  };
})();

const api = {
  token: null,
  // One place where a failed response becomes an Error. There are four call
  // sites and they used to disagree about whether the server's words were worth
  // keeping; the one used for signing in kept nothing, so a manager refused for
  // having no invitation -- explained in Russian, in the body -- was shown the
  // app's default advice instead, which sent him to Telegram to fix a problem
  // that was never Telegram's.
  //
  // The server names its own refusals under "error" (AppException) and
  // FastAPI's arrive under "detail".
  async failure(res) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* not JSON, or no body */ }
    const said = body && (body.error || body.detail || body.message);
    const err = new Error(typeof said === 'string' && said ? said : `API ${res.status}`);
    err.status = res.status;
    err.code = body && body.code;
    return err;
  },
  async request(endpoint, method = 'GET', body = null) {
    const build = () => {
      const headers = { 'Content-Type': 'application/json' };
      if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
      return fetch(`${API_BASE}/api${endpoint}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : null
      });
    };
    let res = await build();
    // JWT expired/invalid: drop the cached token, re-authenticate once, retry.
    if (res.status === 401 && typeof authenticate === 'function' && !endpoint.startsWith('/auth/')) {
      await StorageAdapter.remove('jwt_token');
      this.token = null;
      try { await authenticate(); res = await build(); } catch (e) { /* fall through */ }
    }
    if (!res.ok) throw await this.failure(res);
    return res.json();
  }
};

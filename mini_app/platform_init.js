// Mini App platform abstraction (Telegram + MAX) + API client. TZ section 18.1.
// Static-file friendly: the API base comes from window.REIP_CONFIG (no bundler),
// replacing the TZ's Vite `import.meta.env.VITE_API_URL`.

const PlatformSDK = (() => {
  const initPlatform = () => {
    if (window.Telegram && window.Telegram.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      tg.expand();
      return {
        platform: 'telegram',
        user: tg.initDataUnsafe && tg.initDataUnsafe.user,
        initData: tg.initData,
        theme: tg.colorScheme,
        showMainButton: (text, cb) => {
          tg.MainButton.setText(text);
          tg.MainButton.show();
          tg.MainButton.onClick(cb);
        },
        close: () => tg.close()
      };
    }
    if (window.MAX && window.MAX.WebApp) {
      const max = window.MAX.WebApp;
      max.ready();
      return {
        platform: 'max',
        user: max.initDataUnsafe && max.initDataUnsafe.user,
        initData: max.initData,
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
      user: { id: 0, first_name: 'TestDev' },
      initData: 'mock',
      theme: 'light',
      showMainButton: () => {},
      close: () => {}
    };
  };
  return initPlatform();
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

const api = {
  token: null,
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
    if (!res.ok) throw new Error(`API ${res.status}`);
    return res.json();
  }
};

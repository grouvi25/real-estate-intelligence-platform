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
      try { localStorage.removeItem('jwt_token'); } catch (e) { /* ignore */ }
      this.token = null;
      try { await authenticate(); res = await build(); } catch (e) { /* fall through */ }
    }
    if (!res.ok) throw new Error(`API ${res.status}`);
    return res.json();
  }
};

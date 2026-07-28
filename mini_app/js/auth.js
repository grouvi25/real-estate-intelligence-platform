// Mini App auth: platform initData -> JWT. TZ section 18.2 / 30.
// Exposes async authenticate(); the SPA bootstrap (app.js) calls it. A cached
// cached token (CloudStorage / sessionStorage via StorageAdapter, TZ 33.1) is
// reused so we don't re-auth on every open.

async function authenticate() {
  const cached = api.loadToken ? await api.loadToken() : null;
  if (cached) return cached;
  const res = await api.request('/auth/platform', 'POST', {
    platform: PlatformSDK.platform,
    init_data: PlatformSDK.initData,
  });
  api.setToken(res.token);
  return res.token;
}

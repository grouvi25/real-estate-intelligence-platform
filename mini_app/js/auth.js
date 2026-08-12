// Mini App auth: platform initData -> JWT. TZ section 18.2 / 30.
// Exposes async authenticate(); the SPA bootstrap (app.js) calls it. A cached
// cached token (CloudStorage / sessionStorage via StorageAdapter, TZ 33.1) is
// reused so we don't re-auth on every open.

// The owner's invite link is t.me/<bot>?start=inv_<token>; the bot passes the
// payload on to the Mini App URL. A manager who is already registered never
// needs it -- it only decides which agency a newcomer joins.
function inviteToken() {
  let params;
  try { params = new URLSearchParams(window.location.search); } catch (e) { params = new URLSearchParams(); }
  // _utm.utm_campaign already carries either ?utm_campaign= or the WebApp
  // start_param, which is where the bot puts the deeplink payload.
  const value = params.get('invite') || (window._utm && window._utm.utm_campaign) || '';
  return String(value).startsWith('inv_') ? value : null;
}

async function rememberMapsKey(key) {
  Maps.setKey(key);
  try {
    if (key) await StorageAdapter.set(Maps.KEY_STORE, key);
    else await StorageAdapter.remove(Maps.KEY_STORE);
  } catch (e) { /* storage refused; the key simply is not kept */ }
}

// Asks for the settings the cached-token path skips. A failure here costs a map,
// never the session — the cabinet must open whatever the answer is.
async function refreshConfig() {
  try {
    const cfg = await API.appConfig();
    await rememberMapsKey(cfg && cfg.maps_key);
    if (cfg && cfg.manager) {
      window._manager = cfg.manager;
      try { sessionStorage.setItem('manager', JSON.stringify(cfg.manager)); } catch (e) { /* private mode */ }
    }
    return true;
  } catch (e) {
    return false;
  }
}

// Telegram Desktop can inject its bridge a moment after the page has run, and
// then initData is an empty string only because we asked too early. Ask again
// before concluding anything: three short waits cost a person nothing and save
// them a screen that says the app is not in Telegram while it plainly is.
async function launchSignature() {
  let value = PlatformSDK.initData;
  for (let i = 0; i < 3 && !value && PlatformSDK.inTelegram; i++) {
    await new Promise((r) => setTimeout(r, 300));
    value = PlatformSDK.initData;
  }
  return value;
}

async function authenticate() {
  try { window._agency = JSON.parse(sessionStorage.getItem('agency') || 'null'); } catch (e) { /* ignore */ }
  try { window._manager = JSON.parse(sessionStorage.getItem('manager') || 'null'); } catch (e) { /* ignore */ }
  // The key lives wherever the token lives. It used to sit in sessionStorage
  // while the token sat in Telegram's CloudStorage, which outlives the session:
  // a manager who logged in yesterday skipped the handshake, so the key never
  // arrived and the map quietly vanished for everyone but a first-time visitor.
  try { Maps.setKey(await StorageAdapter.get(Maps.KEY_STORE)); } catch (e) { /* ignore */ }
  const cached = api.loadToken ? await api.loadToken() : null;
  if (cached) {
    // A deleted/disabled user must not survive through Telegram CloudStorage.
    if (await refreshConfig()) return cached;
    await StorageAdapter.remove('jwt_token');
    api.token = null;
    window._manager = null;
    window._agency = null;
    try { sessionStorage.removeItem('manager'); sessionStorage.removeItem('agency'); } catch (e) { /* ignore */ }
  }
  const res = await api.request('/auth/platform', 'POST', {
    platform: PlatformSDK.platform,
    init_data: await launchSignature(),
    invite: inviteToken(),
  });
  api.setToken(res.token);
  if (res.manager) {
    window._manager = res.manager;
    try { sessionStorage.setItem('manager', JSON.stringify(res.manager)); } catch (e) { /* private mode */ }
  }
  // Kept for the Профиль header: an agency has a name, and a person reading the
  // screen should see it rather than its id.
  if (res.agency) {
    window._agency = res.agency;
    try { sessionStorage.setItem('agency', JSON.stringify(res.agency)); } catch (e) { /* private mode */ }
  }
  await rememberMapsKey(res.maps_key);
  return res.token;
}

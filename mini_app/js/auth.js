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

async function authenticate() {
  try { window._agency = JSON.parse(sessionStorage.getItem('agency') || 'null'); } catch (e) { /* ignore */ }
  // The handshake carries the public settings, and the token is cached — so on a
  // second open the settings have to come back from storage or the map would
  // silently disappear for everyone who did not just log in.
  try { Maps.setKey(sessionStorage.getItem(Maps.KEY_STORE)); } catch (e) { /* private mode */ }
  const cached = api.loadToken ? await api.loadToken() : null;
  if (cached) return cached;
  const res = await api.request('/auth/platform', 'POST', {
    platform: PlatformSDK.platform,
    init_data: PlatformSDK.initData,
    invite: inviteToken(),
  });
  api.setToken(res.token);
  // Kept for the Профиль header: an agency has a name, and a person reading the
  // screen should see it rather than its id.
  if (res.agency) {
    window._agency = res.agency;
    try { sessionStorage.setItem('agency', JSON.stringify(res.agency)); } catch (e) { /* private mode */ }
  }
  Maps.setKey(res.maps_key);
  try {
    if (res.maps_key) sessionStorage.setItem(Maps.KEY_STORE, res.maps_key);
    else sessionStorage.removeItem(Maps.KEY_STORE);
  } catch (e) { /* private mode */ }
  return res.token;
}

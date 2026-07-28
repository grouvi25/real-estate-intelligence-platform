// Mini App storage tests. TZ 33.1 / 35.8: the JWT lives in Telegram
// CloudStorage, falling back to sessionStorage -- never localStorage.
//
// The Mini App is plain script files with no bundler, so the sources are loaded
// into a vm context with the browser globals stubbed. Run: node --test mini_app/tests
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    _data: data,
  };
}

/** Load platform_init.js + api_client.js into a fresh context. */
function load({ cloudStorage = null, localSeed = null } = {}) {
  const sessionStorage = memoryStorage();
  const localStorage = memoryStorage();
  if (localSeed) localStorage.setItem('jwt_token', localSeed);

  const window = { REIP_CONFIG: { apiUrl: '' } };
  if (cloudStorage) window.Telegram = { WebApp: { ready() {}, expand() {}, CloudStorage: cloudStorage } };

  const ctx = vm.createContext({
    window, sessionStorage, localStorage, console,
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    escape, unescape, decodeURIComponent, JSON, Promise, Buffer, String,
  });
  ctx.globalThis = ctx;

  for (const f of ['platform_init.js', 'js/api_client.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  // Top-level `const` lands in the context's global lexical scope, not on the
  // context object, so it has to be read back by evaluating the name -- the same
  // scope classic browser scripts share.
  const evaluate = (expr) => vm.runInContext(expr, ctx);
  return { evaluate, sessionStorage, localStorage };
}

/** Callback-based stub of Telegram's CloudStorage. */
function cloudStub() {
  const data = new Map();
  return {
    getItem: (k, cb) => cb(null, data.has(k) ? data.get(k) : null),
    setItem: (k, v, cb) => { data.set(k, v); cb(null, true); },
    removeItem: (k, cb) => { data.delete(k); cb(null, true); },
    _data: data,
  };
}

test('falls back to sessionStorage outside Telegram, never localStorage', async () => {
  const { evaluate, sessionStorage, localStorage } = load();

  await evaluate('StorageAdapter').set('jwt_token', 'abc');
  assert.strictEqual(await evaluate('StorageAdapter').get('jwt_token'), 'abc');
  assert.strictEqual(sessionStorage.getItem('jwt_token'), 'abc');
  assert.strictEqual(localStorage.getItem('jwt_token'), null);

  await evaluate('StorageAdapter').remove('jwt_token');
  assert.strictEqual(await evaluate('StorageAdapter').get('jwt_token'), null);
});

test('prefers Telegram CloudStorage when available', async () => {
  const cloud = cloudStub();
  const { evaluate, sessionStorage } = load({ cloudStorage: cloud });

  await evaluate('StorageAdapter').set('jwt_token', 'cloud-token');
  assert.strictEqual(cloud._data.get('jwt_token'), 'cloud-token');
  assert.strictEqual(await evaluate('StorageAdapter').get('jwt_token'), 'cloud-token');
  // Nothing leaks into the per-session store when CloudStorage is in play.
  assert.strictEqual(sessionStorage.getItem('jwt_token'), null);

  await evaluate('StorageAdapter').remove('jwt_token');
  assert.strictEqual(cloud._data.has('jwt_token'), false);
});

test('a CloudStorage read error yields null rather than throwing', async () => {
  const failing = {
    getItem: (k, cb) => cb(new Error('cloud down')),
    setItem: (k, v, cb) => cb(null, true),
    removeItem: (k, cb) => cb(null, true),
  };
  const { evaluate } = load({ cloudStorage: failing });
  assert.strictEqual(await evaluate('StorageAdapter').get('jwt_token'), null);
});

test('an old localStorage token is purged on load', async () => {
  // Builds before TZ 35.8 persisted the JWT on the device; it must not linger.
  const { localStorage } = load({ localSeed: 'stale-token' });
  assert.strictEqual(localStorage.getItem('jwt_token'), null);
});

test('setToken decodes claims and persists; loadToken restores them', async () => {
  const { evaluate } = load({ cloudStorage: cloudStub() });
  const claims = { sub: 'manager-1', agency_id: 'agency-7' };
  const token = 'h.' + Buffer.from(JSON.stringify(claims)).toString('base64') + '.s';

  evaluate('api').setToken(token);
  assert.strictEqual(evaluate('api').managerId, 'manager-1');
  assert.strictEqual(evaluate('api').agencyId, 'agency-7');

  // A fresh page load: no in-memory token, restored from storage.
  evaluate('api').token = null;
  evaluate('api').agencyId = null;
  assert.strictEqual(await evaluate('api').loadToken(), token);
  assert.strictEqual(evaluate('api').agencyId, 'agency-7');
});

test('loadToken returns null when nothing is stored', async () => {
  const { evaluate } = load();
  assert.strictEqual(await evaluate('api').loadToken(), null);
});

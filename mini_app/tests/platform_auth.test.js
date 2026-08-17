// Getting into the cabinet, and being told the truth when you cannot.
//
// Both halves of this file come from one complaint: a manager opened the Mini
// App inside Telegram and was told to open it inside Telegram. The reason was
// not Telegram at all -- the server had refused him for having no invitation
// and said so in Russian, and the API client threw away the sentence and
// threw "API 403", which the screen could only render as its default advice.
//
// Same harness as storage_adapter.test.js: plain scripts in a vm context.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');

// A launch payload of the shape Telegram actually sends: percent-encoded, with
// the user as JSON inside it.
const SIGNED = 'query_id=AAE&user=' + encodeURIComponent('{"id":7503416516,"first_name":"Миша"}')
  + '&auth_date=1754900000&hash=abc';

function load({ hash = '', search = '', bridge = undefined, respond = null } = {}) {
  const location = { hash, search };
  const window = { REIP_CONFIG: { apiUrl: '' } };
  if (bridge) window.Telegram = { WebApp: bridge };

  const ctx = vm.createContext({
    window, location, console, URLSearchParams, JSON, Promise, String,
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { removeItem() {} },
    fetch: respond || (async () => ({ ok: true, status: 200, json: async () => ({}) })),
  });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'platform_init.js'), 'utf8'), ctx,
                  { filename: 'platform_init.js' });
  return { evaluate: (expr) => vm.runInContext(expr, ctx), location };
}

/** A bridge as telegram-web-app.js leaves it. */
const bridgeWith = (initData) => ({
  initData,
  initDataUnsafe: initData ? { user: { id: 7503416516, first_name: 'Миша' } } : {},
  colorScheme: 'dark',
  ready() {}, expand() {},
});

test('the bridge, when it is there, is what answers', () => {
  const { evaluate } = load({ hash: '#tgWebAppData=x', bridge: bridgeWith(SIGNED) });
  assert.strictEqual(evaluate('PlatformSDK').platform, 'telegram');
  assert.strictEqual(evaluate('PlatformSDK').initData, SIGNED);
});

test('telegram.org unreachable: the signature is still in the URL', () => {
  // telegram-web-app.js is fetched over the network. When that request does not
  // arrive there is no window.Telegram at all -- and the app used to conclude it
  // was in a browser and send init_data "mock", which the server can only
  // refuse. Telegram's own launch parameters are right there in the fragment.
  const { evaluate } = load({
    hash: '#tgWebAppData=' + encodeURIComponent(SIGNED) + '&tgWebAppVersion=8.0',
  });
  assert.strictEqual(evaluate('PlatformSDK').platform, 'telegram');
  assert.strictEqual(evaluate('PlatformSDK').initData, SIGNED);
  assert.strictEqual(evaluate('PlatformSDK').user.first_name, 'Миша');
});

test('the launch parameters survive the router rewriting the hash', () => {
  // Router.start() replaces the fragment with #/dashboard within a tick of
  // boot. A token expires hours later, and re-authenticating then must not
  // depend on a fragment that is long gone.
  const { evaluate, location } = load({ hash: '#tgWebAppData=' + encodeURIComponent(SIGNED) });
  location.hash = '#/leads/42';
  assert.strictEqual(evaluate('PlatformSDK').initData, SIGNED);
});

test('a bridge that fills in late is read again, not remembered empty', () => {
  const bridge = bridgeWith('');
  const { evaluate } = load({ hash: '#tgWebAppVersion=8.0', bridge });
  assert.strictEqual(evaluate('PlatformSDK').initData, '');
  bridge.initData = SIGNED;
  assert.strictEqual(evaluate('PlatformSDK').initData, SIGNED);
});

test('a plain browser is still a plain browser', () => {
  const { evaluate } = load();
  assert.strictEqual(evaluate('PlatformSDK').platform, 'web');
  assert.strictEqual(evaluate('PlatformSDK').inTelegram, false);
});

test('MAX is recognised through the bridge it actually installs', () => {
  // MAX Bridge puts the bridge in window.WebApp. The app used to look for
  // window.MAX.WebApp -- an object MAX never creates -- so inside MAX it
  // decided it was an ordinary browser, sent no signature, and every login
  // was refused.
  const window = {
    REIP_CONFIG: { apiUrl: '' },
    WebApp: {
      initData: SIGNED,
      initDataUnsafe: { user: { id: 7503416516, first_name: 'Миша' } },
      ready() {}, close() {},
    },
  };
  const ctx = vm.createContext({
    window, location: { hash: '', search: '' }, console, URLSearchParams, JSON,
    Promise, String,
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { removeItem() {} },
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'platform_init.js'), 'utf8'), ctx,
                  { filename: 'platform_init.js' });

  const sdk = vm.runInContext('PlatformSDK', ctx);
  assert.strictEqual(sdk.platform, 'max');
  assert.strictEqual(sdk.initData, SIGNED);
  assert.strictEqual(sdk.user.first_name, 'Миша');
});

test('a refusal reaches the screen in the words the server used', async () => {
  const { evaluate } = load({
    respond: async () => ({
      ok: false, status: 403,
      json: async () => ({ error: 'Нужна ссылка-приглашение от владельца агентства',
                           code: 'INVITE_REQUIRED' }),
    }),
  });
  await assert.rejects(
    () => evaluate('api').request('/auth/platform', 'POST', {}),
    (err) => {
      assert.strictEqual(err.message, 'Нужна ссылка-приглашение от владельца агентства');
      assert.strictEqual(err.code, 'INVITE_REQUIRED');
      assert.strictEqual(err.status, 403);
      return true;
    },
  );
});

test("FastAPI's own refusals come through as well", async () => {
  const { evaluate } = load({
    respond: async () => ({ ok: false, status: 401,
                            json: async () => ({ detail: 'Invalid platform signature' }) }),
  });
  await assert.rejects(
    () => evaluate('api').request('/auth/platform', 'POST', {}),
    (err) => err.message === 'Invalid platform signature' && err.status === 401,
  );
});

test('a failure with no JSON in it still says something', async () => {
  const { evaluate } = load({
    respond: async () => ({ ok: false, status: 502,
                            json: async () => { throw new Error('not json'); } }),
  });
  await assert.rejects(() => evaluate('api').request('/health'),
                       (err) => err.message === 'API 502' && err.status === 502);
});

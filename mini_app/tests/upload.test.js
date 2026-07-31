// Catalogue upload from the Mini App. Matching, pitches and offers all read
// from properties, so loading inventory had to stop being a developer task.
//
// Same harness as storage_adapter.test.js: the sources are plain scripts, loaded
// into a vm context with the browser globals stubbed.
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
  };
}

class FakeFormData {
  constructor() { this.entries = []; }
  append(k, v) { this.entries.push([k, v]); }
  get(k) { const e = this.entries.find((x) => x[0] === k); return e && e[1]; }
}

/** Load the client with a scripted fetch; returns the recorded calls. */
function load({ responses = [] } = {}) {
  const calls = [];
  let call = 0;

  const window = { REIP_CONFIG: { apiUrl: '' } };
  const ctx = vm.createContext({
    window,
    sessionStorage: memoryStorage(),
    localStorage: memoryStorage(),
    console,
    location: { search: '' },
    URLSearchParams,
    FormData: FakeFormData,
    fetch: async (url, options) => {
      calls.push({ url, options });
      const r = responses[Math.min(call++, responses.length - 1)] || { status: 200, body: {} };
      return {
        ok: r.status >= 200 && r.status < 300,
        status: r.status,
        json: async () => r.body,
      };
    },
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    escape, unescape, decodeURIComponent, JSON, Promise, Buffer, String, Object,
  });

  for (const file of ['platform_init.js', 'js/api_client.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, file), 'utf8'), ctx, { filename: file });
  }
  return { ctx, calls, evaluate: (expr) => vm.runInContext(expr, ctx) };
}

test('upload posts multipart and does not set Content-Type itself', async () => {
  // The browser must set it, or the multipart boundary is wrong and the server
  // cannot parse the file.
  const { calls, evaluate } = load({ responses: [{ status: 200, body: { created: 3 } }] });
  evaluate("api.setToken('h.eyJhZ2VuY3lfaWQiOiJhIiwic3ViIjoibSJ9.s')");

  const result = await evaluate(
    "window.API.importProperties({ name: 'catalogue.xlsx' }, true)");

  assert.strictEqual(result.created, 3);
  assert.strictEqual(calls.length, 1);
  assert.match(calls[0].url, /\/api\/properties\/import$/);
  assert.strictEqual(calls[0].options.method, 'POST');
  assert.strictEqual(calls[0].options.headers['Content-Type'], undefined);
  assert.match(calls[0].options.headers['Authorization'], /^Bearer /);
});

test('the dry-run flag reaches the server', async () => {
  const { calls, evaluate } = load({ responses: [{ status: 200, body: {} }] });

  await evaluate("window.API.importProperties({ name: 'c.csv' }, true)");
  assert.strictEqual(calls[0].options.body.get('dry_run'), 'true');

  await evaluate("window.API.importProperties({ name: 'c.csv' }, false)");
  assert.strictEqual(calls[1].options.body.get('dry_run'), 'false');
});

test('the file and optional geo are attached', async () => {
  const { calls, evaluate } = load({ responses: [{ status: 200, body: {} }] });

  await evaluate("window.API.importProperties({ name: 'c.csv' }, false, 'geo-1')");
  const body = calls[0].options.body;
  assert.strictEqual(body.get('file').name, 'c.csv');
  assert.strictEqual(body.get('geo_location_id'), 'geo-1');

  await evaluate("window.API.importProperties({ name: 'c.csv' }, false)");
  assert.strictEqual(calls[1].options.body.get('geo_location_id'), undefined);
});

test('a rejected file surfaces the server message, not a status code', async () => {
  // The import explains what is wrong with the file; "API 400" would not.
  const { evaluate } = load({
    responses: [{ status: 400, body: { detail: 'в файле нет строк с данными' } }],
  });

  await assert.rejects(
    () => evaluate("window.API.importProperties({ name: 'empty.csv' }, true)"),
    /в файле нет строк с данными/);
});

test('a failure without a JSON body still reports the status', async () => {
  const { evaluate } = load({ responses: [{ status: 500, body: null }] });

  await assert.rejects(
    () => evaluate("window.API.importProperties({ name: 'c.csv' }, true)"),
    /500/);
});

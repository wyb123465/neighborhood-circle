const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise request ordering with a fake DOM and deferred network responses.
// Map rendering is stubbed here; the browser acceptance check covers Leaflet.
function harness() {
  const elements = new Map();
  const pending = [];
  const rendered = [];
  let isValid = true;
  function element(selector) {
    if (!elements.has(selector)) {
      elements.set(selector, {
        value: selector === '#community' ? 'bridge-demo' : selector === '#speed' ? '80' : '15',
        hidden: false,
        textContent: '',
        attrs: {},
        events: {},
        addEventListener(name, fn) {
          this.events[name] = fn;
        },
        setAttribute(name, value) {
          this.attrs[name] = value;
        },
        reportValidity() {
          return isValid;
        },
        classList: { toggle() {} },
      });
    }
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: {
      querySelector: element,
      querySelectorAll: (selector) => (selector === '[name="category"]:checked' ? [{ value: '养老' }] : []),
    },
    window: {},
    URLSearchParams,
    AbortController,
    AbortSignal: { timeout: () => new AbortController().signal },
    setTimeout: () => 0,
    clearTimeout() {},
    fetch: (url, options) =>
      new Promise((resolve, reject) => pending.push({ url, options, resolve, reject })),
    capture: (result) => rendered.push(result),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8'), context);
  vm.runInContext('render = (result) => capture(result)', context);
  return {
    elements,
    pending,
    rendered,
    element,
    invalid() {
      isValid = false;
    },
    run: (script) => vm.runInContext(script, context),
    answer(request, id = 'result') {
      request.resolve({ ok: true, json: async () => ({ id, parameters: { center: '5,5' } }) });
    },
  };
}

test('invalid parameters abort an earlier request and reject its late result', async () => {
  const h = harness();
  const first = h.run('load()');
  const request = h.pending.at(-1);
  h.invalid();
  await h.run('load()');
  assert.equal(request.options.signal.aborted, true);
  h.answer(request, 'old');
  await first;
  assert.equal(h.rendered.length, 0);
  assert.equal(h.element('#results').hidden, true);
  assert.equal(h.run('state.valid'), false);
});

test('only the latest valid request may render', async () => {
  const h = harness();
  const first = h.run('load()');
  const old = h.pending.at(-1);
  const second = h.run('load()');
  h.answer(h.pending.at(-1), 'new');
  await second;
  h.answer(old, 'old');
  await first;
  assert.deepEqual(
    h.rendered.map((r) => r.id),
    ['new'],
  );
  assert.equal(h.element('#results').hidden, false);
  assert.equal(h.run('state.valid'), true);
});

test('typing invalidates the previous report before the change event', async () => {
  const h = harness();
  const ready = h.run('load()');
  h.answer(h.pending.at(-1));
  await ready;
  h.element('#minutes').events.input();
  assert.equal(h.run('state.valid'), false);
  assert.equal(h.element('#results').hidden, true);
});

test('request and rendering failures hide stale results', async () => {
  const h = harness();
  const failed = h.run('load()');
  h.pending.at(-1).reject(new Error('offline'));
  await failed;
  assert.equal(h.element('#error').hidden, false);
  assert.equal(h.run('state.valid'), false);
  h.run("render = () => { throw new Error('map unavailable'); }");
  const renderFailed = h.run('load()');
  h.answer(h.pending.at(-1));
  await renderFailed;
  assert.equal(h.element('#results').hidden, true);
  assert.equal(h.element('#error').hidden, false);
  assert.equal(h.run('state.valid'), false);
});

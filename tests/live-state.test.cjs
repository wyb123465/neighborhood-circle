const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function harness() {
  const elements = new Map(), pending = [], rendered = [];
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: ({ "#address": "测试地址", "#city": "", "#latitude": "", "#longitude": "", "#minutes": "15", "#gridM": "200" })[selector] || "",
      hidden: false, disabled: false, events: {}, textContent: "",
      addEventListener(name, fn) { this.events[name] = fn; },
      setAttribute() {}, reportValidity() { return true; },
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: { querySelector: element, querySelectorAll: () => ["#address", "#city", "#latitude", "#longitude", "#minutes", "#gridM"].map(element) },
    window: {}, URLSearchParams, AbortController, AbortSignal,
    setTimeout: () => 0, clearTimeout() {},
    fetch: (url, options) => new Promise((resolve, reject) => pending.push({ url, options, resolve, reject })),
    capture: (result) => rendered.push(result),
  });
  vm.runInContext(fs.readFileSync(require("node:path").join(__dirname, "../live.js"), "utf8"), context);
  vm.runInContext("render = (result) => { state.last = result; capture(result); }; state.configured = true;", context);
  return { element, pending, rendered, run: (s) => vm.runInContext(s, context), answer: (r, body) => r.resolve({ ok: true, json: async () => body }) };
}
const result = { mode: "live-replay", center: { lat: 31.2, lng: 121.4 }, parameters: { minutes: 15 }, summary: {} };

test("editing live inputs aborts the pending request and blocks stale exports", async () => {
  const h = harness(), running = h.run("run()");
  const request = h.pending.at(-1);
  h.element("#minutes").events.input();
  assert.equal(request.options.signal.aborted, true);
  h.answer(request, result);
  await running;
  assert.equal(h.rendered.length, 0);
  assert.equal(h.run("state.valid"), false);
  assert.equal(h.element("#liveReport").disabled, true);
});

test("new live request wins when an older isochrone arrives late", async () => {
  const h = harness(), first = h.run("run()");
  const old = h.pending.at(-1), second = h.run("run()");
  h.answer(h.pending.at(-1), { ...result, id: "new" });
  await new Promise(setImmediate);
  h.answer(h.pending.at(-1), { facilities: [], warnings: [] });
  await second;
  h.answer(old, { ...result, id: "old" });
  await first;
  assert.deepEqual(h.rendered.map((r) => r.id), ["new"]);
  assert.equal(h.run("state.valid"), true);
});

test("recorded preset restores city and identifies replay without an AK", async () => {
  const h = harness();
  h.answer(h.pending[0], { configured: true, replay_mode: true, query_profile_valid: true, effective_query_profile: "narrow", replay_preset: { address: "录制地址", city: "上海市", minutes: 15, grid_m: 200 } });
  await new Promise(setImmediate);
  assert.equal(h.element("#city").value, "上海市");
  assert.equal(h.element("#city").readOnly, true);
  assert.match(h.element("#liveModeBadge").textContent, /回放/);
});

test("coordinate requests omit address and preserve both coordinates", async () => {
  const h = harness();
  h.element("#latitude").value = "31.2";
  h.element("#longitude").value = "121.4";
  const running = h.run("run()");
  const req = h.pending.at(-1);
  assert.match(req.url, /lat=31.2&lng=121.4/);
  assert.doesNotMatch(req.url, /address=/);
  req.reject(new Error("offline"));
  await running;
  assert.equal(h.run("state.valid"), false);
});

test("replay reports identify historical data and use only the coarse denominator", () => {
  const h = harness();
  const report = h.run(`buildReportMarkdown({ mode: 'live-replay', replay: {recorded_at: '2026-10-03'}, center: {lat:31.2,lng:121.4}, parameters:{minutes:15,grid_spacing_m:675}, summary:{known:56,reachable:10,unknown:0,coarse_ratio_pct:12.5,coarse:{known:24,reachable:3},refined:{count:32,reachable:7}}, warnings:[], evidence_id:'example',method_version:'v3',source:'baidu' },null,null)`);
  assert.match(report, /历史录制回放/);
  assert.match(report, /2026-10-03/);
  assert.match(report, /24 个已知粗网格点中 3 个可达/);
  assert.doesNotMatch(report, /56 个已知粗网格点/);
});

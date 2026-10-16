const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  let resolve;
  const frames = [],
    locations = [],
    analysis = { id: 'same', type: 'live', inspection: {} };
  const ui = {
    result: { snapshots: { same: { analysis, comparison: [] } } },
    analysis,
    geoReady: new Promise((r) => {
      resolve = r;
    }),
    map: { invalidateSize() {}, fitBounds() {} },
    geo: { active: true, fit() {}, focusOffset: (x, y) => locations.push([x, y]) },
  };
  const source = fs.readFileSync(path.join(__dirname, '../assistant.js'), 'utf8');
  // Exercise the production handler without booting the page's unrelated UI.
  const handler = source.slice(
    source.indexOf('async function focusFact('),
    source.indexOf('async function invalidate('),
  );
  const context = {
    ui,
    analysisKey: (value) => value?.id,
    setResultsView: (view, ready) => frames.push(ready),
    L: { circleMarker: () => ({ addTo: () => ({ remove() {} }) }) },
    text() {},
    $: () => ({ scrollIntoView() {} }),
  };
  vm.createContext(context);
  vm.runInContext(handler, context);
  const fact = (x) => ({
    snapshot_id: 'same',
    target: { type: 'point', x, y: 0 },
    text: 'candidate',
    evidence_id: 'same',
  });
  return { ui, frames, locations, resolve: () => resolve(), focus: (x) => context.focusFact(fact(x)) };
}

test('only the latest evidence selection focuses after the SDK and view are ready', async () => {
  const h = harness();
  const older = h.focus(-1000),
    newer = h.focus(500);
  assert.equal(h.frames.length, 0);
  assert.equal(h.locations.length, 0);
  h.resolve();
  await Promise.all([older, newer]);
  assert.equal(h.locations.length, 0);
  assert.equal(h.frames.length, 1);
  h.frames[0]();
  assert.deepEqual(h.locations, [[500, 0]]);
});

test('resetting the analysis before the view frame prevents a late recenter', async () => {
  const h = harness();
  h.resolve();
  await h.focus(-1000);
  h.ui.analysis = null;
  h.frames[0]();
  assert.equal(h.locations.length, 0);
});

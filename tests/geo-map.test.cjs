const test = require('node:test');
const assert = require('node:assert/strict');
const { offsetToBD, squareCorners, heatColor, buildScene } = require('../geo-map.js');
const center = { lat: 31.2, lng: 121.4 };
function displayHarness() {
  const saved = Object.fromEntries(
    ['document', 'ResizeObserver', 'fetch', 'BMapGL'].map((k) => [k, global[k]]),
  );
  const element = () => ({
    hidden: false,
    disabled: false,
    attrs: {},
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
    append() {},
    before() {},
    after() {},
    addEventListener() {},
    dispatchEvent() {},
  });
  global.document = { createElement: element };
  global.ResizeObserver = class {
    observe() {}
  };
  const overlays = [];
  class Overlay {
    constructor() {
      this.visible = true;
    }
    addEventListener() {}
    show() {
      this.visible = true;
    }
    hide() {
      this.visible = false;
    }
  }
  global.BMapGL = {
    Point: class {
      constructor(lng, lat) {
        this.lng = lng;
        this.lat = lat;
      }
    },
    Polygon: Overlay,
    Circle: Overlay,
    Label: class extends Overlay {
      setStyle() {}
      setZIndex() {}
    },
    Size: class {},
    InfoWindow: class {
      constructor(html) {
        this.html = html;
      }
    },
    Map: class {
      centerAndZoom() {}
      enableScrollWheelZoom() {}
      clearOverlays() {
        overlays.length = 0;
      }
      addOverlay(o) {
        overlays.push(o);
      }
      setViewport() {}
      setCenter(point) {
        this.center = point;
      }
      openInfoWindow(info) {
        this.info = info;
      }
    },
  };
  global.fetch = async () => ({
    ok: true,
    json: async () => ({ configured: true, browser_ak: 'test-browser-key' }),
  });
  const analysis = {
    type: 'live',
    inspection: {
      community: { center },
      parameters: { minutes: 15 },
      facilities: [
        {
          name: '<img src=x onerror=alert(1)>',
          location: center,
          route: { walk_minutes: 4 },
          categories: ['医疗'],
        },
      ],
    },
  };
  return {
    local: element(),
    analysis,
    restore() {
      for (const [key, value] of Object.entries(saved))
        value === undefined ? delete global[key] : (global[key] = value);
    },
  };
}
test('BD09 evidence keeps the origin, north and east in their correct axes', () => {
  assert.deepEqual(offsetToBD(center, 0, 0), center);
  const east = offsetToBD(center, 1000, 0),
    north = offsetToBD(center, 0, 1000);
  assert.ok(east.lng > center.lng && east.lat === center.lat);
  assert.ok(north.lat > center.lat && north.lng === center.lng);
  assert.throws(() => offsetToBD({ lat: NaN, lng: 121 }, 0, 0));
});
test('sample cells are clipped to the actual measured scope', () => {
  const corners = squareCorners(center, 950, 0, 100, 1000);
  assert.equal(corners.length, 4);
  assert.ok(corners.every((p) => p.lng <= offsetToBD(center, 1000, 0).lng));
  assert.deepEqual(squareCorners(center, 2000, 0, 100, 1000), []);
});
test('unknown remains distinct even when an old duration is present', () => {
  assert.equal(heatColor('unknown', 100, 900), '#c7a23a');
  assert.notEqual(heatColor('reachable', 100, 900), heatColor('unreachable', 1000, 900));
});
test('geographic scene preserves raw evidence and does not invent coordinates for synthetic data', () => {
  assert.equal(buildScene({ type: 'synthetic' }), null);
  const analysis = {
    type: 'live',
    inspection: {
      community: { center },
      parameters: { minutes: 15 },
      facilities: [],
      blind_spots: {
        grid_spacing_m: 250,
        radius_m: 1000,
        points: [{ dx_m: 0, dy_m: 0, missing_kinds: ['菜市场'], unknown_kinds: ['药店'] }],
      },
    },
    isochrone: {
      parameters: { extent_m: 1350, grid_spacing_m: 400, minutes: 15 },
      points: [{ ...center, dx_m: 0, dy_m: 0, status: 'unknown', generation: 'coarse' }],
    },
  };
  const before = JSON.stringify(analysis),
    scene = buildScene(analysis);
  assert.equal(scene.samples[0].status, 'unknown');
  assert.equal(scene.gaps[0].color, '#c7a23a');
  assert.deepEqual(scene.samples[0].point, center);
  assert.equal(JSON.stringify(analysis), before);
});

test('late map configuration cannot reopen evidence after the user resets', async () => {
  const harness = displayHarness();
  try {
    let resolve;
    global.fetch = () =>
      new Promise((r) => {
        resolve = r;
      });
    const { GeoEvidenceView } = require('../geo-map.js');
    const view = new GeoEvidenceView(harness.local);
    const pending = view.setData(harness.analysis);
    view.reset();
    resolve({ ok: true, json: async () => ({ configured: true, browser_ak: 'test-browser-key' }) });
    await pending;
    assert.equal(view.active, false);
    assert.equal(view.map, undefined);
    assert.equal(harness.local.hidden, false);
  } finally {
    harness.restore();
  }
});

test('geographic layer toggles work and vendor POI text cannot become HTML', async () => {
  const harness = displayHarness();
  try {
    const { GeoEvidenceView } = require('../geo-map.js');
    const view = new GeoEvidenceView(harness.local);
    await view.setData(harness.analysis);
    assert.equal(view.active, true);
    view.toggle('facilities', false);
    assert.ok(view.overlays.facilities.every((o) => !o.visible));
    assert.equal(view.overlays.origin.length, 2);
    assert.ok(view.overlays.origin.every((o) => o.visible));
    view.focusOrigin();
    assert.equal(view.map.center.lng, center.lng);
    assert.equal(view.map.center.lat, center.lat);
    assert.ok(view.map.info.html.includes('起点'));
    view.focusFacility(0);
    assert.ok(view.overlays.facilities.every((o) => o.visible));
    assert.ok(view.map.info.html.includes('&lt;img'));
    assert.ok(!view.map.info.html.includes('<img'));
    view.reset();
    assert.equal(view.active, false);
  } finally {
    harness.restore();
  }
});

test('rapid fit, candidate focus and zoom keep the latest location after queued animations settle', async () => {
  const harness = displayHarness();
  try {
    const { GeoEvidenceView } = require('../geo-map.js');
    const view = new GeoEvidenceView(harness.local);
    await view.setData(harness.analysis);
    const pending = [];
    let location = center,
      zoom = 15;
    const move = (point, animate) => {
      const apply = () => {
        location = point;
      };
      animate ? pending.push(apply) : apply();
    };
    view.map = {
      setViewport(bounds, options) {
        move(center, options?.enableAnimation !== false);
      },
      setCenter(point, options) {
        move(point, !options?.noAnimation);
      },
      panTo(point) {
        move(point, true);
      },
      getZoom: () => zoom,
      setZoom(value, options) {
        const apply = () => {
          zoom = value;
        };
        options?.noAnimation ? apply() : pending.push(apply);
      },
    };
    view.fit();
    view.focusOffset(-1000, 0);
    view.zoom(1);
    view.zoom(1);
    const expected = offsetToBD(center, -1000, 0);
    assert.equal(location.lng, expected.lng);
    assert.equal(location.lat, expected.lat);
    assert.equal(zoom, 17);
    pending.reverse().forEach((apply) => apply());
    assert.equal(location.lng, expected.lng);
    assert.equal(location.lat, expected.lat);
    assert.equal(zoom, 17);
  } finally {
    harness.restore();
  }
});

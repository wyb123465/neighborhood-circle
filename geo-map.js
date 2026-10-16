/* Geographic evidence uses the same BD-09 coordinates as the route evidence. */
(function (root) {
  'use strict';
  const METERS_PER_DEGREE = 111320;
  const finitePoint = (p) =>
    p && Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 85 && Math.abs(p.lng) <= 180;
  function offsetToBD(center, x, y) {
    if (!finitePoint(center) || !Number.isFinite(x) || !Number.isFinite(y)) throw new Error('地图坐标无效');
    return {
      lng: center.lng + x / (METERS_PER_DEGREE * Math.cos((center.lat * Math.PI) / 180)),
      lat: center.lat + y / METERS_PER_DEGREE,
    };
  }
  function squareCorners(center, x, y, half, extent) {
    if (![x, y, half, extent].every(Number.isFinite) || half <= 0 || extent <= 0) return [];
    const left = Math.max(-extent, x - half),
      right = Math.min(extent, x + half);
    const bottom = Math.max(-extent, y - half),
      top = Math.min(extent, y + half);
    if (left >= right || bottom >= top) return [];
    return [
      [left, bottom],
      [right, bottom],
      [right, top],
      [left, top],
    ].map(([dx, dy]) => offsetToBD(center, dx, dy));
  }
  function heatColor(status, duration, threshold) {
    if (status === 'unknown' || !Number.isFinite(duration)) return '#c7a23a';
    if (status !== 'reachable') return '#b76b7b';
    return duration <= threshold / 3 ? '#247254' : duration <= (threshold * 2) / 3 ? '#6ca981' : '#b1d3b9';
  }
  function buildScene(analysis, comparison = []) {
    if (analysis?.type !== 'live') return null;
    const inspection = analysis.inspection,
      iso = analysis.isochrone;
    const center = inspection?.community?.center || iso?.center;
    if (!finitePoint(center)) throw new Error('缺少有效的 BD-09 中心坐标');
    const extent = iso?.parameters?.extent_m || 1500;
    const threshold = (iso?.parameters?.minutes || inspection.parameters.minutes) * 60;
    const samples = (iso?.points || [])
      .map((p) => {
        const spacing = iso.parameters.grid_spacing_m / (p.generation === 'refined' ? 3 : 1);
        const corners = squareCorners(center, p.dx_m, p.dy_m, spacing / 2, extent);
        return {
          point: finitePoint(p) ? { lat: p.lat, lng: p.lng } : offsetToBD(center, p.dx_m, p.dy_m),
          corners,
          status: p.status,
          near: p.near_threshold,
          color: heatColor(p.status, p.duration_s, threshold),
          refined: p.generation === 'refined',
          title: `${p.generation === 'refined' ? '加密' : '均匀'}测时样点`,
          detail:
            p.status === 'unknown'
              ? '未知：未取得可靠路线耗时'
              : `${p.duration_s} 秒 / ${(p.duration_s / 60).toFixed(1)} 分钟 · ${p.status === 'reachable' ? '阈值内' : '阈值外'}${p.near_threshold ? ' · 近阈值待复核' : ''}`,
        };
      })
      .filter((p) => p.corners.length);
    const blind = inspection.blind_spots;
    const gaps = (blind?.points || [])
      .filter((p) => p.missing_kinds?.length)
      .map((p) => ({
        point: offsetToBD(center, p.dx_m, p.dy_m),
        corners: squareCorners(center, p.dx_m, p.dy_m, blind.grid_spacing_m / 2, blind.radius_m),
        color: p.unknown_kinds?.length ? '#c7a23a' : '#687872',
        title: '1公里专项缺口网格',
        detail: `缺少 ${p.missing_kinds.join('、')}；${p.unknown_kinds?.length ? '另有未知类别 ' + p.unknown_kinds.join('、') : '本次检索边界完整'}。直线口径，网格仅表示样点邻域。`,
      }))
      .filter((p) => p.corners.length);
    const facilities = (inspection.facilities || [])
      .map((f, index) => ({
        point: f.location,
        index,
        title: f.name,
        detail: `${(f.eligible_categories || f.categories || []).join('、')} · 步行 ${f.route?.walk_minutes ?? '未知'} 分钟；营业状态及入口待核验。`,
      }))
      .filter((f) => finitePoint(f.point));
    const rows = comparison.length
      ? comparison.map((r, i) => ({
          x: r.target.x,
          y: r.target.y,
          title: `候选参考点 ${i + 1}`,
          detail: r.category,
        }))
      : (blind?.recommendations || []).map((r) => ({
          x: r.dx_m,
          y: r.dy_m,
          title: `${r.kind}候选参考点 ${r.rank}`,
          detail: `已知缺口增益 ${r.gain_count} 点；非建设选址。`,
        }));
    const candidates = rows
      .filter((r) => Number.isFinite(r.x) && Number.isFinite(r.y))
      .map((r) => ({ ...r, point: offsetToBD(center, r.x, r.y) }));
    return {
      center,
      extent,
      samples,
      gaps,
      facilities,
      candidates,
      bounds: [offsetToBD(center, -extent, -extent), offsetToBD(center, extent, extent)],
    };
  }
  const escape = (value) =>
    String(value ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
  let sdkPromise;
  function loadSDK(key) {
    if (root.BMapGL) return Promise.resolve(root.BMapGL);
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script'),
        callback = 'neighborhoodBaiduReady';
      const cleanup = () => {
        clearTimeout(timer);
        delete root[callback];
      };
      const fail = () => {
        cleanup();
        script.remove();
        reject(new Error('地理地图暂未载入，已保留测时示意。'));
      };
      const timer = setTimeout(fail, 15000);
      root[callback] = () => {
        cleanup();
        root.BMapGL ? resolve(root.BMapGL) : reject(new Error('地图服务未就绪'));
      };
      script.onerror = fail;
      script.src = `https://api.map.baidu.com/api?v=1.0&type=webgl&ak=${encodeURIComponent(key)}&callback=${callback}`;
      document.head.append(script);
    }).catch((error) => {
      sdkPromise = null;
      throw error;
    });
    return sdkPromise;
  }
  class GeoEvidenceView {
    constructor(localElement, onFacility) {
      this.local = localElement;
      this.onFacility = onFacility;
      this.serial = 0;
      this.visibleGroups = {};
      this.overlays = {};
      this.active = false;
      this.controls = document.createElement('div');
      this.controls.className = 'geo-view-controls';
      this.controls.setAttribute('role', 'group');
      this.controls.setAttribute('aria-label', '地图呈现方式');
      this.geoButton = this.button('地理地图', () => this.show(true));
      this.localButton = this.button('测时示意', () => this.show(false));
      this.fitButton = this.button('显示全部', () => this.fit());
      this.minus = this.button('缩小', () => this.zoom(-1));
      this.plus = this.button('放大', () => this.zoom(1));
      this.note = document.createElement('p');
      this.note.className = 'geo-map-note quiet';
      this.note.setAttribute('role', 'status');
      this.canvas = document.createElement('div');
      this.canvas.id = localElement.id + 'Geographic';
      this.canvas.className = 'geo-evidence-map';
      this.canvas.hidden = true;
      this.canvas.setAttribute('aria-label', '百度地理地图：步行测时网格、设施及专项缺口');
      localElement.before(this.controls, this.note);
      localElement.after(this.canvas);
      this.controls.hidden = true;
      this.note.hidden = true;
      this.observer = new ResizeObserver(() => {
        if (this.active) this.map?.checkResize?.();
      });
      this.observer.observe(this.canvas);
    }
    button(label, action) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.addEventListener('click', action);
      this.controls.append(b);
      return b;
    }
    reset() {
      this.serial++;
      this.active = false;
      this.controls.hidden = true;
      this.note.hidden = true;
      this.canvas.hidden = true;
      this.local.hidden = false;
      this.show(false);
    }
    async setData(analysis, comparison = []) {
      this.reset();
      const serial = this.serial;
      if (analysis?.type !== 'live') return;
      this.controls.hidden = false;
      this.note.hidden = false;
      this.geoButton.disabled = true;
      this.note.textContent = '正在检查地理地图…';
      try {
        const scene = buildScene(analysis, comparison);
        const response = await fetch('/api/map/display-config', { cache: 'no-store' });
        if (!response.ok) throw new Error('地图配置读取失败');
        const config = await response.json();
        if (serial !== this.serial) return;
        if (!config.configured) {
          this.note.textContent = '地理底图尚未启用；当前为测时网格示意，可通过设施详情打开官方地图核对。';
          return;
        }
        const sdk = await loadSDK(config.browser_ak);
        if (serial !== this.serial) return;
        this.scene = scene;
        this.geoButton.disabled = false;
        this.show(true);
        if (!this.map) {
          this.map = new sdk.Map(this.canvas.id);
          this.map.centerAndZoom(new sdk.Point(scene.center.lng, scene.center.lat), 15);
          this.map.enableScrollWheelZoom(true);
        }
        this.draw(sdk);
        this.fit();
        this.note.textContent =
          '百度道路底图 · BD-09；色块是测时样点邻域估计，灰格为1公里专项缺口，未知为琥珀色。设施列表可用键盘操作。';
      } catch (error) {
        if (serial === this.serial) {
          this.geoButton.disabled = true;
          this.show(false);
          this.note.textContent = '地理地图暂不可用，已保留测时示意与官方核对入口。';
        }
      }
    }
    show(geographic) {
      this.active = geographic && !this.geoButton.disabled;
      this.canvas.hidden = !this.active;
      this.local.hidden = this.active;
      this.geoButton.setAttribute('aria-pressed', String(this.active));
      this.localButton.setAttribute('aria-pressed', String(!this.active));
      for (const b of [this.fitButton, this.minus, this.plus]) b.hidden = !this.active;
      if (this.active) {
        this.map?.checkResize?.();
        this.fit();
      }
      this.local.dispatchEvent(new Event('geoviewchange'));
    }
    draw(sdk) {
      this.map.clearOverlays();
      this.overlays = { samples: [], gaps: [], review: [], facilities: [], candidates: [] };
      this.facilityRows = new Map();
      const point = (p) => new sdk.Point(p.lng, p.lat);
      const add = (group, overlay, row) => {
        this.overlays[group].push(overlay);
        this.map.addOverlay(overlay);
        if (row)
          overlay.addEventListener('click', () => {
            if (group === 'facilities') this.onFacility?.(row.index);
            this.open(row);
          });
      };
      for (const [group, rows] of [
        ['samples', this.scene.samples],
        ['gaps', this.scene.gaps],
      ])
        for (const row of rows) {
          const overlay = new sdk.Polygon(row.corners.map(point), {
            strokeColor: row.color,
            strokeWeight: 1,
            strokeOpacity: row.refined ? 0.5 : 0.12,
            fillColor: row.color,
            fillOpacity: row.refined ? 0.5 : 0.26,
            strokeStyle: row.refined ? 'dashed' : 'solid',
          });
          add(group, overlay, row);
          if (row.near)
            add(
              'review',
              new sdk.Circle(point(row.point), 22, {
                strokeColor: '#8b6b24',
                strokeWeight: 2,
                strokeStyle: 'dashed',
                fillOpacity: 0,
              }),
              row,
            );
        }
      for (const group of ['facilities', 'candidates'])
        for (const row of this.scene[group]) {
          add(
            group,
            new sdk.Circle(point(row.point), group === 'facilities' ? 23 : 32, {
              strokeColor: group === 'facilities' ? '#263d35' : '#8b6b24',
              fillColor: group === 'facilities' ? '#263d35' : '#8b6b24',
              strokeWeight: 2,
              fillOpacity: 0.9,
            }),
            row,
          );
          if (group === 'facilities') this.facilityRows.set(row.index, row);
        }
      add(
        'facilities',
        new sdk.Circle(point(this.scene.center), 12, {
          strokeColor: '#fff',
          fillColor: '#142b22',
          strokeWeight: 2,
          fillOpacity: 1,
        }),
        { point: this.scene.center, title: '本次体检中心', detail: '坐标 BD-09；设施统计以此中心算路。' },
      );
      for (const [group, visible] of Object.entries(this.visibleGroups)) this.toggle(group, visible);
    }
    open(row) {
      const sdk = root.BMapGL;
      this.map?.openInfoWindow(
        new sdk.InfoWindow(`<strong>${escape(row.title)}</strong><p>${escape(row.detail)}</p>`, {
          width: 250,
        }),
        new sdk.Point(row.point.lng, row.point.lat),
      );
    }
    focusFacility(index) {
      const row = this.facilityRows?.get(index);
      if (!this.active || !row) return;
      this.toggle('facilities', true);
      this.map.setCenter(new root.BMapGL.Point(row.point.lng, row.point.lat), { noAnimation: true });
      this.open(row);
    }
    focusOffset(x, y) {
      if (!this.active || !this.scene) return;
      const p = offsetToBD(this.scene.center, x, y);
      this.map.setCenter(new root.BMapGL.Point(p.lng, p.lat), { noAnimation: true });
    }
    toggle(group, visible) {
      this.visibleGroups[group] = visible;
      for (const overlay of this.overlays[group] || []) visible ? overlay.show() : overlay.hide();
    }
    fit() {
      if (this.active && this.map && this.scene)
        this.map.setViewport(
          this.scene.bounds.map((p) => new root.BMapGL.Point(p.lng, p.lat)),
          { margins: [30, 30, 30, 30], enableAnimation: false, delay: 0 },
        );
    }
    zoom(step) {
      if (this.active && this.map) this.map.setZoom(this.map.getZoom() + step, { noAnimation: true });
    }
  }
  const api = { offsetToBD, squareCorners, heatColor, buildScene, GeoEvidenceView };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NeighborhoodGeo = api;
})(typeof window !== 'undefined' ? window : globalThis);

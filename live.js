"use strict";
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const METERS_PER_DEG_LAT = 111320.0;
const lngScale = (lat) => METERS_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
const STATUS_COLORS = { reachable: "#197257", unreachable: "#b64759", unknown: "#c7a23a" };
const CATEGORY_COLORS = { 医疗: "medical", 养老: "care", 教育: "education", 购物: "shopping" };
const KIND_COLORS = { 菜市场: "shopping", 药店: "medical", 小学: "education" };
const state = { map: null, layers: null, last: null, lastInspect: null, lastInspectError: null, sequence: 0, toastTimer: 0, controller: null, valid: false, configured: false, request: null, replayPreset: null };
const isReplay = (result) => result?.mode === "live-replay";
const markdownCell = (value) => String(value ?? "未知").replace(/\|/g, "\\|").replace(/[\r\n]+/g, " ");

function setMode(replay, recordedAt) {
  $("#liveModeBadge").textContent = replay ? "历史录制回放 · 本次不联网" : "实时 API · 近似采样结果";
  $("#liveModeName").textContent = replay ? "历史回放" : "实时体检";
  $("#liveSubmitLabel").textContent = replay ? "回放体检" : "开始体检";
  $("#liveNavCurrent").textContent = replay ? "历史回放（当前）" : "实时模式（当前）";
  $("#liveSourceNote").textContent = replay
    ? `数据录制于 ${recordedAt || "未知时间"}，输入已载入录制参数；这是历史地图数据，不能反映当前营业状态。`
    : "按百度地图返回的步行耗时测量；网格与设施统计均保留未知状态，不代表人口覆盖率。";
}

function invalidate() {
  ++state.sequence;
  state.controller?.abort();
  state.controller = null;
  state.valid = false;
  state.last = null;
  state.lastInspect = null;
  state.lastInspectError = null;
  $("#liveResults").hidden = true;
  $("#liveReport").disabled = true;
  $("#liveExport").disabled = true;
  $("#liveForm").setAttribute("aria-busy", "false");
  $("#liveForm button[type='submit']").disabled = !state.configured;
}

function icons() { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 1.8, "aria-hidden": "true" } }); }
function notify(message) { const t = $("#liveToast"); t.textContent = message; t.hidden = false; clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => { t.hidden = true; }, 3600); }

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `服务响应异常 (${response.status})`); }
  return response.json();
}

function ensureMap() {
  if (state.map) return state.map;
  const map = L.map("liveMap", { crs: L.CRS.Simple, minZoom: -4, maxZoom: 1, zoomSnap: .25, zoomControl: false, attributionControl: false, preferCanvas: true });
  L.control.attribution({ prefix: false }).addAttribution("真实测时 · 局部坐标 / m").addTo(map);
  new ResizeObserver(() => map.invalidateSize()).observe($("#liveMap"));
  $("#liveFit").addEventListener("click", () => { const b = state.last?.bounds; if (b) map.fitBounds(b, { animate: false }); });
  $("#liveZoomIn").addEventListener("click", () => map.zoomIn(.5));
  $("#liveZoomOut").addEventListener("click", () => map.zoomOut(.5));
  state.map = map;
  return map;
}

function facilityOffsets(facilities, center) {
  const scale = lngScale(center.lat);
  return facilities.map((f) => {
    const dx = Math.round((f.location.lng - center.lng) * scale);
    const dy = Math.round((f.location.lat - center.lat) * METERS_PER_DEG_LAT);
    return { ...f, dx, dy };
  });
}

function renderBlindSpots(blindSpots, center, layers) {
  if (!blindSpots) {
    $("#liveBlindSpotSummary").textContent = "本次响应没有返回 1 公里专项检查。";
    $("#liveBlindSpotRows").innerHTML = "";
    $("#livePlanSummary").textContent = "本次响应没有返回规划候选点。";
    $("#liveBlindSpotRecommendations").innerHTML = "";
    return;
  }
  const knownGapPoints = blindSpots.points.filter((point) => point.known_gap);
  const confirmedGapPoints = blindSpots.points.filter((point) => point.status === "gap");
  const unknownPoints = blindSpots.points.filter((point) => point.status === "unknown");
  $("#liveBlindSpotSummary").textContent =
    `以中心点为圆心 ${blindSpots.radius_m} 米范围，按 ${blindSpots.grid_spacing_m} 米网格检查 ${blindSpots.sample_count} 个样点；` +
    `已知类别缺口样点 ${blindSpots.known_gap_count} 个，其中完整确认 ${confirmedGapPoints.length} 个；未知样点 ${unknownPoints.length} 个。`;
  $("#liveBlindSpotRows").innerHTML = Object.entries(blindSpots.kinds).map(([kind, row]) => {
    const value = row.status === "unknown" ? "未知" : `${row.gap_count}/${row.known_count ?? row.sample_count} · ${row.gap_ratio_pct}%`;
    const detail = `${row.facility_count} 处已检索设施；未知样点 ${row.unknown_count ?? 0}` + (row.reason ? `；${row.reason}` : "");
    return `<div class="blindspot-row"><span><i class="dot ${KIND_COLORS[kind] || "care"}"></i>${escapeHtml(kind)}</span><strong>${value}</strong><small>${escapeHtml(detail)}</small></div>`;
  }).join("");
  const recommendations = blindSpots.recommendations || [];
  $("#livePlanSummary").textContent = recommendations.length
    ? `按类别给出 ${recommendations.length} 个优先参考点；每个点显示可覆盖的已知缺口样点数。`
      + "未知类别不会参与候选点生成。"
    : "当前没有可生成的已知缺口候选点，或相关类别查询仍未知。";
  $("#liveBlindSpotRecommendations").innerHTML = recommendations.map((recommendation) => (
    `<div class="recommendation-row"><i class="dot ${KIND_COLORS[recommendation.kind] || "care"}"></i><span>${escapeHtml(recommendation.kind)} · 优先级 ${recommendation.rank}</span>` +
    `<strong>+${recommendation.gain_count} 点</strong><small>参考位置 (${recommendation.dx_m}, ${recommendation.dy_m}) m · 覆盖 ${recommendation.gain_ratio_pct}% 已知缺口样点</small></div>`
  )).join("");

  const grid = blindSpots.grid_spacing_m * .34;
  for (const point of knownGapPoints) {
    const bounds = [[point.dy_m - grid, point.dx_m - grid], [point.dy_m + grid, point.dx_m + grid]];
    const fillColor = point.status === "gap" ? "#687872" : "#c7a23a";
    const unknown = point.unknown_kinds.length ? `；未知：${point.unknown_kinds.join("、")}` : "";
    L.rectangle(bounds, { color: fillColor, weight: 1, dashArray: "3 3", fillColor, fillOpacity: .25 })
      .bindTooltip(`1 公里专项盲区 · ${point.missing_kinds.join("、")}${unknown}`)
      .addTo(layers);
  }
  for (const recommendation of recommendations) {
    const icon = L.divIcon({
      className: "",
      html: `<span class="plan-pin">${recommendation.rank}</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    L.marker([recommendation.dy_m, recommendation.dx_m], { icon })
      .bindTooltip(`${recommendation.kind}候选参考点 · 优先级 ${recommendation.rank} · 可覆盖 ${recommendation.gain_count} 个已知缺口样点`)
      .addTo(layers);
  }
}

function render(isochrone, inspect, inspectError = null) {
  // Leaflet 必须在可见容器里初始化/布局：隐藏状态下容器高度为 0，
  // 画布图层会按 0 尺寸绘制，显示后也不会自动重画（这是地图空白的根因）。
  $("#liveResults").hidden = false;
  state.last = isochrone;
  state.lastInspect = inspect || null;
  state.lastInspectError = inspectError;
  setMode(isReplay(isochrone), isochrone.replay?.recorded_at);
  const map = ensureMap();
  state.layers?.remove();
  state.layers = L.layerGroup().addTo(map);

  const spacing = isochrone.parameters.grid_spacing_m;
  const extent = isochrone.parameters.extent_m;
  for (const point of isochrone.points) {
    const color = STATUS_COLORS[point.status] || STATUS_COLORS.unknown;
    const r = (point.generation === "refined" ? spacing / 3 : spacing) * .35;
    const bounds = [[point.dy_m - r, point.dx_m - r], [point.dy_m + r, point.dx_m + r]];
    const square = L.rectangle(bounds, { stroke: Boolean(point.near_threshold), color: '#8b6b24', weight: 1, dashArray: '3 3', fillColor: color, fillOpacity: .3 }).addTo(state.layers);
    const tip = point.status === "unknown"
      ? `样点 (${point.dx_m}, ${point.dy_m}) · 未知：${escapeHtml(point.message || "接口未返回耗时")}`
      : `样点 (${point.dx_m}, ${point.dy_m}) · ${point.walk_minutes ?? "?"} 分钟${point.generation === "refined" ? " · 边界加密" : ""}${point.near_threshold ? ' · 近阈值待复核' : ''}`;
    square.bindTooltip(tip);
  }

  const center = isochrone.center;
  const centerIcon = L.divIcon({ className: "", html: '<span class="facility-pin center-pin">C</span>', iconSize: [28, 28], iconAnchor: [14, 14] });
  L.marker([0, 0], { icon: centerIcon }).bindTooltip("中心点（地理编码）").addTo(state.layers);
  $("#liveCenterLabel").textContent = `中心 (${center.lat.toFixed(5)}, ${center.lng.toFixed(5)}) · 网格 ${Math.round(spacing)} m`;

  let facilityRows = "";
  if (inspect) {
    const offsets = facilityOffsets(inspect.facilities, center);
    for (const [index, f] of offsets.entries()) {
      const within = f.route?.status === "ok";
      const icon = L.divIcon({ className: "", html: `<span class="facility-pin ${CATEGORY_COLORS[f.categories[0]] || ""}">${index + 1}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
      const minutes = f.route?.walk_minutes;
      L.marker([f.dy, f.dx], { icon }).bindPopup(`<strong>${escapeHtml(f.name || "未命名设施")}</strong><br>${escapeHtml(f.categories.join("、"))} · ${minutes ?? "未知"} 分钟`).addTo(state.layers);
      facilityRows += `<tr><td>${escapeHtml(f.name || "未命名设施")}<small class="classification-note">${escapeHtml(f.classification_note || "子类待核验")}</small></td><td>${escapeHtml(f.categories.join("、"))}</td><td>${minutes ?? "未知"}</td><td>${within ? (f.route.within_threshold ? "是" : "否") : "路线失败"}</td></tr>`;
    }
    $("#liveFacilityCount").textContent = inspect.facility_count;
    $("#liveFacilityNote").textContent = "中心到设施路线";
  } else {
    $("#liveFacilityCount").textContent = "—";
    $("#liveFacilityNote").textContent = inspectError ? "设施明细请求失败" : "设施明细未加载";
  }
  renderBlindSpots(inspect?.blind_spots, center, state.layers);
  $("#liveFacilityRows").innerHTML = facilityRows;

  const s = isochrone.summary;
  $("#liveRatio").innerHTML = `${s.coarse_ratio_pct ?? "未知"}${s.coarse_ratio_pct == null ? "" : "<small>%</small>"}`;
  $("#liveRatioNote").textContent = "均匀网格口径（不受加密影响）";
  $("#liveReachable").textContent = s.reachable;
  $("#liveKnown").textContent = `已知采样点 ${s.known}/${isochrone.parameters.point_count}`;
  $("#liveUnknown").textContent = s.unknown;
  const refineNote = s.refined.count ? `边界加密 ${s.refined.count} 点（可达 ${s.refined.reachable}）。` : "";
  $("#liveConclusion").textContent = `以「${state.request?.label || "所选坐标"}」为中心，${isochrone.parameters.minutes} 分钟步行阈值内均匀网格覆盖 ${s.coarse_ratio_pct ?? "未知"}%。${refineNote}这是离散采样事实，不是连续边界。`;
  const warnings = [
    ...isochrone.warnings,
    ...(inspect?.warnings || []),
    ...(inspectError ? [`设施明细请求失败：${inspectError}；失败不等于设施不存在。`] : []),
  ];
  $("#liveWarnings").innerHTML = [...new Set(warnings)].map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  $("#liveEvidenceId").textContent = `等时圈证据 ${isochrone.evidence_id}` + (inspect?.evidence_id ? ` · 设施证据 ${inspect.evidence_id}` : "") + ` · ${isochrone.method_version}`;
  $("#liveMethodNote").textContent = `网格采样 · 批量算路 ${isochrone.performance.matrix_calls} 次 · 局部米制坐标`;

  const blindSpotExtent = inspect?.blind_spots
    ? inspect.blind_spots.radius_m + inspect.blind_spots.grid_spacing_m
    : 0;
  const half = Math.max(extent + spacing, blindSpotExtent);
  state.last.bounds = [[-half, -half], [half, half]];
  map.invalidateSize();
  map.fitBounds(state.last.bounds, { padding: [12, 12], animate: false });
  icons();
}

async function run() {
  invalidate();
  const sequence = state.sequence;
  $("#liveError").hidden = true;
  if (!state.configured || !$("#liveForm").reportValidity()) return;
  const address = $("#address").value.trim();
  const city = $("#city").value.trim();
  const lat = $("#latitude").value.trim(), lng = $("#longitude").value.trim();
  if (Boolean(lat) !== Boolean(lng) || (!address && !lat)) {
    $("#liveError").hidden = false;
    $("#liveErrorText").textContent = "请填写社区地址，或同时填写中心点的纬度和经度。";
    return;
  }
  const coordinateSystem = $("#coordinateSystem")?.value || 'bd09ll';
  const location = lat ? { lat, lng, coord_type: coordinateSystem } : { address };
  if (city) location.city = city;
  const params = { minutes: $("#minutes").value, grid_m: $("#gridM").value };
  state.request = { label: lat ? `${lat}, ${lng}（输入 ${coordinateSystem}，分析 BD-09）` : address, ...params };
  state.controller = new AbortController();
  const signal = AbortSignal.any([state.controller.signal, AbortSignal.timeout(90000)]);
  $("#liveForm button[type='submit']").disabled = true;
  $("#liveForm").setAttribute("aria-busy", "true");
  $("#liveStatus").textContent = state.replayPreset ? "正在回放历史录制数据" : "正在计算步行采样与设施路线，约需 30–90 秒";
  try {
    const query = new URLSearchParams({ ...location, ...params });
    const isochrone = await getJson(`/api/live/isochrone?${query}`, { signal });
    if (sequence !== state.sequence) return;
    let inspect = null;
    let inspectError = null;
    try {
      const inspectQuery = new URLSearchParams({
        ...location,
        max_facilities: String(state.replayPreset?.max_facilities || 10),
        minutes: String(params.minutes),
      });
      if (state.replayPreset?.query_profile) inspectQuery.set("query_profile", state.replayPreset.query_profile);
      inspect = await getJson(`/api/live/inspect?${inspectQuery}`, { signal });
    } catch (error) {
      inspectError = error.message;
      notify(`设施明细加载失败：${inspectError}`);
    }
    if (sequence !== state.sequence) return;
    $("#liveStatus").textContent = inspect ? (isReplay(isochrone) ? "计算完成 · 历史录制回放" : "计算完成 · 实时 API") : "等时圈完成 · 设施明细未完成";
    render(isochrone, inspect, inspectError);
    state.valid = true;
    $("#liveReport").disabled = false;
    $("#liveExport").disabled = false;
  } catch (error) {
    if (sequence !== state.sequence) return;
    state.last = null;
    state.lastInspect = null;
    $("#liveResults").hidden = true;
    $("#liveError").hidden = false;
    $("#liveErrorText").textContent = error.name === "TimeoutError" || error.name === "AbortError" ? "实时体检请求超时，请重试。" : `实时体检未完成：${error.message}`;
    $("#liveStatus").textContent = "计算失败，未显示旧结果";
  } finally {
    if (sequence === state.sequence) {
      $("#liveForm button[type='submit']").disabled = !state.configured;
      $("#liveForm").setAttribute("aria-busy", "false");
    }
  }
}

$("#liveForm").addEventListener("submit", (event) => { event.preventDefault(); run(); });
$("#liveRetry").addEventListener("click", run);
for (const input of document.querySelectorAll("#liveForm input, #liveForm select")) {
  input.addEventListener("input", () => { invalidate(); $("#liveStatus").textContent = "参数已改变，请重新体检"; });
}
function buildReportMarkdown(iso, inspect, inspectError) {
  const s = iso.summary, p = iso.parameters;
  const coarseRatioText = s.coarse_ratio_pct == null ? "未知" : `${s.coarse_ratio_pct}%`;
  const lines = [
    `# 邻里圈${isReplay(iso) ? "历史回放" : "实时"}体检报告：${iso.center.lat.toFixed(5)}, ${iso.center.lng.toFixed(5)}`, "",
    isReplay(iso) ? `**历史录制回放，录制时间 ${iso.replay?.recorded_at || "未知"}；本次未发起外部请求。**` : "**百度地图实时 API 步行耗时口径。**", "",
    "## 可追溯元数据",
    `- 证据编号：\`${iso.evidence_id}\``,
    `- 算法版本：\`${iso.method_version}\``,
    `- 数据模式：${iso.mode}；来源：${iso.source}`,
    `- 中心点：${iso.center.lat.toFixed(5)}, ${iso.center.lng.toFixed(5)}`,
    `- 阈值：${p.minutes} 分钟｜粗网格间距：${Math.round(p.grid_spacing_m)} 米`
      + (p.refined_point_count ? `｜边界加密：${p.refined_spacing_m} 米 × ${p.refined_point_count} 点` : ""),
    `- 采样结论：均匀网格可达比例 ${coarseRatioText}（${s.coarse?.known ?? s.known} 个已知粗网格点中 ${s.coarse?.reachable ?? s.reachable} 个可达）`
      + (s.refined.count ? `；边界加密 ${s.refined.count} 点，其中可达 ${s.refined.reachable} 个` : "")
      + `；未知采样点 ${s.unknown} 个，未参与比例计算。`,
    "",
    "## 口径与警告",
    ...iso.warnings.map((w) => `- ${w}`),
    "- 网格采样是近似等时圈，不是连续边界拟合；未知点不计入可达比例。",
  ];
  if (inspect) {
    lines.push("", "## 中心到设施真实路线", "| 设施 | 类别 | 步行/分钟 | 阈值内 |", "| --- | --- | ---: | --- |");
    for (const f of inspect.facilities) {
      const within = f.route?.status === "ok" ? (f.route.within_threshold ? "是" : "否") : "失败";
      lines.push(`| ${markdownCell(f.name || "未命名设施")} | ${markdownCell(f.categories.join("、"))} | ${f.route?.walk_minutes ?? "?"} | ${within} |`);
    }
    for (const f of inspect.facilities.filter((f) => f.classification_note?.includes("排除"))) lines.push("", `子类提示：${markdownCell(f.name)} — ${markdownCell(f.classification_note)}。`);
    const perf = inspect.performance || {};
    lines.push("", `设施证据编号：\`${inspect.evidence_id || "未知"}\`；设施算法：${inspect.method_version || "未知"}。`);
    lines.push("", `检索画像：${inspect.parameters?.query_profile || "未知"}；路线模式：${perf.route_mode || "未知"}；检索耗时 ${perf.poi_phase_ms ?? "未知"} ms；路线耗时 ${perf.route_phase_ms ?? "未知"} ms；路线失败 ${perf.route_errors ?? "未知"} 条；设施截断：${perf.truncated ? "是" : "否"}。`, "失败项如实标注为「失败」，不以直线距离冒充。", ...inspect.warnings.map((w) => `- ${w}`));
    if (inspect.blind_spots) {
      lines.push("", "## 1 公里专项盲区", "| 类别 | 状态 | 缺口样点 | 已知样点 | 未知样点 |", "| --- | --- | ---: | ---: | ---: |");
      for (const [kind, row] of Object.entries(inspect.blind_spots.kinds)) {
        lines.push(`| ${kind} | ${row.status} | ${row.gap_count ?? "未知"} | ${row.known_count ?? row.sample_count} | ${row.unknown_count ?? 0} |`);
      }
      if (inspect.blind_spots.recommendations?.length) {
        lines.push("", "## 规划候选点（采样启发式）", "| 类别 | 优先级 | 参考位置（米） | 新增覆盖样点 | 覆盖比例 |", "| --- | ---: | --- | ---: | ---: |");
        for (const recommendation of inspect.blind_spots.recommendations) {
          lines.push(`| ${recommendation.kind} | ${recommendation.rank} | (${recommendation.dx_m}, ${recommendation.dy_m}) | ${recommendation.gain_count} | ${recommendation.gain_ratio_pct}% |`);
        }
        lines.push("", "候选点是等权网格样点的启发式参考位置，不代表可直接建设的地块、容量或投入产出结论。");
      }
      lines.push("", ...inspect.blind_spots.warnings.map((warning) => `- ${warning}`));
    }
  } else if (inspectError) {
    lines.push(
      "",
      "## 设施检查状态",
      `- 结果：未完成`,
      `- 原因：${inspectError}`,
      "- 该失败不等于设施不存在；本报告未使用合成设施结果补齐。",
    );
  }
  lines.push("", "## 未知点与边界", "- 未输出居民人数、覆盖面积或建设收益。", "- 数据来自百度地图开放能力，受配额与网络状态影响。", "",
    `导出时间：${new Date().toLocaleString()}（客户端导出，数据与证据编号 ${iso.evidence_id} 的接口结果一致）`);
  return lines.join("\n") + "\n";
}
$("#liveReport").addEventListener("click", () => {
  if (!state.valid || !state.last) return;
  const markdown = buildReportMarkdown(state.last, state.lastInspect || null, state.lastInspectError);
  const blob = new Blob([markdown], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `live-report-${state.last.evidence_id}.md`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("#liveExport").addEventListener("click", () => {
  if (!state.valid || !state.last) return;
  const blob = new Blob([JSON.stringify({
    isochrone: state.last,
    inspection: state.lastInspect || null,
    inspection_error: state.lastInspectError,
  }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `live-isochrone-${state.last.evidence_id}.json`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
icons();
(async () => {
  try {
    const liveStatus = await getJson("/api/live/status", { signal: AbortSignal.timeout(10000) });
    const submit = $("#liveForm button[type='submit']");
    const profileName = liveStatus.effective_query_profile || liveStatus.default_query_profile;
    const profile = liveStatus.query_profiles?.[profileName];
    if (!liveStatus.query_profile_valid || liveStatus.replay_error) {
      submit.disabled = true;
      $("#liveStatus").textContent = "服务配置错误，无法进行设施检查";
      $("#liveQuotaNote").textContent = liveStatus.message || "检索画像配置无效";
      return;
    }
    if (profile) {
      $("#liveQuotaNote").textContent =
        `检索词 ${profile.place_queries_per_inspection} 组（${profileName} 画像，分页会增加请求）；批量算路随采样点变化`;
    }
    if (!liveStatus.configured) {
      submit.disabled = true;
      $("#liveStatus").textContent = "服务已连接，但未配置百度 AK";
      $("#liveQuotaNote").textContent = "实时模式不可用；配置服务端 BAIDU_MAP_AK 后再进行真实体检";
      return;
    }
    state.configured = true;
    state.replayPreset = liveStatus.replay_preset;
    if (state.replayPreset) {
      const preset = state.replayPreset;
      for (const [id, value] of Object.entries({ address: preset.address || "", city: preset.city || "", minutes: preset.minutes, gridM: preset.grid_m, latitude: "", longitude: "" })) {
        $(`#${id}`).value = String(value ?? "");
        $(`#${id}`).readOnly = true;
      }
      $("#liveQuotaNote").textContent = "历史回放不消耗地图配额；输入限于录制样例。";
      $("#coordinateOptions").hidden = true;
    }
    setMode(Boolean(state.replayPreset), state.replayPreset?.recorded_at);
    submit.disabled = false;
    $("#liveStatus").textContent = state.replayPreset ? "已载入录制参数，可以开始回放" : "服务已连接，填写地址或坐标即可体检";
  } catch (error) {
    $("#liveForm button[type='submit']").disabled = true;
    $("#liveError").hidden = false;
    $("#liveErrorText").textContent = `本地服务不可用：${error.message}`;
    $("#liveStatus").textContent = "连接失败";
    $("#liveQuotaNote").textContent = "无法读取配额配置";
  }
})();

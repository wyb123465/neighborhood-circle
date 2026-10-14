"use strict";
const $ = (selector) => document.querySelector(selector);
const colors = { 医疗: "medical", 养老: "care", 教育: "education", 购物: "shopping" };
const state = { result: null, center: null, addition: null, view: "gaps", picking: false, valid: false, sequence: 0, abort: null, initialized: false };
let map, baseImage, layers, bounds, nodeById, markerById, mapCommunity, routeLayer, toastTimer, reportSnapshot;
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
function icons() { if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 1.8, "aria-hidden": "true" } }); }
function notify(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 3200); }
function selectedCategories() { return Array.from(document.querySelectorAll('[name="category"]:checked'), (input) => input.value); }
function params() {
  return { community_id: $("#community").value, category: selectedCategories().join(","), minutes: Number($("#minutes").value), speed: Number($("#speed").value), center: state.center, addition_node: state.addition?.node || null, addition_category: state.addition?.category || null };
}
async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(typeof body?.detail === "string" ? body.detail : `服务响应异常 (${response.status})`); }
  return response.json();
}
function invalidateResult(message = "参数已修改，等待重新计算") {
  ++state.sequence;
  state.abort?.abort();
  state.abort = null;
  state.valid = false;
  $("#results").hidden = true;
  $("#results").setAttribute("aria-busy", "false");
  $("#error").hidden = true;
  $("#calculationStatus").textContent = message;
}
async function load() {
  invalidateResult();
  if (!$("#inspectionForm").reportValidity()) { $("#calculationStatus").textContent = "参数无效，未执行体检"; return; }
  const sequence = state.sequence;
  const controller = new AbortController();
  state.abort = controller;
  const timeout = setTimeout(() => controller.abort(), 15000);
  $("#results").setAttribute("aria-busy", "true"); $("#error").hidden = true;
  $("#calculationStatus").textContent = "正在计算最短路径与覆盖率";
  const query = params(); const community = query.community_id; delete query.community_id;
  const search = new URLSearchParams(Object.entries(query).filter(([, value]) => value !== null));
  try {
    const result = await getJson(`/api/communities/${encodeURIComponent(community)}/inspection?${search}`, { signal: controller.signal });
    if (sequence !== state.sequence) return;
    state.result = result; state.center = result.parameters.center;
    $("#results").hidden = false; render(result); state.valid = true;
    $("#calculationStatus").textContent = "计算完成 · 合成样例";
  } catch (error) {
    if (sequence !== state.sequence) return;
    state.valid = false; $("#results").hidden = true; $("#error").hidden = false;
    $("#errorText").textContent = error.name === "AbortError" ? "体检请求超时，请重试。" : `体检未完成：${error.message}`;
    $("#calculationStatus").textContent = "计算失败，未显示旧结果";
  } finally {
    clearTimeout(timeout);
    if (sequence === state.sequence) { state.abort = null; $("#results").setAttribute("aria-busy", "false"); }
  }
}
function ll(node) { return [node.y, node.x]; }
function renderMap(result) {
  if (!map) {
    map = L.map("map", { crs: L.CRS.Simple, minZoom: -4, maxZoom: 1, zoomSnap: .25, zoomControl: false, attributionControl: false, preferCanvas: true });
    L.control.attribution({ prefix: false }).addAttribution("合成路网 · 局部坐标 / m").addTo(map);
    map.on("click", (event) => {
      if (!state.picking || !state.valid) return;
      const nearest = state.result.map.nodes.reduce((best, n) => Math.hypot(n.x - event.latlng.lng, n.y - event.latlng.lat) < Math.hypot(best.x - event.latlng.lng, best.y - event.latlng.lat) ? n : best);
      state.center = nearest.id; setPicking(false); load();
    });
    new ResizeObserver(() => map.invalidateSize()).observe($("#map"));
  }
  layers?.remove(); routeLayer?.remove(); routeLayer = null;
  layers = L.layerGroup().addTo(map); markerById = new Map();
  nodeById = new Map(result.map.nodes.map((node) => [node.id, node]));
  const spacing = result.map.spacing_m, maxX = Math.max(...result.map.nodes.map((n) => n.x)), maxY = Math.max(...result.map.nodes.map((n) => n.y));
  bounds = [[-spacing / 2, -spacing / 2], [maxY + spacing / 2, maxX + spacing / 2]];
  const changed = mapCommunity !== result.community.id;
  if (changed) {
    // Leaflet defers layer creation until the map has a view. Establish it
    // before reading marker elements on the very first render.
    map.fitBounds(bounds, { padding: [12, 12], animate: false });
    baseImage?.remove();
    baseImage = L.imageOverlay(`/api/communities/${result.community.id}/map.png`, bounds, { alt: `${result.community.name}的合成路网底图` }).addTo(map);
    baseImage.on("error", () => notify("样例底图加载失败，请重试"));
    baseImage.bringToBack();
    mapCommunity = result.community.id;
  }
  const reachable = new Set(result.reachability.nodes);
  for (const node of result.map.nodes) {
    const marked = state.view === "gaps" ? node.gap : reachable.has(node.id);
    if (!marked) continue;
    const r = spacing * .35;
    const color = state.view === "gaps" ? "#b64759" : "#197257";
    L.rectangle([[node.y - r, node.x - r], [node.y + r, node.x + r]], { stroke: false, fillColor: color, fillOpacity: .28 }).bindTooltip(`样例节点 ${node.id} · ${state.view === "gaps" ? "至少一类服务不可达" : "中心点阈值内可达"}`).addTo(layers);
  }
  const center = nodeById.get(result.parameters.center);
  L.circle(ll(center), { radius: result.parameters.minutes * result.parameters.speed_m_min, color: "#647d91", weight: 1.5, dashArray: "6 5", fill: false, interactive: false }).addTo(layers);
  const centerIcon = L.divIcon({ className: "", html: '<span class="facility-pin center-pin">C</span>', iconSize: [28, 28], iconAnchor: [14, 14] });
  const centerMarker = L.marker(ll(center), { icon: centerIcon, title: `中心节点 ${center.id}` }).bindTooltip(`中心节点 ${center.id}`).addTo(layers);
  centerMarker.getElement().setAttribute("aria-label", `中心节点 ${center.id}`);
  result.facilities.forEach((facility, index) => {
    const marker = L.marker(ll(nodeById.get(facility.node)), { icon: L.divIcon({ className: "", html: `<span class="facility-pin ${facility.id === "proposed" ? "proposed-pin" : colors[facility.category]}">${index + 1}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] }), title: facility.name, alt: facility.name });
    marker.bindPopup(`<strong>${escapeHtml(facility.name)}</strong><br>${escapeHtml(facility.category)} · 中心点出发 ${facility.walk_minutes ?? "不可达"} 分钟`).addTo(layers);
    marker.getElement().setAttribute("aria-label", facility.name);
    markerById.set(facility.id, marker);
  });
  map.invalidateSize();
}
function render(result) {
  $("#communityTitle").textContent = result.community.name;
  $("#combined").innerHTML = `${result.combined_coverage_pct}<small>%</small>`;
  $("#baseline").textContent = state.addition ? `模拟前 ${result.base_combined_coverage_pct}%` : "等权采样点口径";
  $("#gaps").textContent = result.gap_count;
  $("#sampleCount").textContent = `共 ${result.sample_count} 个采样点`;
  $("#facilityCount").textContent = result.facility_count;
  $("#additionState").textContent = state.addition ? `含 1 个模拟${state.addition.category}点` : "原有样例设施";
  $("#overestimate").textContent = result.reachability.overestimated_count;
  $("#centerLabel").textContent = `中心 (${result.parameters.center}) · 采样间距 ${result.map.spacing_m} m`;
  const w = result.witness;
  $("#routeComparison").textContent = `直线 ${w.straight_minutes} 分钟 / 路网 ${w.network_minutes ?? "不可达"} 分钟`;
  const weakest = Object.entries(result.coverage).sort((a, b) => a[1].pct - b[1].pct)[0];
  $("#conclusion").textContent = result.gap_count ? `${weakest[0]}覆盖率最低（${weakest[1].pct}%）。${result.gap_count} 个采样点至少有一类所选服务在 ${result.parameters.minutes} 分钟内不可达。` : "所有采样点的所选服务均在当前步行阈值内可达。";
  $("#coverageList").innerHTML = Object.entries(result.coverage).map(([category, row]) => `<div><div class="coverage-head"><span><i class="dot ${colors[category]}"></i>${category}</span><strong>${row.count}/${result.sample_count} · ${row.pct}%</strong></div><div class="bar"><span style="width:${row.pct}%"></span></div></div>`).join("");
  $("#candidates").innerHTML = result.recommendations.length ? result.recommendations.map((c, index) => `<button class="candidate" data-candidate="${index}" aria-pressed="${state.addition?.node === c.node}"><strong>模拟${c.category}点 (${c.node})</strong><span>该类覆盖 ${c.before_pct}% → ${c.after_pct}%</span><b>+${c.gain}</b></button>`).join("") : '<p class="quiet">当前没有能新增覆盖的候选点。</p>';
  $("#undoSimulation").disabled = !state.addition;
  $("#kmChecks").innerHTML = result.one_km_checks.map((check, index) => `<div class="km-row"><span>${check.kind} · ${check.facility_count} 处</span><button data-km="${index}">${check.gap_count} 个缺口点</button></div>`).join("");
  $("#facilityRows").innerHTML = result.facilities.map((f, i) => `<tr><td>${i + 1}</td><td><button data-facility="${escapeHtml(f.id)}">${escapeHtml(f.name)}</button></td><td>${f.category} / ${f.kind}</td><td>${f.node}</td><td>${f.walk_minutes ?? "不可达"}</td><td>${f.within_threshold ? "是" : "否"}</td></tr>`).join("");
  $("#evidenceId").textContent = `证据编号 ${result.evidence_id}`;
  $("#methodBadge").textContent = `${result.method_version} · ${result.dataset_version} · NetworkX`;
  $("#limitations").innerHTML = result.limitations.map((text) => `<li>${escapeHtml(text)}</li>`).join("");
  renderMap(result); icons();
}
function setPicking(value) { state.picking = value; $("#pickCenter").setAttribute("aria-pressed", String(value)); $("#map").classList.toggle("picking", value); }
function download(blob, name) { const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function openReport() {
  if (!state.valid) return;
  reportSnapshot = structuredClone(state.result);
  const result = reportSnapshot;
  const p = result.parameters;
  const addition = p.addition;
  const missing = result.missing_categories?.length
    ? `<p class="report-note">缺失设施类别：${escapeHtml(result.missing_categories.join("、"))}（样例中无对应设施，未编造点位）</p>`
    : "";
  const simulation = addition
    ? `候选模拟已启用：${escapeHtml(addition.category)} @ ${escapeHtml(addition.node)}；模拟前同时可达 ${result.base_combined_coverage_pct}%。`
    : "未启用候选模拟。";
  $("#reportTitle").textContent = result.community.name;
  $("#reportContent").innerHTML = `
    <p class="report-warning">合成样例结果，非真实社区体检。指标来自可复算路网，不对应上海任何真实社区。</p>
    <section class="report-block">
      <h3>可追溯元数据</h3>
      <dl class="report-meta">
        <div><dt>证据编号</dt><dd><code>${escapeHtml(result.evidence_id)}</code></dd></div>
        <div><dt>算法版本</dt><dd><code>${escapeHtml(result.method_version)}</code></dd></div>
        <div><dt>数据版本</dt><dd><code>${escapeHtml(result.dataset_version)}</code></dd></div>
        <div><dt>数据来源</dt><dd>${escapeHtml(result.source)}</dd></div>
        <div><dt>运行模式</dt><dd>${escapeHtml(result.mode)} · 离线可复现</dd></div>
        <div><dt>参数</dt><dd>中心 ${escapeHtml(String(p.center))} · 阈值 ${p.minutes} 分钟 · 步速 ${p.speed_m_min} 米/分 · 类别 ${escapeHtml(p.categories.join("、"))}</dd></div>
      </dl>
    </section>
    <section class="report-block">
      <h3>结果摘要</h3>
      <p>所选各类服务同时可达 <strong>${result.combined_coverage_pct}%</strong>（模拟前 ${result.base_combined_coverage_pct}%）· 缺口 ${result.gap_count}/${result.sample_count} 采样点 · 所选设施 ${result.facility_count} 处</p>
      <p class="report-note">各类别覆盖率算术平均 ${result.average_coverage_pct}%，仅作参考，不等于同时可达。</p>
      <p class="report-note">直线范围高估 ${result.reachability.overestimated_count} 个采样点（直线圈内但路网阈值外）。</p>
      ${missing}
    </section>
    <section class="report-block">
      <h3>分类别覆盖</h3>
      <div class="table-scroll"><table><thead><tr><th>类别</th><th>模拟前</th><th>本次结果</th><th>可达点数</th></tr></thead><tbody>${Object.entries(result.coverage).map(([c, r]) => `<tr><td>${c}</td><td>${r.before_pct}%</td><td>${r.pct}%</td><td>${r.count}</td></tr>`).join("")}</tbody></table></div>
    </section>
    <section class="report-block">
      <h3>路径证据（直线 vs 路网）</h3>
      <p>(${escapeHtml(String(result.witness.from))}) → (${escapeHtml(String(result.witness.to))})：直线 ${result.witness.straight_minutes} 分钟 / 样例路网 ${result.witness.network_minutes ?? "不可达"} 分钟</p>
      <p class="report-note">路径节点可按编号复算：${escapeHtml(result.witness.path.join(" / ") || "（不可达）")}</p>
    </section>
    <section class="report-block">
      <h3>1 公里专项检查（直线 · 原有设施）</h3>
      <ul>${result.one_km_checks.map((c) => `<li>${escapeHtml(c.kind)}：${c.facility_count} 处设施；${c.gap_count} 个点周边 1 公里无对应样例设施。</li>`).join("")}</ul>
    </section>
    <section class="report-block">
      <h3>模拟方案</h3>
      <p>${escapeHtml(simulation)}</p>
    </section>
    <section class="report-block">
      <h3>未知点与口径边界</h3>
      <ul>${result.limitations.map((text) => `<li>${escapeHtml(text)}</li>`).join("")}<li>本报告不输出居民人数、节省成本或建设收益。</li></ul>
    </section>`;
  $("#reportDialog").showModal();
}
$("#inspectionForm").addEventListener("submit", (event) => { event.preventDefault(); state.addition = null; load(); });
$("#community").addEventListener("change", () => { state.center = null; state.addition = null; setPicking(false); load(); });
document.querySelectorAll('[name="category"]').forEach((checkbox) => checkbox.addEventListener("change", () => { if (!selectedCategories().length) { checkbox.checked = true; notify("至少保留一种设施类别"); return; } state.addition = null; load(); }));
for (const id of ["#minutes", "#speed"]) {
  $(id).addEventListener("input", () => { state.addition = null; invalidateResult(); });
  $(id).addEventListener("change", () => { state.addition = null; load(); });
}
$("#candidates").addEventListener("click", (event) => { const button = event.target.closest("[data-candidate]"); if (!button || !state.valid) return; const c = state.result.recommendations[Number(button.dataset.candidate)]; state.addition = { node: c.node, category: c.category }; load(); });
$("#undoSimulation").addEventListener("click", () => { state.addition = null; load(); });
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => { state.view = button.dataset.view; document.querySelectorAll("[data-view]").forEach((item) => item.setAttribute("aria-pressed", String(item === button))); renderMap(state.result); }));
$("#pickCenter").addEventListener("click", () => setPicking(!state.picking));
$("#fitMap").addEventListener("click", () => map.fitBounds(bounds, { animate: false }));
$("#zoomIn").addEventListener("click", () => map.zoomIn(.5));
$("#zoomOut").addEventListener("click", () => map.zoomOut(.5));
$("#routeButton").addEventListener("click", () => { routeLayer?.remove(); const points = state.result.witness.path.map((id) => ll(nodeById.get(id))); if (points.length < 2) { notify("当前证据没有可绘制的连通路径"); return; } routeLayer = L.polyline(points, { color: "#8b6b24", weight: 5 }).addTo(map); map.fitBounds(routeLayer.getBounds(), { padding: [45, 45], maxZoom: -.5, animate: false }); });
$("#facilityRows").addEventListener("click", (event) => { const button = event.target.closest("[data-facility]"); if (!button) return; const marker = markerById.get(button.dataset.facility); map.setView(marker.getLatLng(), -.5, { animate: false }); marker.openPopup(); $("#map").scrollIntoView({ block: "center" }); });
$("#kmChecks").addEventListener("click", (event) => { const button = event.target.closest("[data-km]"); if (!button) return; const check = state.result.one_km_checks[Number(button.dataset.km)]; routeLayer?.remove(); routeLayer = L.layerGroup(check.gap_nodes.map((id) => L.circleMarker(ll(nodeById.get(id)), { radius: 5, color: "#8b6b24", fillOpacity: .8 }))).addTo(map); map.fitBounds(bounds, { animate: false }); notify(`${check.kind}：${check.gap_count} 个 1 公里缺口点`); });
$("#reportButton").addEventListener("click", openReport);
$("#methodButton").addEventListener("click", () => $("#methodDialog").showModal());
document.querySelectorAll(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
$("#exportJson").addEventListener("click", () => { if (state.valid) download(new Blob([JSON.stringify(state.result, null, 2)], { type: "application/json" }), `inspection-${state.result.evidence_id}.json`); });
$("#exportJsonFromReport").addEventListener("click", () => { if (reportSnapshot) download(new Blob([JSON.stringify(reportSnapshot, null, 2)], { type: "application/json" }), `inspection-${reportSnapshot.evidence_id}.json`); });
$("#demoPreset").addEventListener("click", () => {
  // 演示闭环固定参数：滨河片区 + 仅养老 + 15 分钟 + 80 米/分钟，便于 3 分钟讲解。
  $("#community").value = "bridge-demo";
  $("#minutes").value = "15";
  $("#speed").value = "80";
  document.querySelectorAll('[name="category"]').forEach((input) => { input.checked = input.value === "养老"; });
  state.center = null; state.addition = null; setPicking(false);
  notify("已载入演示预设：滨河片区 · 仅养老");
  load();
});
$("#downloadReport").addEventListener("click", async () => {
  const snapshot = reportSnapshot, p = snapshot.parameters;
  $("#downloadReport").disabled = true;
  try {
    const response = await fetch("/api/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ community_id: snapshot.community.id, category: p.categories.join(","), minutes: p.minutes, speed: p.speed_m_min, center: p.center, addition_node: p.addition?.node || null, addition_category: p.addition?.category || null }), signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error("报告生成失败");
    download(await response.blob(), `inspection-${snapshot.evidence_id}.md`);
  } catch { notify("报告导出失败，请检查本地服务后重试"); } finally { $("#downloadReport").disabled = false; }
});
async function init() {
  try {
    const communities = await getJson("/api/communities", { signal: AbortSignal.timeout(10000) });
    if (!communities.length) throw new Error("没有可用样例");
    $("#community").replaceChildren(...communities.map((c) => new Option(c.name, c.id)));
    $("#config").disabled = false; state.initialized = true; await load();
  } catch (error) { $("#error").hidden = false; $("#errorText").textContent = `本地服务不可用：${error.message}`; $("#calculationStatus").textContent = "连接失败"; }
}
$("#retryButton").addEventListener("click", () => state.initialized ? load() : init());
icons(); init();

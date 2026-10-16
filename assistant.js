'use strict';
const $ = (selector) => document.querySelector(selector);
const sourceNames = {
  synthetic: '合成样例',
  'live-replay': '历史真实数据回放',
  'live-partial': '百度实时数据（采样）',
};
const modeNames = {
  'rule-only': '规则模式 · 未调用模型',
  'llm-agent': '模型工具调用',
  'llm-agent-partial': '模型运行部分完成',
  pending: '等待执行',
};
const statusNames = {
  queued: '排队等待',
  running: '正在执行',
  cancelling: '正在停止',
  cancelled: '已停止',
  complete: '已完成',
  partial: '部分完成',
  needs_input: '需要补充信息',
  error: '运行失败',
  'connection-error': '连接中断',
};
const ui = {
  result: null,
  job: null,
  analysis: null,
  busy: false,
  map: null,
  layer: null,
  groups: {},
  facilityMarkers: [],
  highlight: null,
  bounds: null,
  mapStatus: null,
  submittedTask: '',
  report: '',
  scenarios: null,
  saved: false,
  recordId: null,
  reviews: {},
};
const controller = new AssistantRunController(window.fetch.bind(window), renderJob);
function text(selector, value) {
  $(selector).textContent = value ?? '';
}
function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}
function busy(value) {
  ui.busy = value;
  $('#startAssistant').disabled = value;
  $('#stopAssistant').hidden = !value;
  $('#retryAssistant').disabled = value;
  $('#newSession').disabled = value;
  for (const id of ['openHistory', 'saveInspection', 'printReport', 'explainPrevious', 'comparePrevious'])
    $('#' + id).disabled = value;
}
function showError(message) {
  $('#assistantError').hidden = !message;
  text('#assistantErrorText', message);
}
function payload() {
  return {
    task: $('#assistantTask').value.trim(),
    data_mode: $('#dataMode').value,
    community_id: $('#assistantCommunity').value,
    address: $('#assistantAddress').value.trim() || null,
    city: $('#assistantCity').value.trim() || null,
    minutes: Number($('#assistantMinutes').value),
    speed: Number($('#assistantSpeed').value),
  };
}
async function submit() {
  if (ui.busy || !$('#assistantForm').reportValidity()) return;
  ui.saved = false;
  ui.recordId = null;
  ui.reviews = {};
  ui.scenarios = null;
  setResultsView('answer');
  for (const id of ['summaryMetrics', 'scenarioPanel', 'reviewPanel', 'viewTabs', 'emptyWorkspace'])
    $('#' + id).hidden = true;
  $('#executionDetails').open = true;
  document.body.classList.add('params-collapsed');
  $('#toggleParameters').setAttribute('aria-expanded', 'false');
  busy(true);
  ui.result = null;
  showError(null);
  $('#assistantAnswer').hidden = true;
  $('#assistantEvidence').hidden = true;
  ui.submittedTask = payload().task;
  text('#runStatus', '正在提交');
  text('#runCounters', '提交请求；执行步骤将随实际进度更新。');
  $('#toolTrace').replaceChildren(element('li', '等待服务接受任务。', 'quiet'));
  await controller.start(payload());
}
function renderJob(job) {
  text('#runStatus', statusNames[job.status] || job.status);
  if (job.events) {
    ui.job = job;
    text(
      '#runCounters',
      `${modeNames[job.mode] || job.mode} · 模型 ${job.model_calls} 轮 · 工具 ${job.tool_calls} 次 · 新发地图请求 ${job.map_requests}/${job.map_request_budget}`,
    );
    const expanded = new Set(
      Array.from($('#toolTrace').querySelectorAll('details[open]'), (node) => node.dataset.id),
    );
    $('#toolTrace').replaceChildren(
      ...job.events.map((event) => {
        const li = element('li');
        li.dataset.status = event.status;
        const detail = element('details');
        detail.dataset.id = String(event.id);
        detail.open = expanded.has(String(event.id));
        const label = `${event.status === 'complete' ? '完成' : event.status === 'error' ? '失败' : '执行中'} · ${event.label}${event.duration_ms !== null ? ' · ' + (event.duration_ms / 1000).toFixed(1) + ' 秒' : ''}`;
        detail.append(element('summary', label));
        if (event.arguments) detail.append(element('pre', JSON.stringify(event.arguments, null, 2)));
        if (event.error) detail.append(element('p', event.error));
        li.append(detail);
        return li;
      }),
    );
    if (!job.events.length) $('#toolTrace').append(element('li', '任务已接受，等待执行。', 'quiet'));
  }
  showError(job.error);
  busy(['queued', 'running', 'cancelling'].includes(job.status));
  if (job.status === 'connection-error') {
    $('#stopAssistant').hidden = false;
    $('#startAssistant').disabled = true;
    text('#runCounters', '服务连接中断；请先停止本次任务或恢复服务，再重新提交。');
  }
  if (job.result) {
    ui.result = job.result;
    renderAnswer(job);
  }
  $('#executionSummary').textContent = job.events
    ? `实际步骤 ${job.events.length} 项 · 查看调用记录`
    : '查看步骤与调用记录';
  if (!['queued', 'running', 'cancelling'].includes(job.status))
    $('#executionDetails').open = Boolean(job.error);
  if (!job.result && !ui.busy) $('#emptyWorkspace').hidden = false;
}
function renderAnswer(job) {
  const result = job.result;
  if (!ui.saved && job.mode === 'llm-agent' && job.status === 'complete')
    text('#modelStatus', '本次AI工具调用已完成');
  if (result.analysis) {
    const r = result.analysis.inspection;
    $('#assistantMinutes').value = r.parameters.minutes;
    if (result.analysis.type === 'synthetic') {
      $('#assistantCommunity').value = r.community.id;
      $('#assistantSpeed').value = r.parameters.speed_m_min;
    } else {
      $('#assistantAddress').value = r.community.address;
      $('#assistantCity').value = r.community.city || '';
    }
  }
  $('#assistantAnswer').hidden = false;
  text('#answerMode', modeNames[job.mode]);
  text('#answerNote', result.note);
  text('#assistantQuestion', result.question);
  $('#assistantQuestion').hidden = !result.question;
  $('#assistantFacts').dataset.expanded = 'false';
  $('#assistantFacts').replaceChildren(
    ...orderedFacts(result).map((fact) => {
      const index = result.facts.indexOf(fact);
      const li = element('li');
      li.append(element('p', fact.text));
      const button = element('button', `证据 [${index + 1}] ↗`, 'assistant-citation');
      button.title = `${sourceNames[fact.data_mode]} · ${fact.evidence_id}`;
      button.setAttribute('aria-label', `查看证据 ${index + 1}：${fact.text}`);
      button.type = 'button';
      button.addEventListener('click', () => focusFact(fact));
      li.append(button);
      return li;
    }),
  );
  $('#assistantActions').replaceChildren(...result.actions.map((action) => element('li', action)));
  $('#explainPrevious').disabled = !result.analysis || ui.saved;
  $('#comparePrevious').disabled = !result.analysis || ui.saved;
  text('#copyStatus', '');
  $('#toggleFacts').hidden = result.facts.length <= 3;
  text('#toggleFacts', `查看其余 ${Math.max(0, result.facts.length - 3)} 项证据`);
  text(
    '#sessionHint',
    ui.saved
      ? '已加载本机快照；重新体检后可继续AI追问。'
      : `会话 ${(job.session_id || '').slice(0, 8)} · 可继续追问`,
  );
  ui.report = reportMarkdown(job);
  text('#assistantReport', ui.report);
  if (result.analysis) renderEvidence(result.analysis, result.comparison);
  renderWorkspace(job);
}
function reportMarkdown(job) {
  const r = job.result;
  const lines = [
    '# 邻里圈智能体检记录',
    '',
    `执行状态：${statusNames[job.status]}；${modeNames[job.mode]}。`,
    `需求：${ui.submittedTask}`,
    `本次新发地图请求：${job.map_requests}；模型调用：${job.model_calls}。`,
    '',
    '## 结论与证据',
    '',
  ];
  if (r.question) lines.push(r.question);
  r.facts.forEach((f) => lines.push(`- ${f.text} [${sourceNames[f.data_mode]}；证据 ${f.evidence_id}]`));
  lines.push('', '## 建议后续核验', '', ...r.actions.map((a) => '- ' + a));
  if (r.analysis) {
    const v = r.analysis.inspection;
    lines.push(
      '',
      '## 计算口径',
      '',
      JSON.stringify(v.parameters),
      '',
      ...(v.limitations || v.warnings || []).map((w) => '- ' + w),
    );
  }
  return lines.join('\n');
}
function tooltip(message) {
  return element('span', message);
}
function point(x, y, message, color = '#197257', radius = 4, group = ui.groups.samples) {
  return L.circleMarker([y, x], { radius, color, weight: 1, fillColor: color, fillOpacity: 0.65 })
    .bindTooltip(tooltip(message))
    .addTo(group);
}
function xy(location, center) {
  return [
    (location.lng - center.lng) * 111320 * Math.cos((center.lat * Math.PI) / 180),
    (location.lat - center.lat) * 111320,
  ];
}
function renderEvidence(analysis, comparison = []) {
  ui.analysis = analysis;
  $('#assistantEvidence').hidden = false;
  if (ui.map) ui.map.remove();
  ui.map = L.map('assistantMap', {
    crs: L.CRS.Simple,
    minZoom: -4,
    maxZoom: 2,
    zoomSnap: 0.25,
    preferCanvas: true,
  });
  ui.layer = L.layerGroup().addTo(ui.map);
  ui.highlight = null;
  ui.facilityMarkers = [];
  for (const name of ['samples', 'facilities', 'gaps', 'review', 'candidates'])
    ui.groups[name] = L.layerGroup().addTo(ui.layer);
  document.querySelectorAll('[data-layer]').forEach((b) => b.setAttribute('aria-pressed', 'true'));
  const r = analysis.inspection;
  const isSynthetic = analysis.type === 'synthetic';
  $('#showWitness').hidden = !isSynthetic;
  text('#evidenceSource', sourceNames[r.mode]);
  text(
    '#mapCaption',
    isSynthetic
      ? '合成路网与等权样点。点击路径证据可查看绕行。'
      : '以社区中心为原点的米制示意图；输入与数据坐标为 BD-09。点位不代替连续等时圈。',
  );
  if (isSynthetic) {
    const spacing = r.map.spacing_m;
    ui.bounds = [
      [-spacing / 2, -spacing / 2],
      [
        Math.max(...r.map.nodes.map((n) => n.y)) + spacing / 2,
        Math.max(...r.map.nodes.map((n) => n.x)) + spacing / 2,
      ],
    ];
    L.imageOverlay(`/api/communities/${r.community.id}/map.png`, ui.bounds, { alt: '合成路网底图' })
      .addTo(ui.map)
      .bringToBack();
    for (const n of r.map.nodes)
      point(n.x, n.y, `${n.id} · ${n.gap ? '服务缺口' : '同时覆盖'}`, n.gap ? '#b76b7b' : '#197257', 3);
    r.facilities.forEach((f, index) => {
      const n = r.map.nodes.find((n) => n.id === f.node);
      if (n)
        ui.facilityMarkers[index] = point(
          n.x,
          n.y,
          `${f.name} · ${f.category}`,
          '#263d35',
          7,
          ui.groups.facilities,
        ).on('click', () => focusFacility(index));
    });
  } else {
    const points = analysis.isochrone?.points || [];
    const extent = analysis.isochrone?.parameters.extent_m || 1500;
    ui.bounds = [
      [-extent, -extent],
      [extent, extent],
    ];
    for (const p of points) {
      point(
        p.dx_m,
        p.dy_m,
        `${p.generation === 'coarse' ? '均匀' : '加密'}样点：${p.walk_minutes ?? '未知'} 分钟`,
        p.status === 'unknown' ? '#b39024' : p.status === 'reachable' ? '#197257' : '#b76b7b',
        p.generation === 'coarse' ? 5 : 3,
      );
      if (p.near_threshold)
        point(p.dx_m, p.dy_m, '近阈值待复核', '#8b6b24', 7, ui.groups.review).setStyle({
          fill: false,
          weight: 2,
        });
    }
    r.facilities.forEach((f, index) => {
      const p = xy(f.location, r.community.center);
      ui.facilityMarkers[index] = point(
        p[0],
        p[1],
        `${f.name} · ${f.route.walk_minutes ?? '路线未知'}`,
        '#263d35',
        6,
        ui.groups.facilities,
      ).on('click', () => focusFacility(index));
    });
    for (const p of r.blind_spots.points.filter((p) => p.missing_kinds.length))
      point(
        p.dx_m,
        p.dy_m,
        `缺少 ${p.missing_kinds.join('、')} · 1 公里直线口径`,
        '#687872',
        4,
        ui.groups.gaps,
      );
  }
  ui.map.fitBounds(ui.bounds, { padding: [20, 20], animate: false });
  const center = isSynthetic ? r.map.nodes.find((n) => n.id === r.parameters.center) : { x: 0, y: 0 };
  if (center) point(center.x, center.y, '体检中心', '#142b22', 9, ui.layer);
  comparison.forEach((row, index) => {
    const icon = L.divIcon({
      className: '',
      html: `<span class="plan-pin">${index + 1}</span>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    L.marker([row.target.y, row.target.x], { icon, title: `候选参考点 ${index + 1}` })
      .bindTooltip(tooltip(`${row.category}候选参考点 ${index + 1}`))
      .addTo(ui.groups.candidates);
  });
  renderComparison(comparison, isSynthetic);
  text('#evidenceParameters', '参数：' + JSON.stringify(r.parameters));
  const warnings = [
    ...(r.limitations || r.warnings || []),
    ...(analysis.isochrone?.warnings || []),
    ...(analysis.isochrone_error ? [analysis.isochrone_error] : []),
  ];
  $('#evidenceWarnings').replaceChildren(...warnings.map((w) => element('li', w)));
  text('#evidenceJson', JSON.stringify(analysis, null, 2));
  text(
    '#focusNote',
    `体检证据 ${r.evidence_id}${analysis.isochrone ? ' · 等时圈证据 ' + analysis.isochrone.evidence_id : ''}`,
  );
  renderFacilities(analysis);
  $('#facilityDetails').hidden = true;
  if (!ui.geo) {
    ui.geo = new NeighborhoodGeo.GeoEvidenceView($('#assistantMap'), focusFacility);
    $('#assistantMap').addEventListener('geoviewchange', () =>
      requestAnimationFrame(() => {
        if (ui.analysis?.type === 'live')
          text(
            '#mapCaption',
            ui.geo?.active
              ? '百度道路地图上的 BD-09 测时网格与专项缺口；色块为采样邻域估计。'
              : '以社区中心为原点的米制示意图；输入与数据坐标为 BD-09。点位不代替连续等时圈。',
          );
        ui.map?.invalidateSize();
        if (ui.bounds) ui.map?.fitBounds(ui.bounds, { animate: false });
      }),
    );
  }
  ui.geo.visibleGroups = {};
  ui.geoReady = ui.geo.setData(analysis, comparison);
}
function renderComparison(rows, synthetic) {
  $('#comparisonPanel').hidden = !rows.length;
  text(
    '#comparisonNote',
    synthetic
      ? '每个候选分别与原始方案比较，属于互斥模拟；新增覆盖按各类服务同时可达计算。'
      : '独立增益分别计算；组合新增去除前序同类点的重叠，仅针对已知缺口。',
  );
  const headings = synthetic
    ? ['方案', '类别 / 节点', '同时可达', '新增样点', '剩余缺口']
    : ['参考点', '类别', '独立增益', '组合新增', '组合剩余缺口'];
  const tr = element('tr');
  headings.forEach((h) => {
    const th = element('th', h);
    th.scope = 'col';
    tr.append(th);
  });
  $('#comparisonHead').replaceChildren(tr);
  $('#comparisonBody').replaceChildren(
    ...rows.map((r, i) => {
      const tr = element('tr');
      const values = synthetic
        ? [
            i + 1,
            `${r.category} @ ${r.node}`,
            `${r.before_pct}% → ${r.after_pct}%`,
            r.gain_count,
            r.gap_count,
          ]
        : [i + 1, r.category, r.independent_gain_count, r.marginal_gain_count, r.gap_count];
      values.forEach((v) => tr.append(element('td', v)));
      return tr;
    }),
  );
}
async function focusFact(fact) {
  const snapshot = ui.result.snapshots[fact.snapshot_id];
  if (!snapshot) return;
  const focusSerial = (ui.focusSerial || 0) + 1;
  ui.focusSerial = focusSerial;
  if (analysisKey(ui.analysis) !== analysisKey(snapshot.analysis))
    renderEvidence(snapshot.analysis, snapshot.comparison);
  await ui.geoReady;
  if (focusSerial !== ui.focusSerial || analysisKey(ui.analysis) !== analysisKey(snapshot.analysis)) return;
  setResultsView('map', () => {
    if (focusSerial !== ui.focusSerial || analysisKey(ui.analysis) !== analysisKey(snapshot.analysis)) return;
    ui.map.invalidateSize();
    ui.highlight?.remove();
    const target = fact.target,
      r = snapshot.analysis.inspection;
    if (target.type === 'point') {
      ui.highlight = L.circleMarker([target.y, target.x], {
        radius: 15,
        color: '#8b6b24',
        weight: 3,
        fill: false,
      }).addTo(ui.map);
      ui.map.fitBounds(ui.bounds, { animate: false });
    } else if (target.type === 'path' && snapshot.analysis.type === 'synthetic') {
      const points = r.witness.path
        .map((id) => r.map.nodes.find((n) => n.id === id))
        .filter(Boolean)
        .map((n) => [n.y, n.x]);
      if (points.length > 1) {
        ui.highlight = L.polyline(points, { color: '#8b6b24', weight: 5 }).addTo(ui.map);
        ui.map.fitBounds(ui.highlight.getBounds(), { padding: [30, 30], animate: false });
      }
    } else if (target.type === 'blind_spots') {
      ui.highlight = L.layerGroup(
        r.blind_spots.points
          .filter((p) => p.missing_kinds.includes(target.kind))
          .map((p) => L.circleMarker([p.dy_m, p.dx_m], { radius: 10, color: '#8b6b24', fill: false })),
      ).addTo(ui.map);
      ui.map.fitBounds(ui.bounds, { animate: false });
    } else ui.map.fitBounds(ui.bounds, { animate: false });
    if (ui.geo?.active) {
      ui.geo.fit();
      if (target.type === 'point') ui.geo.focusOffset(target.x, target.y);
      if (target.type === 'blind_spots') ui.geo.toggle('gaps', true);
    }
    text('#focusNote', fact.text + ' · 证据 ' + fact.evidence_id);
    $('#assistantEvidence').scrollIntoView({ block: 'nearest', behavior: 'auto' });
  });
}
async function invalidate(reset = true) {
  ui.geo?.reset();
  const pending = controller.stop(reset),
    sequence = controller.sequence;
  busy(false);
  ui.result = null;
  $('#assistantAnswer').hidden = true;
  $('#assistantEvidence').hidden = true;
  for (const id of ['summaryMetrics', 'scenarioPanel', 'reviewPanel', 'viewTabs']) $('#' + id).hidden = true;
  $('#emptyWorkspace').hidden = false;
  ui.scenarios = null;
  ui.saved = false;
  text('#runStatus', '参数已修改，请重新提交');
  text('#sessionHint', '已开始新会话，旧结果不会作为本次结论。');
  try {
    await pending;
    if (sequence === controller.sequence) showError(null);
  } catch (error) {
    if (sequence === controller.sequence) showError('停止请求未送达：' + error.message);
  }
}
function syncMode() {
  const live = $('#dataMode').value === 'live';
  $('#communityField').hidden = live;
  $('#addressFields').hidden = !live;
  $('#speedField').hidden = live;
  text(
    '#dataHint',
    live
      ? ui.mapStatus?.replay_mode
        ? `历史真实数据回放 · 录制于 ${ui.mapStatus.replay_preset.recorded_at}，本次不请求百度。地点与参数须匹配录制。`
        : '百度 POI 与步行耗时；坐标 BD-09。检索与测时会消耗账号配额。'
      : '合成路网与设施，等权样点不代表人口。',
  );
}
$('#assistantForm').addEventListener('submit', (e) => {
  e.preventDefault();
  submit();
});
$('#stopAssistant').addEventListener('click', async () => {
  try {
    await controller.stop(true);
    busy(false);
    $('#emptyWorkspace').hidden = false;
    text('#runStatus', '已提交停止；在途请求可能完成');
    text('#sessionHint', '再次提交将开始新会话。');
  } catch (error) {
    showError(error.message);
  }
});
$('#retryAssistant').addEventListener('click', submit);
$('#dataMode').addEventListener('change', () => {
  invalidate();
  syncMode();
});
$('#assistantCommunity').addEventListener('change', () => invalidate());
for (const id of ['assistantAddress', 'assistantCity', 'assistantMinutes', 'assistantSpeed'])
  $('#' + id).addEventListener('input', () => invalidate());
$('#newSession').addEventListener('click', () => invalidate());
document.querySelectorAll('[data-example]').forEach((button) =>
  button.addEventListener('click', () => {
    $('#assistantTask').value = button.dataset.example;
    $('#assistantTask').focus();
  }),
);
for (const [id, task] of [
  ['explainPrevious', '解释刚才的依据与口径限制。'],
  ['comparePrevious', '比较刚才的候选方案，说明独立增益和剩余缺口。'],
])
  $('#' + id).addEventListener('click', () => {
    $('#assistantTask').value = task;
    submit();
  });
$('#copyAnswer').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(
      [...ui.result.facts.map((f) => f.text + ' [证据 ' + f.evidence_id + ']'), ...ui.result.actions].join(
        '\n',
      ),
    );
    text('#copyStatus', '已复制结论与证据编号。');
  } catch {
    text('#copyStatus', '复制失败，请直接选择结论文本复制。');
  }
});
$('#exportAssistantReport').addEventListener('click', () => {
  if (!ui.result || ui.busy) return;
  const url = URL.createObjectURL(new Blob([ui.report], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'neighborhood-assistant-report.md';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function initialize() {
  const results = await Promise.allSettled([
    controller.request('/api/assistant/status'),
    controller.request('/api/live/status'),
  ]);
  if (results[0].status === 'fulfilled') {
    const s = results[0].value;
    text(
      '#modelStatus',
      s.configured
        ? '模型已配置 · 等待体检'
        : s.offline_launch
          ? '离线启动 · 规则分析'
          : '未配置模型 · 规则分析',
    );
  } else text('#modelStatus', '模型状态检查失败');
  if (results[1].status === 'fulfilled') {
    ui.mapStatus = results[1].value;
    if (ui.mapStatus.replay_mode) {
      $('#assistantAddress').value = ui.mapStatus.replay_preset.address;
      $('#assistantCity').value = ui.mapStatus.replay_preset.city || '';
    }
  }
  syncMode();
}
$('#refreshModel').addEventListener('click', async () => {
  try {
    const s = await controller.request('/api/assistant/status');
    text(
      '#modelStatus',
      s.configured
        ? '模型已配置 · 等待体检'
        : s.offline_launch
          ? '离线启动 · 规则分析'
          : '未配置模型 · 规则分析',
    );
  } catch {
    text('#modelStatus', '模型状态检查失败');
  }
});

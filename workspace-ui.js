'use strict';
let localRecords;
try {
  localRecords = new LocalInspectionStore(window.localStorage);
} catch {
  localRecords = null;
}
function icons() {
  if (window.lucide) lucide.createIcons({ attrs: { 'stroke-width': 1.8, 'aria-hidden': 'true' } });
}
function analysisKey(a) {
  return a ? `${a.type}:${a.inspection.evidence_id}:${a.isochrone?.evidence_id || ''}` : '';
}
function orderedFacts(result) {
  const priority = (fact) =>
    fact.id.endsWith(':summary')
      ? 0
      : fact.id.includes(':gap-')
        ? 1
        : fact.id.endsWith(':boundary-review')
          ? 2
          : fact.id.includes(':candidate-')
            ? 3
            : fact.id.endsWith(':limits')
              ? 5
              : 4;
  return [...result.facts].sort((a, b) => priority(a) - priority(b));
}
function setResultsView(view, afterMapReady) {
  $('.workspace-analysis').dataset.view = view;
  document.body.classList.toggle('comparison-view', view === 'compare');
  document.querySelectorAll('[data-view]').forEach((b) => {
    if (b.tagName === 'BUTTON') b.setAttribute('aria-pressed', String(b.dataset.view === view));
  });
  if (view === 'map')
    requestAnimationFrame(() => {
      ui.map?.invalidateSize();
      if (ui.bounds) ui.map?.fitBounds(ui.bounds, { padding: [16, 16], animate: false });
      ui.geo?.fit();
      afterMapReady?.();
    });
}
function renderWorkspace(job) {
  const result = job.result,
    a = result.analysis;
  $('#emptyWorkspace').hidden = true;
  $('#viewTabs').hidden = false;
  document.body.classList.toggle('no-analysis', !a);
  $('#summaryMetrics').hidden = !a;
  $('#saveInspection').disabled = !a;
  $('#printReport').disabled = !a;
  if (!a) {
    $('#scenarioPanel').hidden = true;
    $('#reviewPanel').hidden = true;
    return;
  }
  const r = a.inspection;
  const values =
    a.type === 'synthetic'
      ? [
          [
            '各类服务同时可达',
            r.combined_coverage_pct + '%',
            `${r.sample_count - r.gap_count} / ${r.sample_count} 个等权样点`,
          ],
          ['未覆盖样点', r.gap_count, `阈值 ${r.parameters.minutes} 分钟`],
          [
            '方案1独立新增',
            result.comparison[0]?.gain_count === undefined ? '—' : '+' + result.comparison[0].gain_count,
            '单独与原始方案比较',
          ],
        ]
      : [
          [
            '已评估设施',
            r.facility_count,
            `检索去重 ${r.performance.unique_pois_before_limit} 处，非完整清单`,
          ],
          [
            '已知专项缺口',
            r.blind_spots.known_gap_count,
            `${r.blind_spots.sample_count} 个样点 · 至少一类已知缺口`,
          ],
          ['近阈值待复核', a.isochrone?.summary.near_threshold ?? '—', '距阈值不超过2分钟，非置信区间'],
        ];
  ['Primary', 'Second', 'Third'].forEach((suffix, i) => {
    text('#metric' + suffix + 'Label', values[i][0]);
    text('#metric' + suffix, values[i][1]);
    text('#metric' + suffix + 'Note', values[i][2]);
  });
  if (ui.saved) {
    text('#runStatus', '本机历史快照');
    text('#evidenceSource', sourceNames[r.mode] + ' · 快照');
    text(
      '#runCounters',
      `原运行记录 · 模型 ${job.model_calls} 轮 · 工具 ${job.tool_calls} 次 · 新发地图请求 ${job.map_requests}`,
    );
  }
  renderReviews();
  refreshWorkspaceReport();
  if (ui.saved) renderScenarios(ui.scenarios);
  else {
    const identity = job.id;
    $('#scenarioPanel').hidden = false;
    text('#scenarioLabel', '正在读取同一组样点的情景比较…');
    $('#scenarioRows').replaceChildren();
    text('#scenarioNote', '');
    controller
      .request(`/api/assistant/runs/${identity}/scenarios`)
      .then((value) => {
        if (ui.job?.id !== identity || ui.result !== result || ui.saved) return;
        ui.scenarios = value;
        renderScenarios(value);
      })
      .catch((error) => {
        if (ui.job?.id === identity && ui.result === result && !ui.saved) {
          ui.scenarios = null;
          text('#scenarioLabel', error.message);
        }
      });
  }
  icons();
}
function renderScenarios(value) {
  $('#scenarioPanel').hidden = !value;
  if (!value) return;
  text('#scenarioLabel', `${value.label} · 来源：${sourceNames[value.mode]}`);
  $('#scenarioRows').replaceChildren(
    ...value.rows.map((row) => {
      const node = element('div', undefined, 'scenario-row');
      node.append(
        element('span', row.minutes + ' 分钟'),
        element('strong', row.ratio_pct === null ? '未知' : row.ratio_pct + '%'),
      );
      const bar = element('div', undefined, 'scenario-bar'),
        fill = element('i');
      fill.style.width = (row.ratio_pct || 0) + '%';
      bar.append(fill);
      node.append(bar, element('small', `${row.reachable}/${row.known} 个已知样点 · 未知 ${row.unknown}`));
      return node;
    }),
  );
  text('#scenarioNote', value.note + ` 证据 ${value.evidence_id}`);
}
function renderFacilities(analysis) {
  const r = analysis.inspection;
  text('#facilityListCount', `(${r.facilities.length})`);
  $('#facilityList').replaceChildren(
    ...r.facilities.map((f, index) => {
      const b = element('button');
      b.type = 'button';
      b.append(
        element('strong', f.name),
        element('span', (f.route?.walk_minutes ?? f.walk_minutes ?? '未知') + ' 分钟'),
      );
      b.addEventListener('click', () => focusFacility(index));
      return b;
    }),
  );
}
function focusFacility(index) {
  const a = ui.analysis,
    f = a?.inspection.facilities[index];
  if (!f) return;
  setResultsView('map');
  ui.map.invalidateSize();
  if (!ui.layer.hasLayer(ui.groups.facilities)) ui.groups.facilities.addTo(ui.layer);
  document.querySelector('[data-layer="facilities"]').setAttribute('aria-pressed', 'true');
  const marker = ui.facilityMarkers[index];
  if (marker) {
    ui.map.setView(marker.getLatLng(), ui.map.getZoom(), { animate: false });
    marker.openTooltip();
  }
  ui.geo?.focusFacility(index);
  const detail = $('#facilityDetails');
  detail.hidden = false;
  const route = f.route || f,
    minutes = route.walk_minutes,
    within = route.within_threshold;
  detail.replaceChildren(
    element('h4', f.name),
    element(
      'p',
      (f.eligible_categories || f.categories || [f.category]).join('、') +
        ' · 中心步行 ' +
        (minutes ?? '未知') +
        ' 分钟',
    ),
    element(
      'p',
      route.status === 'error'
        ? '路线未知：' + (route.message || '缺少耗时')
        : within
          ? '在本次时间阈值内'
          : '在本次时间阈值外',
    ),
    element('small', f.classification_note || '设施类别、营业状态和入口仍需核验。'),
    element('small', '证据 ' + a.inspection.evidence_id),
  );
  if (a.type === 'live') {
    const url = officialRouteUrl(a.inspection.community.center, f.location, a.inspection.community.city);
    if (url) {
      const link = element('a', '到百度地图核对同一起终点 ↗');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      detail.append(link);
    }
  } else detail.append(element('small', '合成节点 ' + f.node + '，没有对应的真实地理坐标。'));
  detail.scrollIntoView({ block: 'nearest' });
}
function reviewTasks() {
  const a = ui.result?.analysis;
  if (!a) return [];
  if (a.type === 'synthetic')
    return [
      {
        key: 'synthetic-witness',
        title: '核对合成绕行路径',
        description: `${a.inspection.witness.from} → ${a.inspection.witness.to}，路网 ${a.inspection.witness.network_minutes} 分钟；只验证样例，不能作为现场核验。`,
      },
    ];
  const r = a.inspection;
  const tasks = (a.isochrone?.points || [])
    .filter((p) => p.near_threshold || p.status === 'unknown')
    .map((p) => ({
      key: `sample:${p.dx_m},${p.dy_m}`,
      title: `${p.status === 'unknown' ? '未知' : '近阈值'}样点 (${p.dx_m}, ${p.dy_m}) m`,
      description: `原始耗时 ${p.duration_s ?? '未知'} 秒；本次阈值 ${r.parameters.minutes} 分钟。核对过街和实际入口。`,
      url: officialRouteUrl(r.community.center, { lat: p.lat, lng: p.lng }, r.community.city),
    }));
  r.facilities.forEach((f, index) =>
    tasks.push({
      key: 'facility:' + String(f.identity || f.uid || index),
      title: f.name,
      description:
        (f.classification_note || '设施子类和营业状态待核验') +
        '；路线 ' +
        (f.route.walk_minutes ?? '未知') +
        ' 分钟。',
      url: officialRouteUrl(r.community.center, f.location, r.community.city),
    }),
  );
  return tasks;
}
function renderReviews() {
  const tasks = reviewTasks();
  $('#reviewPanel').hidden = !tasks.length;
  text('#reviewCount', `(${tasks.length})`);
  $('#reviewList').replaceChildren(
    ...tasks.map((task) => {
      const saved = ui.reviews[task.key] || { status: 'pending', note: '' };
      const item = element('div', undefined, 'review-item'),
        description = element('div');
      description.append(element('h4', task.title), element('p', task.description));
      if (task.url) {
        const link = element('a', '官方路线核对 ↗', 'text-button');
        link.href = task.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        description.append(link);
      }
      const select = element('select');
      select.setAttribute('aria-label', task.title + ' 核验状态');
      for (const [value, label] of [
        ['pending', '待核验'],
        ['checked', '已核验'],
        ['excluded', '暂不采用'],
      ]) {
        const option = element('option', label);
        option.value = value;
        select.append(option);
      }
      select.value = saved.status;
      const note = element('textarea');
      note.value = saved.note;
      note.maxLength = 500;
      note.rows = 2;
      note.placeholder = '核验来源、入口情况或发现的问题';
      note.setAttribute('aria-label', task.title + ' 核验备注');
      const time = element(
        'span',
        saved.updated_at ? '本机记录 ' + new Date(saved.updated_at).toLocaleString() : '尚未保存',
        'review-time',
      );
      const save = element('button', '保存备注', 'button review-save');
      save.type = 'button';
      save.addEventListener('click', () => {
        try {
          ensureSaved();
          const value = localRecords.review(ui.recordId, task.key, select.value, note.value);
          ui.reviews[task.key] = value;
          refreshWorkspaceReport();
          time.textContent = '已保存 ' + new Date(value.updated_at).toLocaleString();
          text('#copyStatus', '核验备注已保存在本机，原始结果保持独立。');
        } catch (error) {
          text('#copyStatus', error.message);
          time.textContent = '未保存：' + error.message;
        }
      });
      item.append(description, select, note, time, save);
      return item;
    }),
  );
}
function ensureSaved() {
  if (!localRecords) throw new Error('浏览器未开放本机存储，仍可复制或导出报告。');
  if (ui.saved && ui.recordId && localRecords.get(ui.recordId)) return;
  const value = localRecords.save(ui.job, ui.submittedTask, payload(), ui.scenarios);
  ui.recordId = value.id;
  ui.reviews = value.reviews;
}
function refreshWorkspaceReport() {
  if (!ui.job?.result) return;
  const labels = new Map(reviewTasks().map((task) => [task.key, task.title]));
  const notes = Object.entries(ui.reviews).filter(([, v]) => v.note);
  ui.report = reportMarkdown(ui.job);
  if (notes.length)
    ui.report +=
      '\n\n## 本机核验备注（独立于原始结果）\n\n' +
      notes
        .map(
          ([key, v]) =>
            `- ${labels.get(key) || key}：${{ pending: '待核验', checked: '已核验（本机记录）', excluded: '暂不采用（本机记录）' }[v.status]}；${v.note}；记录时间 ${v.updated_at}`,
        )
        .join('\n');
  text('#assistantReport', ui.report);
}
function renderHistory() {
  const rows = localRecords?.list() || [];
  $('#historyList').replaceChildren(
    ...rows.map((record) => {
      const item = element('article', undefined, 'history-item'),
        a = record.job.result.analysis,
        r = a.inspection;
      item.append(
        element('h3', a.type === 'synthetic' ? r.community.name : r.community.address),
        element(
          'p',
          `${sourceNames[r.mode]} · 保存于 ${new Date(record.created_at).toLocaleString()} · 阈值 ${r.parameters.minutes} 分钟`,
        ),
        element('p', record.task),
      );
      const actions = element('div', undefined, 'history-actions'),
        load = element('button', '加载快照', 'button'),
        remove = element('button', '删除', 'button');
      load.type = remove.type = 'button';
      load.addEventListener('click', async () => {
        await controller.stop(true);
        try {
          ui.saved = true;
          ui.recordId = record.id;
          ui.reviews = record.reviews || {};
          ui.scenarios = record.scenarios;
          ui.submittedTask = record.task;
          ui.result = record.job.result;
          ui.job = record.job;
          for (const [key, id] of [
            ['data_mode', 'dataMode'],
            ['community_id', 'assistantCommunity'],
            ['address', 'assistantAddress'],
            ['city', 'assistantCity'],
            ['minutes', 'assistantMinutes'],
            ['speed', 'assistantSpeed'],
          ])
            if (record.request[key] !== undefined) $('#' + id).value = record.request[key] ?? '';
          $('#assistantTask').value = record.task;
          syncMode();
          renderJob(record.job);
          $('#historyDialog').close();
          document.body.classList.add('params-collapsed');
          setResultsView('answer');
        } catch (error) {
          showError('历史记录无法显示，请重新体检。');
        }
      });
      remove.addEventListener('click', () => {
        if (window.confirm('删除这条本机体检记录？请先导出需要保留的报告。')) {
          try {
            localRecords.remove(record.id);
            renderHistory();
          } catch (error) {
            showError(error.message);
          }
        }
      });
      actions.append(load, remove);
      item.append(actions);
      return item;
    }),
  );
  if (!rows.length)
    $('#historyList').append(element('p', '暂无本机记录。完成体检后点击“保存体检”。', 'history-empty'));
}
function printMap(analysis) {
  const ns = 'http://www.w3.org/2000/svg',
    svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 800 290');
  svg.setAttribute('class', 'print-map');
  svg.setAttribute('aria-label', '体检样点示意图');
  const r = analysis.inspection;
  const points =
    analysis.type === 'synthetic'
      ? r.map.nodes.map((n) => ({ x: n.x, y: n.y, status: n.gap ? 'unreachable' : 'reachable' }))
      : (analysis.isochrone?.points || []).map((p) => ({ x: p.dx_m, y: p.dy_m, status: p.status }));
  if (!points.length) return svg;
  const minX = Math.min(...points.map((p) => p.x)),
    maxX = Math.max(...points.map((p) => p.x)),
    minY = Math.min(...points.map((p) => p.y)),
    maxY = Math.max(...points.map((p) => p.y)),
    scale = Math.min(740 / Math.max(1, maxX - minX), 240 / Math.max(1, maxY - minY));
  const offsetX = (800 - (maxX - minX) * scale) / 2,
    offsetY = (290 - (maxY - minY) * scale) / 2;
  for (const p of points) {
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('cx', String(offsetX + (p.x - minX) * scale));
    c.setAttribute('cy', String(290 - offsetY - (p.y - minY) * scale));
    c.setAttribute('r', '3');
    c.setAttribute(
      'fill',
      p.status === 'reachable' ? '#197257' : p.status === 'unknown' ? '#b39024' : '#b76b7b',
    );
    svg.append(c);
  }
  if (analysis.type === 'synthetic') {
    const path = document.createElementNS(ns, 'polyline');
    path.setAttribute(
      'points',
      r.witness.path
        .map((id) => r.map.nodes.find((n) => n.id === id))
        .filter(Boolean)
        .map((n) => [offsetX + (n.x - minX) * scale, 290 - offsetY - (n.y - minY) * scale].join(','))
        .join(' '),
    );
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#8b6b24');
    path.setAttribute('stroke-width', '2.5');
    svg.append(path);
  }
  return svg;
}
function buildPrintSheet() {
  const sheet = $('#printSheet'),
    a = ui.result?.analysis;
  if (!a) return;
  const r = a.inspection,
    name = a.type === 'synthetic' ? r.community.name : r.community.address;
  const task =
    ui.submittedTask.length > 100 ? ui.submittedTask.slice(0, 100) + '…（全文见Markdown）' : ui.submittedTask;
  sheet.replaceChildren(
    element('h1', '邻里圈 · 生活圈体检摘要'),
    element('p', `${name} · ${sourceNames[r.mode]}${ui.saved ? ' · 已保存快照' : ''}`, 'print-meta'),
    element('p', `需求：${task}`),
    element(
      'p',
      `阈值 ${r.parameters.minutes} 分钟 · 类别 ${r.parameters.categories.join('、')} · 体检证据 ${r.evidence_id}`,
      'print-meta',
    ),
    printMap(a),
    element(
      'p',
      '绿色：阈值内/覆盖；红色：阈值外/缺口；黄色：未知。样点示意不表示连续边界或人口覆盖。',
      'print-note',
    ),
  );
  sheet.append(element('h2', '结论与依据'));
  const facts = element('ul');
  orderedFacts(ui.result)
    .filter((f) => !f.id.endsWith(':limits'))
    .slice(0, 4)
    .forEach((f) => facts.append(element('li', f.text + ' [证据 ' + f.evidence_id + ']')));
  sheet.append(facts);
  if (ui.result.comparison.length) {
    sheet.append(element('h2', '候选方案（分别核算）'));
    const list = element('ul');
    ui.result.comparison
      .slice(0, 3)
      .forEach((c, i) =>
        list.append(
          element(
            'li',
            a.type === 'synthetic'
              ? `方案${i + 1} · ${c.category} @ ${c.node}：同时可达 ${c.before_pct}% → ${c.after_pct}%，独立新增 ${c.gain_count} 个样点；剩余 ${c.gap_count}。`
              : `参考点${i + 1} · ${c.category}：独立增益 ${c.independent_gain_count}，组合新增 ${c.marginal_gain_count}；组合剩余 ${c.gap_count}。`,
          ),
        ),
      );
    sheet.append(list);
  }
  if (ui.scenarios) {
    sheet.append(element('h2', '固定样点情景对比'));
    sheet.append(
      element(
        'p',
        ui.scenarios.rows
          .map(
            (v) =>
              `${v.minutes}分钟：${v.ratio_pct === null ? '未知' : v.ratio_pct + '%'}（${v.reachable}/${v.known}，未知${v.unknown}）`,
          )
          .join('；'),
      ),
    );
    sheet.append(element('p', ui.scenarios.note, 'print-note'));
  }
  const notes = Object.values(ui.reviews)
    .filter((v) => v.note)
    .slice(0, 2);
  if (notes.length) {
    sheet.append(element('h2', '本机核验备注（节选，不改写原始结果）'));
    notes.forEach((v) => sheet.append(element('p', v.note.slice(0, 80) + (v.note.length > 80 ? '…' : ''))));
    sheet.append(element('p', '完整备注见本机记录与Markdown报告。', 'print-note'));
  }
  sheet.append(element('h2', '下一步与口径'));
  sheet.append(element('p', ui.result.actions.join(' ')));
  sheet.append(
    element(
      'p',
      '等权样点不代表人口或土地面积；设施营业、入口、容量与用地仍需核验。完整明细与证据可导出Markdown查看。',
      'print-note',
    ),
  );
  sheet.append(
    element(
      'p',
      `报告生成：${new Date().toLocaleString()}；模型 ${modeNames[ui.job.mode]}；原运行新增地图请求 ${ui.job.map_requests}。${r.replay?.recorded_at ? '地图录制：' + r.replay.recorded_at + '。' : ''}`,
      'print-note',
    ),
  );
}
$('#toggleParameters').addEventListener('click', () => {
  const collapsed = document.body.classList.toggle('params-collapsed');
  $('#toggleParameters').setAttribute('aria-expanded', String(!collapsed));
});
document.querySelectorAll('[data-view]').forEach((b) => {
  if (b.tagName === 'BUTTON') b.addEventListener('click', () => setResultsView(b.dataset.view));
});
document.querySelectorAll('[data-layer]').forEach((b) =>
  b.addEventListener('click', () => {
    const group = ui.groups[b.dataset.layer];
    if (!group || !ui.map) return;
    const visible = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(visible));
    visible ? group.addTo(ui.layer) : ui.layer.removeLayer(group);
    ui.geo?.toggle(b.dataset.layer, visible);
  }),
);
$('#fitMap').addEventListener('click', () => {
  if (ui.geo?.active) ui.geo.fit();
  else if (ui.bounds) ui.map.fitBounds(ui.bounds, { padding: [16, 16], animate: false });
});
$('#showWitness').addEventListener('click', () => {
  const a = ui.analysis;
  if (a?.type !== 'synthetic') return;
  setResultsView('map');
  ui.map.invalidateSize();
  ui.highlight?.remove();
  const r = a.inspection,
    points = r.witness.path
      .map((id) => r.map.nodes.find((n) => n.id === id))
      .filter(Boolean)
      .map((n) => [n.y, n.x]);
  if (points.length > 1) {
    ui.highlight = L.polyline(points, { color: '#8b6b24', weight: 5 }).addTo(ui.map);
    ui.map.fitBounds(ui.highlight.getBounds(), { padding: [25, 25], animate: false, maxZoom: 0 });
  }
  text(
    '#focusNote',
    `合成证据 ${r.witness.from} → ${r.witness.to}：直线 ${r.witness.straight_minutes} 分钟，路网 ${r.witness.network_minutes} 分钟；证据 ${r.evidence_id}`,
  );
});
$('#toggleFacts').addEventListener('click', () => {
  const open = $('#assistantFacts').dataset.expanded !== 'true';
  $('#assistantFacts').dataset.expanded = String(open);
  text('#toggleFacts', open ? '收起详细证据' : '查看全部证据');
});
$('#loadCareExample').addEventListener('click', () => {
  if (ui.busy) return;
  invalidate();
  $('#dataMode').value = 'synthetic';
  $('#assistantCommunity').value = 'bridge-demo';
  $('#assistantTask').value = '检查养老服务缺口，比较前两个候选方案，并说明依据。';
  syncMode();
  document.body.classList.remove('params-collapsed');
  $('#assistantTask').focus();
});
$('#saveInspection').addEventListener('click', () => {
  try {
    ensureSaved();
    text('#copyStatus', '体检和情景比较已保存在本机。');
  } catch (error) {
    text('#copyStatus', error.message);
  }
});
$('#openHistory').addEventListener('click', () => {
  renderHistory();
  $('#historyDialog').showModal();
});
$('#closeHistory').addEventListener('click', () => $('#historyDialog').close());
$('#printReport').addEventListener('click', () => {
  buildPrintSheet();
  $('#printPreviewBody').replaceChildren(
    ...Array.from($('#printSheet').childNodes, (n) => n.cloneNode(true)),
  );
  $('#printPreview').showModal();
});
$('#closePrintPreview').addEventListener('click', () => $('#printPreview').close());
$('#confirmPrint').addEventListener('click', () => window.print());
icons();
initialize();
if (new URLSearchParams(location.search).get('demo') === 'care') {
  $('#assistantTask').value = '检查养老服务缺口，比较前两个候选方案，并说明依据。';
  text('#sessionHint', '合成示例已载入，点击开始体检。');
}

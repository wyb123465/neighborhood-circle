from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from io import BytesIO

import networkx as nx
from PIL import Image, ImageDraw

CATEGORIES = ("医疗", "养老", "教育", "购物")
KINDS = ("菜市场", "药店", "小学")
METHOD_VERSION = "networkx-sample-coverage-v2"


def network(spec):
    graph = nx.Graph()
    for y in range(spec["rows"]):
        for x in range(spec["columns"]):
            graph.add_node(f"{x},{y}", x=x * spec["spacing_m"], y=y * spec["spacing_m"])
    for node in graph:
        x, y = map(int, node.split(","))
        for dx, dy in ((1, 0), (0, 1)):
            other = f"{x + dx},{y + dy}"
            if other not in graph:
                continue
            if dx and x == spec["barrier_column"] and y not in spec["crossing_rows"]:
                continue
            graph.add_edge(node, other, length=spec["spacing_m"])
    return graph


@lru_cache(maxsize=8)
def prepared(serialized):
    graph = network(json.loads(serialized))
    lengths = dict(nx.all_pairs_dijkstra_path_length(graph, weight="length"))
    return graph, lengths


def inspect(spec, categories, minutes=15, speed=80, center=None, addition=None):
    serialized = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    graph, lengths = prepared(serialized)
    center = center or spec["center"]
    if center not in graph:
        raise ValueError("中心点不在合成路网内")
    if addition and (addition["node"] not in graph or addition["category"] not in categories):
        raise ValueError("候选点或设施类别无效")
    threshold = minutes * speed
    facilities = list({f["id"]: f for f in spec["facilities"]}.values())
    relevant = [f for f in facilities if f["category"] in categories]
    targets = {c: [f["node"] for f in relevant if f["category"] == c] for c in categories}

    def distances(nodes):
        return {n: min((lengths[n].get(t, math.inf) for t in nodes), default=math.inf) for n in graph}

    before = {c: distances(targets[c]) for c in categories}
    after = {c: dict(values) for c, values in before.items()}
    if addition:
        category, candidate = addition["category"], addition["node"]
        after[category] = {n: min(d, lengths[n].get(candidate, math.inf)) for n, d in before[category].items()}
        relevant.append({"id": "proposed", "name": "模拟新增服务点", "category": category, "kind": "候选设施", "node": candidate})

    def reachable_counts(values):
        return {c: sum(d <= threshold for d in values[c].values()) for c in categories}

    base_counts, counts = reachable_counts(before), reachable_counts(after)
    total = len(graph)
    pct = lambda n: round(n / total * 100, 1)
    weakest = min(categories, key=lambda c: (base_counts[c], CATEGORIES.index(c)))
    candidates = []
    for candidate in graph:
        if candidate in targets[weakest]:
            continue
        gained = sum(d > threshold and lengths[n].get(candidate, math.inf) <= threshold for n, d in before[weakest].items())
        if gained:
            candidates.append({"node": candidate, "category": weakest, "gain": gained, "before_pct": pct(base_counts[weakest]), "after_pct": pct(base_counts[weakest] + gained)})
    candidates.sort(key=lambda c: (-c["gain"], c["node"]))
    gaps = [n for n in graph if any(after[c][n] > threshold for c in categories)]
    base_gaps = [n for n in graph if any(before[c][n] > threshold for c in categories)]
    routes = lengths[center]
    straight = lambda a, b: math.hypot(graph.nodes[a]["x"] - graph.nodes[b]["x"], graph.nodes[a]["y"] - graph.nodes[b]["y"])
    reachable = [n for n in graph if routes.get(n, math.inf) <= threshold]
    circle = [n for n in graph if straight(center, n) <= threshold]
    mismatch = [n for n in circle if n not in reachable]
    # A single reproducible path witnesses the straight-line overestimate.
    witness = max(mismatch or reachable, key=lambda n: (routes.get(n, -1), n))
    path = nx.shortest_path(graph, center, witness, weight="length") if witness in routes else []
    checks = []
    for kind in KINDS:
        sources = [f["node"] for f in facilities if f["kind"] == kind]
        missing = [n for n in graph if not sources or min(straight(n, s) for s in sources) > 1000]
        checks.append({"kind": kind, "gap_count": len(missing), "gap_nodes": missing, "facility_count": len(sources)})
    all_distances = [d for c in categories for d in after[c].values() if math.isfinite(d)]
    def facility(f):
        distance = routes.get(f["node"])
        return {
            **f,
            "walk_minutes": round(distance / speed, 1) if distance is not None else None,
            "within_threshold": distance is not None and distance <= threshold,
        }
    evidence_id = hashlib.sha256((serialized + METHOD_VERSION + json.dumps([categories, minutes, speed, center, addition], ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]
    return {
        "mode": "synthetic", "method_version": METHOD_VERSION, "evidence_id": evidence_id,
        "community": {"id": spec["id"], "name": spec["name"], "center": center},
        "source": spec["source"], "dataset_version": spec["version"],
        "parameters": {"categories": categories, "minutes": minutes, "speed_m_min": speed, "center": center, "addition": addition},
        "sample_count": total, "facility_count": len(relevant),
        "coverage": {c: {"count": counts[c], "pct": pct(counts[c]), "before_pct": pct(base_counts[c])} for c in categories},
        "combined_coverage_pct": pct(total - len(gaps)), "base_combined_coverage_pct": pct(total - len(base_gaps)),
        "average_coverage_pct": round(sum(pct(counts[c]) for c in categories) / len(categories), 1),
        "gap_count": len(gaps), "avg_walk_minutes": round(sum(all_distances) / len(all_distances) / speed, 1) if all_distances else None,
        "unreachable_pairs": sum(not math.isfinite(d) for c in categories for d in after[c].values()),
        "missing_categories": [c for c in categories if not targets[c]],
        "weakest_category": weakest, "recommendations": candidates[:3],
        "facilities": [facility(f) for f in relevant],
        "reachability": {"network_count": len(reachable), "straight_count": len(circle), "overestimated_count": len(mismatch), "nodes": reachable},
        "witness": {"from": center, "to": witness, "path": path, "straight_minutes": round(straight(center, witness) / speed, 1), "network_minutes": round(routes[witness] / speed, 1) if witness in routes else None},
        "one_km_checks": checks,
        "map": {"nodes": [{"id": n, **graph.nodes[n], "gap": n in gaps} for n in graph], "spacing_m": spec["spacing_m"]},
        "limitations": [
            "合成路网与设施，不代表上海任何真实社区；本次计算未调用百度 API。",
            "覆盖率的分母是等权路网采样点，不是居民人数、人口覆盖率或土地面积。",
            "步速恒定；未考虑坡度、过街等待、设施容量、开放时段和土地可用性。",
            "1 公里检查按直线距离、原有设施单独统计，不受模拟新增点影响。",
            "候选点仅按新增可达采样点排序，不构成建设选址结论。"
        ],
    }


def map_image(spec):
    # The raster is a pure function of the sample spec, so reuse it across requests
    # instead of redrawing every node on each page load. This is an in-process asset
    # cache only; it says nothing about Baidu API caching or live performance.
    return _raster_for(json.dumps(spec, ensure_ascii=False, sort_keys=True))


@lru_cache(maxsize=8)
def _raster_for(serialized):
    spec = json.loads(serialized)
    graph = network(spec)
    spacing = spec["spacing_m"]
    width, height = spec["columns"] * spacing, spec["rows"] * spacing
    image = Image.new("RGB", (width, height), "#f3f5f5")
    draw = ImageDraw.Draw(image)
    barrier = spec["barrier_column"]
    if barrier is not None:
        middle = (barrier + 1) * spacing
        draw.rectangle((middle - 40, 0, middle + 40, height), fill="#c7e4ef")
    for y in range(spec["rows"] - 1):
        for x in range(spec["columns"] - 1):
            if x == barrier:
                continue
            left, top = x * spacing + spacing / 2, y * spacing + spacing / 2
            draw.rectangle((left + 20, top + 20, left + spacing - 20, top + spacing - 20), fill="#e0e5e4", outline="#d3dbd9", width=2)
    for a, b in graph.edges:
        points = [(graph.nodes[n]["x"] + spacing / 2, height - graph.nodes[n]["y"] - spacing / 2) for n in (a, b)]
        draw.line(points, fill="#bcc9c5", width=14)
        draw.line(points, fill="#ffffff", width=10)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def report_markdown(result):
    params = result["parameters"]
    addition = params["addition"]
    lines = [
        f"# 邻里圈体检报告：{result['community']['name']}",
        "",
        "**合成样例结果，非真实社区体检。**",
        "",
        "## 可追溯元数据",
        "",
        f"- 证据编号：`{result['evidence_id']}`",
        f"- 算法版本：`{result['method_version']}`",
        f"- 数据版本：`{result['dataset_version']}`",
        f"- 数据来源：{result['source']}",
        f"- 运行模式：{result['mode']}（离线可复现路径；本次未调用地图开放接口）",
        f"- 中心点：`{params['center']}`",
        f"- 步行阈值：{params['minutes']} 分钟",
        f"- 假设步速：{params['speed_m_min']} 米/分钟",
        f"- 所选设施类别：{'、'.join(params['categories'])}",
        f"- 候选模拟：{'已启用（' + addition['category'] + ' @ ' + addition['node'] + '）' if addition else '未启用'}",
        "",
        "## 结果摘要",
        "",
        f"- 等权采样点：{result['sample_count']} 个",
        f"- 所选各类服务同时可达：{result['combined_coverage_pct']}%（模拟前 {result['base_combined_coverage_pct']}%）",
        f"- 各类别覆盖率算术平均：{result['average_coverage_pct']}%（仅作参考，不等于同时可达）",
        f"- 缺口采样点：{result['gap_count']} 个",
        f"- 所选设施：{result['facility_count']} 处",
        f"- 直线范围高估点数：{result['reachability']['overestimated_count']} 个（直线圈内但路网阈值外）",
    ]
    if result["missing_categories"]:
        lines.append(f"- 缺失设施类别（样例中无对应设施）：{'、'.join(result['missing_categories'])}")
    lines += [
        "",
        "## 分类别覆盖",
        "",
        "| 设施类别 | 可达点数 | 覆盖率 | 模拟前覆盖率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, row in result["coverage"].items():
        lines.append(f"| {category} | {row['count']} | {row['pct']}% | {row['before_pct']}% |")
    witness = result["witness"]
    path_text = " / ".join(witness["path"]) if witness["path"] else "（不可达）"
    lines += [
        "",
        "## 路径证据（直线 vs 路网）",
        "",
        f"{witness['from']} → {witness['to']}：直线 {witness['straight_minutes']} 分钟，样例路网 {witness['network_minutes']} 分钟。",
        f"路径节点：{path_text}",
        "",
        "说明：本条路径用于说明「直线可达」与「路网可达」的差异，可按节点编号复算。",
        "",
        "## 1 公里专项检查（直线距离，原有设施）",
    ]
    for check in result["one_km_checks"]:
        lines.append(f"- {check['kind']}：{check['facility_count']} 处设施；{check['gap_count']} 个点周边 1 公里无对应样例设施。")
    lines += ["", "## 模拟方案"]
    if addition:
        lines += [
            f"- 类别：{addition['category']}",
            f"- 候选节点：`{addition['node']}`",
            "- 含义：仅按新增可达采样点重算覆盖率；不证明用地可行、容量充足或建设收益。",
        ]
    else:
        lines.append("未加入候选设施。")
    lines += ["", "## 未知点与口径边界"]
    lines.extend(f"- {text}" for text in result["limitations"])
    lines += [
        "- 本报告不输出居民人数、节省成本或建设收益；如需正式规划结论须另行调研审批。",
        "",
        "---",
        "",
        "由邻里圈本地服务生成。相同参数重复调用应得到相同证据编号与相同数值。",
    ]
    return "\n".join(lines) + "\n"

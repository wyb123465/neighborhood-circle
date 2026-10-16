"""Validated tools and program-rendered facts for the assistant."""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .analysis import CATEGORIES, inspect
from .baidu import BaiduApiError, BaiduConfig, BaiduMapsClient
from .live_api import client as shared_maps_client
from .live_inspection import inspect_live
from .live_isochrone import build_isochrone
from .sample_data import load_communities

COMMUNITIES = load_communities()


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectArgs(StrictArgs):
    community_id: Literal["bridge-demo", "grid-demo"] = "bridge-demo"
    address: str | None = Field(default=None, min_length=2, max_length=128)
    city: str | None = Field(default=None, max_length=32)
    categories: list[Literal["医疗", "养老", "教育", "购物"]] = Field(
        default_factory=lambda: list(CATEGORIES), min_length=1, max_length=4
    )
    minutes: int = Field(default=15, ge=5, le=30)
    speed: int = Field(default=80, ge=40, le=100)


class EvidenceArgs(StrictArgs):
    snapshot_id: str | None = Field(default=None, max_length=64)


class CompareArgs(EvidenceArgs):
    limit: int = Field(default=3, ge=1, le=3)
    facility_type: Literal["医疗", "养老", "教育", "购物", "菜市场", "药店", "小学"] | None = None


class FinishArgs(StrictArgs):
    fact_ids: list[str] = Field(default_factory=list, max_length=10)
    actions: list[
        Literal["verify_routes", "verify_pois", "verify_site", "compare", "refine", "adjust_scope"]
    ] = Field(default_factory=list, max_length=3)
    clarify_field: Literal["none", "address", "categories", "minutes", "community", "goal"] = "none"


ARGUMENTS = {
    "inspect_neighborhood": InspectArgs,
    "read_evidence": EvidenceArgs,
    "compare_candidates": CompareArgs,
    "finish": FinishArgs,
}
LABELS = {
    "inspect_neighborhood": "体检片区与服务缺口",
    "read_evidence": "读取已有结果与证据",
    "compare_candidates": "重算并比较候选方案",
    "finish": "整理有依据的结论",
}
DESCRIPTIONS = {
    "inspect_neighborhood": "按本次固定的数据模式执行体检。合成模式用 community_id、speed；真实模式用 address、city，步速由百度测时决定。参数改变须重新体检。",
    "read_evidence": "读取当前会话已计算结果，不重复请求地图。用来回答为什么、核验边界和追问。",
    "compare_candidates": "对已有体检的最多3个候选重算比较。合成是互斥方案；真实是样点启发式参考，分别给独立与组合边际增益。",
    "finish": "结束本次任务：只选择工具实际返回的 fact_id 作为结论。引用事实时 clarify_field 必须为 none；缺信息追问时 fact_ids 必须为空。不得编造ID或数值。",
}
ACTIONS = {
    "verify_routes": "复核近阈值路线、道路通行与实际出入口。",
    "verify_pois": "核对设施子类、营业状态及可能漏标的 POI。",
    "verify_site": "候选点用于调研参考，下一步核对用地、容量和建设条件。",
    "compare": "比较候选的独立增益与剩余缺口。",
    "refine": "对结论敏感的边界样点补充测时。",
    "adjust_scope": "调整明确的地点、设施类别或时间阈值后重新计算。",
}
QUESTIONS = {
    "address": "请补充要体检的社区地址或道路门牌，以及所在城市。",
    "categories": "这次主要关注医疗、养老、教育还是购物设施？",
    "minutes": "你希望按多少分钟的步行阈值体检（5–30 分钟）？",
    "community": "请选择滨河片区或连通片区合成样例。",
    "goal": "你想查看服务缺口、比较候选方案，还是解释已有结果？",
}


def requested_candidate_limit(task):
    match = re.search(r"(?:前|最多|比较)\s*([123一二两三])\s*(?:个|处|种)", task)
    return {"1": 1, "2": 2, "3": 3, "一": 1, "二": 2, "两": 2, "三": 3}.get(match.group(1)) if match else None


CANDIDATE_CATEGORIES = {
    "医疗": "医疗",
    "药店": "医疗",
    "养老": "养老",
    "教育": "教育",
    "小学": "教育",
    "购物": "购物",
    "菜市场": "购物",
}


def requested_candidate_facility(task):
    """Only interpret the explicit addition/candidate phrase, not all inspected categories."""
    phrases = re.findall(r"(?:新增|增设|新建|补建|增加|添加)([^，。；;]{0,24})", task)
    phrases += re.findall(r"([^，。；;]{0,10})候选", task)
    found = {kind for phrase in phrases for kind in CANDIDATE_CATEGORIES if kind in phrase}
    if "菜场" in " ".join(phrases):
        found.add("菜市场")
    for kind, category in (("菜市场", "购物"), ("药店", "医疗"), ("小学", "教育")):
        if kind in found:
            found.discard(category)
    if len(found) > 1:
        raise ValueError("请一次指定一个候选设施类型，再分别比较其他类型。")
    return next(iter(found), None)


def tool_definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": DESCRIPTIONS[name],
                "parameters": args.model_json_schema(),
            },
        }
        for name, args in ARGUMENTS.items()
    ]


class ToolContext:
    def __init__(self, request, session, guard):
        self.request, self.session, self.guard = request, session, guard
        self.new_snapshots = []
        self.used_snapshots = []

    @property
    def facts(self):
        return self.session["facts"]

    def fact(self, snapshot, key, text, target=None, evidence_id=None):
        identity = snapshot["id"] + ":" + key
        row = {
            "id": identity,
            "text": text,
            "evidence_id": evidence_id or snapshot["evidence_id"],
            "data_mode": snapshot["mode"],
            "snapshot_id": snapshot["id"],
            "target": target or {"type": "center"},
        }
        self.facts[identity] = row
        if identity not in snapshot["fact_ids"]:
            snapshot["fact_ids"].append(identity)
        return row

    def get_snapshot(self, identity=None):
        identity = identity or self.session.get("latest")
        if identity not in self.session["snapshots"]:
            raise ValueError("没有对应的已计算结果，请先体检。")
        return self.session["snapshots"][identity]

    def summary(self, snapshot):
        return {
            "snapshot_id": snapshot["id"],
            "data_mode": snapshot["mode"],
            "parameters": snapshot["parameters"],
            "facts": [self.facts[k] for k in snapshot["fact_ids"]],
            "candidate_count": snapshot["candidate_count"],
        }

    def inspect_neighborhood(self, args):
        deferred_error = None
        args.categories = list(dict.fromkeys(args.categories))
        facility_type = requested_candidate_facility(self.request.task)
        candidate_category = CANDIDATE_CATEGORIES.get(facility_type)
        if candidate_category and candidate_category not in args.categories:
            raise ValueError(
                f"需求指定{facility_type}候选，体检类别必须包含{candidate_category}，不能改成其他设施。"
            )
        self.guard(False)
        if self.request.data_mode == "synthetic":
            result = inspect(
                COMMUNITIES[args.community_id],
                args.categories,
                args.minutes,
                args.speed,
                candidate_category=candidate_category,
            )
            snapshot = {
                "id": result["evidence_id"],
                "evidence_id": result["evidence_id"],
                "mode": "synthetic",
                "parameters": result["parameters"],
                "fact_ids": [],
                "candidate_count": len(result["recommendations"]),
                "analysis": {"type": "synthetic", "inspection": result},
            }
            self.fact(
                snapshot,
                "summary",
                f"离线示例：{result['sample_count'] - result['gap_count']}/{result['sample_count']}个街道样点在{args.minutes}分钟内能获得{'、'.join(args.categories)}服务（{result['combined_coverage_pct']}%），仍有{result['gap_count']}个样点缺少至少一类所选服务。样点不是居民人数。",
            )
            for category, row in result["coverage"].items():
                self.fact(
                    snapshot,
                    "coverage-" + category,
                    f"{category}覆盖 {row['count']}/{result['sample_count']} 个样点（{row['pct']}%）。",
                )
            witness = result["witness"]
            self.fact(
                snapshot,
                "path",
                f"证据路径 {witness['from']} → {witness['to']}：直线 {witness['straight_minutes']} 分钟，路网 {witness['network_minutes']} 分钟；直线范围高估 {result['reachability']['overestimated_count']} 个样点。",
                {"type": "path"},
            )
            self.fact(
                snapshot, "limits", "数据为合成路网；等权样点不代表人口或土地面积，候选增益不证明地块可建。"
            )
        else:
            config = BaiduConfig.from_env()
            shared = shared_maps_client(config)
            maps = BaiduMapsClient(config, request_guard=self.guard, shared_client=shared)
            try:
                preset = maps.replay_metadata or {}
                address = args.address or self.request.address
                city = args.city or self.request.city
                if not address:
                    raise ValueError("真实模式缺少地址，请先询问地址。")
                if address != self.request.address and address not in self.request.task:
                    raise ValueError("地点必须来自用户地址栏或本次需求原文，请先确认地址。")
                result = inspect_live(
                    maps,
                    address=address,
                    city=city,
                    categories=args.categories,
                    minutes=args.minutes,
                    radius_m=max(1500, args.minutes * 90),
                    max_facilities=preset.get("max_facilities", 20),
                    query_profile=preset.get("query_profile", "narrow"),
                )
                self.guard(False)
                iso, iso_error = None, None
                try:
                    iso = build_isochrone(
                        maps, center=result["community"]["center"], minutes=args.minutes, grid_m=200
                    )
                except BaiduApiError as error:
                    iso_error = str(error)
                except RuntimeError as error:
                    # Preserve the completed inspection if the later grid exhausts a budget.
                    iso_error, deferred_error = str(error), error
                snapshot = {
                    "id": result["evidence_id"],
                    "evidence_id": result["evidence_id"],
                    "mode": result["mode"],
                    "parameters": result["parameters"],
                    "fact_ids": [],
                    "candidate_count": len(result["blind_spots"]["recommendations"]),
                    "analysis": {
                        "type": "live",
                        "inspection": result,
                        "isochrone": iso,
                        "isochrone_error": iso_error,
                    },
                }
                self.fact(
                    snapshot,
                    "summary",
                    f"{address}：检索并去重 {result['performance']['unique_pois_before_limit']} 处 POI，选取 {result['facility_count']} 处测时；这是中心到设施证据，不是居民覆盖率。",
                )
                for category, row in result["category_summary"].items():
                    self.fact(
                        snapshot,
                        "coverage-" + category,
                        f"{category}：已评估 {row['evaluated']} 处，阈值内 {row['reachable']}、阈值外 {row['unreachable']}、路线未知 {row['unknown']}、未评估 {row['unassessed']}；已知路线中的阈值内比例为 {str(row['center_to_facility_rate']) + '%' if row['center_to_facility_rate'] is not None else '未知'}。",
                    )
                for kind, row in result["blind_spots"]["kinds"].items():
                    self.fact(
                        snapshot,
                        "gap-" + kind,
                        f"{kind}专项：{row['known_count']} 个已知样点中缺口 {row['gap_count'] if row['gap_count'] is not None else '未知'} 个，未知 {row['unknown_count']} 个；按 1 公里直线距离检查。",
                        {"type": "blind_spots", "kind": kind},
                    )
                if iso:
                    self.fact(
                        snapshot,
                        "isochrone",
                        f"均匀网格可达比例 {iso['summary']['coarse_ratio_pct'] if iso['summary']['coarse_ratio_pct'] is not None else '未知'}%；实际间距 {iso['parameters']['grid_spacing_m']} 米，边界加密 {iso['summary']['refined']['count']} 点，未知 {iso['summary']['unknown']} 点。",
                        {"type": "isochrone"},
                        evidence_id=iso["evidence_id"],
                    )
                else:
                    self.fact(snapshot, "isochrone-error", "等时圈未完成：" + str(iso_error))
                if iso and iso["summary"].get("near_threshold"):
                    self.fact(
                        snapshot,
                        "boundary-review",
                        f"{iso['summary']['near_threshold']} 个样点耗时距阈值不超过 2 分钟，需重点复核；批量与单条路线接口可能跨阈值分歧。原始测时判别保留。",
                        {"type": "isochrone"},
                        evidence_id=iso["evidence_id"],
                    )
                self.fact(
                    snapshot,
                    "limits",
                    "POI 子类和营业状态需核验；采样比例不代表人口，规划参考点不证明用地、容量或建设收益。",
                )
            finally:
                maps.close()
        snapshot["candidate_facility"] = facility_type
        # A repeated deterministic snapshot replaces its older comparison facts.
        valid_ids = set(snapshot["fact_ids"])
        for key, fact in list(self.facts.items()):
            if fact["snapshot_id"] == snapshot["id"] and key not in valid_ids:
                del self.facts[key]
        self.session["snapshots"].pop(snapshot["id"], None)
        self.session["snapshots"][snapshot["id"]] = snapshot
        self.session["latest"] = snapshot["id"]
        self.new_snapshots.append(snapshot["id"])
        self.used_snapshots.append(snapshot["id"])
        if deferred_error:
            raise deferred_error
        return self.summary(snapshot)

    def read_evidence(self, args):
        snapshot = self.get_snapshot(args.snapshot_id)
        self.used_snapshots.append(snapshot["id"])
        return self.summary(snapshot)

    def compare_candidates(self, args):
        snapshot = self.get_snapshot(args.snapshot_id)
        self.used_snapshots.append(snapshot["id"])
        obsolete = [
            key
            for key in snapshot["fact_ids"]
            if key.startswith(snapshot["id"] + ":candidate-") or key == snapshot["id"] + ":no-candidates"
        ]
        for key in obsolete:
            self.facts.pop(key, None)
        snapshot["fact_ids"] = [key for key in snapshot["fact_ids"] if key not in obsolete]
        result = snapshot["analysis"]["inspection"]
        facility_type = (
            requested_candidate_facility(self.request.task)
            or args.facility_type
            or snapshot.get("candidate_facility")
        )
        category = CANDIDATE_CATEGORIES.get(facility_type)
        rows = []
        if snapshot["mode"] == "synthetic":
            p = result["parameters"]
            before_gaps = {n["id"] for n in result["map"]["nodes"] if n["gap"]}
            planning = inspect(
                COMMUNITIES[result["community"]["id"]],
                p["categories"],
                p["minutes"],
                p["speed_m_min"],
                p["center"],
                candidate_category=category,
            )
            for candidate in planning["recommendations"][: args.limit]:
                self.guard(False)
                after = inspect(
                    COMMUNITIES[result["community"]["id"]],
                    p["categories"],
                    p["minutes"],
                    p["speed_m_min"],
                    p["center"],
                    {"node": candidate["node"], "category": candidate["category"]},
                )
                node = next(n for n in result["map"]["nodes"] if n["id"] == candidate["node"])
                row = {
                    "category": candidate["category"],
                    "node": candidate["node"],
                    "before_pct": result["combined_coverage_pct"],
                    "after_pct": after["combined_coverage_pct"],
                    "gap_count": after["gap_count"],
                    "gain_count": result["gap_count"] - after["gap_count"],
                    "evidence_id": after["evidence_id"],
                    "gained_nodes": [
                        n["id"] for n in after["map"]["nodes"] if not n["gap"] and n["id"] in before_gaps
                    ],
                    "remaining_gap_nodes": [n["id"] for n in after["map"]["nodes"] if n["gap"]],
                    "facility_type": facility_type or candidate["category"],
                    "target": {"type": "point", "x": node["x"], "y": node["y"]},
                }
                rows.append(row)
        else:
            blind = result["blind_spots"]
            covered_by_kind = {}
            candidates = [
                c
                for c in blind["recommendations"]
                if not facility_type
                or c["kind"] == facility_type
                or (facility_type in ("医疗", "教育", "购物") and CANDIDATE_CATEGORIES[c["kind"]] == category)
            ]
            for candidate in candidates[: args.limit]:
                kind = candidate["kind"]
                points = [p for p in blind["points"] if kind in p["missing_kinds"]]
                covered = {
                    i
                    for i, p in enumerate(points)
                    if math.hypot(p["dx_m"] - candidate["dx_m"], p["dy_m"] - candidate["dy_m"])
                    <= blind["radius_m"]
                }
                previous = covered_by_kind.setdefault(kind, set())
                marginal = len(covered - previous)
                previous.update(covered)
                rows.append(
                    {
                        "category": kind,
                        "rank": candidate["rank"],
                        "independent_gain_count": len(covered),
                        "marginal_gain_count": marginal,
                        "cumulative_gain_count": len(previous),
                        "gap_count": len(points) - len(previous),
                        "target": {"type": "point", "x": candidate["dx_m"], "y": candidate["dy_m"]},
                    }
                )
        snapshot["comparison"] = rows
        for i, row in enumerate(rows):
            if snapshot["mode"] == "synthetic":
                text = f"方案{i + 1}：在标记{i + 1}处新增一个{row['category']}服务点，覆盖从{result['sample_count'] - result['gap_count']}增至{result['sample_count'] - row['gap_count']}个样点；新增{row['gain_count']}个，仍缺{row['gap_count']}个。这是单独方案模拟，尚未建设。"
            else:
                text = f"{row['category']}参考点 {row['rank']}：独立覆盖 {row['independent_gain_count']} 个已知缺口样点，与前序同类点组合的新增覆盖为 {row['marginal_gain_count']} 个，组合后剩余缺口 {row['gap_count']} 个。"
            self.fact(
                snapshot, "candidate-" + str(i), text, row["target"], evidence_id=row.get("evidence_id")
            )
        if not rows:
            self.fact(snapshot, "no-candidates", "本次没有可比较的已知缺口候选点；不强行生成建设方案。")
        return {
            **self.summary(snapshot),
            "comparison": rows,
            "semantics": "mutually-exclusive"
            if snapshot["mode"] == "synthetic"
            else "independent-and-cumulative",
            "note": "仅比较等权样点增益；土地、容量、成本未知。",
        }

    def finish(self, args):
        if args.fact_ids and args.clarify_field != "none":
            raise ValueError(
                "事实结论与缺信息追问不能混用：已有计算结果请保留 fact_ids 并把 clarify_field 设为 none；确实缺信息时请清空 fact_ids。"
            )
        if args.clarify_field != "none":
            return {"question": QUESTIONS[args.clarify_field], "facts": [], "actions": []}
        if not args.fact_ids or any(identity not in self.facts for identity in args.fact_ids):
            raise ValueError("请选择工具返回的有效 fact_id；没有结果时应追问缺少的信息。")
        if any(self.facts[k]["snapshot_id"] not in self.used_snapshots for k in args.fact_ids):
            raise ValueError("请先读取或计算本次引用的证据，不能直接使用旧结论。")
        return {
            "question": None,
            "facts": [self.facts[k] for k in dict.fromkeys(args.fact_ids)],
            "actions": [ACTIONS[k] for k in dict.fromkeys(args.actions)],
        }

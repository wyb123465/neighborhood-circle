from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

# 解释层只整理已有计算结果，不生成新设施、不生成未计算的指标。
# 未配置密钥时明确 rule-only；调用失败时回退并原样暴露原因，不用「调用成功」掩盖。


def llm_configured() -> bool:
    return bool(os.getenv("AI_API_KEY", "").strip() and os.getenv("AI_BASE_URL", "").strip())


def _facts(result: dict[str, Any]) -> dict[str, Any]:
    params = result["parameters"]
    coverage = {
        category: {"count": row["count"], "pct": row["pct"], "before_pct": row["before_pct"]}
        for category, row in result["coverage"].items()
    }
    witness = result["witness"]
    return {
        "community": result["community"]["name"],
        "mode": result["mode"],
        "evidence_id": result["evidence_id"],
        "method_version": result["method_version"],
        "dataset_version": result["dataset_version"],
        "source": result["source"],
        "parameters": {
            "categories": params["categories"],
            "minutes": params["minutes"],
            "speed_m_min": params["speed_m_min"],
            "center": params["center"],
            "addition": params["addition"],
        },
        "sample_count": result["sample_count"],
        "facility_count": result["facility_count"],
        "combined_coverage_pct": result["combined_coverage_pct"],
        "base_combined_coverage_pct": result["base_combined_coverage_pct"],
        "average_coverage_pct": result["average_coverage_pct"],
        "gap_count": result["gap_count"],
        "missing_categories": result["missing_categories"],
        "overestimated_count": result["reachability"]["overestimated_count"],
        "coverage": coverage,
        "witness": {
            "from": witness["from"],
            "to": witness["to"],
            "straight_minutes": witness["straight_minutes"],
            "network_minutes": witness["network_minutes"],
        },
        "limitations": result["limitations"],
    }


def rule_explanation(facts: dict[str, Any]) -> list[str]:
    params = facts["parameters"]
    weakest = min(facts["coverage"].items(), key=lambda item: item[1]["pct"])
    lines = [
        f"片区「{facts['community']}」按 {params['minutes']} 分钟 / {params['speed_m_min']} 米每分钟计算："
        f"所选各类服务同时可达 {facts['combined_coverage_pct']}%（模拟前 {facts['base_combined_coverage_pct']}%），"
        f"缺口 {facts['gap_count']}/{facts['sample_count']} 个等权采样点。",
        f"覆盖率最低类别为 {weakest[0]}（{weakest[1]['pct']}%）。"
        f"各类别算术平均 {facts['average_coverage_pct']}% 仅作参考，不等于同时可达。",
        f"直线范围相对路网可达高估 {facts['overestimated_count']} 个采样点；"
        f"证据路径 {facts['witness']['from']} → {facts['witness']['to']}："
        f"直线 {facts['witness']['straight_minutes']} 分钟 / 路网 {facts['witness']['network_minutes']} 分钟。",
    ]
    if params["addition"]:
        addition = params["addition"]
        lines.append(
            f"当前含候选模拟：{addition['category']} @ {addition['node']}；"
            "增益仅按新增可达采样点重算，不证明用地与容量。"
        )
    else:
        lines.append("当前未启用候选模拟。")
    if facts["missing_categories"]:
        lines.append(f"样例中缺失类别：{'、'.join(facts['missing_categories'])}（未编造点位）。")
    lines.append("口径边界：" + facts["limitations"][0])
    return lines


def _llm_payload(facts: dict[str, Any]) -> str:
    system = (
        "你是生活圈体检解释助手。只能整理用户给出的 JSON 事实，禁止新增设施、人数、面积、"
        "置信度或收益。输出 3-5 条中文要点，每条对应一条已计算事实；不确定处写「未知」。"
    )
    return json.dumps({"system": system, "facts": facts}, ensure_ascii=False)


def llm_explanation(facts: dict[str, Any], timeout: float = 12.0) -> list[str]:
    base = os.getenv("AI_BASE_URL", "").strip().rstrip("/")
    key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip() or "default"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只整理给定事实，禁止编造。输出 3-5 条中文要点。"},
            {"role": "user", "content": _llm_payload(facts)},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
        content = payload["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as error:
        raise RuntimeError(f"大模型调用失败：{error}") from error
    lines = [line.strip("- ").strip() for line in content.splitlines() if line.strip()]
    return lines[:6]


def explain(result: dict[str, Any]) -> dict[str, Any]:
    facts = _facts(result)
    if not llm_configured():
        return {
            "mode": "rule-only",
            "llm_called": False,
            "basis": facts,
            "points": rule_explanation(facts),
            "error": None,
            "note": "未配置 AI_API_KEY/AI_BASE_URL，解释仅由规则模板整理已计算事实。",
        }
    try:
        points = llm_explanation(facts)
        return {
            "mode": "llm",
            "llm_called": True,
            "basis": facts,
            "points": points,
            "error": None,
            "note": "解释只引用 basis 中的已计算事实；如模型输出越界应以 basis 为准。",
        }
    except RuntimeError as error:
        return {
            "mode": "rule-only",
            "llm_called": False,
            "basis": facts,
            "points": rule_explanation(facts),
            "error": str(error),
            "note": "大模型调用失败，已回退到规则说明模式；失败原因原样保留。",
        }

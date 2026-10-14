from copy import deepcopy

from backend.analysis import inspect
from backend.sample_data import load_communities
from backend.scenarios import compare_thresholds


def test_synthetic_thresholds_hold_nodes_and_facilities_fixed():
    result = inspect(load_communities()["bridge-demo"], ["养老"])
    before = deepcopy(result)
    scenarios = compare_thresholds({"type": "synthetic", "inspection": result})
    assert [r["minutes"] for r in scenarios["rows"]] == [10, 15, 20]
    assert all(r["known"] == 143 for r in scenarios["rows"])
    assert scenarios["rows"][1]["ratio_pct"] == 44.8
    assert [r["reachable"] for r in scenarios["rows"]] == sorted(r["reachable"] for r in scenarios["rows"])
    assert result == before and scenarios["external_requests"] == 0


def test_live_comparison_uses_seconds_and_excludes_refined_and_unknown():
    analysis = {
        "type": "live",
        "inspection": {
            "mode": "live-partial",
            "parameters": {"categories": ["医疗"]},
            "facilities": [
                {
                    "categories": ["医疗"],
                    "eligible_categories": ["医疗"],
                    "route": {"status": "ok", "duration_s": 900.1},
                },
                {
                    "categories": ["医疗"],
                    "eligible_categories": [],
                    "route": {"status": "ok", "duration_s": 100},
                },
                {"categories": ["医疗"], "route": {"status": "error"}},
            ],
        },
        "isochrone": {
            "evidence_id": "base",
            "parameters": {"extent_m": 1350},
            "points": [
                {"generation": "coarse", "status": "reachable", "duration_s": 600},
                {"generation": "coarse", "status": "unreachable", "duration_s": 900.1},
                {"generation": "coarse", "status": "unknown", "duration_s": 0},
                {"generation": "refined", "status": "reachable", "duration_s": 1},
            ],
        },
    }
    scenarios = compare_thresholds(analysis)
    assert scenarios["sample_count"] == 3
    assert [r["ratio_pct"] for r in scenarios["rows"]] == [50, 50, 100]
    assert all(r["known"] == 2 and r["unknown"] == 1 for r in scenarios["rows"])
    assert scenarios["rows"][1]["facilities"]["医疗"] == {
        "evaluated": 2,
        "known": 1,
        "unknown": 1,
        "reachable": 0,
    }
    assert "完整20分钟" in scenarios["note"]


def test_all_unknown_is_not_zero_coverage():
    analysis = {
        "type": "live",
        "inspection": {"mode": "live-replay", "parameters": {"categories": []}, "facilities": []},
        "isochrone": {
            "evidence_id": "base",
            "parameters": {"extent_m": 1350},
            "points": [{"generation": "coarse", "status": "unknown"}],
        },
    }
    assert all(r["ratio_pct"] is None for r in compare_thresholds(analysis)["rows"])

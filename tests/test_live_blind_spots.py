from __future__ import annotations

from backend.live_inspection import build_blind_spots


def test_one_km_blind_spots_distinguish_known_gaps_and_unknown_queries():
    center = {"lat": 31.2, "lng": 121.4}
    facilities = [
        {
            "location": {"lat": 31.2, "lng": 121.4 + 0.004},
            "matched_kinds": ["药店"],
        },
        {
            "location": {"lat": 31.2, "lng": 121.4 + 0.03},
            "matched_kinds": ["菜市场"],
        },
    ]
    result = build_blind_spots(
        center=center,
        facilities=facilities,
        query_success={"菜市场": True, "药店": True, "小学": False},
    )

    assert result["sample_count"] > 0
    assert result["kinds"]["药店"]["status"] == "complete"
    assert result["kinds"]["药店"]["gap_count"] < result["sample_count"]
    assert result["kinds"]["菜市场"]["gap_count"] == result["sample_count"]
    assert result["kinds"]["小学"]["status"] == "unknown"
    assert result["known_gap_count"] > 0
    assert any("菜市场" in point["missing_kinds"] for point in result["points"])
    assert any(point["status"] == "unknown" for point in result["points"])
    assert result["recommendations"]
    assert {row["kind"] for row in result["recommendations"]} == {"菜市场", "药店"}
    assert all(row["location"]["lat"] and row["location"]["lng"] for row in result["recommendations"])


def test_empty_successful_poi_query_is_unknown_not_a_confirmed_gap():
    result = build_blind_spots(
        center={"lat": 31.2, "lng": 121.4},
        facilities=[],
        query_success={"菜市场": True, "药店": True, "小学": True},
    )

    for kind in ("菜市场", "药店", "小学"):
        assert result["kinds"][kind]["status"] == "unknown"
        assert result["kinds"][kind]["gap_count"] is None
        assert "未返回" in result["kinds"][kind]["reason"]
    assert result["known_gap_count"] == 0
    assert result["recommendations"] == []


def test_truncated_search_proves_nearby_coverage_but_not_absence():
    result = build_blind_spots(
        center={"lat": 31.2, "lng": 121.4},
        facilities=[{"location": {"lat": 31.2, "lng": 121.404}, "matched_kinds": ["药店"]}],
        query_success={"药店": True},
        query_evidence={"药店": {"complete": False, "radius_m": 2000}},
    )
    row = result["kinds"]["药店"]
    assert row["status"] == "partial"
    assert row["known_count"] > 0 and row["unknown_count"] > 0
    assert row["gap_count"] == 0
    assert result["recommendations"] == []


def test_legacy_search_disk_cannot_confirm_edge_sample_gaps():
    result = build_blind_spots(
        center={"lat": 31.2, "lng": 121.4},
        facilities=[{"location": {"lat": 31.2, "lng": 121.43}, "matched_kinds": ["药店"]}],
        query_success={"药店": True},
        query_evidence={"药店": {"complete": True, "radius_m": 1500}},
    )
    middle = next(p for p in result["points"] if p["dx_m"] == p["dy_m"] == 0)
    edge = next(p for p in result["points"] if p["dx_m"] == 1000 and p["dy_m"] == 0)
    assert "药店" in middle["missing_kinds"]
    assert "药店" in edge["unknown_kinds"]
    assert "药店" not in edge["missing_kinds"]

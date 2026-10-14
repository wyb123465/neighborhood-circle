from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from .baidu import BaiduApiError, BaiduConfig, BaiduMapsClient
from .live_inspection import (
    CATEGORY_QUERIES,
    DEFAULT_QUERY_PROFILE,
    QUERY_PROFILES,
    inspect_live,
    resolve_query_profile,
)
from .live_isochrone import build_isochrone

router = APIRouter(prefix="/api/live", tags=["live-baidu"])


@lru_cache(maxsize=2)
def client(config: BaiduConfig) -> BaiduMapsClient:
    return BaiduMapsClient(config)


def raise_api_error(error: BaiduApiError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(error))


def profile_summary() -> dict[str, dict[str, Any]]:
    """Report each profile's place-search cost so quota planning does not need guessing."""
    summary: dict[str, dict[str, Any]] = {}
    for name, queries in QUERY_PROFILES.items():
        per_category = {category: len(items) for category, items in queries.items()}
        summary[name] = {
            "place_queries_per_inspection": sum(per_category.values()),
            "place_queries_per_category": per_category,
        }
    return summary


@router.get("/status")
def status():
    config = BaiduConfig.from_env()
    replay = None
    replay_error = None
    if config.replay_file:
        try:
            maps = client(config)
            replay = maps.replay_metadata
            config = maps.config
        except BaiduApiError as error:
            replay_error = str(error)
    configured_profile = os.getenv("BAIDU_POI_QUERY_PROFILE", DEFAULT_QUERY_PROFILE).strip().lower()
    if replay:
        configured_profile = replay["query_profile"]
    profile_error = None
    try:
        effective_profile, _ = resolve_query_profile(configured_profile)
    except ValueError as error:
        effective_profile = None
        profile_error = str(error)
    return {
        "mode": "live-replay" if replay else ("configuration-error" if replay_error else ("live-ready" if config.ak else "synthetic-only")),
        "configured": replay_error is None and bool(config.ak or replay),
        "base_url": config.base_url,
        "place_api_version": config.place_api_version,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "max_place_pages": config.max_place_pages,
        "max_concurrency": config.max_concurrency,
        "qps": config.qps,
        "matrix_pairs": config.matrix_pairs,
        "force_ipv4": config.force_ipv4,
        "default_query_profile": configured_profile,
        "effective_query_profile": effective_profile,
        "query_profile_valid": profile_error is None,
        "query_profiles": profile_summary(),
        "ak_exposed": False,
        "replay_mode": bool(replay),
        "replay_preset": replay,
        "replay_error": replay_error,
        "message": (
            replay_error or profile_error
            if replay_error or profile_error
            else ("历史录制回放：无需 AK，不发起外部请求。" if replay else
                ("已配置服务端 AK，可调用验证接口。" if config.ak else "未配置 BAIDU_MAP_AK，未发起百度地图请求。"))
        ),
    }


@router.get("/metrics")
def metrics():
    config = BaiduConfig.from_env()
    maps = client(config)
    return {
        "configured": maps.configured,
        "place_api_version": config.place_api_version,
        "metrics": maps.metrics(),
        "note": "进程内累计指标；不包含 AK，不等同于百度控制台计费统计。",
    }


@router.get("/geocode")
def geocode(address: Annotated[str, Query(min_length=2, max_length=128)], city: str | None = None):
    try:
        maps = client(BaiduConfig.from_env())
        return maps.geocode(address, city)
    except BaiduApiError as error:
        raise raise_api_error(error) from error


@router.get("/pois")
def pois(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    query: Annotated[str, Query(min_length=1, max_length=45)],
    radius_m: Annotated[int, Query(ge=100, le=5000)] = 1500,
):
    try:
        maps = client(BaiduConfig.from_env())
        return {
            "query": query,
            "location": {"lat": lat, "lng": lng},
            "radius_m": radius_m,
            "results": maps.search_pois(location={"lat": lat, "lng": lng}, query=query, radius_m=radius_m),
        }
    except BaiduApiError as error:
        raise raise_api_error(error) from error


@router.get("/walking")
def walking(
    origin_lat: Annotated[float, Query(ge=-90, le=90)],
    origin_lng: Annotated[float, Query(ge=-180, le=180)],
    destination_lat: Annotated[float, Query(ge=-90, le=90)],
    destination_lng: Annotated[float, Query(ge=-180, le=180)],
):
    try:
        maps = client(BaiduConfig.from_env())
        return maps.walking_route(
            origin={"lat": origin_lat, "lng": origin_lng},
            destination={"lat": destination_lat, "lng": destination_lng},
        )
    except BaiduApiError as error:
        raise raise_api_error(error) from error


@router.get("/isochrone")
def isochrone(
    address: Annotated[str | None, Query(min_length=2, max_length=128)] = None,
    city: str | None = None,
    lat: Annotated[float | None, Query(ge=-85, le=85)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    minutes: Annotated[int, Query(ge=5, le=30)] = 15,
    grid_m: Annotated[int, Query(ge=100, le=500)] = 200,
    coord_type: Literal["bd09ll", "gcj02ll", "wgs84ll"] = "bd09ll",
    refine: bool = True,
):
    """网格采样等时圈：address 定位或 lat/lng 直传，二选一；refine 控制边界自适应加密。"""
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=400, detail="lat 与 lng 需同时提供。")
    if bool(address) == (lat is not None and lng is not None):
        raise HTTPException(status_code=400, detail="address 与 lat/lng 二选一提供。")
    try:
        maps = client(BaiduConfig.from_env())
        if address:
            center = maps.geocode(address, city)["location"]
        else:
            converted = maps.convert_coordinates({"lat": lat, "lng": lng}, coord_type)
            center = converted["location"]
        result = build_isochrone(maps, center=center, minutes=minutes, grid_m=grid_m, refine=refine)
        if not address:
            result["coordinate_input"] = converted
        return result
    except BaiduApiError as error:
        raise raise_api_error(error) from error


@router.get("/inspect")
def inspect(
    address: Annotated[str | None, Query(min_length=2, max_length=128)] = None,
    city: str | None = None,
    lat: Annotated[float | None, Query(ge=-85, le=85)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    coord_type: Literal["bd09ll", "gcj02ll", "wgs84ll"] = "bd09ll",
    category: Annotated[str, Query(min_length=2, max_length=64)] = "医疗,养老,教育,购物",
    radius_m: Annotated[int, Query(ge=300, le=3000)] = 1500,
    minutes: Annotated[int, Query(ge=5, le=30)] = 15,
    max_facilities: Annotated[int, Query(ge=1, le=50)] = 30,
    query_profile: str | None = Query(default=None, description=f"检索词组画像，默认 {DEFAULT_QUERY_PROFILE}；narrow 可降低地点检索配额消耗。"),
):
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=400, detail="lat 与 lng 需同时提供。")
    if bool(address) == (lat is not None and lng is not None):
        raise HTTPException(status_code=400, detail="address 与 lat/lng 二选一提供。")
    categories = list(dict.fromkeys(part.strip() for part in category.split(",") if part.strip()))
    if not categories or any(item not in CATEGORY_QUERIES for item in categories):
        raise HTTPException(status_code=400, detail="设施类别无效，支持：医疗、养老、教育、购物。")
    if query_profile is not None and query_profile.strip().lower() not in QUERY_PROFILES:
        raise HTTPException(status_code=400, detail=f"检索词组画像无效，支持：{'、'.join(QUERY_PROFILES)}。")
    try:
        maps = client(BaiduConfig.from_env())
        converted = maps.convert_coordinates({"lat": lat, "lng": lng}, coord_type) if lat is not None else None
        result = inspect_live(
            maps,
            address=address,
            city=city,
            categories=categories,
            radius_m=radius_m,
            minutes=minutes,
            max_facilities=max_facilities,
            query_profile=query_profile,
            center_location=converted["location"] if converted else None,
        )
        if converted:
            result["coordinate_input"] = converted
        return result
    except BaiduApiError as error:
        raise raise_api_error(error) from error

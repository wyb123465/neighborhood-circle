from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

import httpx


def load_env_file() -> None:
    """Load the project `.env` that README and docs tell operators to create.

    Without this, copying `.env.example` to `.env` and filling in the AK has no
    effect: the config below only reads os.environ, so the service would keep
    reporting "未配置" with a valid key sitting on disk. python-dotenv ships with
    uvicorn[standard]; if it is absent we degrade to plain environment variables.
    """
    if os.getenv("NEIGHBORHOOD_IGNORE_ENV") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependency is pinned in requirements.txt
        return
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")


load_env_file()


class BaiduApiError(RuntimeError):
    """A normalized, key-free error from a Baidu Maps API call."""

    def __init__(self, message: str, *, code: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class BaiduConfig:
    ak: str
    base_url: str = "https://api.map.baidu.com"
    place_api_version: str = "v3"
    timeout_seconds: float = 8.0
    cache_ttl_seconds: int = 300
    max_place_pages: int = 5
    # 个人认证上限通常为 QPS 3 次/秒（官方配额表写作「并发(次/秒)」，
    # 这里按每秒发起数理解）；实际发起默认留出余量，取 2 次/秒。
    # 企业认证可上调（试用版 30、授权版 200），但仍需低于账号实际配额。
    max_concurrency: int = 3
    # 「在途请求数」与「每秒发起数」是两个口径：上面的信号量只限制前者，
    # 而百米级响应时间会让 3 个线程在半秒内发起 ~10 次请求（瞬时 QPS 超限 10 倍），
    # 这正是 2026-09-25 收到官方并发告警短信的根因。qps 按发起间隔节流，两者配合使用。
    # 实测持续贴着 3/秒运行会被「限制访问」502（单次小调用能过、持续流被拒），
    # 因此默认 2 次/秒留出 33% 余量；批量算路的对数速率同样等于该值（见 weight 节流）。
    qps: float = 2.0
    # 批量算路按「每次请求内的路线对数」计入并发：1×10 的矩阵调用触发了官方
    # 「批量算路 10/3」告警短信（与请求对数精确对应，属实测推断而非文档口径）。
    # 默认 2 对/次而非 3：实测 3 对/次会让每个请求都顶在 3/3 上限，持续贴线
    # 触发了「限制访问」502；2/3 留出余量，时延代价是分块数 +50%。
    matrix_pairs: int = 2
    # api.map.baidu.com 同时解析出 IPv6（AAAA）记录，httpx 会优先走 IPv6，
    # 出口变成家宽临时 IPv6 地址；服务端 AK 的 IP 白名单通常只填 IPv4，
    # 百度端就会报「APP IP校验失败」。默认绑定 IPv4 源地址，可用环境变量关闭。
    force_ipv4: bool = True
    # 回放模式：设置为录制 fixture 路径（.runtime/replay/*.json）后，所有请求
    # 改从本地录制数据应答——现场演示不再依赖网络与当日配额。响应仍是真实
    # 百度接口的录制，但必须以 live-replay 模式标注，绝不冒充实时的结果。
    replay_file: str | None = None

    @classmethod
    def from_env(cls) -> "BaiduConfig":
        replay_file = os.getenv("BAIDU_REPLAY_FILE", "").strip()
        return cls(
            ak=os.getenv("BAIDU_MAP_AK", "").strip(),
            base_url=os.getenv("BAIDU_API_BASE_URL", "https://api.map.baidu.com").rstrip("/"),
            place_api_version=os.getenv("BAIDU_PLACE_API_VERSION", "v3").strip().lower(),
            timeout_seconds=float(os.getenv("BAIDU_API_TIMEOUT", "8")),
            cache_ttl_seconds=int(os.getenv("BAIDU_API_CACHE_TTL", "300")),
            max_place_pages=int(os.getenv("BAIDU_API_MAX_PAGES", "5")),
            max_concurrency=int(os.getenv("BAIDU_API_MAX_CONCURRENCY", "3")),
            qps=float(os.getenv("BAIDU_API_QPS", "2")),
            matrix_pairs=max(1, int(os.getenv("BAIDU_API_MATRIX_PAIRS", "2"))),
            force_ipv4=os.getenv("BAIDU_API_FORCE_IPV4", "1").strip().lower() not in {"0", "false", "off"},
            replay_file=replay_file or None,
        )


def request_key(path: str, params: dict[str, Any]) -> str:
    """请求指纹：路径 + 全部参数（值统一字符串化、键排序，AK 必须先剔除）。

    内存缓存与回放 fixture 共用同一指纹；字符串化保证录制侧（URL 参数恒为
    字符串）与调用侧（page_num 等可能是 int）能对上同一把钥匙。
    """
    normalized = {str(key): str(value) for key, value in params.items() if str(key) != "ak"}
    material = json.dumps({"path": path, "params": normalized}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class PoiResults(list):
    """List-compatible POI results carrying the search's evidence boundary."""

    def __init__(self, *, radius_m: int):
        super().__init__()
        self.radius_m = radius_m
        self.complete = False


class BaiduMapsClient:
    """Small server-side adapter for the APIs used by 邻里圈.

    The client never exposes the AK in responses, exceptions, cache keys, or
    logs. It is intentionally separate from the synthetic graph so both modes
    can be tested without mixing coordinate systems or data claims.
    """

    def __init__(
        self,
        config: BaiduConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
        request_guard=None,
        shared_client=None,
    ):
        self.config = config or BaiduConfig.from_env()
        self._clock = clock
        self._sleep = sleep
        self._request_guard = request_guard
        self._shared_client = shared_client
        self._rate_lock = threading.Lock()
        self._next_start = 0.0
        self._min_interval = 1.0 / max(0.1, self.config.qps)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = threading.RLock()
        self._metrics_lock = threading.RLock()
        self._metrics: dict[str, Any] = {
            "total_calls": 0,
            "network_requests": 0,
            "cache_hits": 0,
            "replay_hits": 0,
            "failures": 0,
            "network_duration_ms": 0.0,
            "paths": {},
        }
        self._replay: dict[str, Any] | None = None
        self.replay_metadata: dict[str, Any] | None = None
        if self.config.replay_file:
            from pathlib import Path

            try:
                recorded = json.loads(Path(self.config.replay_file).read_text(encoding="utf-8"))
                self._replay = recorded["fixtures"]
                if not isinstance(self._replay, dict) or not self._replay:
                    raise ValueError("fixtures 必须为非空对象")
                entries = list(self._replay.values())
                places = [e for e in entries if e["path"].startswith("/place/")]
                queries = {e["params"].get("query") for e in places}
                pairs = max(
                    (
                        len(e["params"]["destinations"].split("|"))
                        for e in entries
                        if "destinations" in e["params"]
                    ),
                    default=2,
                )
                pages = max((int(e["params"].get("page_num", 0)) for e in places), default=0) + 1
                version = "v2" if places and "/v2/" in places[0]["path"] else "v3"
                self.replay_metadata = {
                    "recorded_at": recorded.get("recorded_at"),
                    "address": recorded.get("address"),
                    "city": recorded.get("city"),
                    "minutes": recorded.get("minutes", 15),
                    "grid_m": 200,
                    "max_facilities": 10,
                    "query_profile": "narrow" if queries <= {"药店", "养老院", "小学", "菜市场"} else "full",
                }
                for key in (
                    "address",
                    "city",
                    "minutes",
                    "grid_m",
                    "max_facilities",
                    "query_profile",
                    "selection_strategy",
                ):
                    if key in recorded.get("parameters", {}):
                        self.replay_metadata[key] = recorded["parameters"][key]
                # Replay must reconstruct the recorded request grouping, not the
                # operator's current API version / pagination / pair settings.
                self.config = replace(
                    self.config, matrix_pairs=pairs, max_place_pages=pages, place_api_version=version
                )
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise BaiduApiError("回放文件不可用，请检查文件路径和录制格式。") from error
        self._limiter = threading.BoundedSemaphore(max(1, self.config.max_concurrency))
        # Only applied when the caller did not inject a transport (tests inject
        # MockTransport and must stay address-agnostic). Binding the IPv4 any-address
        # keeps the socket in the IPv4 family, so the egress matches the IP whitelist.
        if transport is None and self.config.force_ipv4:
            transport = httpx.HTTPTransport(local_address="0.0.0.0")
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            transport=transport,
            headers={"User-Agent": "neighborhood-circle/0.3"},
        )
        if shared_client is not None:
            self._cache = shared_client._cache
            self._cache_lock = shared_client._cache_lock

    @property
    def configured(self) -> bool:
        return bool(self.config.ak) or self._replay is not None

    def close(self) -> None:
        self._client.close()

    def metrics(self) -> dict[str, Any]:
        # Acquire the two locks separately instead of nesting them: the cache-hit
        # path in _get_json also needs both, and nesting them in opposite orders
        # lets two threads deadlock. Each lock is now held on its own.
        with self._cache_lock:
            cache_entries = len(self._cache)
        with self._metrics_lock:
            snapshot = deepcopy(self._metrics)
        snapshot["cache_entries"] = cache_entries
        snapshot["network_duration_ms"] = round(snapshot["network_duration_ms"], 1)
        for path in snapshot["paths"].values():
            path["network_duration_ms"] = round(path["network_duration_ms"], 1)
        return snapshot

    def _record(
        self,
        path: str,
        *,
        network_request: bool = False,
        cache_hit: bool = False,
        failure: bool = False,
        duration_ms: float = 0.0,
    ) -> None:
        with self._metrics_lock:
            self._metrics["total_calls"] += 1
            self._metrics["network_requests"] += int(network_request)
            self._metrics["cache_hits"] += int(cache_hit)
            self._metrics["failures"] += int(failure)
            self._metrics["network_duration_ms"] += duration_ms
            path_metrics = self._metrics["paths"].setdefault(
                path,
                {
                    "calls": 0,
                    "network_requests": 0,
                    "cache_hits": 0,
                    "failures": 0,
                    "network_duration_ms": 0.0,
                },
            )
            path_metrics["calls"] += 1
            path_metrics["network_requests"] += int(network_request)
            path_metrics["cache_hits"] += int(cache_hit)
            path_metrics["failures"] += int(failure)
            path_metrics["network_duration_ms"] += duration_ms

    @property
    def replay_mode(self) -> bool:
        return self._replay is not None

    def recorded_search_radius(self, query: str, fallback: int) -> int:
        return next(
            (
                int(e["params"]["radius"])
                for e in (self._replay or {}).values()
                if e["path"].startswith("/place/") and e["params"].get("query") == query
            ),
            fallback,
        )

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        return request_key(path, params)

    def _get_json(self, path: str, params: dict[str, Any], *, weight: int = 1) -> dict[str, Any]:
        if self._request_guard:
            self._request_guard(False)
        if not self.configured:
            raise BaiduApiError("BAIDU_MAP_AK 未配置，未发起外部请求。")

        safe_params = {key: value for key, value in params.items() if value is not None}
        safe_params.update({"ak": self.config.ak, "output": "json"})
        cache_key = self._cache_key(path, {key: value for key, value in safe_params.items() if key != "ak"})
        now = self._clock()
        # Read the cache under its own lock and record the metric after releasing
        # it, so this path never holds the cache lock while taking the metrics lock.
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            fresh = cached is not None and now - cached[0] < self.config.cache_ttl_seconds
            cached_payload = cached[1] if cached else None
        if fresh:
            self._record(path, cache_hit=True)
            return cached_payload

        if self._replay is not None:
            entry = self._replay.get(cache_key)
            if entry is None:
                self._record(path, failure=True)
                raise BaiduApiError(
                    "回放数据缺少该请求；请清空 BAIDU_REPLAY_FILE 或用 scripts/record_replay_fixtures.py 重新录制。"
                )
            with self._metrics_lock:
                self._metrics["replay_hits"] += 1
            self._record(path)
            return entry["response"]

        # Acquire an in-flight slot before scheduling the start. Reservations
        # made before a congested semaphore can expire and then start in a burst.
        # Matrix chunks advance the schedule by their number of route pairs.
        weight = max(1, int(weight))
        gate = self._shared_client or self
        started = time.perf_counter()
        try:
            with gate._limiter:
                with gate._rate_lock:
                    wait = max(0, gate._next_start - self._clock())
                    if wait:
                        self._sleep(wait)
                    gate._next_start = self._clock() + weight * gate._min_interval
                if self._request_guard:
                    self._request_guard(True)
                response = self._client.get(path, params=safe_params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            self._record(
                path, network_request=True, failure=True, duration_ms=(time.perf_counter() - started) * 1000
            )
            raise BaiduApiError("百度地图请求超时，请稍后重试。") from error
        except httpx.HTTPStatusError as error:
            self._record(
                path, network_request=True, failure=True, duration_ms=(time.perf_counter() - started) * 1000
            )
            raise BaiduApiError(
                f"百度地图 HTTP 请求失败（{error.response.status_code}）。",
                http_status=error.response.status_code,
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            self._record(
                path, network_request=True, failure=True, duration_ms=(time.perf_counter() - started) * 1000
            )
            raise BaiduApiError("百度地图响应不可用，未生成体检结论。") from error

        status = payload.get("status")
        if status != 0:
            message = str(payload.get("message") or "百度地图服务返回错误")
            self._record(
                path, network_request=True, failure=True, duration_ms=(time.perf_counter() - started) * 1000
            )
            raise BaiduApiError(f"百度地图接口失败：{message}", code=status)
        with self._cache_lock:
            self._cache[cache_key] = (self._clock(), payload)
        self._record(path, network_request=True, duration_ms=(time.perf_counter() - started) * 1000)
        return payload

    @staticmethod
    def _point(value: dict[str, Any]) -> dict[str, float]:
        return {"lng": float(value["lng"]), "lat": float(value["lat"])}

    def geocode(self, address: str, city: str | None = None) -> dict[str, Any]:
        payload = self._get_json(
            "/geocoding/v3/",
            {"address": address, "city": city, "ret_coordtype": "bd09ll"},
        )
        result = payload.get("result") or {}
        location = result.get("location")
        if not location:
            raise BaiduApiError("地理编码没有返回坐标。")
        return {
            "address": address,
            "city": city,
            "location": self._point(location),
            "precise": result.get("precise"),
            "confidence": result.get("confidence"),
            "comprehension": result.get("comprehension"),
            "level": result.get("level"),
            "source": "baidu-geocoding-v3",
        }

    def convert_coordinates(self, location: dict[str, float], source: str = "bd09ll") -> dict[str, Any]:
        """Explicit source coordinates to BD-09 through the official geoconv v2."""
        lat, lng = float(location["lat"]), float(location["lng"])
        if not math.isfinite(lat) or not math.isfinite(lng) or not -85 <= lat <= 85 or not -180 <= lng <= 180:
            raise BaiduApiError("经纬度超出支持范围。")
        if source not in {"bd09ll", "gcj02ll", "wgs84ll"}:
            raise BaiduApiError("坐标来源仅支持 BD-09、GCJ-02 或 WGS84。")
        result = {
            "input": {"lat": lat, "lng": lng},
            "input_type": source,
            "output_type": "bd09ll",
            "converted": source != "bd09ll",
        }
        if source == "bd09ll":
            return {**result, "location": {"lat": lat, "lng": lng}, "source": "user-bd09ll"}
        payload = self._get_json(
            "/geoconv/v2/", {"coords": f"{lng},{lat}", "model": 1 if source == "gcj02ll" else 2}
        )
        try:
            point = payload["result"][0]
            converted = {"lng": float(point["x"]), "lat": float(point["y"])}
            if (
                not all(math.isfinite(v) for v in converted.values())
                or not -85 <= converted["lat"] <= 85
                or not -180 <= converted["lng"] <= 180
            ):
                raise ValueError("invalid conversion")
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise BaiduApiError("坐标转换没有返回有效经纬度，未继续体检。") from error
        return {**result, "location": converted, "source": "baidu-geoconv-v2"}

    def search_pois(
        self,
        *,
        location: dict[str, float],
        query: str,
        radius_m: int = 1500,
        city_limit: bool = False,
    ) -> list[dict[str, Any]]:
        if self.config.place_api_version not in {"v2", "v3"}:
            raise BaiduApiError("BAIDU_PLACE_API_VERSION 只支持 v2 或 v3。")
        results = PoiResults(radius_m=radius_m)
        seen: set[str] = set()
        for page_num in range(self.config.max_place_pages):
            if self.config.place_api_version == "v3":
                path = "/place/v3/around"
                params = {
                    "query": query,
                    "location": f"{location['lat']:.6f},{location['lng']:.6f}",
                    "radius": radius_m,
                    "page_size": 20,
                    "page_num": page_num,
                    "ret_coordtype": "bd09ll",
                }
            else:
                path = "/place/v2/search"
                params = {
                    "query": query,
                    "location": f"{location['lat']:.6f},{location['lng']:.6f}",
                    "radius": radius_m,
                    "page_size": 20,
                    "page_num": page_num,
                    "scope": 2,
                    "city_limit": "true" if city_limit else "false",
                    "coord_type": 3,
                    "ret_coordtype": "bd09ll",
                }
            payload = self._get_json(
                path,
                params,
            )
            page = payload.get("pois") or payload.get("results") or []
            for item in page:
                item_location = item.get("location") or {}
                uid = (
                    item.get("uid")
                    or f"{item.get('name')}:{item_location.get('lat')}:{item_location.get('lng')}"
                )
                if uid in seen or not item_location:
                    continue
                seen.add(uid)
                results.append(
                    {
                        "uid": item.get("uid"),
                        "name": item.get("name"),
                        "address": item.get("address"),
                        "location": self._point(item_location),
                        "detail_info": item.get("detail_info") or {},
                        "query": query,
                        "source": f"baidu-place-{self.config.place_api_version}",
                    }
                )
            if len(page) < 20:
                results.complete = True
                break
        return results

    def walking_route(
        self,
        *,
        origin: dict[str, float],
        destination: dict[str, float],
        origin_uid: str | None = None,
        destination_uid: str | None = None,
    ) -> dict[str, Any]:
        payload = self._get_json(
            "/direction/v2/walking",
            {
                "origin": f"{origin['lat']:.6f},{origin['lng']:.6f}",
                "destination": f"{destination['lat']:.6f},{destination['lng']:.6f}",
                "origin_uid": origin_uid,
                "destination_uid": destination_uid,
                "coord_type": "bd09ll",
                "ret_coordtype": "bd09ll",
            },
        )
        routes = (payload.get("result") or {}).get("routes") or []
        if not routes:
            raise BaiduApiError("步行路线没有返回可用方案。")
        route = routes[0]
        steps = []
        for step in route.get("steps") or []:
            steps.append(
                {
                    "distance_m": step.get("distance"),
                    "duration_s": step.get("duration"),
                    "instructions": step.get("instructions"),
                    "name": step.get("name"),
                    "path": step.get("path"),
                }
            )
        return {
            "distance_m": route.get("distance"),
            "duration_s": route.get("duration"),
            "steps": steps,
            "source": "baidu-direction-v2-walking",
        }

    def walking_route_matrix(
        self, *, origin: dict[str, float], destinations: list[dict[str, float]]
    ) -> list[dict[str, Any]]:
        """One-to-many walking durations, auto-chunked by the concurrency-safe pair limit.

        官方口径：`/routematrix/v2/walking`，起终点乘积 ≤ 50，结果按请求顺序逐对返回。
        实测（2026-09-25 官方告警短信 10/3）：路线对数计入并发，因此每次请求最多
        matrix_pairs 对，分块顺序发送；QPS 节流保证块间发起间隔 ≥ 1/QPS。
        相比逐点调用仍省请求数与发起频次。不返回分段 steps。
        """
        if not destinations:
            raise BaiduApiError("批量算路至少需要一个终点。")
        if len(destinations) > 50:
            raise BaiduApiError("批量算路起终点乘积上限为 50，请减少终点或分批调用。")
        pairs_per_call = max(1, min(self.config.matrix_pairs, 50))
        results: list[dict[str, Any]] = []
        for chunk_start in range(0, len(destinations), pairs_per_call):
            chunk = destinations[chunk_start : chunk_start + pairs_per_call]
            payload = self._get_json(
                "/routematrix/v2/walking",
                {
                    "origins": f"{origin['lat']:.6f},{origin['lng']:.6f}",
                    "destinations": "|".join(f"{d['lat']:.6f},{d['lng']:.6f}" for d in chunk),
                },
                weight=len(chunk),
            )
            rows = payload.get("result") or []
            if len(rows) != len(chunk):
                raise BaiduApiError("批量算路返回行数与请求不一致，无法按序对齐。")
            for destination, row in zip(chunk, rows):
                if row.get("status") not in (None, 0):
                    results.append(
                        {
                            "destination": destination,
                            "status": "error",
                            "message": str(row.get("message") or "单点算路失败"),
                            "source": "baidu-routematrix-v2-walking",
                        }
                    )
                    continue
                distance = (row.get("distance") or {}).get("value")
                duration = (row.get("duration") or {}).get("value")
                results.append(
                    {
                        "destination": destination,
                        "status": "ok",
                        "distance_m": distance,
                        "duration_s": duration,
                        "source": "baidu-routematrix-v2-walking",
                    }
                )
        return results


class RecordingTransport(httpx.BaseTransport):
    """包装真实传输层并把每次请求/响应录制为回放 fixture。

    只在 scripts/record_replay_fixtures.py 中使用：录制产物写入 .runtime/
    （已 gitignore），绝不入库——交付清单要求远端仓库不含真实原始响应。
    """

    def __init__(self, inner: httpx.BaseTransport):
        self.inner = inner
        self.captured: dict[str, dict[str, Any]] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        content = response.read()
        params = {key: value for key, value in request.url.params.items() if key != "ak"}
        key = request_key(request.url.path, params)
        try:
            payload = json.loads(content)
        except ValueError:
            payload = None
        if payload is not None:
            self.captured[key] = {
                "path": request.url.path,
                "params": {str(k): str(v) for k, v in params.items()},
                "response": payload,
            }
        # 透传时必须剥掉传输层头：content-encoding（内容已被 httpcore 解压一次，
        # 带着 gzip 头重组会让 httpx 二次解压报错）、content-length 与 transfer-encoding。
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
        }
        return httpx.Response(response.status_code, headers=headers, content=content, request=request)

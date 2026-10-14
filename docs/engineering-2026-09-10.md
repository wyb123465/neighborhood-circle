# 工程加固记录：并发与缓存

日期：2026-09-10
> 历史快照：本文记录 2026-09-10 当时的工程问题与修复过程。真实百度链路随后于 2026-09-25 完成过一次 8 次调用验收；当前状态以 `docs/baidu-integration.md`、`docs/roadmap.md` 和 `README.md` 为准。

范围：`backend/baidu.py`、`backend/live_inspection.py`、`backend/analysis.py`、两个测试文件。不涉及合成算法口径、样例数据、前端行为和百度 AK 接入。

## 背景

对照当时的 `winning-brief.md` 评分表，「工程优化」一行当时状态为「未验证真实 API」，缺的是 API 请求量、批量/并发策略、缓存口径和性能数据。本记录先覆盖**不依赖外部 AK 的部分**：进程内并发策略、缓存口径、并发正确性；后续真实验收见当前接入记录。

本次先通读了 `backend/` 全部代码并实机跑通 README 的演示闭环，确认文档自述（40 pytest + 4 前端测试）与代码实际一致，再修下面三处。

## 一、缓存命中路径与指标接口的锁序反转

**问题**。`BaiduMapsClient` 有两个锁：`_cache_lock` 与 `_metrics_lock`。

- 缓存命中路径：先持 `_cache_lock`，在锁内调用 `_record()`，后者再取 `_metrics_lock` → 顺序是 **cache → metrics**。
- `metrics()`：`with self._metrics_lock, self._cache_lock` → 顺序是 **metrics → cache**。

两条路径取锁顺序相反。线程 A 持 cache 等 metrics、线程 B 持 metrics 等 cache 时即死锁。`/api/live/metrics` 与任意一次缓存命中的实时请求同时发生就可能触发。

**改动**。两处都不再嵌套取锁：

- 缓存命中路径改为在 `_cache_lock` 内只读取缓存值和新鲜度，出锁后再调用 `_record()`。
- `metrics()` 改为分两次取锁，先读 `len(self._cache)`，再 `deepcopy` 指标，最后在锁外合并。

改完后全文件已无任何「持一把锁再取另一把」的位置，反转在结构上不可能出现。

**验证**。新增 `test_metrics_and_cache_reads_run_concurrently_without_deadlock`：12 个线程（6 个反复调 `metrics()`、6 个反复读已预热缓存）经 `barrier` 同时起跑，各跑 300 轮，`join(timeout=60)` 后断言无存活线程，并核对 `cache_hits == 1800`、`network_requests == 1`。

**证据边界**。该测试是回归护栏，不是死锁的可复现证明——原缺陷是概率性的，GIL 下未必每次触发。真正消除反转的是上面的结构性改动。

## 二、POI 检索串行执行

**问题**。`inspect_live` 用两层 `for` 顺序遍历「类别 × 检索词」，四类共 10 次 `search_pois` 串行发出。客户端本来就有 `max_concurrency`（默认 4）和 `BoundedSemaphore`，但 POI 阶段完全没用上——同一文件里的路线阶段却是并发的，前后不一致。

**改动**。POI 检索改为 `ThreadPoolExecutor(max_workers=max_concurrency)` 并发提交，`max_concurrency` 语义不变（仍由客户端信号量兜底）。

**关键约束：输出顺序不能变**。原来的顺序由「类别 × 检索词」声明顺序决定。若直接按完成顺序合并：

- `facilities` 的插入顺序会变，进而影响 `balanced_selection` 的结果；
- `matched_queries`、`categories` 的追加顺序会变；
- `warnings`（检索失败提示）的追加顺序也会变。

因此改成**先并发取数、再按固定声明顺序合并**：结果存进以 `(category, query)` 为键的字典，失败项同样按 `(category, query)` 记录，然后在按原声明顺序遍历的合并循环里统一处理。POI 失败时的 `query_stats` 计数与 `warnings` 文案与改动前逐字相同。

顺带在 `performance` 中补充 `poi_phase_ms`、`route_phase_ms`、`poi_query_concurrency`，便于答辩时说明耗时构成。

**验证**。新增 `test_poi_queries_run_concurrently_and_merge_in_fixed_order`：用两个方向相反的延迟表各跑一次（第一次让靠前的检索词先返回、第二次反过来），断言两次的 `facilities` 与 `category_summary` 完全相等；同时用共享计数器测量峰值在途请求数，断言 `2 <= 峰值 <= max_concurrency`（串行时峰值只能是 1，故该断言可判别真假并发）。

该判别器已单独校准，峰值在途数严格跟随并发度、POI 阶段耗时同步下降：

| 并发度 | 峰值在途 POI 查询 | POI 阶段 |
| ---: | ---: | ---: |
| 1 | 1 | 162.0 ms |
| 2 | 2 | 97.7 ms |
| 4 | 4 | 66.6 ms |

实测（`.runtime/verify/poi_phase_bench.py`，每次 POI 查询固定模拟 60 ms，共 10 次）：

| max_concurrency | POI 阶段 | 整条链路 | 相对串行 |
| ---: | ---: | ---: | ---: |
| 1（等价改动前串行） | 614.1 ms | 619.4 ms | 1.00× |
| 2 | 306.1 ms | 311.1 ms | 2.01× |
| **4（默认）** | **183.8 ms** | **189.2 ms** | **3.34×** |
| 8 | 122.7 ms | 128.2 ms | 5.00× |

`max_concurrency=1` 一列同时充当对照组：614 ms ≈ 10 × 60 ms，确认改动前确实是串行。

## 三、底图位图每次请求重绘

**问题**。`map_image()` 是 `spec` 的纯函数，但每次 `/api/communities/{id}/map.png` 都要重建 13×11 路网、逐条画边并重新编码 PNG。前端在切换片区时必然会请求它。

**改动**。抽出 `_raster_for(serialized)` 并加 `lru_cache(maxsize=8)`，`map_image(spec)` 序列化后查缓存。位图为只读 bytes，多请求共享安全。

**验证**。实测同一片区连续两次请求：第 1 次 73.4 ms，第 2 次 5.9 ms。原有 `test_map_bitmap_and_public_assets` 仍校验尺寸 `(2080, 1760)` 与颜色数 ≥ 5，说明缓存未改变图像内容。

## 不变量回归

改动前后，三个代表性的证据编号逐字一致：

| 请求 | evidence_id |
| --- | --- |
| `bridge-demo` + 仅养老 | `a3974b8abd951063` |
| `bridge-demo` + 仅养老 + 候选点 `8,6` | `0ff5030a9a45dbe5` |
| `grid-demo` + 仅养老 | `482a2fb48f62fa7e` |

演示闭环 5 步（选片区 → 直线与路网对比及证据路径 → 候选点重算 → 撤销还原 → 报告导出）在改动后重跑通过，撤销后证据编号回到 `a3974b8abd951063`。

## 测试与健康检查

- `pytest -q`：**42 passed**（原 40 项 + 本次新增 2 项）。
- `node --check app.js`：通过。
- `node tests/request-state.test.cjs`：4 passed。
- 全套耗时由 6.72 s 降至 1.77 s，主要来自底图缓存。
- 本地服务 `http://127.0.0.1:8000`；`/api/health`、`/api/communities`、`/api/live/status`、`/api/live/metrics`、`/api/agent/inspect`（命中与未命中）均返回预期状态。
- 无 AK 时 `/api/live/geocode` 仍返回 502 且不发起外部请求。

## 仍未验证

- 真实百度 AK 下的配额、计费、域名/IP 白名单、真实返回字段与真实 POI/路线——本次未触碰，阻塞条件与 `acceptance-2026-09-07.md` 相同。
- 上述并发收益全部基于 `httpx.MockTransport` 与模拟延迟，**不是真实百度接口的实测耗时**；真实环境还受服务端限流、网络抖动和配额错误影响。
- 指数退避、配额错误处理仍未实现（`technical-design.md` 第 7 条）。
- Docker 实机启动、远端 CI、仓库发布仍未验收。
- POI 检索失败的降级路径只有 MockTransport 覆盖，没有真实超时/断网场景。

## 复现

在项目目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check app.js
node tests/request-state.test.cjs
.\.venv\Scripts\python.exe .runtime\verify\poi_phase_bench.py
```

`.runtime/` 为本地运行产物目录，不应提交到仓库。

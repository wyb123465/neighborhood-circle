# v0.3 验收记录

日期：2026-09-07
> 历史快照：这是 2026-09-07 的早期基线验收，不能代表当前项目状态。当前版本、真实链路和新增盲区能力见 `README.md`、`docs/roadmap.md` 与 `docs/baidu-integration.md`。

## 已验证

- Python 测试：40 passed。
- 前端状态测试：4 passed。
- JavaScript 语法检查：通过。
- 本地 FastAPI 服务：`http://127.0.0.1:8000`。
- OpenAPI 版本：0.3.0。
- `/api/live/status`：默认 synthetic-only，V3 地点检索配置可见，AK 不返回。
- 未配置 `BAIDU_MAP_AK` 时，`/api/live/geocode` 返回 502，且不发起外部请求。
- `/api/live/geocode`、`/api/live/pois`、`/api/live/walking`、`/api/live/inspect` 已注册。
- 服务端适配器 MockTransport：地理编码、V3/V2 地点检索、分页去重、路线解析、缓存和错误状态均通过。
- `/api/live/inspect`：POI 多 query 去重、路线成功和路线失败状态均通过。
- 前端桌面和 390px 手机尺寸：无横向溢出，地图和体检结果可显示。

## 未验证

- 没有真实百度 AK，因此未验证百度账号权限、配额、计费、域名/IP 白名单和实际返回字段。
- 没有真实地址、真实 POI、真实路线和真实社区边界。
- `/api/live/inspect` 不是最终参赛体检报告，只是中心到设施路线证据。
- 没有把百度坐标输入转换为人口/网格加权的居民覆盖率。
- Docker 实机启动、远程 CI 执行和外部仓库发布尚未验收。

## 下一步验收门槛

拿到测试 AK 后，先运行 `/api/live/status`，再用一个公开社区地址依次验证地理编码、四类 POI、5 条步行路线和一次失败/超时 fixture。只有真实字段和配额确认后，才把实时结果接入空间采样层。

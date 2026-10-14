# 邻里圈

面向街道与社区治理的生活圈服务缺口诊断与设施模拟工具。

**参赛定位：2026 上海开源软件应用创新大赛 · 开源 AI 工具赛道 · 百度地图企业命题。**<br>
题材对齐「15 分钟生活圈」场景；主交付是**可复现的缺口诊断闭环**。离线样例用于稳定演示，配置 `BAIDU_MAP_AK` 后启用 `/api/live/*` 真实链路；未配置或调用失败时不会用合成数据冒充百度返回。

## 当前状态：v0.5.0-beta 开发版；v0.4.1 提交基线保留

**v0.5 新增智能助手工作台 `/assistant.html`：**受约束的模型工具调用、事实编号引用、候选方案重算比较、追问复用、实际调用步骤、停止/重试与报告预览导出。实时设施改为分类兼顾近处取样，路线未知不进入已知比例分母；近阈值样点标记待复核。真实页支持显式 BD-09 / GCJ-02 / WGS84 输入，并通过官方接口转换。**2026-10-13 已通过 5 条真实 DeepSeek 模型联调，其中一条串通当前百度数据，发起45次实际地图请求；14日更新出口白名单后再次全部通过。**接入方法见 [AI 接入说明](docs/ai-integration.md)，实施记录见 [v0.5 验收记录](docs/acceptance-v0.5.md)。v0.4.1 提交材料保留为历史基线，不能代表新版功能。

已实现：NetworkX 最短路径计算、两种连通性样例、自定义中心节点、步速与时间阈值、四类设施过滤、采样点覆盖率、候选设施增益重算、1 公里菜市场/药店/小学检查、**从已知盲区生成按类别规划候选参考点**、可缩放地图、**可追溯体检报告**（元数据 / 路径证据 / 模拟状态 / 未知点）、JSON/Markdown 导出、一键演示预设、**规则说明 / 可选大模型解释层**（未配置密钥时 `rule-only`，失败回退并暴露原因）、API 与测试。

真实数据侧（2026-09-25 至 2026-10-02）：服务端**批量算路**接入体检主路径（失败自动回退逐点）、**网格采样近似等时圈** `/api/live/isochrone`（批量测时 + 逐点可达标记 + **自适应边界加密**：粗网格定位边界、锚点周围按 1/3 间距补 3×3 细分点）、**实时体检页** `/live.html`（等时圈地图、设施标记、1 公里盲区、规划候选参考点、Markdown/JSON 导出）、QPS 发起频率节流、批量算路对数拆块与 IPv4 出口强制。2026-09-25 已完成 8 次官方接口真实调用验收；2026-10-02 复测因当前出口 IP 不在百度白名单而被拒，详见 `docs/baidu-integration.md`。

**2026-10-13 收尾更新：**回放无需 AK，自动恢复录制参数；页面与报告区分历史回放和实时数据。实时页支持 BD-09 中心坐标。1 公里专项检索扩大至至少 2 公里，分页截断或范围不足时保留逐点未知；培训等明显小学误命中不参与专项覆盖。测试与材料状态见 `docs/acceptance-2026-10-13.md`。

**当前可交付边界：**合成模式可离线复现，实时模式可在百度 AK 与 IP 白名单正常时运行；1 公里专项检查使用 250 米等权网格，查询失败标记为未知，候选点是已知缺口样点的贪心覆盖参考，不是地块选址或建设收益结论。尚待完成的主要是独立路线核验、进一步 POI 核验、真实用户反馈及团队公开发布/报名；Docker 本地烟测已有记录。2026-10-13 修正国内出口白名单后，8 次官方调用全部通过，完整流程已重新录制 40 个真实请求。

样例是自行构造的米制平面路网，不是百度接口响应，不对应真实上海社区。实时页中的等时圈比例是路线采样点比例，不是人口覆盖率；未知查询不会被当作“没有设施”。旧原型中写死的置信度、面积、历史改善和设施收益已移除。

## 本地启动

在本项目目录执行，Python 3.12 或 3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
.\.venv\Scripts\python.exe scripts/serve.py --mode synthetic --port 8000
```

访问 <http://127.0.0.1:8000>，API 文档 <http://127.0.0.1:8000/docs>。如果端口已占用，将 `8000` 改为 `8001`。

页面依赖后端计算，不支持直接打开 HTML 或纯静态服务器。默认安装依赖后不访问外网，Leaflet 和 Lucide 已本地化，许可证随附。只有设置 `BAIDU_MAP_AK` 后调用 `/api/live/*` 才会访问百度地图。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m py_compile scripts\check_live.py
.\.venv\Scripts\python.exe -m py_compile backend\live_inspection.py
node --check app.js
node --check live.js
node --test tests/*.test.cjs
node --check assistant.js
```

Linux/macOS 将 Python 路径换为 `.venv/bin/python`。Docker：`docker compose up --build`，不需要 `.env`；构建需要访问 Docker Hub。若宿主机 8000 已被占用，可使用 `NEIGHBORHOOD_PORT=8001 docker compose up --build`。2026-10-03 已用本机 Python 3.12 基础镜像完成容器启动烟测：健康接口、首页、实时页和无 AK 状态接口均返回正常；首次从 Docker Hub 拉取基础镜像仍受当前网络影响。

## 可演示闭环（约 3 分钟）

1. 点击「**演示预设**」：自动载入滨河片区 · 仅养老 · 15 分钟 · 80 米/分钟。
2. 对比直线范围与中心可达点，点「定位路径」查看绕行证据。
3. 选择一个养老候选点，查看缺口减少、覆盖率和设施数同步变化。
4. 撤销模拟，验证回到同一结果；切换「连通片区」比较。
5. 打开报告：核对证据编号、算法/数据版本、直线高估点数、口径边界；导出 Markdown 或 JSON。

有 AK 时可加演 `/live.html`：真实步行等时圈采样 → 设施路线证据 → 1 公里菜市场/药店/小学盲区 → 候选参考点 → 报告导出。解释接口 `POST /api/agent/inspect` 附带 `explanation`（默认 rule-only）。

## 指标口径

- 分母为 143 个等权路网节点，不是人口，也不转换为土地面积。
- 某类覆盖：节点到最近同类设施的最短距离 / 恒定步速 <= 时间阈值。
- 同时可达：所选每类设施均满足阈值；不是各类覆盖率平均值。
- 中心点可达与片区服务覆盖是两个不同问题。改变中心不改变片区覆盖率，但改变中心到各点/设施的时间。
- 真实模式的 1 公里检查按类别对中心周边 1,000 米范围做 250 米等权网格采样；它独立于步行等时圈，距离口径仍需与企业确认。
- 候选模拟只计算新增可达节点数，不证明用地可行、容量充足或建设收益。
- 实时规划候选点只计算已知盲区样点的贪心覆盖增益；POI 查询失败或未纳入画像的类别不参与候选生成。
- 相同参数重复调用应得到相同 `evidence_id` 与相同数值；报告可复算。

## 百度地图适配器

适配器是服务端代码，不向浏览器暴露 AK。配置 `.env` 后启动服务：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 BAIDU_MAP_AK
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

验证接口：

- `GET /api/live/status`
- `GET /api/live/geocode?address=上海市长宁区愚园路&city=上海市`
- `GET /api/live/pois?lat=31.2168&lng=121.4269&query=养老服务&radius_m=1500`
- `GET /api/live/walking?origin_lat=31.2168&origin_lng=121.4269&destination_lat=31.2208&destination_lng=121.4352`
- `GET /api/live/inspect?address=上海市长宁区愚园路&city=上海市&category=医疗,养老,教育,购物`
- `GET /api/live/status`（含各检索词组画像的地点检索调用成本）
- `GET /api/live/inspect?...&query_profile=narrow`（配额优先画像，地点检索由 10 次/体检降到 4 次/体检）
- `GET /api/live/isochrone?address=上海市长宁区愚园路&minutes=15`（或 `lat`/`lng` 直传，`refine=false` 关闭加密）：网格采样近似等时圈，批量算路完成全部采样点测时，粗网格 + 边界自适应加密（1/3 间距、阈值优先），逐点标记可达/不可达/未知，不拟合边界、不隐藏障碍孔洞
- `/api/live/inspect` 返回 `blind_spots`：菜市场、药店、小学的 1 公里专项结果、未知状态、已知缺口样点及规划候选参考点。

`/api/live/inspect` 的路线证据自 2026-09-25 起默认走批量算路（`/routematrix/v2/walking`，按对数拆块，失败时自动回退并如实标注）；所有真实请求都受 QPS 发起节流（默认 2 次/秒）与在途并发信号量双重约束。

一次 `/api/live/inspect` 会消耗 1 次地理编码、若干次地点检索和最多 `max_facilities` 次步行路线。**地点检索在个人认证下只有 100 次/日**，配额口径与画像取舍见 `docs/baidu-integration.md`。

没有 AK 时接口返回 502，明确说明未发起外部请求；不会用合成数据冒充百度返回。`/api/live/inspect` 输出中心到设施的真实路线证据和 1 公里专项检查，但不输出居民人口覆盖率或连续灰色区域。实时页和导出报告会同时保留数据来源、未知状态与方法警告。

AK 申请步骤见 `docs/ak-application-checklist.md`（个人认证即时生效，但有 5 次认证机会上限，提交前先自检）。拿到 AK 后跑一次真实链路验收：

```powershell
.\.venv\Scripts\python.exe scripts\check_live.py --address "上海市长宁区愚园路" --city 上海市
```

脚本顺序调用、默认走 `narrow` 画像，合计约 8 次调用，报告写入被忽略的 `.runtime/`；base_url 不是官方地址时报告会显式标注为仿真环境。

地点检索默认使用当前配置的 `BAIDU_PLACE_API_VERSION=v3`；如需兼容旧账号或旧服务，可在本地 `.env` 临时设置为 `v2`。两种响应都会先归一化为同一内部结构，项目不会把版本差异暴露给前端。

## 文件与安全

`backend/analysis.py` 为样例算法，`backend/main.py` 为 API，`data/sample_communities.json` 为合成数据。前端为 HTML/CSS/JavaScript + Leaflet，未额外引入构建工具。

只公开三个前端文件和 `assets/`，不会把 `.env`、源代码或赛题 PDF 暴露为静态文件。`.env.example` 不含真实密钥；实际 `.env` 只由服务端读取，浏览器不会拿到 AK。未配置 AK 时实时页会明确提示，不会发起百度请求。

参赛计划见 `docs/roadmap.md`，技术边界见 `docs/technical-design.md`，定位与答辩证据见 `docs/winning-brief.md`，服务端适配器的并发与缓存加固记录见 `docs/engineering-2026-09-10.md`，AK 申请与配额口径见 `docs/ak-application-checklist.md` 与 `docs/baidu-integration.md`。

代码许可证：MIT；上游组件遵循各自许可证。公开发布与报名由团队执行；首次 Docker Hub 拉取仍需联网复核。


## 参赛交付与显式启动模式（v0.4.1）

官网于 2026-10-13 核验：报名和材料截止 **2026-10-16 24:00（北京时间）**。以 https://www.oschina.net/os2026/ 及报名确认邮件为准。

```powershell
# 首次会自动创建虚拟环境并安装依赖；已有环境需要更新时加 -InstallDependencies
powershell -ExecutionPolicy Bypass -File .\start.ps1
# 本地历史回放：不读取 AK，不联网；录制文件不随公开源码分发
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Mode replay -Port 8001
# 实时模式：读取本地 .env，需要百度服务端 AK 与 IP 白名单正常
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Mode live
# 真值对比报告（不访问百度）
.\.venv\Scripts\python.exe scripts/verify_release.py
# 附带本地历史回放的验收
.\.venv\Scripts\python.exe scripts/verify_release.py --replay-file .runtime/replay/fixtures.json
# 安全扫描并生成独立源码包
.\.venv\Scripts\python.exe scripts/package_release.py
```

Linux/macOS：`bash start.sh`；其他模式：`bash start.sh live 8001`。默认启动脚本使用 synthetic 模式，清除进程内地图/AI 凭证并跳过 .env，保证评委演示不意外消耗配额。

新查询至少覆盖中心周边 2 公里，才能检查中心周边 1 公里网格内各样点的 1 公里服务范围。POI 分页达到上限仍有满页时，仅保留已找到设施的覆盖证据，未找到的样点记为未知。complete 表示本次查询的证据边界完整，不保证设施当前营业或地图数据库没有漏标。

- 收尾计划：`docs/release-plan.md`
- 本轮验收：`docs/acceptance-2026-10-13.md`
- 作品简介、发布与提交模板：`docs/submission-guide.md`
- 三分钟演示：`docs/demo-script.md`
- 独立源码包位于 `output/release/`，不含原始录制响应、AK、虚拟环境和另一参赛作品。解压后的项目文件应置于公开仓库根目录，使 CI 能被发现。

依赖版本见 `constraints.txt`，已在独立 Windows / Python 3.13 环境从源码包安装并通过全部 93 项 Python 测试。网络诊断可显式执行 `python scripts/check_network.py`；若存在国内外分流，须核对百度方向的出口，不能仅采用国外 IP 查询站结果。

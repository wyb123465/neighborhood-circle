# 参与邻里圈

邻里圈是处于早期阶段的开源 Web 工具。当前维护账号为 [wyb123465](https://github.com/wyb123465)，没有宣称已有用户社区、合作机构或专职维护团队。

## 报告问题与提出建议

在仓库 Issues 使用缺陷或功能模板，说明版本、启动模式、复现步骤、预期结果与实际结果。地图问题请注明坐标来源、数据时点及是否回放。截图先去除凭证、手机号和其他个人信息；不要公开 `.env` 或原始接口响应。

## 提交变更

1. Fork 仓库，从 main 建立有明确目的的分支。先说明问题，再实现最小完整改动。
2. Python 3.12/3.13；安装 `python -m pip install -r requirements-dev.txt -c constraints.txt`。前端检查需要 Node 22 和 `npm ci --ignore-scripts`，运行应用本身不需要 Node。
3. 用 `python -m ruff format backend scripts tests` 和 `npm run format` 整理格式。
4. 提交前运行 `python -m ruff check backend scripts tests`、`python -m pytest -q`、`npm test`、`npm run format:check`、`python scripts/verify_release.py` 和 `python scripts/security_scan.py`。
5. PR 写清触发条件、行为变化、验证方法和剩余限制。涉及视觉或交互时附实际界面截图；涉及空间算法时附坐标、分母和独立期望结果。
6. 维护者审阅通过且 CI 成功后合并。未通过检查的改动不发布为已验收版本。

测试默认使用合成数据或 Mock，不自动消耗外部接口配额。真实联调必须显式执行并记录日期、请求数与数据模式。

## 证据与数据约定

- 数值由计算工具产生，模型只能引用已存在的证据。
- 不混合 BD-09、GCJ-02、WGS84 与合成米制坐标。
- 未知不能写成缺口；近阈值复核标记不能写成置信区间。
- 本机核验备注与原始接口结果独立；没有现场或独立参照就不声明现实准确率。
- 不向仓库提交百度原始响应、底图瓦片、密钥或未获授权的数据。

代码贡献按仓库 MIT 许可证提交；第三方内容继续保留其原许可证与来源。

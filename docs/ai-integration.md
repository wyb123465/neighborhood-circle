# 智能助手接入与验收

当前版本为 **0.5.0-beta**。2026-10-13 已通过5条真实 DeepSeek 模型联调，其中一条串通当前百度地图数据，使用45次实际地图HTTP请求；14日当前网络白名单恢复后再次5/5通过。规则结果及 Mock 测试单独记录，不作为真实接入证明。验收摘要见 [验收记录](acceptance-v0.5.md)。

## 本地模型配置

在项目已有 `.env` 填写下列字段；不要覆盖已有百度配置，也不要提交或分享密钥：

```dotenv
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
AI_PROTOCOL=chat_completions
AI_TIMEOUT=45
AI_MAX_MAP_REQUESTS=64
```

`AI_BASE_URL` 为 API 根地址，通常以 `/v1` 结尾，不包含 `/chat/completions` 或 `/responses`。选择服务实际支持工具调用的模型。兼容 Chat Completions 的服务使用 `chat_completions`；要求 Responses 的模型使用 `responses`。适配器保留 Responses 后续调用所需的推理输出，模型密钥只在服务端发送。

协议依据：[OpenAI 函数调用官方文档](https://developers.openai.com/api/docs/guides/function-calling)。兼容厂商可能有字段差异，以真实调用测试为准。

```powershell
# 模型联网 + 合成路网；不发百度请求
.\start.ps1 -Mode assistant
# 模型联网 + 私有历史真实地图回放
.\start.ps1 -Mode assistant -MapMode replay
# 模型联网 + 当前百度地图（需要 AK、白名单和配额）
.\start.ps1 -Mode assistant -MapMode live
```

Linux/macOS 对应 `./start.sh assistant 8000 synthetic`、`./start.sh assistant 8000 replay`、`./start.sh assistant 8000 live`。打开 <http://127.0.0.1:8000/assistant.html>。

`synthetic`、`replay` 独立启动模式始终禁用模型，保留原有离线演示能力。`assistant` 才读取模型配置；模型未配时页面明确显示规则模式。初次空配置补齐后可点“刷新模型状态”；更换已加载的非空配置建议重启服务。

## 工作流与证据

模型可调用四个受约束工具：`inspect_neighborhood`、`read_evidence`、`compare_candidates`、`finish`。地址、类别、阈值、候选数量及证据编号均经服务端校验。模型选择工具和事实编号；展示的数值与事实句由程序计算生成，不把模型自由文本当作统计结论。

合成方案分别重算，与原始基线比较；真实参考点分别列出独立覆盖、与前序同类点组合的边际覆盖和剩余缺口。后续追问可复用已有证据。每次最多 5 轮模型、6 次工具、默认 64 次新增地图 HTTP 请求，总运行时间受限。缓存和回放不占新增请求计数；该计数不等于地图计费量。

停止会阻止后续请求，在途调用可能完成。修改地点、时间、步速或模式会作废旧页面结果；模型失败、额度用尽、会话过期均有明确状态，不自动冒充成功。会话仅存本地服务内存，闲置 30 分钟后可过期。

页面提供结论、证据地图、候选比较和 Markdown 报告预览；“复制结论”保留证据编号。原有合成/真实页继续提供 JSON 与 Markdown 文件导出。

本次配置使用 DeepSeek 的 Chat Completions 工具调用协议，依据其 [官方 Tool Calls 文档](https://api-docs.deepseek.com/guides/tool_calls/)；未启用 Beta strict 模式，参数与证据引用均由本地 Pydantic 和允许列表验证。

## 真实联调门槛

先用 `assistant + replay` 进行模型协议验证，再用 `assistant + live` 至少完成一条当前百度链路；不能把回放通过记作当前地图联调通过。

```powershell
.\.venv\Scripts\python.exe scripts/check_assistant.py --base-url http://127.0.0.1:8000
```

脚本验证五个场景：含糊需求追问、合成体检比较、同条件追问、改变时间重算、真实数据比较。记录写入忽略的 `.runtime/assistant-validation.json`，明确保留模型调用、数据模式、工具步骤和失败原因；配置为空时明确退出，不能生成“通过”记录。

公开发布前仍须真实模型验收、端到端页面检查和材料更新。现有 v0.4.1 提交包保留为已验证基线。

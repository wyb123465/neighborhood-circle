"""Create the current AI competition brief without overwriting the baseline."""
from pathlib import Path
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, Spacer
from create_project_brief import BriefDocTemplate, p, rich, title, subtitle, body, small, make_table, section_heading, INK

ROOT = Path(__file__).resolve().parents[1]


def main():
    body.textColor = small.textColor = INK
    output = ROOT / 'output/pdf/邻里圈-v0.5-项目介绍.pdf'
    story = [Spacer(1, 5*mm), Paragraph('邻里圈', title), Paragraph('15 分钟生活圈智能体检与规划助手', subtitle), p('2026 上海开源软件应用创新大赛 · 开源 AI 工具赛道 · 百度地图企业命题', body), p('版本：0.5.0-beta；材料更新：2026-10-14；真实模型与地图验收：2026-10-13及14日。', small)]
    story += section_heading('1. 从需求到可核验的方案')
    story += [p('面向街道和社区调研，回答服务哪里缺、依据是什么、补充一个参考点能覆盖多少已知缺口样点。自然语言入口直接组织计算工具与证据，方便非开发者复核。', body), make_table([['需求理解','计算与比较','核验与交付'],['缺少信息时追问\n地点、设施、时间','真实地图 / 合成路网\n候选重算与边际增益','证据编号定位地图\n报告预览与导出']], [56*mm,56*mm,56*mm]), Spacer(1,3*mm)]
    screenshot = ROOT / 'output/screenshots/ai-overview.png'
    image = Image(str(screenshot), width=168*mm, height=100*mm, kind='proportional')
    story += [image, p('实际运行截图：真实 DeepSeek 模型选择工具，地图数据模式在界面明确标注。', small)]
    story += section_heading('2. AI 的职责与计算边界')
    story += [p('模型负责理解需求、选择体检 / 证据读取 / 方案比较工具和事实编号。服务端验证参数、计算全部数值并生成事实句；自由文本不作为统计结论。追问复用同条件证据，参数变化重新计算，错误和取消都有独立状态。', body), p('合成方案分别与同一基线比较；真实候选区分独立覆盖与组合新增。覆盖样点不代表人口，候选点不证明用地、容量或建设收益。', body), PageBreak()]
    story += section_heading('3. 已验证的结果')
    story += [make_table([['验收','结果','证据含义'],['真实模型联调','最新5/5通过，11轮调用','追问、比较、条件变更与当前地图分析'],['当前百度链路','45次实际HTTP请求','去重69处POI，选20处测时；49个专项样点'],['合成方案重算','44.8% → 92.3%，新增68点','同一基线、143个等权节点；另一个方案新增66点'],['独立源码验收','115项Python测试通过','解压源码、无密钥启动、公开内容扫描'],['前端状态测试','12项通过','停止、晚到响应、追问、参数失效与报告保护'],['官方坐标转换','GCJ-02 / WGS84各一次成功','明确来源，经geoconv v2转为BD-09']], [34*mm,55*mm,79*mm]), Spacer(1,3*mm)]
    story += section_heading('4. 对不确定性的处理')
    story += [p('路线未知不进入已知分母；POI分页截断、检索范围不足时保留未知。三条边界路线在同一轮百度批量与单条接口之间仍跨过900秒阈值。产品标记距阈值不超过2分钟的样点待复核，保留原始判别；该范围不是置信区间。', body), p('愚园路菜市场专项有1个已知缺口样点。菜市场、农贸市场补查均为空，只支持地图检索未找到对应POI，不能证明现实不存在或确认营业状态。实际粗网格间距为675米，边界加密32点，不能宣称200米完整采样。', body)]
    story += section_heading('5. 技术结构与演示方式')
    story += [make_table([['层','实现'],['交互层','原生HTML/CSS/JS、Leaflet；任务、过程、结论、地图与报告'],['智能体层','兼容Chat Completions / Responses；允许列表、结构化校验与证据引用'],['计算层','NetworkX最短路、等权覆盖、候选重算、真实POI及采样测时'],['工程边界','服务端密钥、缓存、共享限流、请求预算、取消与会话过期']], [32*mm,136*mm]), p('默认合成模式可离线启动；assistant模式读取本地模型配置。真实地图需要百度AK及正确白名单；私有历史回放单独标记，不冒充实时数据。视频由实际截图分步讲解，配合合成中文解说与字幕。', body)]
    story += section_heading('6. 提交前由团队完成')
    story += [p('补充团队名、作者、公开源码仓库和公开视频链接；核对参赛平台要求后自行报名提交。非开发者首次使用体验、实际出入口和设施营业状态仍需团队复核。14日更新出口白名单后，实时链路复测通过；更换网络须核对国内出口，历史回放可用于稳定演示。材料不含密钥或私有原始响应。', body), p('可追溯记录随包附：v0.5验收、边界补充复核、原20条路线网页对照、POI公开资料核对。', small)]
    output.parent.mkdir(parents=True, exist_ok=True)
    BriefDocTemplate(str(output), title='邻里圈 v0.5 项目介绍', author='邻里圈项目团队').build(story)
    print(output)


if __name__ == '__main__':
    main()

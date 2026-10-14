"""Current project brief, preserving older submission artifacts."""
from pathlib import Path
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, Spacer
from create_project_brief import BriefDocTemplate, p, rich, title, subtitle, body, small, make_table, section_heading, INK

ROOT=Path(__file__).resolve().parents[1]


def main():
    body.textColor=small.textColor=INK
    output=ROOT/'output/pdf/邻里圈-v0.6-项目介绍.pdf'
    story=[Spacer(1,4*mm),Paragraph('邻里圈',title),Paragraph('15分钟生活圈智能体检与规划助手',subtitle),p('2026上海开源软件应用创新大赛 · 开源AI工具赛道 · 百度地图企业命题',body),p('版本0.6.0 · 更新于2026-10-14',small)]
    story+=section_heading('1. 走得到，才算生活圈')
    story += [p('面向街道与社区调研，把“哪里缺、依据是什么、补一个参考点能改善多少”放在同一条可核验流程中。模型理解需求并选择受约束的工具；数值与事实由程序计算产生。',body),Image(str(ROOT/'assets/screenshots/workspace-v06.png'),width=168*mm,height=95*mm,kind='proportional'),p('实际运行界面：合成案例与真实模型工具调用；合成数据不对应真实上海社区。',small)]
    story+=section_heading('2. 从问题到证据，再到参考方案')
    story += [make_table([['需求与执行','空间判断','后续核验'],['地点、类别、时间\n缺信息追问；停止/重试','指标、地图与候选并排\n设施联动；短引用定位','固定样点情景对比\n本机快照、备注与打印']], [56*mm,56*mm,56*mm]),Spacer(1,2*mm),p('滨河合成样例：养老覆盖44.8%、缺口79/143。首个候选单独重算后覆盖92.3%，新增68个样点，剩余11；第二个方案新增66个。两项是相对同一基线的独立方案，不能直接累加。',body),rich('<link href="https://github.com/wyb123465/neighborhood-circle" color="#197257">公开源码：github.com/wyb123465/neighborhood-circle</link>',small),PageBreak()]
    story+=section_heading('3. 本轮实现与证据')
    story += [make_table([['能力 / 验证','结果与边界'],['真实模型与地图','5个真实模型场景通过；当前百度链路45次HTTP请求，去重69处POI、选20处测时。'],['情景对比','合成固定143节点：10/15/20分钟分别30.8%/44.8%/55.9%；真实模式复用原始秒数、均匀样点及固定范围，0新增请求。'],['工程验证','独立源码环境119项Python测试，15项前端状态测试；公开GitHub远程CI通过。'],['数据与交互','设施详情、图层、合成绕行路径、官方核对链接；真实、回放、合成分别显示来源。'],['本机工作流','保存体检与情景；核验备注独立于原始结果；快照加载后需重算才能AI追问。'],['报告','先预览摘要，再由用户选择A4打印/存PDF；保留参数、模式、证据、口径和未知。']], [35*mm,133*mm]),Spacer(1,3*mm)]
    story+=section_heading('4. 可信度来自明确的边界')
    story += [p('设施统计描述中心到已评估设施的路线证据；采样比例不是人口覆盖率。候选参考点不证明地块可建、容量充足或建设收益。POI检索截断、失败和范围不足时保留未知。',body),p('三条近阈值路线在百度单条与批量接口间仍有跨阈值分歧。原始判别保留，距阈值不超过2分钟的样点标记待复核；该窗口是复核策略，不是误差置信区间。',body),p('真实地图目前为BD-09坐标的局部米制样点示意，附官方核对入口。嵌入道路底图仍需网页端地图配置。10/15/20分钟真实对比固定本次采样范围，不代表三条完整等时圈。',body)]
    story+=section_heading('5. 开源复现与提交')
    story += [p('Python 3.12/3.13、FastAPI、NetworkX、原生HTML/CSS/JS、Leaflet。默认合成模式不读取密钥、不请求外网；assistant模式接入用户自备模型，live模式另需百度服务端AK及白名单。源码不含密钥、私有原始响应、虚拟环境或其他参赛项目。',body),p('视频采用实际运行截图分步讲解，配合合成中文解说和字幕，不是连续录屏。团队还需补充真实署名、公开视频链接、非开发者试用和现场设施/入口核验，并自行报名提交。',body),p('详细记录随包附：v0.6验收、既有路线与POI核对、边界补充复核和接入说明。',small)]
    output.parent.mkdir(parents=True,exist_ok=True)
    BriefDocTemplate(str(output),title='邻里圈 v0.6 项目介绍',author='邻里圈项目团队').build(story)
    print(output)


if __name__=='__main__':main()

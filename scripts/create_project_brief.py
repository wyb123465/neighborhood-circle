from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "邻里圈-项目介绍.pdf"

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"

GREEN = colors.HexColor("#197257")
INK = colors.HexColor("#1d2928")
SECONDARY = colors.HexColor("#526260")
MUTED = colors.HexColor("#7b8986")
PALE_GREEN = colors.HexColor("#e6f1ed")
PALE_GOLD = colors.HexColor("#f5ecd4")
PALE_RED = colors.HexColor("#f7e8eb")
LINE = colors.HexColor("#d9e1df")


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def rich(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


class BriefDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, pagesize=A4, **kwargs)
        frame = Frame(
            18 * mm,
            16 * mm,
            A4[0] - 36 * mm,
            A4[1] - 32 * mm,
            id="normal",
        )
        self.addPageTemplates([PageTemplate(id="brief", frames=frame, onPage=draw_page)])


def draw_page(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.HexColor("#f7faf9"))
    canvas.rect(0, height - 6 * mm, width, 6 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 7 * mm, "邻里圈 | 2026 上海开源软件应用创新大赛")
    canvas.drawRightString(width - 18 * mm, 7 * mm, f"{doc.page}")
    canvas.restoreState()


styles = getSampleStyleSheet()
title = ParagraphStyle(
    "TitleCN",
    parent=styles["Title"],
    fontName=FONT,
    fontSize=25,
    leading=32,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=6 * mm,
)
subtitle = ParagraphStyle(
    "SubtitleCN",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=12,
    leading=20,
    textColor=SECONDARY,
    spaceAfter=7 * mm,
)
h1 = ParagraphStyle(
    "H1CN",
    parent=styles["Heading1"],
    fontName=FONT,
    fontSize=16,
    leading=21,
    textColor=INK,
    spaceBefore=4 * mm,
    spaceAfter=2 * mm,
)
h2 = ParagraphStyle(
    "H2CN",
    parent=styles["Heading2"],
    fontName=FONT,
    fontSize=12,
    leading=18,
    textColor=GREEN,
    spaceBefore=4 * mm,
    spaceAfter=2 * mm,
)
body = ParagraphStyle(
    "BodyCN",
    parent=styles["BodyText"],
    fontName=FONT,
    fontSize=9.5,
    leading=14,
    textColor=SECONDARY,
    spaceAfter=2.5 * mm,
)
small = ParagraphStyle(
    "SmallCN",
    parent=body,
    fontSize=8,
    leading=12,
    textColor=MUTED,
)
card = ParagraphStyle(
    "CardCN",
    parent=body,
    fontSize=9,
    leading=13,
    textColor=INK,
)
metric = ParagraphStyle(
    "MetricCN",
    parent=body,
    fontSize=13,
    leading=19,
    textColor=GREEN,
)
center = ParagraphStyle(
    "CenterCN",
    parent=body,
    alignment=TA_CENTER,
)


def section_heading(text: str):
    rule = HRFlowable(width="100%", thickness=0.7, color=LINE, spaceAfter=3 * mm)
    rule.keepWithNext = True
    return [Paragraph(escape(text), h1), rule]


def make_table(data, widths, header=True, row_heights=None):
    converted = []
    for row_index, row in enumerate(data):
        converted.append(
            [
                cell if hasattr(cell, "wrap") else p(str(cell), small if row_index else card)
                for cell in row
            ]
        )
    table = Table(converted, colWidths=widths, rowHeights=row_heights, repeatRows=1 if header else 0)
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), PALE_GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ]
    table.setStyle(TableStyle(commands))
    return table


def build_story():
    story = []
    story += [
        Spacer(1, 9 * mm),
        Paragraph("邻里圈", title),
        Paragraph("15 分钟生活圈智能体检与规划助手", subtitle),
        rich(
            "<font color='#197257'><b>参赛定位</b></font>　2026 上海开源软件应用创新大赛 · 开源 AI 工具赛道 · 百度地图企业命题",
            body,
        ),
        rich(
            "一句话：把真实地图数据转成“哪里缺、为什么缺、补一个参考点可能改善多少”的可追溯证据链。",
            body,
        ),
        Spacer(1, 2 * mm),
    ]

    hero = Table(
        [
            [
                rich("<font size='18' color='#197257'><b>从体检到规划</b></font><br/><font color='#526260'>真实路线证据 + 1 公里专项盲区 + 候选参考点</font>", card),
                rich("<font color='#7a5b12'><b>交付版 v0.4.1</b></font><br/><font color='#526260'>合成可复现，真实链路可验证<br/>未知状态不冒充缺口</font>", card),
            ]
        ],
        colWidths=[92 * mm, 74 * mm],
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), PALE_GREEN),
                ("BACKGROUND", (1, 0), (1, 0), PALE_GOLD),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 11),
                ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(hero)

    story += section_heading("1. 为什么做")
    story.append(
        p(
            "街道和社区在做生活圈判断时，常见问题不是“没有地图”，而是缺少一条能被复核的判断链：设施是否真的在步行阈值内，直线距离和道路绕行差多少，专项服务是否存在盲区，新增一个服务点的改善是否可解释。",
            body,
        )
    )
    story.append(
        p(
            "邻里圈将结果拆成三层：离线合成模式用于稳定复现算法和演示；百度地图实时模式提供地理编码、POI 和步行路线证据；报告把来源、参数、未知点和限制一起保留下来。",
            body,
        )
    )

    story += section_heading("2. 产品闭环")
    flow = [
        ["输入", "计算", "判断", "规划", "交付"],
        ["社区地址\n设施类别\n步行阈值", "地理编码\nPOI 检索\n批量步行算路", "网格采样等时圈\n1 公里专项盲区\n未知状态", "按类别生成\n候选参考点\n覆盖增益", "地图展示\nMarkdown / JSON\n证据编号"],
    ]
    story.append(make_table(flow, [34 * mm, 34 * mm, 34 * mm, 34 * mm, 34 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(p("核心产品叙事：不是“附近有什么”，而是“哪里确实缺、证据是什么、补一个点可能改善多少”。候选参考点不是建设选址，不替代规划审批。", body))

    story += section_heading("3. 参赛题要求的直接响应")
    score = [
        ["能力", "当前实现", "展示方式"],
        ["真实地图能力", "百度地理编码、POI V3/V2 兼容、步行路线和 RouteMatrix 批量算路", "实时页状态、路线表、性能字段"],
        ["空间分析", "网格采样近似等时圈，自适应边界加密，逐点 reachable / unreachable / unknown", "地图方格、比例、口径警告"],
        ["1 公里专项", "菜市场、药店、小学按 250 米等权网格检查；查询失败、分页截断或范围不足为 unknown", "类别统计、灰色缺口与黄色未知样点"],
        ["从问题到方案", "对已知缺口按类别生成最多 3 个贪心覆盖参考点", "编号标记、覆盖增益、报告表格"],
        ["工程可信度", "缓存、QPS 节流、并发边界、失败回退、服务端 AK、不泄露密钥", "代码、测试、验收记录"],
    ]
    story.append(make_table(score, [29 * mm, 89 * mm, 52 * mm]))

    story.append(PageBreak())
    story += section_heading("4. 已有证据")
    evidence = [
        ["证据", "结果", "说明"],
        ["自动测试", "Python 93 passed（独立源码环境）", "全新虚拟环境、解压源码；API、等时圈、盲区、安全与错误边界"],
        ["前端状态测试", "9 passed", "请求竞态、旧结果清除、回放参数、报告分母"],
        ["合成真值对比", "6 组 BFS 与 Dijkstra 点数一致", "2 个样例、3 组参数；不是实际社区准确率"],
        ["历史回放", "40 个录制请求，0 次回放网络请求", "无需 AK；录制于 2026-10-13，明确保留时点"],
        ["POI 外部资料核对", "3 类正向样本获支持，1 个误命中排除", "政府公开资料交叉核对；不是实地或营业状态核验"],
        ["路线网页对照", "20 条完成，阈值判断 17/20 一致", "历史 API 与当前网页同平台对照，3 条分歧保留；非实地准确率"],
        ["真实百度验收", "2026-10-13：8 次调用，0 失败", "1 地理编码 + 4 POI + 3 步行路线；报告保存在本地运行目录"],
        ["路线审计", "20 / 20 自动一致性通过", "绕行系数和步速范围均记录，人工目测仍需回填"],
        ["复测边界", "2026-10-13：白名单修正后恢复", "排查国内外出口分流；保持 IPv4 与服务端 IP 限制"],
    ]
    story.append(make_table(evidence, [34 * mm, 53 * mm, 83 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(p("证据原则：真实成功记录和当前失败边界都保留；一次 API 调用不被包装成真实社区治理成效。", body))

    story += section_heading("5. 技术结构")
    architecture = [
        ["层", "职责", "边界"],
        ["合成算法层", "NetworkX 路网最短路径、覆盖率、候选设施增益", "米制平面样例，不代表真实社区"],
        ["百度适配层", "服务端 AK、V3/V2 POI、路线、批量算路、缓存和限流", "AK 不进入浏览器；接口失败不等于没有设施"],
        ["空间采样层", "等时圈网格采样、边界加密、1 公里专项网格", "输出采样事实，不拟合连续边界"],
        ["产品交互层", "实时地图、设施表、盲区统计、候选点、导出", "真实与合成模式明确分离"],
    ]
    story.append(make_table(architecture, [31 * mm, 93 * mm, 46 * mm]))

    story += section_heading("6. 关键口径")
    caveats = [
        ["输出", "明确含义"],
        ["等时圈比例", "均匀网格采样点的可达比例，不是人口覆盖率、土地面积或居民数量"],
        ["1 公里盲区", "中心周边 1,000 米内的 250 米等权网格专项检查，独立于步行等时圈"],
        ["unknown", "POI 查询失败、路线缺耗时或其他证据不足时使用；不会被当成“没有设施”"],
        ["规划参考点", "从已知缺口样点做贪心覆盖得到的参考位置，不代表地块适宜性、容量、成本或建设收益"],
        ["AI 解释", "默认 rule-only；只引用已有计算事实，不补造用户反馈、设施和效果"],
    ]
    story.append(make_table(caveats, [42 * mm, 128 * mm]))

    story.append(PageBreak())
    story += section_heading("7. 现场演示脚本")
    demo = [
        ["时间", "动作", "要说清楚"],
        ["0:00 - 1:00", "离线样例：桥梁绕行、直线与路网差异、候选设施前后重算", "先证明算法可复现，断网也能演示"],
        ["1:00 - 2:20", "实时页：真实步行等时圈、设施路线和未知点", "百度耗时与合成固定步速分开，不混口径"],
        ["2:20 - 3:30", "1 公里专项：菜市场、药店、小学统计和地图缺口", "查询失败显示未知，不直接下结论"],
        ["3:30 - 4:20", "规划候选点：按类别查看覆盖增益", "这是采样启发式，不是建设选址"],
        ["4:20 - 5:00", "打开报告和证据编号，说明限流、失败回退、安全边界", "用证据组织故事，不用故事替代证据"],
    ]
    story.append(make_table(demo, [28 * mm, 74 * mm, 68 * mm]))

    story += section_heading("8. 交付前剩余事项")
    remaining = [
        ["优先级", "事项", "交付标准"],
        ["P1", "路线对照中的 3 条阈值分歧复核", "20 条网页对照已完成，仍需核对实际通行与出入口"],
        ["P0", "团队署名、公开地址与报名材料统一", "项目介绍与 约 4 分钟截图讲解视频已准备，提交前核对署名"],
        ["P0", "远端仓库安全检查和发布", "无 .env、AK、.runtime、真实原始响应和个人信息"],
        ["P1", "Docker 镜像构建与启动验收", "已用本机 Python 3.12 基础镜像完成 8001 烟测；Docker Hub 首次拉取需网络可用"],
        ["P1", "用户访谈或试用反馈", "只能记录真实受访者角色和授权反馈，不虚构客户"],
    ]
    story.append(make_table(remaining, [22 * mm, 72 * mm, 76 * mm]))
    story.append(Spacer(1, 4 * mm))
    story.append(rich("<font color='#7a5b12'><b>交付判断</b></font>　功能主线已冻结。已补齐无 AK 回放、来源标识、中心坐标和缺口证据边界；后续优先独立核验及公开发布。", body))

    story += section_heading("9. 评委快速复现")
    story.append(make_table([
        ["场景", "操作与说明"],
        ["Windows 首次启动", "powershell -ExecutionPolicy Bypass -File .\\start.ps1；首次自动创建环境并安装依赖"],
        ["Linux / macOS", "bash start.sh；默认合成模式不读取密钥、不请求地图"],
        ["真值核对", "python scripts/verify_release.py；报告写入 output/verification"],
        ["私有历史回放", "start.ps1 -Mode replay；录制数据只在本地，不随公共源码分发"],
    ], [38 * mm, 132 * mm]))

    story += [
        Spacer(1, 5 * mm),
        HRFlowable(width="100%", thickness=0.7, color=LINE, spaceAfter=3 * mm),
        p("公开仓库与团队署名：由参赛团队在提交前确认填写。", small),
        p("代码许可证：MIT；真实接口响应仅用于本地验收，不随公开仓库分发。", small),
    ]
    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = BriefDocTemplate(str(OUTPUT), title="邻里圈项目介绍", author="邻里圈项目")
    document.build(build_story())
    print(OUTPUT)


if __name__ == "__main__":
    main()

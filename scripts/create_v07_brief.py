"""Versioned three-page brief with a vector architecture diagram."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, PageBreak, Paragraph, Spacer

from create_project_brief import (
    FONT,
    BriefDocTemplate,
    body,
    small,
    title,
    subtitle,
    p,
    rich,
    make_table,
    section_heading,
    INK,
    GREEN,
    LINE,
    PALE_GREEN,
)

ROOT = Path(__file__).resolve().parents[1]


class Architecture(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = 168 * mm, 76 * mm

    def draw(self):
        c = self.canv
        c.setFont(FONT, 9)

        def node(x, y, first, second):
            c.setFillColor(PALE_GREEN)
            c.setStrokeColor(LINE)
            c.roundRect(x, y, 38 * mm, 22 * mm, 3 * mm, fill=1, stroke=1)
            c.setFillColor(INK)
            c.drawCentredString(x + 19 * mm, y + 13 * mm, first)
            c.setFont(FONT, 8)
            c.drawCentredString(x + 19 * mm, y + 6 * mm, second)
            c.setFont(FONT, 9)

        def arrow(x1, y1, x2, y2):
            c.setStrokeColor(GREEN)
            c.setLineWidth(1)
            c.line(x1, y1, x2, y2)
            if x1 != x2:
                c.line(x2 - 3, y2 + 2, x2, y2)
                c.line(x2 - 3, y2 - 2, x2, y2)
            else:
                c.line(x2 - 2, y2 + 3, x2, y2)
                c.line(x2 + 2, y2 + 3, x2, y2)

        xs = [0, 43 * mm, 86 * mm, 129 * mm]
        for x, labels in zip(
            xs,
            [
                ("Web工作台", "参数 / 结论 / 报告"),
                ("智能体任务", "校验 / 工具 / 预算"),
                ("空间计算", "测时 / 缺口 / 证据"),
                ("百度Web服务", "POI / 路线矩阵"),
            ],
        ):
            node(x, 47 * mm, *labels)
        for x in xs[:-1]:
            arrow(x + 38 * mm, 58 * mm, x + 42 * mm, 58 * mm)
        for x, labels in zip(
            xs[:3],
            [
                ("网页道路地图", "独立浏览器AK"),
                ("用户模型服务", "选择工具 / 引用事实"),
                ("合成 / 历史回放", "与当前数据分别标明"),
            ],
        ):
            node(x, 7 * mm, *labels)
            arrow(x + 19 * mm, 47 * mm, x + 19 * mm, 30 * mm)
        c.setFillColor(colors.HexColor("#526260"))
        c.setFont(FONT, 8)
        c.drawString(0, 0, "计算结果携带来源、时点与证据编号返回界面；模型不自行产生数值。")


def main():
    body.textColor = small.textColor = INK
    output = ROOT / "output/pdf/邻里圈-v0.7-项目介绍.pdf"
    screenshot = ROOT / "assets/screenshots/workspace-v07.png"
    if not screenshot.is_file():
        raise SystemExit("请先保存新版实际工作台截图")
    story = [
        Spacer(1, 3 * mm),
        Paragraph("邻里圈", title),
        Paragraph("15分钟生活圈智能体检与规划助手", subtitle),
        p("2026上海开源软件应用创新大赛 · 开源AI工具赛道 · 百度地图企业命题", body),
        p("版本0.7.0 · 2026-10-14 · 团队署名待填写", small),
    ]
    story += section_heading("1. 从服务缺口到可核验的改善参考")
    story += [
        p(
            "面向街道与社区调研，把设施、真实步行测时、1公里专项缺口和候选复算连成同一条证据链。AI理解需求并选择工具，程序负责数值计算；未知与待复核不被隐藏。",
            body,
        ),
        Image(str(screenshot), width=168 * mm, height=94 * mm, kind="proportional"),
        p("实际工作台合成案例：合成数据用于复现算法，不对应真实上海社区。", small),
    ]
    story += section_heading("2. 可复现的产品闭环")
    story += [
        p(
            "输入地点、类别和时间 → 工具计算并引用证据 → 看设施与缺口 → 比较候选 → 固定样点情景 → 核验备注与报告。支持停止、重试与本机历史快照。",
            body,
        ),
        p(
            "滨河合成养老案例：原覆盖44.8%、缺口79/143；首个候选单独重算覆盖92.3%，独立新增68点，剩余11。第二候选独立新增66点，两个互斥方案不能直接累加。",
            body,
        ),
        rich(
            '<link href="https://github.com/wyb123465/neighborhood-circle" color="#197257">公开代码：github.com/wyb123465/neighborhood-circle</link>',
            small,
        ),
        PageBreak(),
    ]
    story += section_heading("3. 技术架构")
    story += [
        Architecture(),
        Spacer(1, 3 * mm),
        p(
            "FastAPI提供受约束任务和公开资源；NetworkX处理合成图；百度Web服务提供真实设施与步行测时；浏览器端地图使用独立AK。默认离线模式不读密钥、不加载外部SDK。",
            body,
        ),
    ]
    story += section_heading("4. 计算策略与差异点")
    story += [
        make_table(
            [
                ["环节", "实现与口径"],
                [
                    "等时圈",
                    "按真实原始秒数判别，粗网格定位、边界预算内加密；网格表示样点邻域估计，保留未知和近阈值。",
                ],
                [
                    "1公里专项",
                    "菜市场、药店、小学采用直线口径；UID去重、子类排除、分页和检索范围检查，未知不计为缺口。",
                ],
                [
                    "智能体",
                    "模型选择体检、读证据、候选重算工具；结论只引用存在的事实编号，受轮次、时间和地图预算约束。",
                ],
                [
                    "情景与方案",
                    "同样点、同范围复用秒数比较10/15/20分钟，0新增地图请求；候选独立与组合边际增益分开。",
                ],
                [
                    "工程",
                    "矩阵拆批、加权限速、缓存、排队后再安排发送；超时/失败保留未知。本机备注独立于接口结果。",
                ],
            ],
            [29 * mm, 139 * mm],
        ),
        Spacer(1, 3 * mm),
        p(
            "路线采样不恢复精确连通边界；中心到设施比例不是居民覆盖率。候选点不证明地块可建、容量或建设收益。真实地图接入代码已加入，实际道路展示还需浏览器AK及SDK联调确认。",
            body,
        ),
        PageBreak(),
    ]
    story += section_heading("5. 验证证据与现实边界")
    story += [
        make_table(
            [
                ["证据", "结果 / 限制"],
                [
                    "工程检查",
                    "独立源码123项Python测试全部通过、无跳过；21项前端测试通过。源码扫描、HTTP启动与无密钥路径均通过。",
                ],
                ["真实AI链路", "10月14日既有5条真实模型场景通过，其中45次当前百度请求；不把Mock当真实联调。"],
                [
                    "新增缓存基准",
                    "同输入8处设施：冷查询14.05秒/15次请求，热查询3.6毫秒/0次新请求，证据编号一致。仅为单次本机缓存对照。",
                ],
                ["路线对照", "20条同平台网页对照，17条阈值一致、3条分歧保留；不称实地准确率。"],
                ["POI核验", "3个政府资料正向类别样本、1个培训误命中排除；营业状态、入口和缺口仍需独立核验。"],
                [
                    "地理呈现",
                    "专用浏览器AK、BD-09网格/设施/灰格叠加及失败示意已实现；实际SDK验收状态见当前验收文档。",
                ],
            ],
            [32 * mm, 136 * mm],
        ),
        Spacer(1, 3 * mm),
    ]
    story += section_heading("6. 开源交付与下一步")
    story += [
        p(
            "MIT源码、依赖约束、Windows/Linux启动脚本和Docker。GitHub Actions检查Python/前端格式、测试、合成真值与凭证安全。贡献流程、维护职责、安全反馈和版本计划公开；早期单维护者阶段，不虚构社区或机构支持。",
            body,
        ),
        p(
            "完整社区验证方案与空白记录模板随源码提供。仍需团队确认具体社区归属、补充独立入口/营业/盲区参照及真实署名；上传视频取得可访问链接，再按报名确认邮件提交。",
            body,
        ),
        p(
            "介绍视频为实际界面截图分步讲解，配合合成中文解说与字幕，不是连续录屏。模型、实时地图与历史回放依赖分别标明；公开源码不含密钥、原始私有响应或其他参赛项目。",
            body,
        ),
        p(
            "不报告未经独立真值验证的现实准确率、用户人数、落地收益或政府合作。命题与官网通用评分同时覆盖，最终规则以组委会解释为准。",
            small,
        ),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    BriefDocTemplate(str(output), title="邻里圈0.7项目介绍", author="邻里圈项目团队（署名待填写）").build(
        story
    )
    print(output)


if __name__ == "__main__":
    main()

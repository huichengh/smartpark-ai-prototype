#!/usr/bin/env python
"""把 demo_shots.json 录下的截图打包成一个自包含的 HTML 演示页。

为什么是自包含：交付给用户的是一个单文件，图片以 base64 内联，换电脑/换目录都能打开，
不依赖任何外部资源或本地服务（符合"零外链"的交付习惯）。

用法：
    python build_demo_html.py            # 读 docs/demo/*.png → docs/demo/演示.html
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # 2026-09-17-00-03-35
DEMO_DIR = ROOT / "docs" / "demo"
OUT = DEMO_DIR / "园智汇-平台演示.html"

# (图片, 幕次, 标题, 讲解要点[], 可核对数字[(说明, 值)])
SECTIONS: list[tuple[str, str, str, list[str], list[tuple[str, str]]]] = [
    ("01_login.png", "开场", "登录",
     ["多园区多租户平台，账号决定数据范围：集团管理员看全域，园区负责人只看本园区，"
      "企业管理员只看自己企业。",
      "后端 RBAC：15 个角色 × 9 个动作 × 22 个模块 = 198 个权限点。"],
     [("演示账号", "admin / Park@2026"), ("权限点", "198")]),

    ("02_dashboard.png", "第一幕 · 集团管理员", "数据驾驶舱 —— 全园一屏",
     ["18 项核心 KPI，全部由后端实时聚合，点开任一指标可看计算口径（basis）。",
      "切换右上角「全部园区 / 单园区」，所有 KPI 与图表同步重算 —— 数据范围在数据库侧过滤，"
      "不是前端筛选。"],
     [("园区 / 企业", "4 个 / 344 家"), ("空间出租率", "44.06%"),
      ("企业入驻率", "46.28%"), ("招商线索", "573 条")]),

    ("03_twin.png", "第一幕", "园区数字孪生",
     ["2.5D 等轴测楼栋视图，楼栋颜色由后端 status_legend 下发，前端不维护状态色表。",
      "点楼栋可下钻到楼层看板的出租状态。"],
     [("楼栋状态图例", "运营良好 / 正常 / 招商压力"), ("布局", "等轴测 SVG 2.5D")]),

    ("04_space.png", "第一幕", "空间资产管理",
     ["楼栋、空间单元、楼层出租状态三级贯通，面积口径逐项注明来源字段。"],
     [("楼栋 / 空间单元", "22 栋 / 1457 个"), ("可租面积", "538,226.82 ㎡"),
      ("已租面积", "237,138.17 ㎡")]),

    ("05_ai.png", "第一幕", "AI 智能体 —— 平台的大脑",
     ["问「本月园区经营情况如何？有哪些风险需要关注？」：主 Agent 先做意图路由，"
      "再派给经营分析AI，跨 7 个模块取数后给出结论。",
      "输出严格八段式：结论 / 关键数据 / 原因分析 / 建议措施 / 影响范围 / 风险 / 责任部门 / 决策状态，"
      "并附证据链（引用了哪张表、多少条记录）。",
      "权限三级：L1 直接回答、L2 给建议、L3 高影响动作只能生成审批请求 —— AI 不做任何写操作。"],
     [("子智能体 / 工具", "11 个 / 23 个"), ("识别出的优先问题", "8 项"),
      ("最高优先级", "逾期欠费 25,366,382 元")]),

    ("06_project.png", "第一幕", "项目管理中心 —— 项目详情",
     ["WBS 分解、CPM 关键路径、挣值分析、风险矩阵同页切换。",
      "瀑布式项目切到「敏捷」视图会返回业务提示而不是报错，这是刻意的产品化处理。"],
     [("关键路径", "161 天"), ("CPI", "0.998"), ("EAC", "4,609,218.44 元")]),

    ("07_approval.png", "第一幕", "审批中心",
     ["多级审批流转：AI 可发起、不可代为决策，每个决策动作都记录审批人与意见。",
      "「我的待办」数量由后端按当前账号角色实时统计。"],
     [("待办", "67 张"), ("滞留超 3 天", "64 张")]),

    ("08_safety.png", "第二幕 · 运营与安全", "安全管理",
     ["安全指数是 100 分制扣减模型，扣减项与数量在页面上逐条列明，可完整回溯。",
      "隐患是台账明细（502 条），按条扣分会让指数恒为 0，所以只作为独立指标呈现，不参与扣分。"],
     [("安全指数", "97.0 分（状态良好）"), ("事件 / 隐患", "39 起 / 502 项"),
      ("闭环率", "94.9%")]),

    ("09_operations.png", "第二幕", "物业运维",
     ["工单受理、SLA 超时、设备台账与维保预警；完成率 = 已闭环（CLOSED/RATED）÷ 工单总数。"],
     [("工单总量", "1400 单"), ("完成率", "81.4%"), ("超时率", "18.43%"),
      ("平均处理时长", "8.6 h")]),

    ("10_contracts.png", "第二幕", "合同管理",
     ["到期预警按 30/31-60/61-90/90 天以上分档，在险年租金与在险面积同步给出。"],
     [("合同总数 / 生效中", "249 份 / 109 份"), ("90 天内到期", "39 份"),
      ("在险年租金", "2495.9 万元")]),

    ("11_audit.png", "第三幕 · 治理", "日志审计",
     ["每一次业务写操作都留痕：操作人、模块、动作、变更前后值、来源与结果，支持按资源追溯。",
      "登录登出、AI 调用、审批决策全部计入。"],
     [("日志总数", "2722 条"), ("高风险操作", "91 次"), ("AI 调用", "280 次")]),
]

HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>园智汇 · 平台演示</title>
<style>
  :root{--bg:#07111F;--panel:#0D1B2A;--line:rgba(255,255,255,.10);--txt:#E6EDF7;
        --dim:#8CA3BF;--brand:#2F80ED;--ai:#7B61FF;--ok:#22C55E;--warn:#F59E0B}
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(160deg,#07111F,#0A1628 45%,#0D1B2A);color:var(--txt);
       font:15px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
  .wrap{max-width:1180px;margin:0 auto;padding:40px 22px 70px}
  header{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:8px}
  h1{margin:0 0 6px;font-size:30px;letter-spacing:.5px}
  h1 span{background:linear-gradient(90deg,var(--brand),var(--ai));-webkit-background-clip:text;
          background-clip:text;color:transparent}
  .sub{color:var(--dim);font-size:14px}
  .meta{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
  .chip{border:1px solid var(--line);background:rgba(255,255,255,.04);border-radius:999px;
        padding:4px 12px;font-size:12.5px;color:var(--dim)}
  .chip b{color:var(--txt);font-weight:600}
  section{margin-top:34px;background:rgba(255,255,255,.028);border:1px solid var(--line);
          border-radius:14px;overflow:hidden;backdrop-filter:blur(15px)}
  .hd{display:flex;align-items:baseline;gap:12px;padding:16px 20px 10px;flex-wrap:wrap}
  .act{font-size:12px;color:#fff;background:linear-gradient(90deg,var(--brand),var(--ai));
       border-radius:999px;padding:3px 11px;white-space:nowrap}
  h2{margin:0;font-size:19px}
  .body{padding:0 20px 18px}
  ul{margin:8px 0 12px;padding-left:20px}
  li{margin:5px 0;color:#CBD9EA}
  .kv{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 14px}
  .kv div{border:1px solid var(--line);border-radius:9px;padding:7px 12px;background:rgba(255,255,255,.03)}
  .kv i{display:block;font-style:normal;font-size:11.5px;color:var(--dim)}
  .kv b{font-size:15px;color:#fff}
  img{display:block;width:100%;height:auto;border-radius:10px;border:1px solid var(--line)}
  .cap{font-size:12px;color:var(--dim);margin-top:7px;text-align:right}
  footer{margin-top:40px;border-top:1px solid var(--line);padding-top:20px;color:var(--dim);font-size:13px}
  code{background:rgba(255,255,255,.07);border-radius:5px;padding:1.5px 6px;font-size:12.5px}
  .note{border-left:3px solid var(--warn);background:rgba(245,158,11,.08);border-radius:0 8px 8px 0;
        padding:10px 14px;margin:12px 0 0;font-size:13px;color:#F3D9A4}
</style>
</head>
<body><div class="wrap">
<header>
  <h1><span>园智汇</span> · AI 产业园区智慧运营管理平台 —— 平台演示</h1>
  <div class="sub">按演示脚本录制的关键动线截图。所有页面均标注「演示数据」，全部数值由后端实时计算，可追溯到数据表与计算口径。</div>
  <div class="meta">
    <span class="chip">账号 <b>admin / Park@2026</b></span>
    <span class="chip">访问地址 <b>http://127.0.0.1:8010</b>（单端口）</span>
    <span class="chip">规模 <b>129 路径 · 65 表 · 22 页 · 11 子智能体</b></span>
    <span class="chip">验收 <b>21/21 页通过 · 0 JS 异常</b></span>
  </div>
</header>
"""

TAIL = """
<footer>
  <p><b>自己跑一遍：</b><br>
  <code>cd backend &amp;&amp; python run.py</code>（首次先 <code>python run.py --seed</code>）→
  浏览器打开 <code>http://127.0.0.1:8010</code>。前端产物已由后端托管，无需另起服务。</p>
  <p><b>说明：</b>平台为多租户演示环境，数据为模拟生成的「演示数据」；AI 不执行任何写操作，
  高影响动作一律进入审批中心由人工决策。</p>
</footer>
</div></body></html>
"""


def data_uri(p: Path) -> str:
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def main() -> int:
    parts = [HEAD]
    missing = []
    for fname, act, title, points, kvs in SECTIONS:
        f = DEMO_DIR / fname
        if not f.is_file():
            missing.append(fname)
            continue
        kv_html = "".join(f"<div><i>{k}</i><b>{v}</b></div>" for k, v in kvs)
        pts = "".join(f"<li>{p}</li>" for p in points)
        parts.append(
            f'<section>\n<div class="hd"><span class="act">{act}</span><h2>{title}</h2></div>\n'
            f'<div class="body"><ul>{pts}</ul><div class="kv">{kv_html}</div>\n'
            f'<img src="{data_uri(f)}" alt="{title}">\n'
            f'<div class="cap">{fname}</div></div>\n</section>\n'
        )
    if missing:
        parts.append('<section><div class="hd"><h2>缺失截图</h2></div><div class="body">'
                     f'<p>{", ".join(missing)} 尚未生成，请先运行 demo 截图批次。</p></div></section>')
    parts.append(TAIL)

    html = "".join(parts)
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT}（{len(html) / 1024 / 1024:.2f} MB，"
          f"{len(SECTIONS) - len(missing)}/{len(SECTIONS)} 张截图）")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

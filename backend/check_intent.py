"""意图路由回归校验：把「问 A 却答 B」的误判固化成用例。

只测纯函数 classify_intent（不连库、不起服务），因此可以进 CI。

用法：
    python check_intent.py            # 全部用例
    python check_intent.py -v         # 打印每个用例的完整得分明细
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.agent.orchestrator import SUB_AGENTS, classify_intent  # noqa: E402

# (问题, 期望主意图, 说明)
CASES: list[tuple[str, str, str]] = [
    # ---- 经营概览（本轮误判的核心场景）----
    ("本月园区经营情况如何？有哪些风险需要关注？", "operations", "经营+风险 → 经营分析，不是项目"),
    ("园区整体经营情况怎么样", "operations", "整体经营"),
    ("给我一份园区经营概览", "operations", "经营概览"),
    ("本月经营月报", "operations", "经营月报"),
    ("目前园区有哪些需要优先处理的问题？", "operations", "综合问题扫描"),
    ("帮我做个综合诊断", "operations", "综合诊断"),
    ("驾驶舱里最重要的指标是什么", "operations", "驾驶舱"),
    ("园区现在有什么风险", "operations", "泛化风险 → 综合扫描，不是项目"),
    ("分析一下", "operations", "无业务对象的空泛提问 → 兜底"),
    ("最近怎么样", "operations", "无关键词 → 兜底"),

    # ---- 招商 ----
    ("招商线索转化率如何", "leasing", "招商"),
    ("有哪些客户意向比较强", "leasing", "客户/意向"),
    ("招商漏斗哪个环节流失最多", "leasing", "漏斗"),

    # ---- 项目（必须仍然进项目）----
    ("A栋改造项目现在进度如何", "project", "项目名+进度"),
    ("当前有哪些项目延期了", "project", "项目+延期"),
    ("项目关键路径上有哪些超期任务", "project", "关键路径"),
    ("帮我看看项目的里程碑完成情况", "project", "里程碑"),
    ("敏捷项目的 Sprint 情况", "project", "Sprint"),

    # ---- 财务 ----
    ("本月收缴率是多少", "finance", "收缴率"),
    ("欠费最多的企业是哪家", "finance", "欠费（不能因为「企业」二字跑到企业画像）"),
    ("欠费账龄分布怎么样", "finance", "账龄"),
    ("本月应收实收情况", "finance", "应收/实收"),

    # ---- 空间 ----
    ("园区出租率多少", "space", "出租率"),
    ("哪些空间空置超过 90 天", "space", "空置"),
    ("B 栋楼层的房源情况", "space", "楼栋/房源"),

    # ---- 合同 ----
    ("有哪些合同快到期了", "contract", "合同到期"),
    ("30 天内到期合同涉及多少年租金", "contract", "到期+租金（合同域）"),

    # ---- 物业 / 能源 / 安全 / 政策 / 企业 ----
    ("工单超时率是多少", "property", "工单"),
    ("报修单处理得及时吗", "property", "报修"),
    ("这个月用电量是多少", "energy", "用电"),
    ("有没有能耗异常需要核查", "energy", "能耗异常"),
    ("夜间用电占比高不高", "energy", "夜间用电"),
    ("安全指数多少分", "safety", "安全指数"),
    ("有多少重大安全隐患未闭环", "safety", "隐患"),
    ("消防安全检查情况", "safety", "消防"),
    ("有哪些政策我们可以申报", "policy", "政策"),
    ("高新技术企业补贴", "policy", "高企/补贴"),
    ("帮我查一下星海科技这家企业", "enterprise", "企业名+企业"),
    ("企业画像分析", "enterprise", "画像"),
    ("麻烦查一下智联科技有限公司的情况", "enterprise", "公司名+「公司」通用名词"),
    ("欠费最多的公司是哪家", "finance", "通用名词「公司」不能压过「欠费」"),
]


def main() -> int:
    verbose = "-v" in sys.argv
    ok = fail = 0
    failures: list[str] = []

    for question, expect, note in CASES:
        got = classify_intent(question)
        head = got[0]
        passed = head == expect
        if passed:
            ok += 1
        else:
            fail += 1
            failures.append(f"  ✗ 「{question}」\n      期望 {expect}（{SUB_AGENTS[expect]['name']}）"
                            f"  实际 {head}（{SUB_AGENTS[head]['name']}）  ← {note}")
        if verbose:
            detail = _detail(question)
            mark = "✓" if passed else "✗"
            print(f"{mark} {question}\n    expect={expect} got={head} all={got}\n    {detail}")

    print("=" * 72)
    print(f"意图路由校验：{ok} 通过 / {fail} 失败 / 共 {len(CASES)}")
    if failures:
        print("\n失败用例：")
        for f in failures:
            print(f)
    print("=" * 72)
    return 1 if fail else 0


def _detail(question: str) -> str:
    """打印每个子 Agent 的原始得分，便于定位是哪个关键词把意图带偏的。"""
    from app.agent.orchestrator import score_intents

    raw = score_intents(question)
    if not raw:
        return "（无命中）"
    return "  ".join(f"{k}={v:.2f}" for k, v in sorted(raw.items(), key=lambda x: -x[1]))


if __name__ == "__main__":
    raise SystemExit(main())

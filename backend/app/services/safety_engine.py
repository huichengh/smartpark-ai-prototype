"""安全指数单一数据源。

背景
    安全指数原先在三个地方各写了一遍公式：
      · app/services/dashboard_service.py（驾驶舱）
      · app/api/v1/operation.py          （安全页面 /operations/safety/summary）
      · app/agent/tools/__init__.py      （安全AI / 每日洞察）
    其中只有工具层额外加了「未闭环隐患 × 1」这一项。库里有 502 条隐患记录，
    于是 100 − 500 = 0，安全AI 一律回答"安全指数 0 分（形势严峻）"，
    与安全页面显示的 90+ 分直接冲突。

口径
    安全指数 = 100 − 未闭环重大/紧急×8 − 未闭环较大×4 − 未闭环一般×1.5 − 整改逾期×3
    隐患数量**不参与扣分**：隐患是台账明细（数百条量级），按条扣分会让指数恒为 0，
    失去指标意义。隐患以 hazard_total / hazard_open / hazard_overdue 独立指标呈现。

    本函数是所有调用方的唯一实现，扣分明细随结果一并返回，保证可完整回溯。
"""
from __future__ import annotations

from typing import Any, Iterable

BASE = 100.0
DEDUCT_CRITICAL = 8.0    # 未闭环重大/紧急事件
DEDUCT_MAJOR = 4.0       # 未闭环较大事件
DEDUCT_GENERAL = 1.5     # 未闭环一般事件
DEDUCT_OVERDUE = 3.0     # 整改逾期事件


def status_of(score: float) -> str:
    if score >= 90:
        return "状态良好"
    if score >= 75:
        return "需要关注"
    if score >= 60:
        return "存在风险"
    return "形势严峻"


def score_model(incidents: Iterable[Any]) -> tuple[float, str, dict[str, Any]]:
    """返回 (安全指数, 状态文案, 扣分明细)。

    入参只需具备 status / risk_level / is_overdue 三个属性的安全事件对象。
    """
    incs = list(incidents)
    open_incs = [i for i in incs if i.status != "CLOSED"]
    critical = [i for i in open_incs if i.risk_level in ("CRITICAL", "URGENT")]
    major = [i for i in open_incs if i.risk_level == "MAJOR"]
    general = [i for i in open_incs if i.risk_level == "GENERAL"]
    overdue = [i for i in incs if i.is_overdue]

    score = BASE
    score -= len(critical) * DEDUCT_CRITICAL
    score -= len(major) * DEDUCT_MAJOR
    score -= len(general) * DEDUCT_GENERAL
    score -= len(overdue) * DEDUCT_OVERDUE
    score = round(max(min(score, BASE), 0.0), 1)

    detail = {
        "base": BASE,
        "deductions": [
            {"item": "重大/紧急未闭环事件", "count": len(critical),
             "per": DEDUCT_CRITICAL, "total": round(len(critical) * DEDUCT_CRITICAL, 1)},
            {"item": "较大未闭环事件", "count": len(major),
             "per": DEDUCT_MAJOR, "total": round(len(major) * DEDUCT_MAJOR, 1)},
            {"item": "一般未闭环事件", "count": len(general),
             "per": DEDUCT_GENERAL, "total": round(len(general) * DEDUCT_GENERAL, 1)},
            {"item": "整改逾期", "count": len(overdue),
             "per": DEDUCT_OVERDUE, "total": round(len(overdue) * DEDUCT_OVERDUE, 1)},
        ],
        "final": score,
        "formula": (f"安全指数 = {BASE:g} − 未闭环重大/紧急×{DEDUCT_CRITICAL:g} "
                    f"− 未闭环较大×{DEDUCT_MAJOR:g} − 未闭环一般×{DEDUCT_GENERAL:g} "
                    f"− 整改逾期×{DEDUCT_OVERDUE:g}（隐患数量单独统计，不参与扣分）"),
        "note": "安全指数为 100 分制扣减模型，扣减项与数量均在此列明，可完整回溯",
    }
    return score, status_of(score), detail


def summary(incidents: Iterable[Any]) -> dict[str, Any]:
    """便捷封装：直接返回 {"safety_score", "safety_status", "score_model"}。"""
    score, status, detail = score_model(incidents)
    return {"safety_score": score, "safety_status": status, "score_model": detail}

"""续租风险规则引擎 —— 可解释、可纠错，不输出"退租概率"。

设计底线（来自提示词 03 与建议书 3.2）：

* **只产出规则标签，不产出统计概率**。没有带真实退租标签的数据做过时间外验证，
  任何"退租概率 80%"都是编的。所以结果里固定带
  `is_probability=false` 与 `probability_note`，前端必须原样展示。
* **每条信号都要能追溯**：给出表名 + 记录 id + 具体事实，让业务人员自己判断，
  而不是丢一个分数让人猜。
* **缺数据就说缺数据**：没有任何信号时返回 `UNKNOWN/证据不足`，
  不是"低风险"——两者含义完全不同，混起来等于假装没有盲区。
* **允许解除误报**：规则必然有误报，所以提供人工复核入口（见 API 层）。

评分只用于排序，不是概率。权重集中在此处，改权重等于改口径。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

LEVEL_HIGH = "HIGH"
LEVEL_MEDIUM = "MEDIUM"
LEVEL_LOW = "LOW"
LEVEL_UNKNOWN = "UNKNOWN"

LEVEL_LABELS = {
    LEVEL_HIGH: "高风险（待核实）",
    LEVEL_MEDIUM: "中风险（待核实）",
    LEVEL_LOW: "低风险",
    LEVEL_UNKNOWN: "证据不足",
}

#: 规则权重（同一指标只在这里定义一次）
WEIGHTS = {
    "days_left_30": 30,
    "days_left_60": 20,
    "days_left_90": 10,
    "arrears": 25,
    "arrears_max_bonus": 15,
    "open_high_priority_order": 10,
    "open_order_max": 20,
    "no_renewal_contact": 5,
}

#: 触发"到期关注"的天数阈值
EXPIRY_WINDOW_DAYS = 90
#: 工单回溯窗口
ORDER_LOOKBACK_DAYS = 90


@dataclass
class Signal:
    code: str
    label: str
    weight: int
    fact: str
    source: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "label": self.label, "weight": self.weight,
            "fact": self.fact, "source": self.source, "evidence": self.evidence,
        }


def _level_of(score: int, data_complete: bool) -> str:
    if not data_complete:
        return LEVEL_UNKNOWN
    if score >= 60:
        return LEVEL_HIGH
    if score >= 30:
        return LEVEL_MEDIUM
    return LEVEL_LOW


def evaluate(
    *,
    contract_id: int,
    contract_code: str,
    enterprise_id: int | None,
    enterprise_name: str | None,
    end_date: dt.date | None,
    today: dt.date,
    overdue_bills: list[dict[str, Any]] | None = None,
    open_orders: list[dict[str, Any]] | None = None,
    renewal_contact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """评估一份合同的续租风险。

    参数都是**已查好的字典**（不在引擎里查库），便于单测与金标准回归。
    overdue_bills: [{id, bill_code, amount, arrears, due_date, overdue_days}]
    open_orders:   [{id, order_code, title, priority, submit_at}]
    renewal_contact: {has_contact: bool, last_contact_at, note} 或 None（无记录）
    """
    overdue_bills = overdue_bills or []
    open_orders = open_orders or []
    signals: list[Signal] = []
    missing: list[str] = []

    # ---- 信号 1：距到期天数 ----
    days_left: int | None = None
    if end_date is None:
        missing.append("合同缺少到期日，无法判断到期紧迫度")
    else:
        days_left = (end_date - today).days
        if days_left < 0:
            signals.append(Signal(
                "expired", "合同已过期未处理", 40,
                f"到期日 {end_date} 已过 {-days_left} 天，仍处于未结状态",
                f"contracts#{contract_id}",
                [{"field": "end_date", "value": end_date.isoformat(), "days_left": days_left}],
            ))
        elif days_left <= 30:
            signals.append(Signal(
                "days_left_30", "30 天内到期", WEIGHTS["days_left_30"],
                f"距到期仅 {days_left} 天",
                f"contracts#{contract_id}",
                [{"field": "end_date", "value": end_date.isoformat(), "days_left": days_left}],
            ))
        elif days_left <= 60:
            signals.append(Signal(
                "days_left_60", "60 天内到期", WEIGHTS["days_left_60"],
                f"距到期 {days_left} 天", f"contracts#{contract_id}",
                [{"field": "end_date", "value": end_date.isoformat(), "days_left": days_left}],
            ))
        elif days_left <= EXPIRY_WINDOW_DAYS:
            signals.append(Signal(
                "days_left_90", "90 天内到期", WEIGHTS["days_left_90"],
                f"距到期 {days_left} 天", f"contracts#{contract_id}",
                [{"field": "end_date", "value": end_date.isoformat(), "days_left": days_left}],
            ))

    # ---- 信号 2：账单逾期 ----
    if overdue_bills:
        total_arrears = sum((b.get("arrears") or 0) for b in overdue_bills)
        bonus = min(WEIGHTS["arrears_max_bonus"], len(overdue_bills) * 5)
        signals.append(Signal(
            "arrears", "存在逾期未缴账单", WEIGHTS["arrears"] + bonus,
            f"{len(overdue_bills)} 笔账单逾期，欠费合计 {total_arrears:,.2f} 元",
            "finance.bills",
            [{"bill_code": b.get("bill_code"), "arrears": b.get("arrears"),
              "overdue_days": b.get("overdue_days"), "due_date": b.get("due_date")}
             for b in overdue_bills[:5]],
        ))

    # ---- 信号 3：近 90 天未闭环的高优先级工单 ----
    if open_orders:
        bonus = min(WEIGHTS["open_order_max"], len(open_orders) * WEIGHTS["open_high_priority_order"])
        signals.append(Signal(
            "open_orders", f"近 {ORDER_LOOKBACK_DAYS} 天高优先级工单未闭环", bonus,
            f"{len(open_orders)} 单未闭环，涉及服务响应问题",
            "operation.work_orders",
            [{"order_code": o.get("order_code"), "title": o.get("title"),
              "priority": o.get("priority"), "submit_at": o.get("submit_at")}
             for o in open_orders[:5]],
        ))

    # ---- 信号 4：续租意向记录 ----
    if renewal_contact is None:
        missing.append("系统内无续租沟通记录（不代表客户没有沟通，需线下核实）")
    elif not renewal_contact.get("has_contact"):
        signals.append(Signal(
            "no_renewal_contact", "到期前尚未建立续租接触", WEIGHTS["no_renewal_contact"],
            "系统内无到期前 90 天的有效联系记录",
            "contracts.renew_intent",
            [{"last_contact_at": renewal_contact.get("last_contact_at")}],
        ))

    score = sum(s.weight for s in signals)
    data_complete = days_left is not None
    level = _level_of(score, data_complete)

    # 有数据但一个信号都没有 → 低风险；缺关键数据 → 证据不足
    if data_complete and not signals:
        level = LEVEL_LOW

    return {
        "contract_id": contract_id,
        "contract_code": contract_code,
        "enterprise_id": enterprise_id,
        "enterprise_name": enterprise_name,
        "end_date": end_date.isoformat() if end_date else None,
        "days_left": days_left,
        "level": level,
        "level_label": LEVEL_LABELS[level],
        "score": score,
        "signals": [s.to_dict() for s in signals],
        "signal_count": len(signals),
        "missing_data": missing,
        # —— 这两项必须随结果返回并原样展示，防止被当成概率 ——
        "is_probability": False,
        "probability_note": "这是规则标签，不是经校准的退租概率；未使用任何统计模型或历史标签训练。",
        "rule_version": "renewal-rules-v1",
        "evaluated_at": today.isoformat(),
        "data_label": "演示数据",
    }


def sort_key(item: dict[str, Any]) -> tuple:
    """排序：先按等级，再按分数，再按剩余天数（越近越前）。"""
    order = {LEVEL_HIGH: 0, LEVEL_MEDIUM: 1, LEVEL_LOW: 2, LEVEL_UNKNOWN: 3}
    return (order.get(item.get("level"), 9), -int(item.get("score") or 0),
            item.get("days_left") if item.get("days_left") is not None else 9999)

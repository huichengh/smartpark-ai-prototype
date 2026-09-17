"""物业运维指标单一数据源（工单）。

背景
    /operation/work-orders/stats/by-type 只返回 by_type / by_priority / trend / total，
    而 Operations 页面按 s.open / s.closed / s.completion_rate / s.timeout_count /
    s.timeout_rate / s.avg_handle_hours / s.avg_rating 读取 KPI。
    键名对不上 → 页面上「未闭环 0 单、完成率 —%、平均处理时长 —h」，
    而同一批数据经 AI 工具算出来是「完成率 81.36%、超时 258 单」。
    两处口径与字段都对不齐，指标自然对不上。

口径（唯一实现，接口与 AI 工具共用）
    已闭环 = status ∈ (CLOSED, RATED)
    未闭环 = 其余状态
    完成率 = 已闭环 ÷ 工单总数
    超时   = is_timeout 为真的工单
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

CLOSED_STATUSES: tuple[str, ...] = ("CLOSED", "RATED")
PRIORITY_ORDER: tuple[str, ...] = ("URGENT", "HIGH", "MEDIUM", "LOW")


def _shift_month(d: dt.date, n: int) -> dt.date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, 1)


def _avg(xs: list[float], digits: int = 1) -> float | None:
    return round(sum(xs) / len(xs), digits) if xs else None


def work_order_stats(orders: Iterable[Any], trend_months: int = 12) -> dict[str, Any]:
    """工单统计：聚合指标 + 按类型 / 优先级 / 月度分布。

    返回的 by_type 为**列表**（图表直接消费），by_type_map 为**字典**（按类型取用），
    两者同源，避免调用方各自再算一遍导致口径漂移。
    """
    rows = list(orders)
    total = len(rows)
    closed = [o for o in rows if o.status in CLOSED_STATUSES]
    timeout = [o for o in rows if o.is_timeout]

    types = {o.order_type for o in rows}
    by_type = [
        {
            "name": k,
            "total": len([o for o in rows if o.order_type == k]),
            "closed": len([o for o in rows if o.order_type == k and o.status in CLOSED_STATUSES]),
            "open": len([o for o in rows if o.order_type == k and o.status not in CLOSED_STATUSES]),
            "timeout": len([o for o in rows if o.order_type == k and o.is_timeout]),
        }
        for k in types
    ]
    by_type.sort(key=lambda x: -x["total"])

    by_type_map: dict[str, dict[str, int]] = {
        x["name"]: {"total": x["total"], "closed": x["closed"], "timeout": x["timeout"]}
        for x in by_type
    }

    by_priority = [
        {
            "name": k,
            "total": len([o for o in rows if o.priority == k]),
            "timeout": len([o for o in rows if o.priority == k and o.is_timeout]),
            "open": len([o for o in rows if o.priority == k and o.status not in CLOSED_STATUSES]),
        }
        for k in PRIORITY_ORDER
    ]

    m_start = dt.date.today().replace(day=1)
    trend = []
    for ms in [_shift_month(m_start, -i) for i in range(trend_months - 1, -1, -1)]:
        me = _shift_month(ms, 1)
        mo = [o for o in rows if o.submit_at and ms <= o.submit_at.date() < me]
        trend.append({
            "month": f"{ms.year}-{ms.month:02d}",
            "total": len(mo),
            "closed": len([o for o in mo if o.status in CLOSED_STATUSES]),
            "timeout": len([o for o in mo if o.is_timeout]),
        })

    ratings = [o.rating for o in rows if o.rating]
    return {
        "total": total,
        "open": total - len(closed),
        "closed": len(closed),
        "completion_rate": round(len(closed) / total * 100, 2) if total else 0.0,
        "timeout_count": len(timeout),
        "timeout_rate": round(len(timeout) / total * 100, 2) if total else 0.0,
        "avg_response_minutes": _avg([o.response_minutes for o in rows if o.response_minutes]),
        "avg_handle_hours": _avg([o.handle_hours for o in rows if o.handle_hours]),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "rated_count": len(ratings),
        "by_type": by_type,
        "by_type_map": by_type_map,
        "by_priority": by_priority,
        "trend": trend,
        "closed_statuses": list(CLOSED_STATUSES),
    }

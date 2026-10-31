"""经营决策的服务层：把「取数 + 口径」从路由里抽出来，供 API 与 Agent 工具共用。

为什么必须抽出来：项目已经吃过"同一指标多份实现"的亏（合同到期曾出现 37/39 两个值，
见 docs/测试日记.md）。续租风险的取数口径（哪些合同进入窗口、逾期怎么算、工单回溯多久）
如果 API 和 Agent 各写一遍，迟早会分叉——而 Agent 恰恰是答辩现场最容易被追问的地方。

此处不做鉴权判断，调用方须先 `auth.require(...)` 并传入已鉴权的 AuthContext。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthContext
from app.models import Bill, Contract, OperatingRiskReview, Space, WorkOrder
from app.services import renewal_risk_engine as risk_engine


def _scope_parks(auth: AuthContext, park_id: int | None) -> list[int] | None:
    vis = auth.visible_park_ids()
    if park_id:
        return [park_id] if vis is None or park_id in vis else []
    return vis


def renewal_risks(db: Session, auth: AuthContext, park_id: int | None = None,
                  window_days: int = 90, level: str | None = None) -> dict[str, Any]:
    """续租风险待核实清单（规则 + 证据链）。API 与 Agent 共用此实现。"""
    today = dt.date.today()
    horizon = today + dt.timedelta(days=window_days)
    parks = _scope_parks(auth, park_id)

    q = select(Contract).where(Contract.status.in_(("ACTIVE", "EXPIRING")))
    q = q.where(Contract.end_date.isnot(None), Contract.end_date <= horizon)
    if parks is not None:
        q = q.where(Contract.park_id.in_(parks)) if parks else q.where(Contract.id == -1)
    ent_clause = auth.enterprise_scope_clause(Contract.enterprise_id)
    if ent_clause is not None:
        q = q.where(ent_clause)
    contracts = list(db.scalars(q).all())

    ids = [c.id for c in contracts]
    bills_by_contract: dict[int, list[dict[str, Any]]] = {}
    if ids:
        bq = select(Bill).where(Bill.contract_id.in_(ids),
                                Bill.status.in_(("OVERDUE", "UNPAID")))
        for b in db.scalars(bq).all():
            if (b.overdue_days or 0) > 0 or b.status == "OVERDUE":
                bills_by_contract.setdefault(b.contract_id, []).append({
                    "id": b.id, "bill_code": b.bill_code, "arrears": b.arrears,
                    "overdue_days": b.overdue_days,
                    "due_date": b.due_date.isoformat() if b.due_date else None,
                })

    ent_ids = [c.enterprise_id for c in contracts if c.enterprise_id]
    orders_by_enterprise: dict[int, list[dict[str, Any]]] = {}
    if ent_ids:
        since = dt.datetime.now() - dt.timedelta(days=risk_engine.ORDER_LOOKBACK_DAYS)
        oq = select(WorkOrder).where(
            WorkOrder.enterprise_id.in_(ent_ids),
            WorkOrder.status.notin_(("CLOSED", "RATED")),
            WorkOrder.priority.in_(("HIGH", "URGENT")),
            WorkOrder.submit_at >= since,
        )
        for o in db.scalars(oq).all():
            orders_by_enterprise.setdefault(o.enterprise_id, []).append({
                "id": o.id, "order_code": o.order_code, "title": o.title,
                "priority": o.priority,
                "submit_at": o.submit_at.isoformat() if o.submit_at else None,
            })

    reviewed: dict[int, OperatingRiskReview] = {}
    for r in db.scalars(select(OperatingRiskReview)
                        .order_by(OperatingRiskReview.id.desc())).all():
        reviewed.setdefault(r.contract_id, r)

    results = []
    for c in contracts:
        item = risk_engine.evaluate(
            contract_id=c.id, contract_code=c.contract_code,
            enterprise_id=c.enterprise_id, enterprise_name=c.enterprise_name,
            end_date=c.end_date, today=today,
            overdue_bills=bills_by_contract.get(c.id),
            open_orders=orders_by_enterprise.get(c.enterprise_id or -1),
            renewal_contact=None,
        )
        rv = reviewed.get(c.id)
        item["review"] = ({"decision": rv.decision, "reason": rv.reason,
                           "decided_by_name": rv.decided_by_name,
                           "decided_at": rv.created_at.isoformat() if rv.created_at else None}
                          if rv else None)
        results.append(item)

    results.sort(key=risk_engine.sort_key)
    by_level: dict[str, int] = {}
    for item in results:
        by_level[item["level"]] = by_level.get(item["level"], 0) + 1

    if level:
        results = [x for x in results if x["level"] == level]

    return {
        "items": results,
        "total": len(results),
        "by_level": by_level,
        "window_days": window_days,
        "level_labels": risk_engine.LEVEL_LABELS,
        "is_probability": False,
        "rule_version": "renewal-rules-v1",
        "data_label": "演示数据",
        "disclaimer": "风险等级由公开规则给出，不是统计概率；每条结论均可回溯到原始记录。",
    }


def pick_vacant_space(db: Session, auth: AuthContext, park_id: int | None = None,
                      space_id: int | None = None) -> Space | None:
    """挑一个可推演空间：指定 id 优先，否则取空置面积最大的那个。"""
    if space_id:
        s = db.get(Space, space_id)
        if not s or not auth.can_access_park(s.park_id):
            return None
        return s
    parks = _scope_parks(auth, park_id)
    q = select(Space).where(Space.status != "RENTED")
    if parks is not None:
        q = q.where(Space.park_id.in_(parks)) if parks else q.where(Space.id == -1)
    rows = [s for s in db.scalars(q).all() if (s.rentable_area or 0) > 0]
    if not rows:
        return None
    rows.sort(key=lambda s: (s.rentable_area or 0), reverse=True)
    return rows[0]

"""财务收费：账单、收款、欠费催收、账龄分析。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.core.audit import write_audit
from app.core.enums import AGE_BUCKET_LABELS, AGE_BUCKETS
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Bill,
    Contract,
    Enterprise,
    Park,
    Payment,
    Project,
)
from app.schemas.common import BillPayRequest, paginate

router = APIRouter(prefix="/finance", tags=["财务收费"])

FEE_TYPES = {
    "RENT": "租金", "PROPERTY": "物业费", "ELECTRICITY": "电费", "WATER": "水费",
    "PARKING": "停车费", "SERVICE": "服务费", "MEETING_ROOM": "会议室费",
}
STATUS_NAMES = {"UNPAID": "未收", "PARTIAL": "部分收款", "PAID": "已收",
                "OVERDUE": "已逾期", "WAIVED": "已减免"}


def _month_range(d: dt.date) -> tuple[dt.date, dt.date]:
    start = d.replace(day=1)
    nxt = (start + dt.timedelta(days=32)).replace(day=1)
    return start, nxt


@router.get("/bills")
def list_bills(db: DbSession, auth: CurrentAuth,
               park_id: int | None = None, fee_type: str | None = None,
               status_: str | None = Query(None, alias="status"),
               enterprise_id: int | None = None, contract_id: int | None = None,
               period: str | None = None, age_bucket: str | None = None,
               keyword: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("finance", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Bill)
    if park_id:
        q = q.where(Bill.park_id == park_id)
    elif vis is not None:
        q = q.where(Bill.park_id.in_(vis)) if vis else q.where(Bill.id == -1)
    if auth.enterprise_id:
        q = q.where(Bill.enterprise_id == auth.enterprise_id)
    if fee_type:
        q = q.where(Bill.fee_type == fee_type)
    if status_:
        q = q.where(Bill.status == status_)
    if enterprise_id:
        q = q.where(Bill.enterprise_id == enterprise_id)
    if contract_id:
        q = q.where(Bill.contract_id == contract_id)
    if period:
        q = q.where(Bill.period == period)
    if age_bucket:
        q = q.where(Bill.age_bucket == age_bucket)
    if keyword:
        q = q.where(or_(Bill.bill_code.contains(keyword),
                        Bill.enterprise_name.contains(keyword)))
    bills = list(db.scalars(q.order_by(Bill.bill_date.desc(), Bill.id.desc())).all())
    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    items = [{
        "id": b.id, "bill_code": b.bill_code, "fee_type": b.fee_type,
        "fee_type_name": FEE_TYPES.get(b.fee_type, b.fee_type),
        "enterprise_id": b.enterprise_id, "enterprise_name": b.enterprise_name,
        "contract_id": b.contract_id, "park_id": b.park_id,
        "park_name": parks.get(b.park_id),
        "period": b.period, "bill_date": b.bill_date.isoformat() if b.bill_date else None,
        "due_date": b.due_date.isoformat() if b.due_date else None,
        "receivable": b.receivable, "received": b.received, "arrears": b.arrears,
        "status": b.status, "status_name": STATUS_NAMES.get(b.status, b.status),
        "overdue_days": b.overdue_days, "age_bucket": b.age_bucket,
        "dunning_count": b.dunning_count, "last_dunning_at": b.last_dunning_at.isoformat()
        if b.last_dunning_at else None,
        "invoice_status": b.invoice_status,
        "collection_rate": round((b.received or 0) / b.receivable * 100, 2)
        if b.receivable else None,
    } for b in bills]
    result = paginate(items, page, page_size)
    total_recv = round(sum(i["receivable"] or 0 for i in items), 2)
    total_got = round(sum(i["received"] or 0 for i in items), 2)
    result["stats"] = {
        "total": len(items),
        "total_receivable": total_recv,
        "total_received": total_got,
        "total_arrears": round(sum(i["arrears"] or 0 for i in items
                                   if i["status"] in ("UNPAID", "PARTIAL", "OVERDUE")), 2),
        "overdue_arrears": round(sum(i["arrears"] or 0 for i in items
                                     if i["status"] == "OVERDUE"), 2),
        "collection_rate": round(total_got / total_recv * 100, 2) if total_recv else 0.0,
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in STATUS_NAMES if len([i for i in items if i["status"] == k])},
        "by_fee_type": {FEE_TYPES.get(k, k): round(sum(i["receivable"] or 0 for i in items
                                                       if i["fee_type"] == k), 2)
                        for k in {i["fee_type"] for i in items}},
        "dunning_count": len([i for i in items if (i["dunning_count"] or 0) > 0]),
    }
    return result


@router.get("/summary")
def finance_summary(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """财务总览：本月/年初至今 + 账龄 + 欠费 TOP + 12 个月趋势。"""
    auth.require("finance", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Bill)
    if park_id:
        q = q.where(Bill.park_id == park_id)
    elif vis is not None:
        q = q.where(Bill.park_id.in_(vis)) if vis else q.where(Bill.id == -1)
    bills = list(db.scalars(q).all())
    today = dt.date.today()
    m_start, m_next = _month_range(today)
    lm_start = m_start - dt.timedelta(days=1)
    lm_start = lm_start.replace(day=1)
    y_start = dt.date(today.year, 1, 1)

    def sm(items, attr):
        return round(sum(getattr(i, attr) or 0 for i in items), 2)

    cur = [b for b in bills if b.bill_date and m_start <= b.bill_date < m_next]
    lm = [b for b in bills if b.bill_date and lm_start <= b.bill_date < m_start]
    ytd = [b for b in bills if b.bill_date and y_start <= b.bill_date <= today]

    open_bills = [b for b in bills if b.status in ("UNPAID", "PARTIAL", "OVERDUE")]
    overdue = [b for b in bills if b.status == "OVERDUE"]

    # 欠费 TOP10
    ents = {e.id: e for e in db.scalars(select(Enterprise)).all()}
    arrears_map: dict[int, float] = {}
    for b in open_bills:
        if b.enterprise_id:
            arrears_map[b.enterprise_id] = arrears_map.get(b.enterprise_id, 0) + (b.arrears or 0)
    top = sorted(arrears_map.items(), key=lambda x: -x[1])[:10]

    # 账龄：键必须与 bills.age_bucket 的实际取值一致（见 core/enums.AGE_BUCKETS）。
    # 旧代码用的 "0-30"/"31-60"/"61-90"/"90+" 与库内 D1_30/…/OVER_365 完全不交集，
    # 导致财务页账龄分布四项恒为 0。
    arrears_age = [{
        "name": AGE_BUCKET_LABELS[k], "key": k,
        "amount": round(sum(b.arrears or 0 for b in open_bills if b.age_bucket == k), 2),
        "count": len([b for b in open_bills if b.age_bucket == k]),
    } for k in AGE_BUCKETS]

    # 12 个月趋势
    def shift(d: dt.date, n: int) -> dt.date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return dt.date(y, m, 1)

    trend = []
    for ms in [shift(m_start, -i) for i in range(11, -1, -1)]:
        me = shift(ms, 1)
        mb = [b for b in bills if b.bill_date and ms <= b.bill_date < me]
        trend.append({
            "month": f"{ms.year}-{ms.month:02d}",
            "receivable": sm(mb, "receivable"),
            "received": sm(mb, "received"),
            "arrears": sm(mb, "arrears"),
            "collection_rate": round(sm(mb, "received") / sm(mb, "receivable") * 100, 2)
            if sm(mb, "receivable") else 0.0,
        })

    # 收费类型结构
    fee_dist = [{"name": FEE_TYPES.get(k, k), "key": k,
                 "receivable": sm([b for b in cur if b.fee_type == k], "receivable"),
                 "received": sm([b for b in cur if b.fee_type == k], "received")}
                for k in FEE_TYPES if [b for b in cur if b.fee_type == k]]

    total_receivable = sm(bills, "receivable")
    total_received = sm(bills, "received")
    due = [b for b in bills if b.due_date and b.due_date <= today and (b.receivable or 0) > 0]

    return {
        "kpi": {
            "month_receivable": sm(cur, "receivable"),
            "month_received": sm(cur, "received"),
            "month_mom": round((sm(cur, "received") - sm(lm, "received"))
                               / (sm(lm, "received") or 1) * 100, 2),
            "ytd_receivable": sm(ytd, "receivable"),
            "ytd_received": sm(ytd, "received"),
            "total_arrears": sm(open_bills, "arrears"),
            "overdue_arrears": sm(overdue, "arrears"),
            "overdue_count": len(overdue),
            "collection_rate": round(sm(due, "received") / (sm(due, "receivable") or 1) * 100, 2),
            "total_receivable": total_receivable,
            "total_received": total_received,
            "open_bill_count": len(open_bills),
            "dunning_total": sum(b.dunning_count or 0 for b in open_bills),
        },
        "top_arrears": [{
            "enterprise_id": eid, "enterprise_name": ents[eid].enterprise_name if eid in ents else None,
            "industry": ents[eid].industry if eid in ents else None,
            "risk_level": ents[eid].risk_level if eid in ents else None,
            "arrears": round(amt, 2),
            "overdue_days": max((b.overdue_days or 0) for b in open_bills if b.enterprise_id == eid),
            "bill_count": len([b for b in open_bills if b.enterprise_id == eid]),
        } for eid, amt in top],
        "arrears_age": arrears_age,
        "trend": trend,
        "fee_dist": fee_dist,
        "basis": {
            "collection_rate": "已到期账单实收 ÷ 已到期账单应收（仅统计 due_date ≤ 今日的账单）",
            "arrears": "状态为未收/部分收款/已逾期的账单 arrears 字段合计",
            "month_mom": "本月实收 vs 上月实收",
        },
        "data_label": "演示数据",
    }


@router.get("/bills/{bill_id}")
def bill_detail(bill_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("finance", "VIEW")
    b = db.get(Bill, bill_id)
    if not b or not auth.can_access_park(b.park_id):
        raise HTTPException(404, "账单不存在或无权访问")
    if auth.enterprise_id and auth.enterprise_id != b.enterprise_id:
        raise HTTPException(403, "企业账号只能查看本企业账单")
    payments = list(db.scalars(select(Payment).where(Payment.bill_id == bill_id)
                               .order_by(Payment.pay_date.desc())).all())
    c = db.get(Contract, b.contract_id) if b.contract_id else None
    return {
        "bill": {
            "id": b.id, "bill_code": b.bill_code, "fee_type": b.fee_type,
            "fee_type_name": FEE_TYPES.get(b.fee_type, b.fee_type),
            "enterprise_id": b.enterprise_id, "enterprise_name": b.enterprise_name,
            "contract_id": b.contract_id, "period": b.period,
            "bill_date": b.bill_date.isoformat() if b.bill_date else None,
            "due_date": b.due_date.isoformat() if b.due_date else None,
            "receivable": b.receivable, "received": b.received, "arrears": b.arrears,
            "status": b.status, "status_name": STATUS_NAMES.get(b.status, b.status),
            "overdue_days": b.overdue_days, "age_bucket": b.age_bucket,
            "dunning_count": b.dunning_count,
            "last_dunning_at": b.last_dunning_at.isoformat() if b.last_dunning_at else None,
            "invoice_status": b.invoice_status, "remark": b.remark,
        },
        "contract": {"id": c.id, "contract_code": c.contract_code,
                     "contract_name": c.contract_name,
                     "start_date": c.start_date.isoformat() if c.start_date else None,
                     "end_date": c.end_date.isoformat() if c.end_date else None} if c else None,
        "payments": [{"id": p.id, "payment_code": p.payment_code, "amount": p.amount,
                      "pay_date": p.pay_date.isoformat() if p.pay_date else None,
                      "pay_method": p.pay_method, "pay_type": p.pay_type,
                      "operator": p.operator} for p in payments],
        "data_label": "演示数据",
    }


@router.post("/bills/{bill_id}/pay")
def pay_bill(bill_id: int, payload: BillPayRequest, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """收款登记（真实写入收款流水 + 更新账单 + 审计）。"""
    auth.require("finance", "EDIT")
    b = db.get(Bill, bill_id)
    if not b or not auth.can_access_park(b.park_id):
        raise HTTPException(404, "账单不存在或无权访问")
    if b.status in ("PAID", "WAIVED"):
        raise HTTPException(400, f"账单状态为「{STATUS_NAMES.get(b.status, b.status)}」，不可再收款")
    amount = round(payload.amount, 2)
    if amount > round(b.arrears or 0, 2) + 0.01:
        raise HTTPException(400, f"收款金额 {amount:,.2f} 元超过欠费金额 {(b.arrears or 0):,.2f} 元")

    before_received, before_arrears, before_status = b.received, b.arrears, b.status
    pay_date = dt.date.fromisoformat(payload.pay_date) if payload.pay_date else dt.date.today()
    pay = Payment(
        payment_code=f"PAY{dt.datetime.now():%Y%m%d%H%M%S}{random_suffix()}",
        bill_id=b.id, contract_id=b.contract_id, enterprise_id=b.enterprise_id,
        enterprise_name=b.enterprise_name,
        park_id=b.park_id, amount=amount, pay_date=pay_date,
        pay_method=payload.pay_method, pay_type="收款",
        operator=auth.user.real_name, remark=payload.remark,
    )
    db.add(pay)

    b.received = round((b.received or 0) + amount, 2)
    b.arrears = round(max((b.receivable or 0) - b.received, 0), 2)
    if b.arrears <= 0.01:
        b.arrears = 0.0
        b.status = "PAID"
        b.overdue_days = 0
        b.age_bucket = None
    elif b.status == "OVERDUE":
        pass  # 仍有欠费且原已逾期 → 保持逾期
    else:
        b.status = "PARTIAL"

    write_audit(db, module="finance", action="EDIT", auth=auth, object_type="Bill",
                object_id=b.id, object_name=b.bill_code,
                before_value={"received": before_received, "arrears": before_arrears,
                              "status": before_status},
                after_value={"received": b.received, "arrears": b.arrears, "status": b.status},
                change_summary=f"收款登记 {amount:,.2f} 元（{payload.pay_method}）",
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": f"已登记收款 {amount:,.2f} 元，账单剩余欠费 {b.arrears:,.2f} 元",
        "payment_id": pay.id, "bill_status": b.status, "arrears": b.arrears,
    }


def random_suffix() -> str:
    import random
    return f"{random.randint(0, 9999):04d}"


@router.post("/bills/{bill_id}/dunning")
def dunning(bill_id: int, db: DbSession, auth: CurrentAuth, note: str | None = None) -> dict[str, Any]:
    """登记催收动作（累加催收次数 + 审计）。"""
    auth.require("finance", "EDIT")
    b = db.get(Bill, bill_id)
    if not b or not auth.can_access_park(b.park_id):
        raise HTTPException(404, "账单不存在或无权访问")
    if b.status in ("PAID", "WAIVED"):
        raise HTTPException(400, "账单已结清或减免，无需催收")
    b.dunning_count = (b.dunning_count or 0) + 1
    b.last_dunning_at = dt.datetime.now()
    write_audit(db, module="finance", action="EDIT", auth=auth, object_type="Bill",
                object_id=b.id, object_name=b.bill_code,
                after_value={"dunning_count": b.dunning_count},
                change_summary=f"第 {b.dunning_count} 次催收：{note or '电话催收'}",
                source="USER")
    db.commit()
    return {"success": True, "message": f"已登记第 {b.dunning_count} 次催收",
            "dunning_count": b.dunning_count}


@router.get("/payments")
def list_payments(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                  enterprise_id: int | None = None, bill_id: int | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("finance", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Payment)
    if park_id:
        q = q.where(Payment.park_id == park_id)
    elif vis is not None:
        q = q.where(Payment.park_id.in_(vis)) if vis else q.where(Payment.id == -1)
    if auth.enterprise_id:
        q = q.where(Payment.enterprise_id == auth.enterprise_id)
    if enterprise_id:
        q = q.where(Payment.enterprise_id == enterprise_id)
    if bill_id:
        q = q.where(Payment.bill_id == bill_id)
    rows = list(db.scalars(q.order_by(Payment.pay_date.desc()).limit(1000)).all())
    items = [{
        "id": p.id, "payment_code": p.payment_code, "bill_id": p.bill_id,
        "contract_id": p.contract_id, "enterprise_id": p.enterprise_id,
        "enterprise_name": p.enterprise_name, "amount": p.amount,
        "pay_date": p.pay_date.isoformat() if p.pay_date else None,
        "pay_method": p.pay_method, "pay_type": p.pay_type,
        "operator": p.operator, "remark": p.remark,
    } for p in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {"total": len(items),
                       "total_amount": round(sum(i["amount"] or 0 for i in items), 2)}
    return result


@router.get("/projects/investment")
def project_investment(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """项目投资与预算执行（财务视角）。"""
    auth.require("finance", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Project)
    if park_id:
        q = q.where(Project.park_id == park_id)
    elif vis is not None:
        q = q.where(Project.park_id.in_(vis)) if vis else q.where(Project.id == -1)
    projects = list(db.scalars(q).all())
    items = [{
        "id": p.id, "project_code": p.project_code, "project_name": p.project_name,
        "project_type": p.project_type, "status": p.status,
        "management_method": p.management_method,
        "budget": p.budget, "approved_budget": p.approved_budget,
        "actual_cost": p.actual_cost, "progress": p.progress,
        "execution_rate": round((p.actual_cost or 0) / (p.approved_budget or p.budget or 1) * 100, 2),
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "planned_end_date": p.planned_end_date.isoformat() if p.planned_end_date else None,
    } for p in projects]
    tb = round(sum(i["approved_budget"] or i["budget"] or 0 for i in items), 2)
    ta = round(sum(i["actual_cost"] or 0 for i in items), 2)
    return {
        "items": items,
        "summary": {
            "project_count": len(items),
            "total_budget": tb, "total_actual": ta,
            "execution_rate": round(ta / tb * 100, 2) if tb else 0.0,
            "overspend_count": len([i for i in items if i["execution_rate"] > 100
                                    and i["status"] not in ("COMPLETED", "CLOSED")]),
        },
        "basis": "预算执行率 = 项目实际成本 ÷ 批准预算（未批准时取预算值）",
        "data_label": "演示数据",
    }

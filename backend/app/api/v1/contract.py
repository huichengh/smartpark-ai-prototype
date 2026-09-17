"""合同管理：合同台账、到期预警、租金、履约状态。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.core.audit import write_audit
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Bill,
    Building,
    Contract,
    Enterprise,
    Park,
    Space,
)
from app.schemas.common import paginate
from app.services import contract_engine

router = APIRouter(prefix="/contracts", tags=["合同管理"])

STATUS_NAMES = {
    "DRAFT": "草稿", "PENDING": "待审批", "ACTIVE": "生效中",
    "EXPIRING": "即将到期", "EXPIRED": "已到期", "TERMINATED": "已终止",
}

# ---------------------------------------------------------------------------
# 合同「即将到期」的口径只有一份实现：见 app/services/contract_engine.py
# ---------------------------------------------------------------------------
# 这里曾经自己算过一遍（只看日期不看状态），把 2 份**已终止**合同也算进
# "90 天内到期"，于是驾驶舱显示 37、合同页显示 39。已终止合同不可能续租，
# 算进去会凭空多出催办任务。凡是"到期预警"语义一律走 contract_engine。
EXPIRING_WINDOW_STATUSES = contract_engine.EXPIRING_WINDOW_STATUSES
is_expiring_within = contract_engine.is_expiring_within


@router.get("")
def list_contracts(db: DbSession, auth: CurrentAuth,
                   park_id: int | None = None, building_id: int | None = None,
                   status: str | None = None, enterprise_id: int | None = None,
                   keyword: str | None = None, expiring_days: int | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("contract", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Contract)
    if park_id:
        q = q.where(Contract.park_id == park_id)
    elif vis is not None:
        q = q.where(Contract.park_id.in_(vis)) if vis else q.where(Contract.id == -1)
    ent_clause = auth.enterprise_scope_clause(Contract.enterprise_id)
    if ent_clause is not None:
        q = q.where(ent_clause)
    if building_id:
        q = q.where(Contract.building_id == building_id)
    if status:
        q = q.where(Contract.status == status)
    if enterprise_id:
        q = q.where(Contract.enterprise_id == enterprise_id)
    if keyword:
        q = q.where(or_(Contract.contract_code.contains(keyword),
                        Contract.contract_name.contains(keyword),
                        Contract.enterprise_name.contains(keyword)))
    contracts = list(db.scalars(q).all())
    today = dt.date.today()

    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    bills = list(db.scalars(select(Bill)).all())
    bill_by_contract: dict[int, list[Bill]] = {}
    for b in bills:
        if b.contract_id:
            bill_by_contract.setdefault(b.contract_id, []).append(b)

    items = []
    for c in contracts:
        days_left = (c.end_date - today).days if c.end_date else None
        if expiring_days is not None and not is_expiring_within(c.status, days_left, expiring_days):
            # 这里的过滤条件必须与 /contracts/expiring 和驾驶舱 KPI 同口径，
            # 否则同一个"90 天内到期"会出现 37 / 39 两个数（已终止合同不该算进来）。
            continue
        cb = bill_by_contract.get(c.id, [])
        arrears = round(sum(b.arrears or 0 for b in cb
                            if b.status in ("UNPAID", "PARTIAL", "OVERDUE")), 2)
        received = round(sum(b.received or 0 for b in cb), 2)
        receivable = round(sum(b.receivable or 0 for b in cb), 2)
        items.append({
            "id": c.id, "contract_code": c.contract_code, "contract_name": c.contract_name,
            "contract_type": c.contract_type, "status": c.status,
            "status_name": STATUS_NAMES.get(c.status, c.status),
            "enterprise_id": c.enterprise_id, "enterprise_name": c.enterprise_name,
            "park_id": c.park_id, "park_name": parks.get(c.park_id),
            "building_id": c.building_id, "building_name": buildings.get(c.building_id),
            "space_name": c.space_name, "leased_area": c.leased_area,
            "rent_price": c.rent_price, "property_price": c.property_price, "monthly_property_fee": c.monthly_property_fee,
            "monthly_rent": c.monthly_rent, "deposit": c.deposit,
            "contract_amount": c.contract_amount, "payment_day": c.payment_day,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "sign_date": c.sign_date.isoformat() if c.sign_date else None,
            "days_left": days_left,
            "free_rent_months": c.free_rent_months,
            "payment_cycle": c.payment_cycle,
            "annual_rent": round((c.monthly_rent or 0) * 12, 2),
            "arrears": arrears,
            "collection_rate": round(received / receivable * 100, 2) if receivable else None,
            "owner_name": c.owner_name, "signed_by": c.signed_by,
            "approval_status": c.approval_status, "terminate_reason": c.terminate_reason,
            "renewed_from_id": c.renewed_from_id, "remark": c.remark,
        })
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in STATUS_NAMES if len([i for i in items if i["status"] == k])},
        "active_count": len([i for i in items if i["status"] in ("ACTIVE", "EXPIRING")]),
        "expiring_90": len([i for i in items
                            if is_expiring_within(i["status"], i["days_left"], 90)]),
        "expiring_30": len([i for i in items
                            if is_expiring_within(i["status"], i["days_left"], 30)]),
        "expired_open": len([i for i in items if i["days_left"] is not None and i["days_left"] < 0
                             and i["status"] in ("ACTIVE", "EXPIRING")]),
        "total_leased_area": round(sum(i["leased_area"] or 0 for i in items), 2),
        "total_monthly_rent": round(sum(i["monthly_rent"] or 0 for i in items
                                        if i["status"] in ("ACTIVE", "EXPIRING")), 2),
        "total_arrears": round(sum(i["arrears"] for i in items), 2),
    }
    return result


@router.get("/expiring")
def expiring_contracts(db: DbSession, auth: CurrentAuth,
                       park_id: int | None = None, days: int = 90) -> dict[str, Any]:
    """合同到期预警（分组 + 风险敞口）。"""
    auth.require("contract", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Contract).where(Contract.status.in_(EXPIRING_WINDOW_STATUSES))
    if park_id:
        q = q.where(Contract.park_id == park_id)
    elif vis is not None:
        q = q.where(Contract.park_id.in_(vis)) if vis else q.where(Contract.id == -1)
    contracts = list(db.scalars(q).all())
    today = dt.date.today()

    def bucket(d: int) -> str:
        if d <= 30:
            return "30天内"
        if d <= 60:
            return "31-60天"
        if d <= 90:
            return "61-90天"
        return "90天以上"

    rows = []
    for c in contracts:
        if not c.end_date:
            continue
        days_left = (c.end_date - today).days
        if not is_expiring_within(c.status, days_left, days):
            continue
        rows.append({
            "id": c.id, "contract_code": c.contract_code,
            "enterprise_id": c.enterprise_id, "enterprise_name": c.enterprise_name,
            "park_id": c.park_id, "building_id": c.building_id,
            "space_name": c.space_name, "leased_area": c.leased_area,
            "monthly_rent": c.monthly_rent,
            "end_date": c.end_date.isoformat(),
            "days_left": days_left,
            "bucket": bucket(days_left),
            "annual_rent": round((c.monthly_rent or 0) * 12, 2),
            "owner_name": c.owner_name,
        })
    rows.sort(key=lambda x: x["days_left"])
    grouped: dict[str, list] = {"30天内": [], "31-60天": [], "61-90天": [], "90天以上": []}
    for r in rows:
        grouped.setdefault(r["bucket"], []).append(r)

    return {
        "items": rows,
        "grouped": grouped,
        "total": len(rows),
        "window_days": days,
        "total_annual_rent_at_risk": round(sum(r["annual_rent"] for r in rows), 2),
        "total_leased_area_at_risk": round(sum(r["leased_area"] or 0 for r in rows), 2),
        "by_park": [{
            "park_id": pid, "park_name": pname,
            "count": len([r for r in rows if r["park_id"] == pid]),
            "annual_rent": round(sum(r["annual_rent"] for r in rows if r["park_id"] == pid), 2),
        } for pid, pname in {p.id: p.park_name for p in db.scalars(select(Park)).all()}.items()
            if len([r for r in rows if r["park_id"] == pid])],
        "basis": f"筛选：状态为生效中/即将到期，且到期日距今 0~{days} 天（今日 {today}）",
        "data_label": "演示数据",
    }


@router.get("/{contract_id}")
def contract_detail(contract_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("contract", "VIEW")
    c = db.get(Contract, contract_id)
    if not c or not auth.can_access_park(c.park_id):
        raise HTTPException(404, "合同不存在或无权访问")
    auth.require_enterprise(c.enterprise_id, "企业账号只能查看本企业合同")
    today = dt.date.today()
    bills = list(db.scalars(select(Bill).where(Bill.contract_id == contract_id)
                            .order_by(Bill.bill_date.desc())).all())
    ent = db.get(Enterprise, c.enterprise_id) if c.enterprise_id else None
    space = db.get(Space, c.space_id) if c.space_id else None
    building = db.get(Building, c.building_id) if c.building_id else None
    return {
        "contract": {
            "id": c.id, "contract_code": c.contract_code, "contract_name": c.contract_name,
            "contract_type": c.contract_type, "status": c.status,
            "status_name": STATUS_NAMES.get(c.status, c.status),
            "enterprise_id": c.enterprise_id, "enterprise_name": c.enterprise_name,
            "park_id": c.park_id, "building_id": c.building_id,
            "space_id": c.space_id, "space_name": c.space_name,
            "leased_area": c.leased_area, "rent_price": c.rent_price,
            "property_price": c.property_price,
            "monthly_property_fee": c.monthly_property_fee,
            "monthly_rent": c.monthly_rent,
            "deposit": c.deposit, "payment_cycle": c.payment_cycle,
            "payment_day": c.payment_day, "contract_amount": c.contract_amount,
            "free_rent_months": c.free_rent_months,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "sign_date": c.sign_date.isoformat() if c.sign_date else None,
            "days_left": (c.end_date - today).days if c.end_date else None,
            "annual_rent": round((c.monthly_rent or 0) * 12, 2),
            "owner_name": c.owner_name, "signed_by": c.signed_by,
            "renewed_from_id": c.renewed_from_id,
            "terminate_date": c.terminate_date.isoformat() if c.terminate_date else None,
            "terminate_reason": c.terminate_reason, "remark": c.remark,
        },
        "enterprise": {"id": ent.id, "enterprise_name": ent.enterprise_name,
                       "industry": ent.industry, "status": ent.status,
                       "risk_level": ent.risk_level} if ent else None,
        "space": {"id": space.id, "space_code": space.space_code,
                  "space_name": space.space_name, "space_type": space.space_type,
                  "area": space.area} if space else None,
        "building": {"id": building.id, "building_name": building.building_name} if building else None,
        "bills": [{"id": b.id, "bill_code": b.bill_code, "fee_type": b.fee_type,
                   "period": b.period, "receivable": b.receivable, "received": b.received,
                   "arrears": b.arrears, "status": b.status,
                   "bill_date": b.bill_date.isoformat() if b.bill_date else None,
                   "due_date": b.due_date.isoformat() if b.due_date else None,
                   "overdue_days": b.overdue_days} for b in bills],
        "finance_summary": {
            "total_receivable": round(sum(b.receivable or 0 for b in bills), 2),
            "total_received": round(sum(b.received or 0 for b in bills), 2),
            "total_arrears": round(sum(b.arrears or 0 for b in bills
                                       if b.status in ("UNPAID", "PARTIAL", "OVERDUE")), 2),
        },
        "data_label": "演示数据",
    }


@router.post("/{contract_id}/terminate")
def terminate_contract(contract_id: int, reason: str, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """终止合同（高影响动作，需 contract:APPROVE 权限 + 强制审计）。"""
    auth.require("contract", "APPROVE")
    c = db.get(Contract, contract_id)
    if not c or not auth.can_access_park(c.park_id):
        raise HTTPException(404, "合同不存在或无权访问")
    if c.status in ("TERMINATED", "EXPIRED"):
        raise HTTPException(400, f"合同当前状态为 {STATUS_NAMES.get(c.status, c.status)}，不可终止")
    before = c.status
    c.status = "TERMINATED"
    c.terminate_reason = reason
    c.terminate_date = dt.date.today()
    c.remark = (c.remark or "") + f"｜终止原因：{reason}（{auth.user.real_name}，{dt.date.today()}）"
    write_audit(db, module="contract", action="APPROVE", auth=auth, object_type="Contract",
                object_id=c.id, object_name=c.contract_name,
                before_value={"status": before}, after_value={"status": "TERMINATED"},
                change_summary=f"合同终止：{reason}", source="USER")
    db.commit()
    return {"success": True, "message": f"合同「{c.contract_name}」已终止"}


@router.post("/{contract_id}/renew-intent")
def renew_intent(contract_id: int, db: DbSession, auth: CurrentAuth,
                 intent: str = "续签", note: str | None = None) -> dict[str, Any]:
    """登记续签意向（为招商与预警提供依据）。"""
    auth.require("contract", "EDIT")
    c = db.get(Contract, contract_id)
    if not c or not auth.can_access_park(c.park_id):
        raise HTTPException(404, "合同不存在或无权访问")
    c.remark = (c.remark or "") + f"｜续签意向：{intent}（{note or '无备注'}，{dt.date.today()}）"
    write_audit(db, module="contract", action="EDIT", auth=auth, object_type="Contract",
                object_id=c.id, object_name=c.contract_name,
                after_value={"renew_intent": intent, "renew_note": note},
                change_summary=f"登记续签意向：{intent}", source="USER")
    db.commit()
    return {"success": True, "message": f"续签意向已登记为「{intent}」"}

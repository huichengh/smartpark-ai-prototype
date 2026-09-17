"""招商 CRM：渠道、线索、漏斗、跟进、招商活动。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.audit import write_audit
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Channel,
    Enterprise,
    LeasingActivity,
    LeasingFollowup,
    LeasingLead,
    Park,
    User,
)
from app.schemas.common import paginate

router = APIRouter(prefix="/leasing", tags=["招商租赁"])

STAGE_ORDER = ["LEAD", "CONTACTED", "QUALIFIED", "SITE_VISIT", "NEGOTIATION",
               "CONTRACT_APPROVAL", "SIGNED", "SETTLED"]
STAGE_NAMES = {
    "LEAD": "潜在线索", "CONTACTED": "已联系", "QUALIFIED": "有效商机",
    "SITE_VISIT": "实地看房", "NEGOTIATION": "商务谈判",
    "CONTRACT_APPROVAL": "合同审批", "SIGNED": "签约", "SETTLED": "入驻",
    "LOST": "已流失",
}
SOURCE_NAMES = {
    "REFERRAL": "老客户转介绍", "ONLINE": "线上推广", "EXHIBITION": "展会",
    "GOVERNMENT": "政府推荐", "CHANNEL": "合作渠道", "WALK_IN": "主动上门",
    "CALL": "电话开发", "OTHER": "其他",
}


@router.get("/channels")
def list_channels(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    auth.require("leasing", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Channel)
    if park_id:
        q = q.where(Channel.park_id == park_id)
    elif vis is not None:
        q = q.where(Channel.park_id.in_(vis)) if vis else q.where(Channel.id == -1)
    rows = list(db.scalars(q).all())
    leads = list(db.scalars(select(LeasingLead)).all())
    items = []
    for c in rows:
        cl = [x for x in leads if x.channel_id == c.id]
        signed = len([x for x in cl if x.stage in ("SIGNED", "SETTLED")])
        cost = c.cost or 0
        items.append({
            "id": c.id, "channel_code": c.channel_code, "channel_name": c.channel_name,
            "channel_type": c.channel_type, "park_id": c.park_id,
            "cost": cost, "remark": c.remark,
            "lead_count": len(cl), "signed_count": signed,
            "conversion_rate": round(signed / len(cl) * 100, 2) if cl else 0.0,
            # 获客成本 = 渠道投入 ÷ 签约数；无签约时给出明确说明
            "cost_per_sign": round(cost / signed, 2) if signed else None,
            "cost_per_sign_note": None if signed else "该渠道暂无签约，获客成本不可计算",
            "demand_area": round(sum(x.demand_area or 0 for x in cl), 2),
        })
    items.sort(key=lambda x: -x["signed_count"])
    return {"items": items, "total": len(items), "data_label": "演示数据"}


@router.get("/funnel")
def funnel(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """招商漏斗：各阶段转化率 + 各园区对比。"""
    auth.require("leasing", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(LeasingLead)
    if park_id:
        q = q.where(LeasingLead.park_id == park_id)
    elif vis is not None:
        q = q.where(LeasingLead.park_id.in_(vis)) if vis else q.where(LeasingLead.id == -1)
    leads = list(db.scalars(q).all())
    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}

    stages = []
    for i, st in enumerate(STAGE_ORDER):
        reached = [x for x in leads if x.stage in STAGE_ORDER[i:] and x.stage != "LOST"]
        prev_reached = (len([x for x in leads if x.stage in STAGE_ORDER[i - 1:] and x.stage != "LOST"])
                        if i > 0 else len(leads))
        stages.append({
            "stage": st, "stage_name": STAGE_NAMES[st],
            "count": len(reached),
            "step_rate": round(len(reached) / prev_reached * 100, 2) if prev_reached else 0.0,
            "overall_rate": round(len(reached) / len(leads) * 100, 2) if leads else 0.0,
            "demand_area": round(sum(x.demand_area or 0 for x in reached), 2),
        })

    by_park = []
    for pid, pname in parks.items():
        pl = [x for x in leads if x.park_id == pid]
        if not pl:
            continue
        matured = [x for x in pl if x.stage not in ("LEAD", "LOST")]
        signed = [x for x in pl if x.stage in ("SIGNED", "SETTLED")]
        by_park.append({
            "park_id": pid, "park_name": pname, "lead_count": len(pl),
            "signed_count": len(signed),
            "conversion_rate": round(len(signed) / len(matured) * 100, 2) if matured else 0.0,
            "stagnant": len([x for x in pl if x.stage not in ("SIGNED", "SETTLED", "LOST")
                             and (dt.datetime.now()
                                  - (x.stage_entered_at or dt.datetime.now())).days >= 30]),
        })
    by_park.sort(key=lambda x: x["conversion_rate"])

    today = dt.date.today()
    stagnant = [x for x in leads if x.stage not in ("SIGNED", "SETTLED", "LOST")
                and x.stage_entered_at
                and (dt.datetime.now() - x.stage_entered_at).days >= 30]

    return {
        "stages": stages,
        "by_park": by_park,
        "summary": {
            "total_leads": len(leads),
            "active_leads": len([x for x in leads if x.stage not in ("SIGNED", "SETTLED", "LOST")]),
            "signed_leads": len([x for x in leads if x.stage in ("SIGNED", "SETTLED")]),
            "lost_leads": len([x for x in leads if x.stage == "LOST"]),
            "total_demand_area": round(sum(x.demand_area or 0 for x in leads), 2),
            "total_investment": round(sum(x.investment_amount or 0 for x in leads), 2),
            "stagnant_count": len(stagnant),
            "conversion_rate": round(
                len([x for x in leads if x.stage in ("SIGNED", "SETTLED")])
                / (len([x for x in leads if x.stage not in ("LEAD", "LOST")]) or 1) * 100, 2),
        },
        "data_label": "演示数据",
    }


@router.get("/leads")
def list_leads(db: DbSession, auth: CurrentAuth,
               park_id: int | None = None, stage: str | None = None,
               channel_id: int | None = None, owner: str | None = None,
               keyword: str | None = None, stagnant_only: bool = False,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("leasing", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(LeasingLead)
    if park_id:
        q = q.where(LeasingLead.park_id == park_id)
    elif vis is not None:
        q = q.where(LeasingLead.park_id.in_(vis)) if vis else q.where(LeasingLead.id == -1)
    if stage:
        q = q.where(LeasingLead.stage == stage)
    if channel_id:
        q = q.where(LeasingLead.channel_id == channel_id)
    if owner:
        q = q.where(LeasingLead.owner_name == owner)
    if keyword:
        q = q.where(or_(LeasingLead.company_name.contains(keyword),
                        LeasingLead.contact_person.contains(keyword),
                        LeasingLead.contact_phone.contains(keyword),
                        LeasingLead.lead_code.contains(keyword)))
    leads = list(db.scalars(q.order_by(LeasingLead.id.desc())).all())
    channels = {c.id: c.channel_name for c in db.scalars(select(Channel)).all()}
    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    now = dt.datetime.now()
    items = []
    for x in leads:
        stagnant_days = ((now - x.stage_entered_at).days
                         if x.stage_entered_at and x.stage not in ("SIGNED", "SETTLED", "LOST")
                         else None)
        if stagnant_only and not (stagnant_days and stagnant_days >= 30):
            continue
        items.append({
            "id": x.id, "lead_code": x.lead_code, "company_name": x.company_name,
            "contact_person": x.contact_person, "contact_phone": x.contact_phone,
            "industry": x.industry, "park_id": x.park_id, "park_name": parks.get(x.park_id),
            "stage": x.stage, "stage_name": STAGE_NAMES.get(x.stage, x.stage),
            "source": x.source, "source_name": SOURCE_NAMES.get(x.source, x.source),
            "channel_id": x.channel_id, "channel_name": channels.get(x.channel_id),
            "owner_name": x.owner_name,
            "demand_space_type": x.demand_space_type,
            "demand_area": x.demand_area, "demand_budget": x.demand_budget,
            "investment_amount": x.investment_amount,
            "expected_employees": x.expected_employees,
            "priority": x.priority, "score": x.score,
            "stage_entered_at": x.stage_entered_at.isoformat() if x.stage_entered_at else None,
            "stagnant_days": stagnant_days,
            "is_stagnant": bool(stagnant_days and stagnant_days >= 30),
            "next_followup_at": x.next_followup_at.isoformat() if x.next_followup_at else None,
            "created_at": x.created_at.isoformat() if x.created_at else None,
            "remark": x.remark,
        })
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "by_stage": {k: len([i for i in items if i["stage"] == k])
                     for k in STAGE_ORDER + ["LOST"]
                     if len([i for i in items if i["stage"] == k])},
        "stagnant_count": len([i for i in items if i["is_stagnant"]]),
        "total_demand_area": round(sum(i["demand_area"] or 0 for i in items), 2),
    }
    return result


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("leasing", "VIEW")
    x = db.get(LeasingLead, lead_id)
    if not x or not auth.can_access_park(x.park_id):
        raise HTTPException(404, "线索不存在或无权访问")
    followups = list(db.scalars(select(LeasingFollowup).where(LeasingFollowup.lead_id == lead_id)
                                .order_by(LeasingFollowup.followup_at.desc())).all())
    ent = db.get(Enterprise, x.converted_enterprise_id) if x.converted_enterprise_id else None
    now = dt.datetime.now()
    return {
        "lead": {
            "id": x.id, "lead_code": x.lead_code, "company_name": x.company_name,
            "contact_person": x.contact_person, "contact_phone": x.contact_phone,
            "contact_position": x.contact_position,
            "industry": x.industry, "park_id": x.park_id,
            "stage": x.stage, "stage_name": STAGE_NAMES.get(x.stage, x.stage),
            "source": x.source, "source_name": SOURCE_NAMES.get(x.source, x.source),
            "owner_name": x.owner_name, "priority": x.priority, "score": x.score,
            "demand_space_type": x.demand_space_type, "demand_area": x.demand_area,
            "demand_budget": x.demand_budget, "investment_amount": x.investment_amount,
            "expected_employees": x.expected_employees,
            "win_probability": x.win_probability,
            "stage_entered_at": x.stage_entered_at.isoformat() if x.stage_entered_at else None,
            "stagnant_days": ((now - x.stage_entered_at).days
                              if x.stage_entered_at and x.stage not in ("SIGNED", "SETTLED", "LOST") else None),
            "next_followup_at": x.next_followup_at.isoformat() if x.next_followup_at else None,
            "lost_reason": x.lost_reason, "remark": x.remark,
        },
        "enterprise": {"id": ent.id, "enterprise_name": ent.enterprise_name,
                       "status": ent.status} if ent else None,
        "followups": [{"id": f.id, "followup_type": f.followup_type, "content": f.content,
                       "result": f.result, "followup_by": f.followup_by,
                       "followup_at": f.followup_at.isoformat() if f.followup_at else None,
                       "next_action": f.next_action,
                       "next_action_at": f.next_action_at.isoformat() if f.next_action_at else None}
                      for f in followups],
        "data_label": "演示数据",
    }


@router.post("/leads/{lead_id}/followup")
def add_followup(lead_id: int, content: str, followup_type: str = "电话跟进",
                 result: str | None = None, next_action: str | None = None,
                 db: DbSession = None, auth: CurrentAuth = None) -> dict[str, Any]:
    auth.require("leasing", "EDIT")
    x = db.get(LeasingLead, lead_id)
    if not x or not auth.can_access_park(x.park_id):
        raise HTTPException(404, "线索不存在或无权访问")
    f = LeasingFollowup(
        lead_id=lead_id, followup_type=followup_type, content=content,
        result=result, followup_by=auth.user.real_name,
        followup_at=dt.datetime.now(), next_action=next_action,
    )
    db.add(f)
    x.stage_entered_at = dt.datetime.now()   # 跟进后重置停滞计时
    x.last_followup_at = dt.datetime.now()
    write_audit(db, module="leasing", action="ADD", auth=auth, object_type="LeasingLead",
                object_id=lead_id, object_name=x.company_name,
                change_summary=f"新增跟进记录：{followup_type}", source="USER")
    db.commit()
    return {"success": True, "message": "跟进记录已保存", "followup_id": f.id}


@router.post("/leads/{lead_id}/stage")
def move_stage(lead_id: int, stage: str, db: DbSession, auth: CurrentAuth,
               lost_reason: str | None = None) -> dict[str, Any]:
    """推进线索阶段（含审计与合法性校验）。"""
    auth.require("leasing", "EDIT")
    x = db.get(LeasingLead, lead_id)
    if not x or not auth.can_access_park(x.park_id):
        raise HTTPException(404, "线索不存在或无权访问")
    if stage not in STAGE_ORDER + ["LOST"]:
        raise HTTPException(400, f"非法阶段：{stage}")
    before = x.stage
    x.stage = stage
    x.stage_entered_at = dt.datetime.now()
    if stage == "LOST":
        x.lost_reason = lost_reason or "未填写"
    write_audit(db, module="leasing", action="EDIT", auth=auth, object_type="LeasingLead",
                object_id=lead_id, object_name=x.company_name,
                before_value={"stage": before}, after_value={"stage": stage},
                change_summary=f"线索阶段由「{STAGE_NAMES.get(before, before)}」变更为「{STAGE_NAMES.get(stage, stage)}」",
                source="USER")
    db.commit()
    return {"success": True, "message": f"阶段已从「{STAGE_NAMES.get(before, before)}」更新为「{STAGE_NAMES.get(stage, stage)}」"}


@router.get("/activities")
def list_activities(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("leasing", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(LeasingActivity)
    if park_id:
        q = q.where(LeasingActivity.park_id == park_id)
    elif vis is not None:
        q = q.where(LeasingActivity.park_id.in_(vis)) if vis else q.where(LeasingActivity.id == -1)
    rows = list(db.scalars(q.order_by(LeasingActivity.start_date.desc())).all())
    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    items = [{
        "id": a.id, "activity_code": a.activity_code, "activity_name": a.activity_name,
        "activity_type": a.activity_type, "park_id": a.park_id,
        "park_name": parks.get(a.park_id),
        "start_date": a.start_date.isoformat() if a.start_date else None,
        "end_date": a.end_date.isoformat() if a.end_date else None,
        "location": a.location, "owner": a.owner,
        "budget": a.budget, "actual_cost": a.actual_cost,
        "lead_count": a.lead_count, "sign_count": a.sign_count,
        "status": a.status,
        "cost_per_lead": round((a.actual_cost or 0) / a.lead_count, 2) if a.lead_count else None,
    } for a in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "total_leads": sum(i["lead_count"] or 0 for i in items),
        "total_signs": sum(i["sign_count"] or 0 for i in items),
        "total_cost": round(sum(i["actual_cost"] or 0 for i in items), 2),
    }
    return result


@router.get("/stagnant")
def stagnant_leads(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                   days: int = 30) -> dict[str, Any]:
    """停滞线索分析（供 AI 与看板使用）。"""
    auth.require("leasing", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(LeasingLead)
    if park_id:
        q = q.where(LeasingLead.park_id == park_id)
    elif vis is not None:
        q = q.where(LeasingLead.park_id.in_(vis)) if vis else q.where(LeasingLead.id == -1)
    leads = list(db.scalars(q).all())
    now = dt.datetime.now()
    parks = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    items = []
    for x in leads:
        if x.stage in ("SIGNED", "SETTLED", "LOST") or not x.stage_entered_at:
            continue
        stuck = (now - x.stage_entered_at).days
        if stuck < days:
            continue
        items.append({
            "id": x.id, "lead_code": x.lead_code, "company_name": x.company_name,
            "stage": x.stage, "stage_name": STAGE_NAMES.get(x.stage, x.stage),
            "owner_name": x.owner_name, "park_name": parks.get(x.park_id),
            "stuck_days": stuck, "demand_area": x.demand_area, "owner_name": x.owner_name,
            "estimated_monthly_rent_loss": round((x.demand_area or 0) * 65, 2),
        })
    items.sort(key=lambda x: -x["stuck_days"])
    return {
        "items": items,
        "total": len(items),
        "threshold_days": days,
        "estimated_total_rent_loss": round(sum(i["estimated_monthly_rent_loss"] for i in items), 2),
        "basis": f"筛选条件：线索阶段停留 ≥ {days} 天且未签约/未流失；月租金损失按 65 元/㎡·月估算",
        "data_label": "演示数据",
    }

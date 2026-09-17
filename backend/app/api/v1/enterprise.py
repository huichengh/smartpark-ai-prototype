"""企业全生命周期 + 企业联系人/标签 + 企业服务 + 政策匹配。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.audit import write_audit
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Bill,
    Contract,
    Enterprise,
    EnterpriseContact,
    EnterpriseTag,
    LeasingFollowup,
    LeasingLead,
    Policy,
    PolicyMatch,
    ServiceRequest,
    Space,
)
from app.schemas.common import paginate

router = APIRouter(prefix="/enterprise", tags=["企业与政策"])

STATUS_NAMES = {
    "POTENTIAL": "潜在企业", "INTENT": "意向企业", "SIGNED": "签约企业",
    "SETTLED": "入驻企业", "GROWING": "成长企业", "RISK": "风险企业", "EXITED": "退园企业",
}


def scale_of(ent: Enterprise) -> str:
    n = ent.employee_count or 0
    if n >= 300:
        return "LARGE"
    if n >= 80:
        return "MEDIUM"
    if n >= 20:
        return "SMALL"
    return "MICRO"


# ---------------------------------------------------------------- 企业列表
@router.get("/enterprises")
def list_enterprises(db: DbSession, auth: CurrentAuth,
                     park_id: int | None = None, keyword: str | None = None,
                     industry: str | None = None, status: str | None = None,
                     risk_level: str | None = None, is_high_tech: bool | None = None,
                     scale: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("enterprise", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Enterprise)
    if park_id:
        q = q.where(Enterprise.park_id == park_id)
    elif vis is not None:
        q = q.where(Enterprise.park_id.in_(vis)) if vis else q.where(Enterprise.id == -1)
    if auth.enterprise_id:
        q = q.where(Enterprise.id == auth.enterprise_id)
    if keyword:
        q = q.where(or_(Enterprise.enterprise_name.contains(keyword),
                        Enterprise.unified_social_credit_code.contains(keyword),
                        Enterprise.legal_person.contains(keyword)))
    if industry:
        q = q.where(Enterprise.industry == industry)
    if status:
        q = q.where(Enterprise.status == status)
    if risk_level:
        q = q.where(Enterprise.risk_level == risk_level)
    if is_high_tech is not None:
        q = q.where(Enterprise.is_high_tech == is_high_tech)
    ents = list(db.scalars(q.order_by(Enterprise.id)).all())

    bills = list(db.scalars(select(Bill)).all())
    arrears_map: dict[int, float] = {}
    for b in bills:
        if b.status in ("UNPAID", "PARTIAL", "OVERDUE") and b.enterprise_id:
            arrears_map[b.enterprise_id] = arrears_map.get(b.enterprise_id, 0) + (b.arrears or 0)

    items = []
    for e in ents:
        sc = scale_of(e)
        if scale and sc != scale:
            continue
        items.append({
            "id": e.id, "enterprise_code": e.enterprise_code,
            "enterprise_name": e.enterprise_name,
            "unified_social_credit_code": e.unified_social_credit_code,
            "industry": e.industry, "sub_industry": e.sub_industry,
            "enterprise_type": e.enterprise_type, "park_id": e.park_id,
            "status": e.status, "status_name": STATUS_NAMES.get(e.status, e.status),
            "register_capital": e.register_capital,
            "legal_person": e.legal_person,
            "contact_person": e.contact_person, "contact_phone": e.contact_phone,
            "employee_count": e.employee_count,
            "annual_revenue": e.annual_revenue, "annual_tax": e.annual_tax,
            "scale": sc,
            "is_high_tech": e.is_high_tech, "is_specialized": e.is_specialized,
            "is_little_giant": e.is_little_giant, "is_tech_sme": e.is_tech_sme,
            "ip_count": e.ip_count,
            "leased_area": e.leased_area,
            "risk_level": e.risk_level, "credit_rating": e.credit_rating,
            "settle_date": e.settle_date.isoformat() if e.settle_date else None,
            "exit_date": e.exit_date.isoformat() if e.exit_date else None,
            "arrears": round(arrears_map.get(e.id, 0), 2),
        })
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in STATUS_NAMES if len([i for i in items if i["status"] == k])},
        "by_industry": dict(sorted(
            {k: len([i for i in items if i["industry"] == k]) for k in
             {i["industry"] for i in items}}.items(), key=lambda x: -x[1])[:12]),
        "high_tech_count": len([i for i in items if i["is_high_tech"]]),
        "risk_count": len([i for i in items if i["risk_level"] in ("HIGH", "CRITICAL")]),
        "with_arrears": len([i for i in items if i["arrears"] > 0]),
        "total_leased_area": round(sum(i["leased_area"] or 0 for i in items), 2),
    }
    return result


@router.get("/enterprises/{ent_id}")
def enterprise_detail(ent_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """企业一企一档：档案 + 空间 + 合同 + 账单 + 服务 + 政策。"""
    auth.require("enterprise", "VIEW")
    e = db.get(Enterprise, ent_id)
    if not e or not auth.can_access_park(e.park_id):
        raise HTTPException(404, "企业不存在或无权访问")
    if auth.enterprise_id and auth.enterprise_id != ent_id:
        raise HTTPException(403, "企业账号只能查看本企业档案")

    spaces = list(db.scalars(select(Space).where(Space.enterprise_id == ent_id)).all())
    contracts = list(db.scalars(select(Contract).where(Contract.enterprise_id == ent_id)
                                .order_by(Contract.end_date)).all())
    bills = list(db.scalars(select(Bill).where(Bill.enterprise_id == ent_id)
                            .order_by(Bill.bill_date.desc())).all())
    contacts = list(db.scalars(select(EnterpriseContact).where(EnterpriseContact.enterprise_id == ent_id)).all())
    tags = list(db.scalars(select(EnterpriseTag).where(EnterpriseTag.enterprise_id == ent_id)).all())
    services = list(db.scalars(select(ServiceRequest).where(ServiceRequest.enterprise_id == ent_id)
                               .order_by(ServiceRequest.submit_at.desc())).all())
    matches = list(db.scalars(select(PolicyMatch).where(PolicyMatch.enterprise_id == ent_id)).all())
    policies = {p.id: p for p in db.scalars(select(Policy)).all()}
    leads = list(db.scalars(select(LeasingLead).where(LeasingLead.converted_enterprise_id == ent_id)).all())
    followups = []
    if leads:
        followups = list(db.scalars(select(LeasingFollowup).where(
            LeasingFollowup.lead_id.in_([x.id for x in leads])).order_by(LeasingFollowup.id.desc())).all())

    today = dt.date.today()
    arrears = round(sum(b.arrears or 0 for b in bills
                        if b.status in ("UNPAID", "PARTIAL", "OVERDUE")), 2)
    overdue = [b for b in bills if b.status == "OVERDUE"]
    total_receivable = round(sum(b.receivable or 0 for b in bills), 2)
    total_received = round(sum(b.received or 0 for b in bills), 2)
    expiring = [c for c in contracts if c.end_date and c.status in ("ACTIVE", "EXPIRING")
                and c.end_date <= today + dt.timedelta(days=90)]

    # 经营风险信号（可解释）
    risk_signals = []
    if arrears > 0:
        lv = "RISK" if arrears > 200000 else "WARNING"
        risk_signals.append({"type": "财务", "level": lv,
                             "text": f"存在欠费 {arrears:,.0f} 元",
                             "basis": f"共 {len([b for b in bills if b.status in ('UNPAID','PARTIAL','OVERDUE')])} 张账单未结清"})
    if overdue:
        risk_signals.append({"type": "财务", "level": "RISK",
                             "text": f"{len(overdue)} 期账单逾期，最长逾期 {max(b.overdue_days or 0 for b in overdue)} 天",
                             "basis": "逾期账单明细见账单列表"})
    if e.risk_level in ("HIGH", "CRITICAL"):
        risk_signals.append({"type": "经营", "level": e.risk_level,
                             "text": f"企业风险等级为 {e.risk_level}：{e.risk_note or '无说明'}",
                             "basis": "来自企业档案风险标记"})
    if expiring:
        risk_signals.append({"type": "合同", "level": "WARNING",
                             "text": f"{len(expiring)} 份合同将在 90 天内到期",
                             "basis": "合同到期日 ≤ 今日+90 天"})
    if not e.annual_revenue:
        risk_signals.append({"type": "数据", "level": "INFO",
                             "text": "缺少年度营业收入数据，无法评估经营健康度",
                             "basis": "企业档案 annual_revenue 为空"})

    return {
        "enterprise": {
            "id": e.id, "enterprise_code": e.enterprise_code,
            "enterprise_name": e.enterprise_name,
            "unified_social_credit_code": e.unified_social_credit_code,
            "industry": e.industry, "sub_industry": e.sub_industry,
            "enterprise_type": e.enterprise_type, "status": e.status,
            "status_name": STATUS_NAMES.get(e.status, e.status),
            "scale": scale_of(e), "scale_label": {"LARGE": "大型", "MEDIUM": "中型",
                                                  "SMALL": "小型", "MICRO": "微型"}[scale_of(e)],
            "register_capital": e.register_capital,
            "established_date": e.established_date.isoformat() if e.established_date else None,
            "legal_person": e.legal_person, "contact_person": e.contact_person,
            "contact_phone": e.contact_phone, "contact_email": e.contact_email,
            "legal_person": e.legal_person, "register_capital": e.register_capital,
            "employee_count": e.employee_count, "rnd_employee_count": e.rnd_employee_count,
            "annual_revenue": e.annual_revenue, "annual_tax": e.annual_tax,
            "financing_stage": e.financing_stage, "financing_amount": e.financing_amount,
            "ip_count": e.ip_count, "invention_patent_count": e.invention_patent_count,
            "software_copyright_count": e.software_copyright_count,
            "is_high_tech": e.is_high_tech, "is_specialized": e.is_specialized,
            "is_little_giant": e.is_little_giant, "is_tech_sme": e.is_tech_sme,
            "settle_date": e.settle_date.isoformat() if e.settle_date else None,
            "exit_date": e.exit_date.isoformat() if e.exit_date else None,
            "leased_area": e.leased_area, "risk_level": e.risk_level,
            "risk_note": e.risk_note, "credit_rating": e.credit_rating,
            "description": e.description,
        },
        "kpi": {
            "leased_area": round(sum(s.rentable_area or s.area or 0 for s in spaces), 2),
            "space_count": len(spaces),
            "contract_count": len(contracts),
            "active_contract_count": len([c for c in contracts if c.status in ("ACTIVE", "EXPIRING")]),
            "monthly_rent": round(sum(c.monthly_rent or 0 for c in contracts
                                      if c.status in ("ACTIVE", "EXPIRING")), 2),
            "total_receivable": total_receivable,
            "total_received": total_received,
            "arrears": arrears,
            "collection_rate": round(total_received / total_receivable * 100, 2) if total_receivable else 0.0,
            "overdue_count": len(overdue),
            "expiring_90": len(expiring),
            "service_request_count": len(services),
            "policy_match_count": len(matches),
        },
        "risk_signals": risk_signals,
        "spaces": [{"id": s.id, "space_code": s.space_code, "space_name": s.space_name,
                    "space_type": s.space_type, "status": s.status,
                    "area": s.area, "rentable_area": s.rentable_area,
                    "rent_price": s.rent_price,
                    "lease_end": s.lease_end.isoformat() if s.lease_end else None} for s in spaces],
        "contracts": [{"id": c.id, "contract_code": c.contract_code,
                       "contract_name": c.contract_name, "status": c.status,
                       "start_date": c.start_date.isoformat() if c.start_date else None,
                       "end_date": c.end_date.isoformat() if c.end_date else None,
                       "monthly_rent": c.monthly_rent, "leased_area": c.leased_area,
                       "rent_price": c.rent_price, "monthly_property_fee": c.monthly_property_fee,
                       "days_left": (c.end_date - today).days if c.end_date else None}
                      for c in contracts],
        "bills": [{"id": b.id, "bill_code": b.bill_code, "fee_type": b.fee_type,
                   "period": b.period, "receivable": b.receivable, "received": b.received,
                   "arrears": b.arrears, "status": b.status,
                   "bill_date": b.bill_date.isoformat() if b.bill_date else None,
                   "due_date": b.due_date.isoformat() if b.due_date else None,
                   "overdue_days": b.overdue_days, "age_bucket": b.age_bucket,
                   "dunning_count": b.dunning_count}
                  for b in bills[:60]],
        "contacts": [{"id": c.id, "name": c.name, "position": c.position,
                      "phone": c.phone, "email": c.email,
                      "is_primary": c.is_primary, "remark": c.remark} for c in contacts],
        "tags": [t.tag_name for t in tags],
        "service_requests": [{"id": s.id, "request_code": s.request_code,
                              "service_type": s.service_type, "title": s.title,
                              "status": s.status, "priority": s.priority,
                              "submit_at": s.submit_at.isoformat() if s.submit_at else None,
                              "handler": s.handler, "satisfaction": s.satisfaction,
                              "finish_at": s.finish_at.isoformat() if s.finish_at else None}
                             for s in services[:30]],
        "policy_matches": [{
            "id": m.id, "policy_id": m.policy_id,
            "policy_name": policies[m.policy_id].policy_name if m.policy_id in policies else None,
            "subsidy_amount": policies[m.policy_id].subsidy_amount if m.policy_id in policies else None,
            "match_score": m.match_score, "match_level": m.match_level,
            "match_reason": m.match_reason, "missing_data": m.missing_data,
            "risk_note": m.risk_note, "status": m.status, "matched_by": m.matched_by,
        } for m in matches],
        "leasing_followups": [{"id": f.id, "followup_type": f.followup_type,
                               "content": f.content, "result": f.result,
                               "followup_at": f.followup_at.isoformat() if f.followup_at else None,
                               "followup_by": f.followup_by} for f in followups[:30]],
        "data_label": "演示数据",
    }


@router.post("/enterprises/{ent_id}/tags")
def add_enterprise_tag(ent_id: int, tag_name: str, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("enterprise", "EDIT")
    e = db.get(Enterprise, ent_id)
    if not e or not auth.can_access_park(e.park_id):
        raise HTTPException(404, "企业不存在或无权访问")
    exists = db.scalar(select(EnterpriseTag).where(EnterpriseTag.enterprise_id == ent_id,
                                                   EnterpriseTag.tag_name == tag_name))
    if exists:
        return {"success": False, "message": "该标签已存在"}
    db.add(EnterpriseTag(enterprise_id=ent_id, tag_name=tag_name, tag_type="自定义"))
    write_audit(db, module="enterprise", action="ADD", auth=auth, object_type="Enterprise",
                object_id=ent_id, object_name=e.enterprise_name,
                change_summary=f"新增企业标签「{tag_name}」", source="USER")
    db.commit()
    return {"success": True, "message": "标签已添加"}


@router.get("/enterprises/meta/industries")
def industry_options(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("enterprise", "VIEW")
    rows = db.execute(select(Enterprise.industry, func.count(Enterprise.id))
                      .group_by(Enterprise.industry).order_by(func.count(Enterprise.id).desc())).all()
    return {"items": [{"name": i or "未填写", "count": c} for i, c in rows],
            "data_label": "演示数据"}


# ---------------------------------------------------------------- 政策
@router.get("/policies")
def list_policies(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("policy", "VIEW")
    pols = list(db.scalars(select(Policy)).all())
    matches = list(db.scalars(select(PolicyMatch)).all())
    items = []
    for p in pols:
        pm = [m for m in matches if m.policy_id == p.id]
        items.append({
            "id": p.id, "policy_code": p.policy_code, "policy_name": p.policy_name,
            "issuing_authority": p.issuing_authority,
            "policy_level": p.policy_level,
            "applicable_industry": p.applicable_industry,
            "applicable_scale": p.applicable_scale,
            "subsidy_amount": p.subsidy_amount,
            "publish_date": p.publish_date.isoformat() if p.publish_date else None,
            "deadline": p.deadline.isoformat() if p.deadline else None,
            "status": p.status,
            "days_left": ((p.deadline - dt.date.today()).days
                          if p.deadline and isinstance(p.deadline, dt.date) else None),
            "match_count": len(pm),
            "likely_match_count": len([m for m in pm if m.match_level == "LIKELY_MATCH"]),
        })
    return {"items": items, "total": len(items), "data_label": "演示数据"}


@router.get("/policies/{policy_id}")
def policy_detail(policy_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("policy", "VIEW")
    p = db.get(Policy, policy_id)
    if not p:
        raise HTTPException(404, "政策不存在")
    matches = list(db.scalars(select(PolicyMatch).where(PolicyMatch.policy_id == policy_id)).all())
    ents = {e.id: e for e in db.scalars(select(Enterprise)).all()}
    return {
        "policy": {
            "id": p.id, "policy_code": p.policy_code, "policy_name": p.policy_name,
            "issuing_authority": p.issuing_authority, "policy_level": p.policy_level,
            "applicable_industry": p.applicable_industry,
            "applicable_scale": p.applicable_scale,
            "subsidy_amount": p.subsidy_amount, "material_list": p.material_list,
            "content": p.content,
            "publish_date": p.publish_date.isoformat() if p.publish_date else None,
            "deadline": p.deadline.isoformat() if p.deadline else None,
            "status": p.status,
        },
        "matches": [{
            "enterprise_id": m.enterprise_id,
            "enterprise_name": ents[m.enterprise_id].enterprise_name if m.enterprise_id in ents else None,
            "industry": ents[m.enterprise_id].industry if m.enterprise_id in ents else None,
            "match_score": m.match_score, "match_level": m.match_level,
            "match_reason": m.match_reason, "missing_data": m.missing_data,
            "risk_note": m.risk_note, "status": m.status,
        } for m in sorted(matches, key=lambda x: -(x.match_score or 0))],
        "data_label": "演示数据",
    }


@router.get("/policy-matches")
def list_policy_matches(db: DbSession, auth: CurrentAuth,
                        park_id: int | None = None, match_level: str | None = None,
                        status_: str | None = Query(None, alias="status"),
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("policy", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(PolicyMatch)
    if park_id:
        q = q.where(PolicyMatch.park_id == park_id)
    elif vis is not None:
        q = q.where(PolicyMatch.park_id.in_(vis)) if vis else q.where(PolicyMatch.id == -1)
    if match_level:
        q = q.where(PolicyMatch.match_level == match_level)
    if status_:
        q = q.where(PolicyMatch.status == status_)
    rows = list(db.scalars(q.order_by(PolicyMatch.match_score.desc())).all())
    ents = {e.id: e for e in db.scalars(select(Enterprise)).all()}
    pols = {p.id: p for p in db.scalars(select(Policy)).all()}
    items = [{
        "id": m.id, "policy_id": m.policy_id,
        "policy_name": pols[m.policy_id].policy_name if m.policy_id in pols else None,
        "subsidy_amount": pols[m.policy_id].subsidy_amount if m.policy_id in pols else None,
        "deadline": (pols[m.policy_id].deadline.isoformat()
                      if m.policy_id in pols and pols[m.policy_id].deadline
                      else None),
        "enterprise_id": m.enterprise_id,
        "enterprise_name": ents[m.enterprise_id].enterprise_name if m.enterprise_id in ents else None,
        "industry": ents[m.enterprise_id].industry if m.enterprise_id in ents else None,
        "match_score": m.match_score, "match_level": m.match_level,
        "match_reason": m.match_reason, "missing_data": m.missing_data,
        "risk_note": m.risk_note, "status": m.status, "matched_by": m.matched_by,
    } for m in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "likely_match": len([i for i in items if i["match_level"] == "LIKELY_MATCH"]),
        "need_verify": len([i for i in items if i["match_level"] == "NEED_VERIFY"]),
        "data_insufficient": len([i for i in items if i["match_level"] == "DATA_INSUFFICIENT"]),
    }
    return result


# ---------------------------------------------------------------- 企业服务
@router.get("/service-requests")
def list_service_requests(db: DbSession, auth: CurrentAuth,
                          park_id: int | None = None, status_: str | None = Query(None, alias="status"),
                          service_type: str | None = None, enterprise_id: int | None = None,
                          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("service", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(ServiceRequest)
    if park_id:
        q = q.where(ServiceRequest.park_id == park_id)
    elif vis is not None:
        q = q.where(ServiceRequest.park_id.in_(vis)) if vis else q.where(ServiceRequest.id == -1)
    if auth.enterprise_id:
        q = q.where(ServiceRequest.enterprise_id == auth.enterprise_id)
    if enterprise_id:
        q = q.where(ServiceRequest.enterprise_id == enterprise_id)
    if status_:
        q = q.where(ServiceRequest.status == status_)
    if service_type:
        q = q.where(ServiceRequest.service_type == service_type)
    rows = list(db.scalars(q.order_by(ServiceRequest.submit_at.desc())).all())
    ents = {e.id: e.enterprise_name for e in db.scalars(select(Enterprise)).all()}
    items = [{
        "id": s.id, "request_code": s.request_code, "service_type": s.service_type,
        "title": s.title, "content": s.content,
        "enterprise_id": s.enterprise_id, "enterprise_name": ents.get(s.enterprise_id),
        "park_id": s.park_id, "priority": s.priority, "status": s.status,
        "submit_at": s.submit_at.isoformat() if s.submit_at else None,
        "handler": s.handler,
        "submit_at": s.submit_at.isoformat() if s.submit_at else None,
        "finish_at": s.finish_at.isoformat() if s.finish_at else None,
        "satisfaction": s.satisfaction, "handle_note": s.handle_note,
        "requirement": s.requirement,
        "handle_hours": (round((s.finish_at - s.submit_at).total_seconds() / 3600, 2)
                         if s.finish_at and s.submit_at else None),
        "is_timeout": bool(s.finish_at and s.submit_at
                           and (s.finish_at - s.submit_at).total_seconds() / 3600 > 48),
    } for s in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in {i["status"] for i in items}},
        "by_type": {k: len([i for i in items if i["service_type"] == k])
                    for k in {i["service_type"] for i in items}},
        "timeout_count": len([i for i in items if i["is_timeout"]]),
    }
    return result

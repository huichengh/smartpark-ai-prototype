"""AI Agent 工具集（对应需求书第 84 节核心 Agent 工具）。

设计原则：
1. 每个工具只读取数据库真实数据，绝不编造。
2. 数据不足时返回 data_sufficient=False 与 missing_data，由 Agent 明确告知用户。
3. 每个工具返回 evidence（数据来源、表名、记录数、筛选条件），保证可追溯。
4. 工具分三级权限：L1 查询 / L2 分析与建议 / L3 高影响动作（仅生成待审批单据）。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    AGE_BUCKET_LABELS,
    AGE_BUCKETS,
    ENERGY_TYPE_ORDER,
    ENERGY_UNITS,
    ENUM_LABELS,
    AIPermissionLevel,
)
from app.core.security import AuthContext
from app.models import (
    ApprovalRequest,
    Bill,
    Building,
    Contract,
    Device,
    Enterprise,
    EnergyRecord,
    LeasingLead,
    Park,
    Policy,
    PolicyMatch,
    Project,
    ProjectChange,
    ProjectCost,
    ProjectRisk,
    SafetyHazard,
    SafetyIncident,
    Space,
    Sprint,
    SprintTask,
    WbsItem,
    WorkOrder,
)
from app.services import project_engine, property_engine, safety_engine

logger = logging.getLogger("smartpark")


# --------------------------------------------------------------------------
# 工具注册表
# --------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def tool(name: str, level: str = AIPermissionLevel.L1_QUERY, description: str = "",
         tables: list[str] | None = None):
    def deco(fn: Callable):
        TOOL_REGISTRY[name] = {
            "name": name,
            "level": level,
            "description": description,
            "tables": tables or [],
            "fn": fn,
        }
        return fn

    return deco


def _evidence(tables: list[str], records: int, filters: dict | None = None,
              formula: str | None = None) -> dict[str, Any]:
    return {
        "data_source": "平台业务数据库",
        "tables": tables,
        "record_count": records,
        "filters": filters or {},
        "formula": formula,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_label": "演示数据",
    }


def _park_scope(auth: AuthContext, park_id: int | None = None) -> list[int]:
    vis = auth.visible_park_ids()
    if park_id is not None:
        return [park_id]
    if vis is None:
        return []
    return vis


def _scoped_park_ids(db: Session, auth: AuthContext, park_id: int | None) -> list[int]:
    ids = _park_scope(auth, park_id)
    if ids:
        return ids
    vis = auth.visible_park_ids()
    if vis is None:
        return list(db.scalars(select(Park.id)).all())
    return vis


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（企业名很短，O(n·m) 动态规划足够）。"""
    best = 0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, ch2 in enumerate(b, 1):
            if ch == ch2:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _closest_enterprise_names(db: Session, auth: AuthContext, hint: str | None,
                              limit: int = 3) -> list[str]:
    """名称未命中时给出最相近的候选企业。

    "星海科技" 这类用户口语名往往与库内全称（"星云科技有限公司"）不等，
    直接回"未找到企业"会让用户以为是系统没有数据；给出候选名可以直接纠偏。
    """
    if not hint:
        return []
    rows = [e for e in db.scalars(select(Enterprise)).all()
            if e.park_id is None or auth.can_access_park(e.park_id)]
    scored = [(_lcs_len(hint, e.enterprise_name), e.enterprise_name) for e in rows]
    scored = [s for s in scored if s[0] >= 2]
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [name for _, name in scored[:limit]]


# ==========================================================================
# 1. get_dashboard_summary
# ==========================================================================


@tool("get_dashboard_summary", AIPermissionLevel.L1_QUERY,
      "获取园区经营驾驶舱核心指标（园区/企业/空间/招商/合同/收费/工单/设备/能耗/安全/项目）",
      ["parks", "enterprises", "spaces", "leasing_leads", "contracts", "bills", "projects"])
def get_dashboard_summary(db: Session, auth: AuthContext, park_id: int | None = None,
                          building_id: int | None = None, **kw) -> dict[str, Any]:
    from app.services.dashboard_service import get_dashboard_summary as svc

    data = svc(db, auth, park_id=park_id, building_id=building_id)
    return {
        "data": data,
        "evidence": _evidence(
            ["parks", "buildings", "spaces", "enterprises", "leasing_leads", "contracts",
             "bills", "projects", "work_orders", "devices", "energy_records", "safety_incidents"],
            sum(len(p.get("park_ids", [])) for p in [data["scope"]]) or 1,
            {"park_id": park_id, "building_id": building_id, "visible_parks": data["scope"]["park_ids"]},
        ),
        "data_sufficient": True,
    }


# ==========================================================================
# 2. get_park_profile
# ==========================================================================


@tool("get_park_profile", AIPermissionLevel.L1_QUERY, "获取园区档案与运营概况",
      ["parks", "buildings", "spaces", "enterprises"])
def get_park_profile(db: Session, auth: AuthContext, park_id: int | None = None,
                     park_name: str | None = None, **kw) -> dict[str, Any]:
    q = select(Park)
    if park_name:
        q = q.where(Park.park_name.like(f"%{park_name}%"))
    parks_all = list(db.scalars(q).all())
    if park_id:
        parks_all = [p for p in parks_all if p.id == park_id]
    parks_all = [p for p in parks_all if auth.can_access_park(p.id)]
    if not parks_all:
        return {"data": [], "data_sufficient": False,
                "missing_data": ["未找到符合条件的园区，或当前账号无该园区数据权限"],
                "evidence": _evidence(["parks"], 0)}

    out = []
    for p in parks_all:
        blds = list(db.scalars(select(Building).where(Building.park_id == p.id)).all())
        spaces = list(db.scalars(select(Space).where(Space.park_id == p.id)).all())
        rentable = [s for s in spaces if s.space_type != "PARKING"]
        rented = [s for s in rentable if s.status == "RENTED"]
        ents = list(db.scalars(select(Enterprise).where(Enterprise.park_id == p.id)).all())
        area = sum(s.rentable_area or s.area or 0 for s in rentable)
        ra = sum(s.rentable_area or s.area or 0 for s in rented)
        out.append({
            "id": p.id, "park_code": p.park_code, "park_name": p.park_name,
            "park_type": p.park_type, "city": p.city, "address": p.address,
            "total_area": p.total_area, "build_area": p.build_area,
            "building_count": len(blds),
            "space_count": len(rentable),
            "occupancy_rate": round(ra / area * 100, 2) if area else 0.0,
            "enterprise_count": len(ents),
            "settled_count": len([e for e in ents if e.status in ("SETTLED", "GROWING", "RISK")]),
            "manager_name": p.manager_name,
            "enabled_modules": p.enabled_modules or [],
            "operation_mode": p.operation_mode,
            "status": p.status,
        })
    return {"data": out, "evidence": _evidence(["parks", "buildings", "spaces", "enterprises"],
                                               len(parks_all)), "data_sufficient": True}


# ==========================================================================
# 3. get_enterprise_profile
# ==========================================================================


@tool("get_enterprise_profile", AIPermissionLevel.L1_QUERY,
      "获取企业画像（基础信息/资质/知识产权/租赁/合同/收费/服务/风险）",
      ["enterprises", "spaces", "contracts", "bills", "policy_matches"])
def get_enterprise_profile(db: Session, auth: AuthContext, enterprise_id: int | None = None,
                           enterprise_name: str | None = None, park_id: int | None = None,
                           **kw) -> dict[str, Any]:
    q = select(Enterprise)
    if enterprise_id:
        q = q.where(Enterprise.id == enterprise_id)
    if enterprise_name:
        q = q.where(Enterprise.enterprise_name.like(f"%{enterprise_name}%"))
    if park_id:
        q = q.where(Enterprise.park_id == park_id)
    ent_clause = auth.enterprise_scope_clause(Enterprise.id)
    if ent_clause is not None:
        q = q.where(ent_clause)
    ents = [e for e in db.scalars(q).all() if e.park_id is None or auth.can_access_park(e.park_id)]
    if not ents:
        cand = _closest_enterprise_names(db, auth, enterprise_name)
        msg = (f"未找到名称包含「{enterprise_name}」的企业"
               + (f"；库内相近企业：{'、'.join(cand)}" if cand else "")) \
            if enterprise_name else "当前数据范围内没有可访问的企业档案"
        return {"data": [], "data_sufficient": False,
                "missing_data": [msg], "candidates": cand,
                "evidence": _evidence(["enterprises"], 0)}

    out = []
    for e in ents:
        spaces = list(db.scalars(select(Space).where(Space.enterprise_id == e.id)).all())
        contracts = list(db.scalars(select(Contract).where(Contract.enterprise_id == e.id)).all())
        bills = list(db.scalars(select(Bill).where(Bill.enterprise_id == e.id)).all())
        matches = list(db.scalars(select(PolicyMatch).where(PolicyMatch.enterprise_id == e.id)).all())
        arrears = round(sum(b.arrears or 0 for b in bills if b.status in ("UNPAID", "PARTIAL", "OVERDUE")), 2)
        overall = round(sum(b.received or 0 for b in bills), 2)

        missing = []
        if not e.annual_revenue:
            missing.append("年度营业收入")
        if not e.employee_count:
            missing.append("员工人数")
        if not e.industry:
            missing.append("所属行业")
        if not e.contact_person:
            missing.append("企业联系人")
        if not e.contact_phone:
            missing.append("企业联系电话")

        risk_signals = []
        if arrears > 0:
            risk_signals.append({"type": "财务", "level": "WARNING",
                                 "text": f"存在欠费 {arrears:,.0f} 元"})
            if arrears > 200000:
                risk_signals[-1]["level"] = "RISK"
        overdue = [b for b in bills if b.status == "OVERDUE"]
        if overdue:
            risk_signals.append({"type": "财务", "level": "RISK",
                                 "text": f"{len(overdue)} 期账单逾期，最长逾期 {max(b.overdue_days or 0 for b in overdue)} 天"})
        if e.risk_level in ("HIGH", "CRITICAL"):
            risk_signals.append({"type": "经营", "level": "CRITICAL" if e.risk_level == "CRITICAL" else "RISK",
                                 "text": f"企业被标记为 {e.risk_level} 风险等级：{e.risk_note or '无说明'}"})
        expiring = [c for c in contracts if c.end_date and c.status in ("ACTIVE", "EXPIRING")
                    and c.end_date <= dt.date.today() + dt.timedelta(days=90)]
        if expiring:
            risk_signals.append({"type": "合同", "level": "WARNING",
                                 "text": f"{len(expiring)} 份合同将在 90 天内到期"})

        out.append({
            "id": e.id, "enterprise_code": e.enterprise_code,
            "enterprise_name": e.enterprise_name,
            "unified_social_credit_code": e.unified_social_credit_code,
            "industry": e.industry, "sub_industry": e.sub_industry,
            "enterprise_type": e.enterprise_type, "status": e.status,
            "register_capital": e.register_capital, "established_date": e.established_date.isoformat() if e.established_date else None,
            "legal_person": e.legal_person, "contact_person": e.contact_person,
            "contact_phone": e.contact_phone,
            "employee_count": e.employee_count, "rnd_employee_count": e.rnd_employee_count,
            "annual_revenue": e.annual_revenue, "annual_tax": e.annual_tax,
            "financing_stage": e.financing_stage, "financing_amount": e.financing_amount,
            "ip_count": e.ip_count, "invention_patent_count": e.invention_patent_count,
            "software_copyright_count": e.software_copyright_count,
            "is_high_tech": e.is_high_tech, "is_specialized": e.is_specialized,
            "is_little_giant": e.is_little_giant, "is_tech_sme": e.is_tech_sme,
            "settle_date": e.settle_date.isoformat() if e.settle_date else None,
            "exit_date": e.exit_date.isoformat() if e.exit_date else None,
            "leased_area": e.leased_area, "risk_level": e.risk_level, "credit_rating": e.credit_rating,
            "tags": e.tags or [],
            "spaces": [{"space_name": s.space_name, "space_type": s.space_type,
                        "area": s.rentable_area or s.area, "status": s.status,
                        "lease_end": s.lease_end.isoformat() if s.lease_end else None} for s in spaces],
            "contracts": [{"contract_code": c.contract_code, "contract_name": c.contract_name,
                           "start_date": c.start_date.isoformat() if c.start_date else None,
                           "end_date": c.end_date.isoformat() if c.end_date else None,
                           "monthly_rent": c.monthly_rent, "contract_amount": c.contract_amount,
                           "status": c.status} for c in contracts],
            "finance": {
                "total_billed": round(sum(b.receivable or 0 for b in bills), 2),
                "total_paid": overall,
                "arrears": arrears,
                "count": len(bills),
                "avg_monthly": round(sum(b.receivable or 0 for b in bills) / max(len(bills), 1), 2),
            },
            "policy_matches": [{"policy_id": m.policy_id, "score": m.match_score,
                                "level": m.match_level, "reason": m.match_reason}
                               for m in matches],
            "risk_signals": risk_signals,
            "missing_data": missing,
        })

    return {"data": out, "evidence": _evidence(
        ["enterprises", "spaces", "contracts", "bills", "policy_matches"], len(out)),
        "data_sufficient": True,
        "note": ("企业档案存在字段缺失，经营风险判断置信度受限。" if any(o["missing_data"] for o in out) else None)}


# ==========================================================================
# 4. get_space_status
# ==========================================================================


@tool("get_space_status", AIPermissionLevel.L1_QUERY,
      "获取空间状态：出租率、空置情况、空置时长、按楼栋/类型统计",
      ["spaces", "buildings", "floors"])
def get_space_status(db: Session, auth: AuthContext, park_id: int | None = None,
                     building_id: int | None = None, min_vacant_days: int | None = None,
                     **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(Space).where(Space.park_id.in_(ids)) if ids else select(Space).where(Space.id == -1)
    if building_id:
        q = q.where(Space.building_id == building_id)
    spaces = list(db.scalars(q).all())
    if not spaces:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有空间数据"], "evidence": _evidence(["spaces"], 0)}

    today = dt.date.today()
    rentable = [s for s in spaces if s.space_type != "PARKING"]
    by_status: dict[str, dict[str, float]] = {}
    for s in rentable:
        row = by_status.setdefault(s.status, {"count": 0, "area": 0.0})
        row["count"] += 1
        row["area"] += s.rentable_area or s.area or 0

    by_type: dict[str, dict[str, float]] = {}
    for s in rentable:
        row = by_type.setdefault(s.space_type, {"count": 0, "area": 0.0, "rented_area": 0.0})
        row["count"] += 1
        a = s.rentable_area or s.area or 0
        row["area"] += a
        if s.status == "RENTED":
            row["rented_area"] += a

    vacant = [s for s in rentable if s.status == "AVAILABLE"]
    vacant_list = sorted(
        [{"space_id": s.id, "space_code": s.space_code, "space_name": s.space_name,
          "space_type": s.space_type, "area": s.rentable_area or s.area,
          "vacant_days": (today - s.vacant_since).days if s.vacant_since else None,
          "building_id": s.building_id, "rent_price": s.rent_price}
         for s in vacant],
        key=lambda x: -(x["vacant_days"] or 0))

    if min_vacant_days is not None:
        vacant_list = [v for v in vacant_list if (v["vacant_days"] or 0) >= min_vacant_days]

    # 楼栋出租率排名
    blds = list(db.scalars(select(Building).where(Building.park_id.in_(ids))).all()) if ids else []
    building_rank = []
    for b in blds:
        bs = [s for s in rentable if s.building_id == b.id]
        a = sum(s.rentable_area or s.area or 0 for s in bs)
        ra = sum(s.rentable_area or s.area or 0 for s in bs if s.status == "RENTED")
        building_rank.append({"building_id": b.id, "building_name": b.building_name,
                              "occupancy_rate": round(ra / a * 100, 2) if a else 0.0,
                              "rentable_area": round(a, 2), "vacant_area": round(a - ra, 2)})
    building_rank.sort(key=lambda x: x["occupancy_rate"])

    total_area = sum(v["area"] for v in by_status.values())
    rented_area = by_status.get("RENTED", {}).get("area", 0)
    return {
        "data": {
            "total_space": len(rentable),
            "total_area": round(total_area, 2),
            "rented_area": round(rented_area, 2),
            "vacant_area": round(total_area - rented_area, 2),
            "occupancy_rate": round(rented_area / total_area * 100, 2) if total_area else 0.0,
            "vacant_count": len(vacant),
            "by_status": by_status,
            "by_type": by_type,
            "vacant_spaces": vacant_list[:30],
            "long_vacant": [v for v in vacant_list if (v["vacant_days"] or 0) > 90],
            "building_rank": building_rank,
        },
        "evidence": _evidence(["spaces", "buildings"], len(spaces),
                              {"park_ids": ids, "building_id": building_id},
                              "出租率 = 已出租面积 / 可租面积 × 100%"),
        "data_sufficient": True,
    }


# ==========================================================================
# 5. get_leasing_pipeline
# ==========================================================================


@tool("get_leasing_pipeline", AIPermissionLevel.L1_QUERY,
      "获取招商漏斗、转化率、停滞线索、商机评分",
      ["leasing_leads", "leasing_followups"])
def get_leasing_pipeline(db: Session, auth: AuthContext, park_id: int | None = None,
                         stagnant_days: int = 30, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(LeasingLead).where(LeasingLead.park_id.in_(ids)) if ids else select(LeasingLead).where(LeasingLead.id == -1)
    leads = list(db.scalars(q).all())
    if not leads:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有招商线索"], "evidence": _evidence(["leasing_leads"], 0)}

    today = dt.datetime.now()
    stages = ["LEAD", "CONTACTED", "QUALIFIED", "SITE_VISIT", "NEGOTIATION",
              "CONTRACT_APPROVAL", "SIGNED", "SETTLED"]
    names = {"LEAD": "潜在线索", "CONTACTED": "已联系", "QUALIFIED": "有效商机",
             "SITE_VISIT": "实地看房", "NEGOTIATION": "商务谈判",
             "CONTRACT_APPROVAL": "合同审批", "SIGNED": "签约", "SETTLED": "入驻"}
    funnel = []
    for st in stages:
        cnt = len([x for x in leads if x.stage == st])
        idx = stages.index(st)
        reached = len([x for x in leads if x.stage in stages[idx:]])
        funnel.append({"stage": st, "stage_name": names[st], "count": cnt, "reached": reached,
                       "conversion_from_prev": None})

    for i in range(1, len(funnel)):
        prev = funnel[i - 1]["reached"]
        funnel[i]["conversion_from_prev"] = round(funnel[i]["reached"] / prev * 100, 2) if prev else None

    matured = [x for x in leads if x.stage not in ("LEAD", "LOST")]
    signed = [x for x in leads if x.stage in ("SIGNED", "SETTLED")]
    lost = [x for x in leads if x.stage == "LOST"]

    stagnant = []
    for x in leads:
        last = x.last_followup_at or x.updated_at or x.created_at
        if last and x.stage not in ("SIGNED", "SETTLED", "LOST"):
            days = (today - last).days
            if days >= stagnant_days:
                stagnant.append({"lead_id": x.id, "lead_code": x.lead_code, "company_name": x.company_name,
                                 "stage": x.stage, "stage_name": names.get(x.stage, x.stage),
                                 "days_since_followup": days, "owner_name": x.owner_name,
                                 "win_probability": x.win_probability, "demand_area": x.demand_area})
    stagnant.sort(key=lambda x: -x["days_since_followup"])

    # 各园区转化率（用于"哪个园区招商转化率最低"这类问题）
    park_names = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    park_stat = {}
    for x in leads:
        s = park_stat.setdefault(x.park_id, {"park_id": x.park_id,
                                             "park_name": park_names.get(x.park_id, "未知"),
                                             "total": 0, "matured": 0, "signed": 0, "lost": 0})
        s["total"] += 1
        if x.stage not in ("LEAD", "LOST"):
            s["matured"] += 1
        if x.stage in ("SIGNED", "SETTLED"):
            s["signed"] += 1
        if x.stage == "LOST":
            s["lost"] += 1
    park_list = list(park_stat.values())
    for s in park_list:
        s["conversion_rate"] = round(s["signed"] / s["matured"] * 100, 2) if s["matured"] else 0.0
    park_list.sort(key=lambda x: x["conversion_rate"])

    return {
        "data": {
            "total_leads": len(leads),
            "active_leads": len([x for x in leads if x.stage not in ("SIGNED", "SETTLED", "LOST")]),
            "signed_leads": len(signed),
            "lost_leads": len(lost),
            "conversion_rate": round(len(signed) / len(matured) * 100, 2) if matured else 0.0,
            "funnel": funnel,
            "stagnant_leads": stagnant[:20],
            "stagnant_count": len(stagnant),
            "total_demand_area": round(sum(x.demand_area or 0 for x in leads if x.stage not in ("LOST",)), 2),
            "total_investment": round(sum(x.investment_amount or 0 for x in leads if x.stage not in ("LOST",)), 2),
            "park_ranking": park_list,
            "lowest_conversion_park": park_list[0] if park_list else None,
            "top_opportunities": sorted(
                [{"lead_code": x.lead_code, "company_name": x.company_name, "stage": x.stage,
                  "score": x.score, "win_probability": x.win_probability,
                  "demand_area": x.demand_area, "investment_amount": x.investment_amount,
                  "priority": x.priority} for x in leads if x.stage not in ("SIGNED", "SETTLED", "LOST")],
                key=lambda x: -(x["win_probability"] or 0))[:10],
        },
        "evidence": _evidence(["leasing_leads", "leasing_followups"], len(leads),
                              {"park_ids": ids, "stagnant_days": stagnant_days},
                              "转化率 = 签约线索数 / 已进入有效商机及以后的线索数 × 100%"),
        "data_sufficient": True,
    }


# ==========================================================================
# 6. get_contract_expiry
# ==========================================================================


@tool("get_contract_expiry", AIPermissionLevel.L1_QUERY, "获取合同到期预警、续租机会、合同风险",
      ["contracts", "enterprises", "spaces"])
def get_contract_expiry(db: Session, auth: AuthContext, park_id: int | None = None,
                        days: int = 90, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(Contract).where(Contract.park_id.in_(ids)) if ids else select(Contract).where(Contract.id == -1)
    contracts = list(db.scalars(q).all())
    if not contracts:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有合同数据"], "evidence": _evidence(["contracts"], 0)}

    today = dt.date.today()
    active = [c for c in contracts if c.status in ("ACTIVE", "EXPIRING")]
    expiring = sorted([c for c in active if c.end_date and today <= c.end_date <= today + dt.timedelta(days=days)],
                      key=lambda x: x.end_date)
    expired = [c for c in contracts if c.end_date and c.end_date < today and c.status not in ("TERMINATED", "EXPIRED")]

    grouped = {"30天内": [], "31-60天": [], "61-90天": []}
    for c in expiring:
        d = (c.end_date - today).days
        bucket = "30天内" if d <= 30 else ("31-60天" if d <= 60 else "61-90天")
        grouped[bucket].append({
            "contract_id": c.id, "contract_code": c.contract_code, "contract_name": c.contract_name,
            "enterprise_id": c.enterprise_id, "enterprise_name": c.enterprise_name,
            "space_name": c.space_name, "leased_area": c.leased_area,
            "monthly_rent": c.monthly_rent, "end_date": c.end_date.isoformat(),
            "days_left": d, "contract_amount": c.contract_amount,
            "owner_name": c.owner_name,
        })

    return {
        "data": {
            "total_contracts": len(contracts),
            "active_contracts": len(active),
            "expiring_count": len(expiring),
            "expired_not_closed": len(expired),
            "warning_days": days,
            "grouped": grouped,
            "expiring_list": [{"contract_id": c.id, "contract_code": c.contract_code,
                               "enterprise_name": c.enterprise_name, "space_name": c.space_name,
                               "end_date": c.end_date.isoformat(),
                               "days_left": (c.end_date - today).days,
                               "monthly_rent": c.monthly_rent,
                               "annual_rent_impact": round((c.monthly_rent or 0) * 12, 2)}
                              for c in expiring],
            "total_monthly_rent_at_risk": round(sum(c.monthly_rent or 0 for c in expiring), 2),
            "total_annual_rent_at_risk": round(sum((c.monthly_rent or 0) * 12 for c in expiring), 2),
            "total_leased_area_at_risk": round(sum(c.leased_area or 0 for c in expiring), 2),
            "expired_list": [{"contract_code": c.contract_code, "enterprise_name": c.enterprise_name,
                              "end_date": c.end_date.isoformat(), "status": c.status}
                             for c in expired[:20]],
        },
        "evidence": _evidence(["contracts"], len(contracts),
                              {"park_ids": ids, "warning_window_days": days},
                              "到期预警 = 合同结束日期在 [今天, 今天+90天] 区间内"),
        "data_sufficient": True,
    }


# ==========================================================================
# 7-12. 项目相关工具
# ==========================================================================


@tool("get_project_summary", AIPermissionLevel.L1_QUERY,
      "获取项目组合概况：总数/在建/延期/高风险/预算执行/里程碑完成率",
      ["projects", "milestones", "project_risks"])
def get_project_summary(db: Session, auth: AuthContext, park_id: int | None = None,
                        project_manager: str | None = None, project_type: str | None = None,
                        **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(Project).where(Project.park_id.in_(ids)) if ids else select(Project).where(Project.id == -1)
    if project_manager:
        q = q.where(Project.project_manager_name.like(f"%{project_manager}%"))
    if project_type:
        q = q.where(Project.project_type == project_type)
    projects = list(db.scalars(q).all())
    vis = auth.visible_project_ids()
    if vis is not None:
        projects = [p for p in projects if p.id in vis]

    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有项目数据，或无项目数据权限"],
                "evidence": _evidence(["projects"], 0)}

    today = dt.date.today()
    delayed = [p for p in projects if (p.planned_end_date and p.planned_end_date < today
                                       and p.status not in ("COMPLETED", "CLOSED"))]
    budget = sum(p.approved_budget or p.budget or 0 for p in projects)
    actual = sum(p.actual_cost or 0 for p in projects)
    # 里程碑从 milestones 表实时聚合（projects 上的冗余计数列恒为 0，不可用）
    ms_map = project_engine.milestone_stats(db, [p.id for p in projects])
    ms_total = sum(t for t, _ in ms_map.values())
    ms_done = sum(d for _, d in ms_map.values())

    by_method = {m: len([p for p in projects if p.management_method == m])
                 for m in ("WATERFALL", "AGILE", "HYBRID")}
    by_status = {}
    for p in projects:
        by_status[p.status] = by_status.get(p.status, 0) + 1
    by_risk = {}
    for p in projects:
        by_risk[p.risk_level] = by_risk.get(p.risk_level, 0) + 1

    park_names = {p.id: p.park_name for p in db.scalars(select(Park)).all()}
    by_park = {}
    for p in projects:
        s = by_park.setdefault(p.park_id, {"park_id": p.park_id,
                                           "park_name": park_names.get(p.park_id, "未知"),
                                           "count": 0, "delayed": 0, "budget": 0.0, "actual": 0.0})
        s["count"] += 1
        if p.id in {d.id for d in delayed}:
            s["delayed"] += 1
        s["budget"] += p.approved_budget or p.budget or 0
        s["actual"] += p.actual_cost or 0

    return {
        "data": {
            "total": len(projects),
            "in_progress": len([p for p in projects if p.status == "IN_PROGRESS"]),
            "planned": len([p for p in projects if p.status == "PLANNED"]),
            "completed": len([p for p in projects if p.status in ("COMPLETED", "CLOSED")]),
            "delayed": len(delayed),
            "high_risk": len([p for p in projects if p.risk_level in ("HIGH", "CRITICAL")]),
            "total_budget": round(budget, 2),
            "total_actual_cost": round(actual, 2),
            "budget_execution_rate": round(actual / budget * 100, 2) if budget else 0.0,
            "total_investment": round(budget, 2),
            "milestone_total": ms_total,
            "milestone_done": ms_done,
            "milestone_completion_rate": round(ms_done / ms_total * 100, 2) if ms_total else 0.0,
            "avg_progress": round(sum(p.progress or 0 for p in projects) / len(projects), 2),
            "by_management_method": by_method,
            "by_status": by_status,
            "by_risk": by_risk,
            "by_park": list(by_park.values()),
            "delayed_projects": [{"id": p.id, "project_code": p.project_code, "project_name": p.project_name,
                                  "project_manager_name": p.project_manager_name,
                                  "planned_end_date": p.planned_end_date.isoformat() if p.planned_end_date else None,
                                  "delay_days": (today - p.planned_end_date).days if p.planned_end_date else 0,
                                  "progress": p.progress, "risk_level": p.risk_level,
                                  "method": p.management_method}
                                 for p in sorted(delayed, key=lambda x: x.planned_end_date or today)],
            "high_risk_projects": [{"id": p.id, "project_code": p.project_code, "project_name": p.project_name,
                                    "risk_level": p.risk_level, "progress": p.progress,
                                    "budget": p.approved_budget or p.budget,
                                    "actual_cost": p.actual_cost, "status": p.status}
                                   for p in projects if p.risk_level in ("HIGH", "CRITICAL")],
        },
        "evidence": _evidence(["projects", "milestones", "project_risks"], len(projects),
                              {"park_ids": ids, "project_manager": project_manager,
                               "visible_projects": vis},
                              "延期 = 计划结束日期 < 今天 且 状态 ∉ {已完成, 已关闭}"),
        "data_sufficient": True,
    }


@tool("get_project_schedule", AIPermissionLevel.L1_QUERY,
      "获取项目进度分析：计划vs实际进度、延期天数、延期主因、关键路径影响",
      ["projects", "wbs_items", "task_dependencies", "project_risks", "project_changes"])
def get_project_schedule(db: Session, auth: AuthContext, project_id: int | None = None,
                         project_name: str | None = None, **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目，或无数据权限"], "evidence": _evidence(["projects"], 0)}
    out = []
    for p in projects:
        diag = project_engine.compute_schedule_variance(db, p)
        cpm = project_engine.compute_critical_path(db, p.id)
        diag["critical_path"] = cpm["critical_path"]
        diag["critical_path_basis"] = cpm["basis"]
        diag["critical_task_count"] = cpm.get("critical_task_count", 0)
        out.append(diag)
    return {"data": out, "evidence": _evidence(
        ["projects", "wbs_items", "task_dependencies", "project_risks", "project_changes"],
        len(out), {"project_ids": [p.id for p in projects]}), "data_sufficient": True}


@tool("get_project_wbs", AIPermissionLevel.L1_QUERY,
      "获取项目 WBS 结构、任务依赖、关键路径与甘特数据",
      ["wbs_items", "task_dependencies"])
def get_project_wbs(db: Session, auth: AuthContext, project_id: int | None = None,
                    project_name: str | None = None, **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目"], "evidence": _evidence(["projects"], 0)}
    out = []
    for p in projects:
        items = list(db.scalars(
            select(WbsItem).where(WbsItem.project_id == p.id).order_by(WbsItem.sort_order, WbsItem.id)).all())
        if not items:
            out.append({"project_id": p.id, "project_name": p.project_name, "wbs": [],
                        "data_sufficient": False,
                        "missing_data": [f"项目「{p.project_name}」尚未建立 WBS 分解结构"]})
            continue
        cpm = project_engine.compute_critical_path(db, p.id)
        cp_map = {t["wbs_code"]: t for t in cpm["tasks"]}
        out.append({
            "project_id": p.id, "project_name": p.project_name,
            "management_method": p.management_method,
            "wbs": [{
                "id": i.id, "parent_id": i.parent_id, "wbs_code": i.wbs_code,
                "item_name": i.item_name, "item_level": i.item_level,
                "owner_name": i.owner_name, "responsible_role": i.responsible_role,
                "plan_start": i.plan_start.isoformat() if i.plan_start else None,
                "plan_end": i.plan_end.isoformat() if i.plan_end else None,
                "actual_start": i.actual_start.isoformat() if i.actual_start else None,
                "actual_end": i.actual_end.isoformat() if i.actual_end else None,
                "duration_days": i.duration_days, "progress": i.progress,
                "budget": i.budget, "actual_cost": i.actual_cost, "status": i.status,
                "risk_level": i.risk_level,
                "is_critical": cp_map.get(i.wbs_code, {}).get("is_critical", False),
                "slack_days": cp_map.get(i.wbs_code, {}).get("slack_days", 0),
                "predecessors": i.predecessors or [], "successors": i.successors or [],
                "deliverable": i.deliverable,
            } for i in items],
            "critical_path": cpm["critical_path"],
            "project_duration_days": cpm["project_duration_days"],
            "basis": cpm["basis"],
            "data_sufficient": True,
        })
    return {"data": out, "evidence": _evidence(["wbs_items", "task_dependencies"], len(out)),
            "data_sufficient": True}


@tool("get_project_risks", AIPermissionLevel.L2_ADVISE,
      "获取项目风险登记册与 5×5 风险矩阵，并给出AI风险识别建议",
      ["project_risks"])
def get_project_risks(db: Session, auth: AuthContext, project_id: int | None = None,
                      project_name: str | None = None, include_ai_identification: bool = True,
                      **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目"], "evidence": _evidence(["projects"], 0)}
    out = []
    for p in projects:
        r = project_engine.compute_risk_analysis(db, p.id)
        if include_ai_identification:
            r["ai_identified_risks"] = _ai_identify_risks(db, p)
        out.append(r)
    return {"data": out, "evidence": _evidence(["project_risks", "projects", "wbs_items", "project_costs"],
                                               len(out)), "data_sufficient": True}


@tool("get_project_costs", AIPermissionLevel.L1_QUERY,
      "获取项目成本：预算/合同/采购/实际/支付、执行率、CPI/SPI、超支风险",
      ["project_costs", "projects"])
def get_project_costs(db: Session, auth: AuthContext, project_id: int | None = None,
                      project_name: str | None = None, **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目"], "evidence": _evidence(["projects"], 0)}
    out = [project_engine.compute_cost_analysis(db, p) for p in projects]
    return {"data": out, "evidence": _evidence(["project_costs", "projects"], len(out)),
            "data_sufficient": True}


@tool("get_project_changes", AIPermissionLevel.L1_QUERY,
      "获取项目变更记录与变更影响（范围/工期/成本/风险）",
      ["project_changes"])
def get_project_changes(db: Session, auth: AuthContext, project_id: int | None = None,
                        project_name: str | None = None, **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目"], "evidence": _evidence(["projects"], 0)}
    out = []
    for p in projects:
        changes = list(db.scalars(
            select(ProjectChange).where(ProjectChange.project_id == p.id)
            .order_by(ProjectChange.apply_date.desc())).all())
        out.append({
            "project_id": p.id, "project_name": p.project_name,
            "change_count": len(changes),
            "pending_count": len([c for c in changes if c.status in ("PENDING", "IN_REVIEW")]),
            "approved_count": len([c for c in changes if c.status == "APPROVED"]),
            "total_schedule_impact": sum(c.impact_schedule_days or 0 for c in changes if c.status == "APPROVED"),
            "total_cost_impact": round(sum(c.impact_cost or 0 for c in changes if c.status == "APPROVED"), 2),
            "changes": [{
                "id": c.id, "change_code": c.change_code, "change_title": c.change_title,
                "change_type": c.change_type, "change_reason": c.change_reason,
                "before_snapshot": c.before_snapshot, "after_snapshot": c.after_snapshot,
                "impact_schedule_days": c.impact_schedule_days, "impact_cost": c.impact_cost,
                "impact_risk": c.impact_risk, "impact_scope": c.impact_scope,
                "applicant_name": c.applicant_name,
                "apply_date": c.apply_date.isoformat() if c.apply_date else None,
                "approver_name": c.approver_name,
                "approve_date": c.approve_date.isoformat() if c.approve_date else None,
                "status": c.status, "is_baseline_change": c.is_baseline_change,
                "new_baseline_version": c.new_baseline_version,
                "ai_analysis": c.ai_analysis,
            } for c in changes],
            "data_sufficient": True,
        })
    return {"data": out, "evidence": _evidence(["project_changes"], len(out)), "data_sufficient": True}


@tool("get_sprint_status", AIPermissionLevel.L1_QUERY,
      "获取敏捷项目 Sprint 状态、Velocity、燃尽图与看板",
      ["sprints", "user_stories", "sprint_tasks"])
def get_sprint_status(db: Session, auth: AuthContext, project_id: int | None = None,
                      project_name: str | None = None, **kw) -> dict[str, Any]:
    projects = _resolve_projects(db, auth, project_id, project_name)
    agile = [p for p in projects if p.management_method in ("AGILE", "HYBRID")]
    if not agile:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到敏捷或混合式管理项目"],
                "evidence": _evidence(["projects"], 0)}
    out = [project_engine.compute_agile_metrics(db, p.id) for p in agile]
    return {"data": out, "evidence": _evidence(["sprints", "user_stories", "sprint_tasks", "epics"],
                                               len(out)), "data_sufficient": True}


def _resolve_projects(db: Session, auth: AuthContext, project_id: int | None,
                      project_name: str | None) -> list[Project]:
    q = select(Project)
    if project_id:
        q = q.where(Project.id == project_id)
    if project_name:
        q = q.where(Project.project_name.like(f"%{project_name}%"))
    projects = list(db.scalars(q).all())
    vis = auth.visible_project_ids()
    if vis is not None:
        projects = [p for p in projects if p.id in vis]
    return [p for p in projects if auth.can_access_park(p.park_id)]


def _ai_identify_risks(db: Session, p: Project) -> list[dict[str, Any]]:
    """AI 辅助风险识别：仅基于数据库现有事实推导，每条附证据。"""
    today = dt.date.today()
    risks: list[dict[str, Any]] = []
    wbs = list(db.scalars(select(WbsItem).where(WbsItem.project_id == p.id)).all())
    costs = list(db.scalars(select(ProjectCost).where(ProjectCost.project_id == p.id)).all())
    changes = list(db.scalars(select(ProjectChange).where(ProjectChange.project_id == p.id)).all())

    # 1) 延期风险
    delayed = [t for t in wbs if t.plan_end and t.plan_end < today and t.progress < 100]
    if delayed:
        worst = max(delayed, key=lambda x: (today - x.plan_end).days)
        risks.append({
            "risk_type": "延期风险", "level": "HIGH" if (today - worst.plan_end).days > 15 else "MEDIUM",
            "title": f"{len(delayed)} 项任务已超期未完成",
            "detail": f"最严重：{worst.wbs_code} {worst.item_name}，超期 {(today - worst.plan_end).days} 天，完成率 {worst.progress:.0f}%",
            "evidence": [t.wbs_code for t in delayed[:6]],
            "response": "对超期任务重新核定资源投入并更新剩余工期；若在关键路径上需上报项目变更。",
        })

    # 2) 预算超支
    budget = p.approved_budget or p.budget or 0
    actual = p.actual_cost or 0
    if budget and actual / budget > (p.progress / 100 if p.progress else 1):
        ratio = actual / budget
        prog = (p.progress or 0) / 100
        if ratio > prog + 0.08:
            risks.append({
                "risk_type": "预算超支", "level": "HIGH" if ratio > prog + 0.15 else "MEDIUM",
                "title": "成本投入超前于进度产出",
                "detail": f"成本执行率 {ratio*100:.1f}% 高于进度完成率 {prog*100:.1f}%，存在超支风险",
                "evidence": [f"预算 {budget:,.0f} 元", f"实际成本 {actual:,.0f} 元", f"进度 {p.progress}%"],
                "response": "核查成本发生明细，识别超前采购或返工成本；必要时启动预算变更审批。",
            })

    # 3) 采购/供应商风险
    gap_items = [c for c in costs if (c.contract_amount or 0) > (c.paid_amount or 0)]
    if gap_items:
        gap = sum((c.contract_amount or 0) - (c.paid_amount or 0) for c in gap_items)
        risks.append({
            "risk_type": "采购风险", "level": "MEDIUM",
            "title": f"{len(gap_items)} 项采购/合同未完成支付",
            "detail": f"未支付差额合计 {gap:,.0f} 元，可能影响供应商履约",
            "evidence": [c.cost_subject for c in gap_items[:6]],
            "response": "与供应商确认付款节点与交付节点匹配情况，避免因资金问题造成停工。",
        })

    # 4) 变更累积风险
    approved = [c for c in changes if c.status == "APPROVED"]
    total_impact = sum(c.impact_schedule_days or 0 for c in approved)
    if total_impact >= 10:
        risks.append({
            "risk_type": "变更风险", "level": "HIGH" if total_impact >= 30 else "MEDIUM",
            "title": "变更累计影响工期显著",
            "detail": f"{len(approved)} 项已批准变更累计工期影响 {total_impact} 天，成本影响 "
                      f"{sum(c.impact_cost or 0 for c in approved):,.0f} 元",
            "evidence": [c.change_code for c in approved],
            "response": "建立新基线后重新评估关键路径；对后续变更实施更严格的准入控制。",
        })

    # 5) 资源冲突（同一负责人并行任务过多）
    owner_tasks: dict[str, int] = {}
    for t in wbs:
        if t.owner_name and t.status not in ("COMPLETED", "CANCELLED"):
            owner_tasks[t.owner_name] = owner_tasks.get(t.owner_name, 0) + 1
    overload = {k: v for k, v in owner_tasks.items() if v >= 5}
    if overload:
        risks.append({
            "risk_type": "资源冲突", "level": "MEDIUM",
            "title": "存在责任人并行任务过载",
            "detail": "；".join(f"{k} 负责 {v} 项在执行任务" for k, v in overload.items()),
            "evidence": list(overload.keys()),
            "response": "重新分配任务或增加人手，避免关键任务因资源争抢而延期。",
        })

    # 6) 验收/质量风险
    quality_tasks = [t for t in wbs if "验收" in (t.item_name or "") or "质检" in (t.item_name or "")]
    if quality_tasks and any(t.progress < 100 and t.plan_end and t.plan_end < today for t in quality_tasks):
        risks.append({
            "risk_type": "验收风险", "level": "MEDIUM",
            "title": "验收环节进度滞后",
            "detail": "验收类任务存在超期，可能影响项目移交与结算",
            "evidence": [t.wbs_code for t in quality_tasks],
            "response": "提前组织预验收，梳理遗留问题清单，确保正式验收一次通过。",
        })

    return risks


# ==========================================================================
# 13-18. 运营类工具
# ==========================================================================


@tool("get_work_orders", AIPermissionLevel.L1_QUERY, "获取物业工单：完成率、超时、SLA、类型分布",
      ["work_orders"])
def get_work_orders(db: Session, auth: AuthContext, park_id: int | None = None,
                    status: str | None = None, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(WorkOrder).where(WorkOrder.park_id.in_(ids)) if ids else select(WorkOrder).where(WorkOrder.id == -1)
    if status:
        q = q.where(WorkOrder.status == status)
    orders = list(db.scalars(q).all())
    if not orders:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有工单数据"], "evidence": _evidence(["work_orders"], 0)}

    # 与 /operation/work-orders/stats/by-type 共用同一口径实现
    st = property_engine.work_order_stats(orders)
    timeout = [o for o in orders if o.is_timeout]
    return {
        "data": {
            "total": st["total"],
            "open": st["open"],
            "closed": st["closed"],
            "completion_rate": st["completion_rate"],
            "timeout_count": st["timeout_count"],
            "timeout_rate": st["timeout_rate"],
            "avg_response_minutes": st["avg_response_minutes"],
            "avg_handle_hours": st["avg_handle_hours"],
            "avg_rating": st["avg_rating"],
            "by_type": st["by_type_map"],
            "by_priority": st["by_priority"],
            "trend": st["trend"],
            "timeout_orders": [{"order_code": o.order_code, "title": o.title, "order_type": o.order_type,
                                "priority": o.priority, "status": o.status,
                                "submit_at": o.submit_at.isoformat() if o.submit_at else None,
                                "sla_hours": o.sla_hours, "handle_hours": o.handle_hours,
                                "assignee_name": o.assignee_name}
                               for o in timeout[:20]],
            "pending_orders": [{"order_code": o.order_code, "title": o.title, "order_type": o.order_type,
                                "priority": o.priority, "status": o.status, "location": o.location,
                                "assignee_name": o.assignee_name}
                               for o in orders if o.status not in property_engine.CLOSED_STATUSES][:20],
        },
        "evidence": _evidence(["work_orders"], len(orders), {"park_ids": ids, "status": status},
                              "工单完成率 = status∈(CLOSED,RATED) ÷ 工单总数；超时 = is_timeout 为真"),
        "data_sufficient": True,
    }


@tool("get_device_status", AIPermissionLevel.L1_QUERY,
      "获取设备状态：在线率、故障、即将保养、巡检逾期",
      ["devices", "device_inspections"])
def get_device_status(db: Session, auth: AuthContext, park_id: int | None = None,
                      device_type: str | None = None, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(Device).where(Device.park_id.in_(ids)) if ids else select(Device).where(Device.id == -1)
    if device_type:
        q = q.where(Device.device_type == device_type)
    devices = list(db.scalars(q).all())
    if not devices:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有设备台账数据"],
                "evidence": _evidence(["devices"], 0)}

    today = dt.date.today()
    active = [d for d in devices if d.status != "SCRAPPED"]
    fault = [d for d in devices if d.status == "FAULT"]
    maintain_due = [d for d in devices if d.next_maintain_date and d.next_maintain_date <= today + dt.timedelta(days=15)]
    inspect_overdue = [d for d in devices if d.last_inspect_date and d.inspect_cycle_days and
                       (today - d.last_inspect_date).days > d.inspect_cycle_days]
    by_type = {}
    for d in devices:
        s = by_type.setdefault(d.device_type, {"total": 0, "fault": 0, "online": 0})
        s["total"] += 1
        if d.status == "FAULT":
            s["fault"] += 1
        if d.is_online:
            s["online"] += 1
    return {
        "data": {
            "total": len(devices),
            "active": len(active),
            "online": len([d for d in active if d.is_online]),
            "online_rate": round(len([d for d in active if d.is_online]) / len(active) * 100, 2) if active else 0.0,
            "fault_count": len(fault),
            "maintenance_count": len([d for d in devices if d.status == "MAINTENANCE"]),
            "avg_health_score": round(sum(d.health_score for d in devices) / len(devices), 1),
            "iot_connected": len([d for d in devices if d.is_iot_connected]),
            "by_type": by_type,
            "fault_devices": [{"device_code": d.device_code, "device_name": d.device_name,
                               "device_type": d.device_type, "location": d.location,
                               "health_score": d.health_score, "fault_count": d.fault_count,
                               "supplier": d.supplier} for d in fault],
            "maintain_due": [{"device_code": d.device_code, "device_name": d.device_name,
                              "device_type": d.device_type, "location": d.location,
                              "next_maintain_date": d.next_maintain_date.isoformat(),
                              "days_left": (d.next_maintain_date - today).days,
                              "owner_name": d.owner_name} for d in maintain_due],
            "inspect_overdue": [{"device_code": d.device_code, "device_name": d.device_name,
                                 "last_inspect_date": d.last_inspect_date.isoformat(),
                                 "inspect_cycle_days": d.inspect_cycle_days,
                                 "overdue_days": (today - d.last_inspect_date).days - d.inspect_cycle_days}
                                for d in inspect_overdue],
        },
        "evidence": _evidence(["devices", "device_inspections"], len(devices),
                              {"park_ids": ids, "device_type": device_type}),
        "data_sufficient": True,
    }


@tool("get_energy_summary", AIPermissionLevel.L2_ADVISE,
      "获取能耗总览：分类型/分楼栋/分企业/分时、同比环比、单位面积能耗、异常识别",
      ["energy_records"])
def get_energy_summary(db: Session, auth: AuthContext, park_id: int | None = None,
                       days: int = 30, building_id: int | None = None, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(EnergyRecord).where(EnergyRecord.park_id.in_(ids)) if ids else select(EnergyRecord).where(EnergyRecord.id == -1)
    if building_id:
        q = q.where(EnergyRecord.building_id == building_id)
    records = list(db.scalars(q).all())
    if not records:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["能耗设备尚未接入，未采集到能耗数据"],
                "conclusion": "能耗设备尚未接入，无法进行能耗分析。",
                "evidence": _evidence(["energy_records"], 0)}

    today = dt.date.today()
    window_start = today - dt.timedelta(days=days)
    prev_start = window_start - dt.timedelta(days=days)
    cur = [r for r in records if r.record_date and window_start <= r.record_date <= today]
    prev = [r for r in records if r.record_date and prev_start <= r.record_date < window_start]

    # 标签/单位统一取自 core/enums.py，避免各处自维护一份中英映射
    types = ENUM_LABELS["EnergyType"]
    units = ENERGY_UNITS
    by_type = []
    for et in ENERGY_TYPE_ORDER:
        label = types.get(et, et)
        c = sum(r.consumption or 0 for r in cur if r.energy_type == et)
        p = sum(r.consumption or 0 for r in prev if r.energy_type == et)
        if c == 0 and p == 0:
            continue
        by_type.append({
            "energy_type": et, "label": label, "unit": units[et],
            "consumption": round(c, 2),
            "prev_consumption": round(p, 2),
            "mom": round((c - p) / p * 100, 2) if p else None,
            "cost": round(sum(r.cost or 0 for r in cur if r.energy_type == et), 2),
            "carbon": round(sum(r.carbon_kg or 0 for r in cur if r.energy_type == et), 2),
        })

    # 按楼栋
    blds = list(db.scalars(select(Building).where(Building.park_id.in_(ids))).all()) if ids else []
    by_building = []
    for b in blds:
        c = sum(r.consumption or 0 for r in cur if r.building_id == b.id and r.energy_type == "ELECTRICITY")
        area = b.build_area or 0
        by_building.append({"building_id": b.id, "building_name": b.building_name,
                            "consumption": round(c, 2),
                            "unit_consumption": round(c / area, 3) if area else None,
                            "area": area})
    by_building.sort(key=lambda x: -(x["unit_consumption"] or 0))

    # 按企业
    ent_ids = {r.enterprise_id for r in cur if r.enterprise_id}
    ents = {e.id: e for e in db.scalars(select(Enterprise).where(Enterprise.id.in_(ent_ids))).all()} if ent_ids else {}
    by_enterprise = []
    for eid in ent_ids:
        c = sum(r.consumption or 0 for r in cur if r.enterprise_id == eid and r.energy_type == "ELECTRICITY")
        e = ents.get(eid)
        area = (e.leased_area if e else 0) or 0
        by_enterprise.append({"enterprise_id": eid,
                              "enterprise_name": e.enterprise_name if e else f"企业#{eid}",
                              "industry": e.industry if e else None,
                              "consumption": round(c, 2),
                              "unit_consumption": round(c / area, 3) if area else None,
                              "leased_area": area})
    by_enterprise.sort(key=lambda x: -(x["unit_consumption"] or 0))

    # 分时
    hourly = {}
    for r in cur:
        if r.record_hour is not None:
            hourly[r.record_hour] = hourly.get(r.record_hour, 0) + (r.consumption or 0)
    hourly_data = [{"hour": h, "consumption": round(hourly.get(h, 0), 2)} for h in range(24)]
    night = sum(v for h, v in hourly.items() if h in (0, 1, 2, 3, 4, 5))
    day = sum(v for h, v in hourly.items() if 8 <= h <= 20)
    night_ratio = round(night / (night + day) * 100, 2) if (night + day) else None

    # 异常
    anomalies = [r for r in cur if r.is_anomaly]
    anomaly_list = sorted([{
        "id": r.id, "energy_type": r.energy_type,
        "label": types.get(r.energy_type, r.energy_type),
        "record_date": r.record_date.isoformat(),
        "record_hour": r.record_hour,
        "building_id": r.building_id,
        "building_name": next((b.building_name for b in blds if b.id == r.building_id), None),
        "enterprise_id": r.enterprise_id,
        "enterprise_name": ents.get(r.enterprise_id).enterprise_name if r.enterprise_id in ents else None,
        "consumption": r.consumption, "baseline": r.baseline,
        "anomaly_ratio": r.anomaly_ratio, "note": r.anomaly_note,
    } for r in anomalies], key=lambda x: -abs(x["anomaly_ratio"] or 0))

    # 趋势
    trend = {}
    for r in records:
        if r.record_date and r.energy_type == "ELECTRICITY":
            k = r.record_date.isoformat()
            trend[k] = round(trend.get(k, 0) + (r.consumption or 0), 2)
    trend_list = [{"date": k, "consumption": v} for k, v in sorted(trend.items())]

    total_carbon = round(sum(r.carbon_kg or 0 for r in cur), 2)
    space_area = sum(s.rentable_area or s.area or 0 for s in db.scalars(
        select(Space).where(Space.park_id.in_(ids))).all()) if ids else 0

    return {
        "data": {
            "window_days": days,
            "by_type": by_type,
            "by_building": by_building,
            "by_enterprise": by_enterprise[:20],
            "hourly": hourly_data,
            "night_consumption_ratio": night_ratio,
            "night_consumption": round(night, 2),
            "day_consumption": round(day, 2),
            "anomaly_count": len(anomaly_list),
            "anomalies": anomaly_list[:20],
            "trend": trend_list,
            "total_carbon_kg": total_carbon,
            "total_carbon_ton": round(total_carbon / 1000, 3),
            "total_area": round(space_area, 2),
            "unit_area_consumption": round(sum(r.consumption or 0 for r in cur if r.energy_type == "ELECTRICITY") /
                                          space_area, 3) if space_area else None,
        },
        "evidence": _evidence(["energy_records", "buildings", "enterprises", "spaces"], len(records),
                              {"park_ids": ids, "window_days": days, "building_id": building_id},
                              "异常判定：单条记录用量偏离同类型基线（baseline 字段）超过阈值"),
        "data_sufficient": True,
    }


@tool("get_safety_risks", AIPermissionLevel.L2_ADVISE,
      "获取安全风险：安全指数、未闭环事件、隐患、逾期整改、危险源",
      ["safety_incidents", "safety_hazards"])
def get_safety_risks(db: Session, auth: AuthContext, park_id: int | None = None, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(SafetyIncident).where(SafetyIncident.park_id.in_(ids)) if ids else select(SafetyIncident).where(SafetyIncident.id == -1)
    incidents = list(db.scalars(q).all())
    hq = select(SafetyHazard).where(SafetyHazard.park_id.in_(ids)) if ids else select(SafetyHazard).where(SafetyHazard.id == -1)
    hazards = list(db.scalars(hq).all())

    if not incidents and not hazards:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有安全事件与隐患记录"],
                "evidence": _evidence(["safety_incidents"], 0)}

    today = dt.date.today()
    open_inc = [i for i in incidents if i.status != "CLOSED"]
    critical = [i for i in incidents if i.risk_level in ("CRITICAL", "URGENT")]
    overdue = [i for i in incidents if i.rectify_deadline and i.rectify_deadline < today and i.status != "CLOSED"]

    # 安全指数走单一数据源。原实现在此额外扣「未闭环隐患 × 1」，
    # 502 条隐患直接把指数压到 0 分，与安全页面的 90+ 分自相矛盾。
    score, safety_status, score_model = safety_engine.score_model(incidents)

    by_type = {}
    for i in incidents:
        s = by_type.setdefault(i.incident_type, {"total": 0, "open": 0, "critical": 0})
        s["total"] += 1
        if i.status != "CLOSED":
            s["open"] += 1
        if i.risk_level in ("CRITICAL", "URGENT"):
            s["critical"] += 1

    closed = [i for i in incidents if i.status == "CLOSED"]
    handle_hours = [i.handle_hours for i in closed if i.handle_hours]
    return {
        "data": {
            "safety_score": score,
            "safety_status": safety_status,
            "score_model": score_model,
            "total_incidents": len(incidents),
            "open_incidents": len(open_inc),
            "closed_incidents": len(closed),
            "closure_rate": round(len(closed) / len(incidents) * 100, 2) if incidents else 0.0,
            "critical_open": len([i for i in critical if i.status != "CLOSED"]),
            "overdue_rectify": len(overdue),
            "avg_handle_hours": round(sum(handle_hours) / len(handle_hours), 1) if handle_hours else None,
            "hazard_total": len(hazards),
            "hazard_open": len([h for h in hazards if h.status != "CLOSED"]),
            "by_type": by_type,
            "critical_incidents": [{"id": i.id, "incident_code": i.incident_code, "title": i.title,
                                    "incident_type": i.incident_type, "risk_level": i.risk_level,
                                    "location": i.location, "status": i.status,
                                    "found_at": i.found_at.isoformat() if i.found_at else None,
                                    "responsible_dept": i.responsible_dept,
                                    "rectify_deadline": i.rectify_deadline.isoformat() if i.rectify_deadline else None,
                                    "is_overdue": i.is_overdue,
                                    "handle_hours": i.handle_hours}
                                   for i in incidents if i.risk_level in ("CRITICAL", "URGENT")],
            "open_incident_list": [{"id": i.id, "incident_code": i.incident_code, "title": i.title,
                                    "incident_type": i.incident_type, "risk_level": i.risk_level,
                                    "status": i.status, "location": i.location,
                                    "responsible_dept": i.responsible_dept,
                                    "rectify_deadline": i.rectify_deadline.isoformat() if i.rectify_deadline else None,
                                    "is_overdue": i.is_overdue}
                                   for i in open_inc],
            "overdue_list": [{"incident_code": i.incident_code, "title": i.title,
                              "rectify_deadline": i.rectify_deadline.isoformat(),
                              "overdue_days": (today - i.rectify_deadline).days,
                              "responsible_dept": i.responsible_dept}
                             for i in overdue],
        },
        "evidence": _evidence(["safety_incidents", "safety_hazards"], len(incidents) + len(hazards),
                              {"park_ids": ids},
                              score_model["formula"]),
        "data_sufficient": True,
    }


@tool("get_financial_summary", AIPermissionLevel.L1_QUERY,
      "获取财务收费概览：应收/实收/欠费/收缴率/账龄/欠费企业排名",
      ["bills", "payments", "contracts"])
def get_financial_summary(db: Session, auth: AuthContext, park_id: int | None = None,
                          months: int = 12, **kw) -> dict[str, Any]:
    ids = _scoped_park_ids(db, auth, park_id)
    q = select(Bill).where(Bill.park_id.in_(ids)) if ids else select(Bill).where(Bill.id == -1)
    bills = list(db.scalars(q).all())
    if not bills:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["当前范围内没有账单数据"], "evidence": _evidence(["bills"], 0)}

    today = dt.date.today()
    month_start = today.replace(day=1)
    window_start = month_start - dt.timedelta(days=months * 31)

    cur = [b for b in bills if b.bill_date and month_start <= b.bill_date <= today]
    ytd = [b for b in bills if b.bill_date and b.bill_date >= dt.date(today.year, 1, 1)]
    overdue_list = [b for b in bills if b.status == "OVERDUE"]
    unsettled = [b for b in bills if b.status in ("UNPAID", "PARTIAL", "OVERDUE")]

    def s(items, attr):
        return round(sum(getattr(i, attr) or 0 for i in items), 2)

    by_fee_type = {}
    for b in bills:
        row = by_fee_type.setdefault(b.fee_type, {"receivable": 0.0, "received": 0.0, "arrears": 0.0})
        row["receivable"] += b.receivable or 0
        row["received"] += b.received or 0
        row["arrears"] += b.arrears or 0

    # 欠费企业排名
    ent_arrears = {}
    for b in unsettled:
        if b.arrears and b.arrears > 0:
            s2 = ent_arrears.setdefault(b.enterprise_id, {"enterprise_id": b.enterprise_id,
                                                          "enterprise_name": b.enterprise_name,
                                                          "arrears": 0.0, "bill_count": 0,
                                                          "max_overdue_days": 0})
            s2["arrears"] += b.arrears
            s2["bill_count"] += 1
            s2["max_overdue_days"] = max(s2["max_overdue_days"], b.overdue_days or 0)
    ent_list = sorted(ent_arrears.values(), key=lambda x: -x["arrears"])
    for e in ent_list:
        e["arrears"] = round(e["arrears"], 2)

    # 账龄：键与 bills.age_bucket 实际取值对齐（core/enums.AGE_BUCKETS）
    age_rows = []
    for k in AGE_BUCKETS:
        items = [b for b in unsettled if b.age_bucket == k]
        age_rows.append({"bucket": k, "name": AGE_BUCKET_LABELS[k],
                         "amount": s(items, "arrears"), "count": len(items)})

    # 趋势
    trend = []
    for i in range(months - 1, -1, -1):
        y = month_start.year + (month_start.month - 1 - i) // 12
        m = (month_start.month - 1 - i) % 12 + 1
        ms = dt.date(y, m, 1)
        me = dt.date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
        mb = [b for b in bills if b.bill_date and ms <= b.bill_date < me]
        trend.append({"month": f"{y}-{m:02d}", "receivable": s(mb, "receivable"),
                      "received": s(mb, "received"), "arrears": s(mb, "arrears")})

    all_due = [b for b in bills if b.due_date and b.due_date <= today and (b.receivable or 0) > 0]
    collection_rate = round(s(all_due, "received") / s(all_due, "receivable") * 100, 2) if s(all_due, "receivable") else 0.0

    return {
        "data": {
            "total_bills": len(bills),
            "month_receivable": s(cur, "receivable"),
            "month_received": s(cur, "received"),
            "month_arrears": s(cur, "arrears"),
            "ytd_received": s(ytd, "received"),
            "ytd_receivable": s(ytd, "receivable"),
            "total_arrears": s(unsettled, "arrears"),
            "overdue_arrears": s(overdue_list, "arrears"),
            "overdue_count": len(overdue_list),
            "collection_rate": collection_rate,
            "unsettled_count": len(unsettled),
            "by_fee_type": [{"fee_type": k, **{kk: round(vv, 2) for kk, vv in v.items()}}
                            for k, v in by_fee_type.items()],
            "arrears_by_enterprise": ent_list[:20],
            "arrears_age": age_rows,
            "trend": trend,
            "top_arrears": ent_list[:5],
        },
        "evidence": _evidence(["bills", "payments", "contracts"], len(bills),
                              {"park_ids": ids, "months": months},
                              "收缴率 = 已到期账单实收 / 已到期账单应收 × 100%；"
                              "账龄按 due_date 距今时长分桶"),
        "data_sufficient": True,
    }


@tool("get_policy_matches", AIPermissionLevel.L2_ADVISE,
      "企业政策匹配：按行业/规模/资质/研发/知识产权/成长阶段匹配政策，输出匹配度与核验建议",
      ["policies", "enterprises", "policy_matches"])
def get_policy_matches(db: Session, auth: AuthContext, enterprise_id: int | None = None,
                       enterprise_name: str | None = None, park_id: int | None = None,
                       **kw) -> dict[str, Any]:
    policies = list(db.scalars(select(Policy).where(Policy.status == "ACTIVE")).all())
    if not policies:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["政策知识库为空"], "evidence": _evidence(["policies"], 0)}

    q = select(Enterprise)
    if enterprise_id:
        q = q.where(Enterprise.id == enterprise_id)
    if enterprise_name:
        q = q.where(Enterprise.enterprise_name.like(f"%{enterprise_name}%"))
    if park_id:
        q = q.where(Enterprise.park_id == park_id)
    ents = [e for e in db.scalars(q).all() if e.park_id is None or auth.can_access_park(e.park_id)]
    if not ents:
        cand = _closest_enterprise_names(db, auth, enterprise_name)
        msg = (f"未找到名称包含「{enterprise_name}」的企业，无法进行政策匹配"
               + (f"；库内相近企业：{'、'.join(cand)}" if cand else "")) \
            if enterprise_name else "当前数据范围内没有可访问的企业档案，无法进行政策匹配"
        return {"data": None, "data_sufficient": False,
                "missing_data": [msg], "candidates": cand,
                "evidence": _evidence(["enterprises"], 0)}

    results = []
    for e in ents:
        matches = []
        for p in policies:
            m = _match_policy(e, p)
            if m:
                matches.append(m)
        matches.sort(key=lambda x: -x["match_score"])
        missing = []
        if not e.employee_count:
            missing.append("员工人数")
        if not e.annual_revenue:
            missing.append("年度营业收入")
        if e.ip_count == 0:
            missing.append("知识产权数量（若确实为 0 则可正常申报）")
        if not e.industry:
            missing.append("所属行业")
        results.append({
            "enterprise_id": e.id, "enterprise_name": e.enterprise_name,
            "industry": e.industry, "employee_count": e.employee_count,
            "annual_revenue": e.annual_revenue, "ip_count": e.ip_count,
            "is_high_tech": e.is_high_tech, "is_specialized": e.is_specialized,
            "is_tech_sme": e.is_tech_sme,
            "matches": matches,
            "missing_data": missing,
            "confidence_note": ("企业关键字段存在缺失，匹配结论仅可用于初步参考，需补充数据后核验。"
                                if missing else "企业关键字段完整，匹配结论可作为申报参考。"),
        })

    return {
        "data": results,
        "evidence": _evidence(["policies", "enterprises", "policy_matches"],
                              len(policies) * len(ents),
                              {"enterprise_id": enterprise_id, "policy_count": len(policies)},
                              "匹配度 = 逐条政策公开条件与企业档案字段比对加权计算"),
        "data_sufficient": True,
        "disclaimer": "政策匹配结论仅表示「可能符合」或「建议核验」，不构成申报资格确认。",
    }


def _policy_conditions(p: Policy) -> dict[str, Any]:
    """安全读取 Policy.conditions。

    该列声明为 JSON，但历史上 seeder 曾写入纯字符串，导致 cond.get() 抛
    AttributeError，被 call_tool 吞成"数据不足"，政策AI 长期静默失效。
    这里做一层容错：非 dict 一律视为无结构化条件，并打印告警，让问题可见。
    """
    cond = p.conditions
    if isinstance(cond, dict):
        return cond
    if cond:
        logger.warning("政策 %s 的 conditions 不是 dict（实际 %s），已按无条件处理；"
                       "请执行 python migrate_policy_conditions.py 修复存量数据",
                       getattr(p, "policy_code", "?"), type(cond).__name__)
    return {}


def _match_policy(e: Enterprise, p: Policy) -> dict[str, Any] | None:
    """结构化政策匹配：逐条件比对，输出匹配理由与缺失数据。"""
    cond = _policy_conditions(p)
    total = 0
    hit = 0
    reasons = []
    missing = []
    risks = []

    def check(key: str, ok: bool | None, desc: str):
        nonlocal total, hit
        total += 1
        if ok is None:
            missing.append(desc)
        elif ok:
            hit += 1
            reasons.append(f"✓ {desc}")

    # 行业
    if cond.get("industries"):
        ok = None if not e.industry else (e.industry in cond["industries"] or
                                          any(i in (e.industry or "") for i in cond["industries"]))
        check("industries", ok, f"所属行业是否属于 {('/'.join(cond['industries']))}")
    # 营收区间（万元）
    if cond.get("revenue_min") is not None or cond.get("revenue_max") is not None:
        if not e.annual_revenue:
            check("revenue", None, "年度营业收入是否在政策区间内")
        else:
            lo = cond.get("revenue_min", 0)
            hi = cond.get("revenue_max", float("inf"))
            check("revenue", lo <= e.annual_revenue <= hi,
                  f"年度营业收入 {e.annual_revenue} 万元是否在 {lo}-{hi} 万元区间")
    # 员工数
    if cond.get("employee_min") is not None or cond.get("employee_max") is not None:
        if not e.employee_count:
            check("employee", None, "员工人数是否满足要求")
        else:
            lo = cond.get("employee_min", 0)
            hi = cond.get("employee_max", float("inf"))
            check("employee", lo <= e.employee_count <= hi,
                  f"员工人数 {e.employee_count} 人是否满足 {lo}-{hi} 人要求")
    # 知识产权
    if cond.get("ip_min") is not None:
        check("ip", e.ip_count >= cond["ip_min"],
              f"知识产权数量 {e.ip_count} 项是否达到 {cond['ip_min']} 项要求")
    if cond.get("invention_patent_min") is not None:
        check("invention", e.invention_patent_count >= cond["invention_patent_min"],
              f"发明专利 {e.invention_patent_count} 项是否达到 {cond['invention_patent_min']} 项要求")
    # 研发人员占比
    if cond.get("rnd_ratio_min") is not None:
        if not e.employee_count:
            check("rnd_ratio", None, "研发人员占比是否达标")
        else:
            ratio = (e.rnd_employee_count or 0) / e.employee_count * 100
            check("rnd_ratio", ratio >= cond["rnd_ratio_min"],
                  f"研发人员占比 {ratio:.1f}% 是否达到 {cond['rnd_ratio_min']}% 要求")
    # 企业资质
    if cond.get("require_high_tech"):
        check("high_tech", e.is_high_tech, "是否为高新技术企业")
    if cond.get("require_specialized"):
        check("specialized", e.is_specialized, "是否为专精特新企业")
    if cond.get("require_tech_sme"):
        check("tech_sme", e.is_tech_sme, "是否为科技型中小企业")
    # 注册年限
    if cond.get("established_years_min") is not None:
        if not e.established_date:
            check("years", None, "企业注册年限是否满足要求")
        else:
            years = (dt.date.today() - e.established_date).days / 365
            check("years", years >= cond["established_years_min"],
                  f"成立 {years:.1f} 年是否满足 {cond['established_years_min']} 年要求")

    if total == 0:
        return None
    score = round(hit / total * 100, 1)

    if e.risk_level in ("HIGH", "CRITICAL"):
        risks.append(f"企业当前风险等级为 {e.risk_level}，申报前建议先核实经营状态。")

    if missing:
        level = "数据不足"
        reason = "关键数据缺失，无法给出匹配结论：" + "、".join(missing)
    elif score >= 80:
        level = "可能符合"
        reason = "；".join(reasons)
    elif score >= 50:
        level = "建议核验"
        reason = "；".join(reasons) + (f"；另有 {total - hit} 项条件未满足，建议核验后申报。" if total > hit else "")
    else:
        level = "建议核验"
        reason = f"仅满足 {hit}/{total} 项条件：" + "；".join(reasons)

    return {
        "policy_id": p.id, "policy_code": p.policy_code, "policy_name": p.policy_name,
        "policy_level": p.policy_level, "policy_category": p.policy_category,
        "issuing_authority": p.issuing_authority, "subsidy_amount": p.subsidy_amount,
        "deadline": p.deadline.isoformat() if p.deadline else None,
        "days_to_deadline": (p.deadline - dt.date.today()).days if p.deadline else None,
        "match_score": score, "match_level": level, "match_reason": reason,
        "missing_data": missing, "risk_note": "；".join(risks) if risks else None,
        "requirement": p.requirement,
        "material_list": p.material_list or [],
        "condition_hit": hit, "condition_total": total,
    }


# ==========================================================================
# 19-20. 写操作工具：仅生成建议 / 待审批单据（L3 全部需人工审批）
# ==========================================================================


@tool("create_ai_recommendation", AIPermissionLevel.L2_ADVISE,
      "生成一条 AI 建议（写入 ai_recommendations，供驾驶舱 AI 洞察展示）",
      ["ai_recommendations"])
def create_ai_recommendation(db: Session, auth: AuthContext, *, title: str, summary: str,
                             category: str = "经营管理", agent_key: str = "operations",
                             severity: str = "INFO", suggestion: str = "",
                             park_id: int | None = None, evidence: dict | None = None,
                             permission_level: str = "L2",
                             decision_status: str = "AI建议",
                             action_label: str | None = None,
                             action_route: str | None = None,
                             detail: dict | None = None) -> dict[str, Any]:
    from app.models import AIRecommendation
    import itertools

    code = f"AIR{dt.datetime.now():%Y%m%d%H%M%S}{abs(hash(title)) % 1000:03d}"
    rec = AIRecommendation(
        rec_code=code, park_id=park_id, agent_key=agent_key, category=category,
        title=title, summary=summary, detail=detail, severity=severity,
        confidence=evidence.get("confidence", 0.85) if evidence else 0.85,
        related_module=category, evidence=evidence, suggestion=suggestion,
        action_label=action_label, action_route=action_route,
        permission_level=permission_level, decision_status=decision_status,
        status="OPEN", generated_date=dt.date.today(),
    )
    db.add(rec)
    db.flush()
    return {
        "data": {"id": rec.id, "rec_code": code, "title": title},
        "evidence": _evidence(["ai_recommendations"], 1, formula="AI 分析结果落库"),
        "data_sufficient": True,
        "decision_status": decision_status,
        "permission_level": permission_level,
    }


@tool("create_approval_request", AIPermissionLevel.L3_ACTION,
      "创建审批申请（L3 高影响动作：合同签署/资金支付/企业退出/处罚/重大采购/供应商淘汰/重大变更/价格调整）。"
      "AI 只能创建待审批单据，不得自行执行。",
      ["approval_requests", "approval_steps"])
def create_approval_request(db: Session, auth: AuthContext, *, approval_type: str, title: str,
                            content: str = "", amount: float = 0.0,
                            park_id: int | None = None,
                            related_object_type: str | None = None,
                            related_object_id: int | None = None,
                            enterprise_id: int | None = None, project_id: int | None = None,
                            risk_level: str = "LOW", urgency: str = "NORMAL",
                            ai_analysis: dict | None = None,
                            steps: list[dict] | None = None) -> dict[str, Any]:
    steps = steps or [
        {"step_name": "业务负责人初审", "approver_role": "PARK_MANAGER"},
        {"step_name": "园区负责人复审", "approver_role": "PARK_MANAGER"},
        {"step_name": "集团审批", "approver_role": "GROUP_ADMIN"},
    ]
    count = db.scalar(select(func.count()).select_from(ApprovalRequest)) or 0
    code = f"APP{dt.datetime.now():%Y%m%d}{count + 1:04d}"
    req = ApprovalRequest(
        approval_code=code, approval_type=approval_type, title=title, park_id=park_id,
        related_object_type=related_object_type, related_object_id=related_object_id,
        enterprise_id=enterprise_id, project_id=project_id, amount=amount,
        content=content, ai_analysis=ai_analysis, risk_level=risk_level, urgency=urgency,
        status="PENDING", current_step=1, total_steps=len(steps),
        applicant_id=auth.user.id, applicant_name=auth.user.real_name,
        apply_at=dt.datetime.now(), is_ai_generated=True, source="AI建议",
    )
    db.add(req)
    db.flush()
    from app.models import ApprovalStep

    for i, s in enumerate(steps, start=1):
        db.add(ApprovalStep(approval_id=req.id, step_no=i, step_name=s["step_name"],
                            approver_role=s.get("approver_role"), status="PENDING"))
    db.flush()
    return {
        "data": {"id": req.id, "approval_code": code, "title": title,
                 "total_steps": len(steps), "status": "PENDING"},
        "evidence": _evidence(["approval_requests", "approval_steps"], 1,
                              formula="L3 高影响动作：仅创建待审批单据，不执行实际业务动作"),
        "data_sufficient": True,
        "decision_status": "待审批",
        "permission_level": AIPermissionLevel.L3_ACTION,
        "notice": "该申请已提交人工审批流程，AI 无权自行执行该动作。",
    }


# ==========================================================================
# 21-22. 报告生成
# ==========================================================================


@tool("generate_operating_report", AIPermissionLevel.L2_ADVISE,
      "生成园区运营报告（经营/招商/空间/财务/物业/设备/能源/安全）",
      ["parks", "enterprises", "spaces", "leasing_leads", "contracts", "bills",
       "work_orders", "devices", "energy_records", "safety_incidents", "projects"])
def generate_operating_report(db: Session, auth: AuthContext, park_id: int | None = None,
                              period: str | None = None, **kw) -> dict[str, Any]:
    from app.services.report_service import build_operating_report

    report = build_operating_report(db, auth, park_id=park_id, period=period)
    return {"data": report, "evidence": report.get("evidence"), "data_sufficient": True}


@tool("generate_project_report", AIPermissionLevel.L2_ADVISE,
      "生成项目报告（周报/月报/风险报告/复盘）",
      ["projects", "wbs_items", "milestones", "project_costs", "project_risks", "project_changes"])
def generate_project_report(db: Session, auth: AuthContext, project_id: int | None = None,
                            project_name: str | None = None, report_type: str = "WEEKLY",
                            **kw) -> dict[str, Any]:
    from app.services.report_service import build_project_report

    projects = _resolve_projects(db, auth, project_id, project_name)
    if not projects:
        return {"data": None, "data_sufficient": False,
                "missing_data": ["未找到指定项目"], "evidence": _evidence(["projects"], 0)}
    reports = [build_project_report(db, p, report_type) for p in projects]
    return {"data": reports, "evidence": _evidence(["projects", "wbs_items", "milestones",
                                                    "project_costs", "project_risks"],
                                                   len(reports)), "data_sufficient": True}


def call_tool(name: str, db: Session, auth: AuthContext, **kwargs) -> dict[str, Any]:
    """统一工具调用入口，附加调用元信息。

    ⚠ 工具内部异常必须与"业务数据不足"区分开：
    历史实现把异常信息塞进 missing_data，于是 NameError（SafetyHazard 未导入）
    在前端显示成"数据缺失：name 'SafetyHazard' is not defined"，
    安全AI / 政策AI 因此静默失效很久都没被发现。
    现在异常统一标记 tool_error=True 并写 ERROR 日志，便于 check_tools.py 断言。
    """
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return {"error": f"未知工具：{name}", "tool_error": True, "data_sufficient": False,
                "missing_data": [f"工具 {name} 未注册"], "_tool": name}
    try:
        result = entry["fn"](db, auth, **kwargs)
        result["_tool"] = name
        result["_level"] = entry["level"]
        result["_description"] = entry["description"]
        return result
    except TypeError as exc:
        logger.exception("Agent 工具 %s 参数错误（kwargs=%s）", name, sorted(kwargs))
        return {"error": f"工具 {name} 参数错误：{exc}", "tool_error": True,
                "data_sufficient": False,
                "missing_data": [f"系统异常（参数错误）：{exc}"], "_tool": name}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent 工具 %s 执行失败（kwargs=%s）", name, sorted(kwargs))
        return {"error": f"工具 {name} 执行失败：{exc}", "tool_error": True,
                "data_sufficient": False,
                "missing_data": [f"系统异常：{exc}"], "_tool": name}


def list_tools() -> list[dict[str, Any]]:
    return [{"name": k, "level": v["level"], "description": v["description"], "tables": v["tables"]}
            for k, v in TOOL_REGISTRY.items()]

"""经营决策：招商方案沙盘、续租风险清单、建议执行任务。

设计取舍（对应提示词 02/03/04/05/10）：

* **算与判分离**：所有数字由 `operating_engine` 的纯函数算出，本层只做取数、鉴权、落库；
  风险由 `renewal_risk_engine` 的规则产出。任何地方都不调用大模型生成财务数字。
* **AI 不写正式数据**：本模块的写操作只有两类——保存方案（只读推演结果）与
  创建/推进任务（走审批状态机）。调价、改合同、减免账单都不在这里发生。
* **越权按企业范围过滤**：沙盘空间、风险合同、任务都按 `visible_park_ids()` 与
  企业范围裁剪，沿用 security.py 的 fail-closed 约定。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.audit import write_audit
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Bill,
    Contract,
    Enterprise,
    OperatingAction,
    OperatingRiskReview,
    OperatingScenario,
    Space,
    User,
    WorkOrder,
)
from app.schemas.common import paginate
from app.services import operating_engine as engine
from app.services import operating_service

router = APIRouter(prefix="/operating", tags=["经营决策"])

#: 任务状态机：只允许这些迁移，任何越级都会被拒（提示词 05）
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("PENDING_APPROVAL", "CANCELLED"),
    "PENDING_APPROVAL": ("APPROVED", "REJECTED", "CANCELLED"),
    "APPROVED": ("IN_PROGRESS", "CANCELLED"),
    "REJECTED": ("DRAFT", "CANCELLED"),
    "IN_PROGRESS": ("PENDING_REVIEW",),
    "PENDING_REVIEW": ("CLOSED", "IN_PROGRESS"),
    "CLOSED": (),
    "CANCELLED": (),
}

#: 需要审批动作才能推进的迁移（审批人 ≠ 创建人，防自审）
NEED_APPROVE_PERM = {"APPROVED", "REJECTED", "CLOSED"}

STATUS_LABELS = {
    "DRAFT": "草稿", "PENDING_APPROVAL": "待审批", "APPROVED": "已批准",
    "REJECTED": "已驳回", "IN_PROGRESS": "执行中", "PENDING_REVIEW": "待验收",
    "CLOSED": "已关闭", "CANCELLED": "已取消",
}

TASK_TEMPLATES = {
    "PROPERTY_FIX": ("物业整改", "物业运维", 72),
    "LEASING_FOLLOWUP": ("招商跟进", "招商运营", 48),
    "ENTERPRISE_VISIT": ("企业回访", "企业服务", 24),
}


# --------------------------------------------------------------------------- 契约
class ScenarioInput(BaseModel):
    space_id: int | None = None
    area: float = Field(gt=0, le=200_000)
    list_rent: float = Field(gt=0, le=10_000)
    lease_months: int = Field(default=36, ge=1, le=engine.MAX_LEASE_MONTHS)
    vacancy_days: int = Field(default=60, ge=0, le=365)
    discount: float = Field(default=0.0, ge=0, le=engine.MAX_DISCOUNT)
    rent_free_months: int = Field(default=0, ge=0, le=engine.MAX_RENT_FREE_MONTHS)
    commission_months: float = Field(default=0.5, ge=0, le=6)
    fitout_per_sqm: float = Field(default=0.0, ge=0, le=10_000)
    service_cost_monthly: float = Field(default=0.0, ge=0)
    payment_cycle_days: int = Field(default=30, ge=0, le=180)
    name: str | None = None


class ReviewInput(BaseModel):
    decision: str = Field(pattern="^(CONFIRMED|DISMISSED)$")
    reason: str | None = Field(default=None, max_length=500)


class ActionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    source_type: str = Field(default="MANUAL", pattern="^(RENEWAL_RISK|SCENARIO|MANUAL)$")
    source_id: int | None = None
    task_template: str | None = Field(default=None, pattern="^(PROPERTY_FIX|LEASING_FOLLOWUP|ENTERPRISE_VISIT)$")
    contract_id: int | None = None
    enterprise_id: int | None = None
    priority: str = Field(default="MEDIUM", pattern="^(HIGH|MEDIUM|LOW)$")
    owner_name: str | None = None
    owner_role: str | None = None
    due_date: str | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=720)


class TransitionInput(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=500)
    result_note: str | None = Field(default=None, max_length=1000)


def _scope(q, auth, model):
    """统一的数据范围裁剪：园区 + 企业（fail-closed）。"""
    vis = auth.visible_park_ids()
    if vis is not None:
        q = q.where(model.park_id.in_(vis)) if vis else q.where(model.id == -1)
    return q


def _ent_scope(q, auth, column):
    clause = auth.enterprise_scope_clause(column)
    return q.where(clause) if clause is not None else q


# --------------------------------------------------------------------------- 指标
@router.get("/metrics")
def operating_metrics(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """经营指标 + 口径说明 + 数据质量。缺失数据返回 null 与原因，不填 0。"""
    auth.require("operating", "VIEW")
    park_id = resolve_park(auth, park_id)

    sq = _scope(select(Space), auth, Space)
    if park_id:
        sq = sq.where(Space.park_id == park_id)
    spaces = list(db.scalars(sq).all())

    cq = _ent_scope(_scope(select(Contract), auth, Contract), auth, Contract.enterprise_id)
    if park_id:
        cq = cq.where(Contract.park_id == park_id)
    contracts = list(db.scalars(cq).all())

    total_area = sum(s.rentable_area or 0 for s in spaces)
    rented_area = sum(s.rentable_area or 0 for s in spaces if s.status == "RENTED")
    vacant_area = round(total_area - rented_area, 2)

    occupied_rate = round(rented_area / total_area * 100, 2) if total_area else None
    active = [c for c in contracts if c.status in ("ACTIVE", "EXPIRING")]
    annual_rent = round(sum((c.monthly_rent or 0) * 12 for c in active), 2)

    # 空置天数：优先用 vacant_since，没有则明确说明缺失
    today = dt.date.today()
    vacant_days_samples = [
        (today - s.vacant_since).days
        for s in spaces
        if s.status != "RENTED" and getattr(s, "vacant_since", None)
    ]
    avg_vacant_days = round(sum(vacant_days_samples) / len(vacant_days_samples), 1) if vacant_days_samples else None

    missing = []
    if not total_area:
        missing.append("可出租面积：空间台账无可用面积字段或数据为空")
    if avg_vacant_days is None:
        missing.append("平均空置天数：空间记录缺少 vacant_since（空置起始日），无法计算")

    return {
        "kpis": [
            {"key": "total_area", "label": "可出租面积", "value": round(total_area, 2), "unit": "㎡",
             "basis": "统计范围为当前数据权限内的全部空间可出租面积"}, 
            {"key": "rented_area", "label": "已出租面积", "value": round(rented_area, 2), "unit": "㎡",
             "basis": "空间状态为 RENTED 的可出租面积合计"},
            {"key": "vacant_area", "label": "空置面积", "value": vacant_area, "unit": "㎡",
             "basis": "可出租面积 − 已出租面积"},
            {"key": "occupancy_rate", "label": "出租率", "value": occupied_rate, "unit": "%",
             "basis": "已出租面积 ÷ 可出租面积（按面积，不按间数）",
             "unavailable_reason": None if occupied_rate is not None else "可出租面积为 0，无法计算"},
            {"key": "annual_rent", "label": "年化合同租金", "value": annual_rent, "unit": "元",
             "basis": "生效中/即将到期合同的月租金 × 12，不含免租期扣减"},
            {"key": "avg_vacant_days", "label": "平均空置天数", "value": avg_vacant_days, "unit": "天",
             "basis": "当前空置空间自 vacant_since 起至今天数的算术平均",
             "unavailable_reason": None if avg_vacant_days is not None else "缺少空置起始日"},
        ],
        "missing_data": missing,
        "data_quality": {
            "space_count": len(spaces),
            "contract_count": len(contracts),
            "active_contract_count": len(active),
            "space_without_area": len([s for s in spaces if not s.rentable_area]),
        },
        "data_label": "演示数据",
        "assumption_note": "所有指标按当前台账实时聚合；演示数据由固定种子生成，可重复复现。",
    }


# --------------------------------------------------------------------------- 沙盘
@router.get("/spaces")
def scenario_spaces(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """可用于推演的空间（空置优先）。挂牌价为推演默认值，非真实报价。"""
    auth.require("operating", "VIEW")
    park_id = resolve_park(auth, park_id)
    q = _scope(select(Space), auth, Space).where(Space.status != "RENTED")
    if park_id:
        q = q.where(Space.park_id == park_id)
    rows = list(db.scalars(q.order_by(Space.vacant_since.is_(None), Space.vacant_since)).all())

    items = [{
        "id": s.id, "space_code": s.space_code, "space_name": s.space_name,
        "park_id": s.park_id, "building_id": s.building_id,
        "space_type": s.space_type, "status": s.status,
        "rentable_area": s.rentable_area or 0,
        "list_rent": s.rent_price or 0,
        "vacant_since": s.vacant_since.isoformat() if s.vacant_since else None,
        "vacant_days": (dt.date.today() - s.vacant_since).days if s.vacant_since else None,
    } for s in rows]
    return {**paginate(items, page, page_size), "data_label": "演示数据",
            "note": "挂牌价用于推演默认值，不构成真实报价"}


@router.post("/scenarios/compare")
def compare_scenarios(payload: ScenarioInput, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """三方案收益比较（只读推演，不落库、不改任何正式数据）。"""
    auth.require("operating", "VIEW")
    base = engine.LeaseScenario(
        area=payload.area, list_rent=payload.list_rent, lease_months=payload.lease_months,
        discount=payload.discount, rent_free_months=payload.rent_free_months,
        vacancy_days=payload.vacancy_days, commission_months=payload.commission_months,
        fitout_per_sqm=payload.fitout_per_sqm,
        service_cost_monthly=payload.service_cost_monthly,
        payment_cycle_days=payload.payment_cycle_days,
    )
    try:
        result = engine.compare(base)
    except engine.ScenarioInputError as exc:
        # 拒算而不是兜底：说明哪个字段不合法，让使用者改参数
        raise HTTPException(422, f"参数不可用于推演：{exc}") from exc
    result["space_id"] = payload.space_id
    return result


@router.post("/scenarios")
def save_scenario(payload: ScenarioInput, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("operating", "ADD")
    base = engine.LeaseScenario(
        area=payload.area, list_rent=payload.list_rent, lease_months=payload.lease_months,
        discount=payload.discount, rent_free_months=payload.rent_free_months,
        vacancy_days=payload.vacancy_days, commission_months=payload.commission_months,
        fitout_per_sqm=payload.fitout_per_sqm,
        service_cost_monthly=payload.service_cost_monthly,
        payment_cycle_days=payload.payment_cycle_days,
    )
    try:
        result = engine.compare(base)
    except engine.ScenarioInputError as exc:
        raise HTTPException(422, f"参数不可用于推演：{exc}") from exc

    space = db.get(Space, payload.space_id) if payload.space_id else None
    if space is not None and not auth.can_access_park(space.park_id):
        raise HTTPException(404, "空间不存在或无权访问")

    seq = (db.scalar(select(func.count(OperatingScenario.id))) or 0) + 1
    obj = OperatingScenario(
        scenario_code=f"SCN{dt.datetime.now():%Y%m%d}{seq:04d}",
        name=payload.name or f"{space.space_name if space else '推演'} · 三方案",
        park_id=(space.park_id if space else resolve_park(auth, None)),
        space_id=payload.space_id,
        space_name=space.space_name if space else None,
        params=payload.model_dump(),
        result=result,
        assumption_version=engine.ASSUMPTION_VERSION,
        created_by_id=auth.user.id, created_by_name=auth.user.real_name,
        is_demo=True, remark="演示数据·沙盘方案",
    )
    db.add(obj)
    db.flush()
    write_audit(db, module="operating", action="ADD", auth=auth, object_type="OperatingScenario",
                object_id=obj.id, object_name=obj.name, change_summary="保存经营沙盘方案")
    db.commit()
    return {"id": obj.id, "scenario_code": obj.scenario_code, "result": result}


@router.get("/scenarios")
def list_scenarios(db: DbSession, auth: CurrentAuth,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("operating", "VIEW")
    q = _scope(select(OperatingScenario), auth, OperatingScenario)
    rows = list(db.scalars(q.order_by(OperatingScenario.id.desc())).all())
    items = [{
        "id": s.id, "scenario_code": s.scenario_code, "name": s.name,
        "space_id": s.space_id, "space_name": s.space_name, "park_id": s.park_id,
        "assumption_version": s.assumption_version,
        "created_by_name": s.created_by_name,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "best_net_contribution": max(
            (x.get("net_contribution") or 0) for x in ((s.result or {}).get("scenarios") or [{}])
        ) if s.result else None,
    } for s in rows]
    return {**paginate(items, page, page_size), "data_label": "演示数据"}


# --------------------------------------------------------------------------- 续租风险
@router.get("/renewal-risks")
def renewal_risks(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                  window_days: int = Query(90, ge=1, le=365),
                  level: str | None = None) -> dict[str, Any]:
    """续租风险待核实清单（规则驱动，带证据链）。

    取数口径在 app/services/operating_service.py，与 Agent 工具共用同一实现——
    避免 API 与 AI 各写一遍导致数字分叉（合同到期曾因此出现 37/39 两个值）。
    """
    auth.require("operating", "VIEW")
    park_id = resolve_park(auth, park_id)
    return operating_service.renewal_risks(db, auth, park_id=park_id,
                                           window_days=window_days, level=level)


@router.post("/renewal-risks/{contract_id}/review")
def review_risk(contract_id: int, payload: ReviewInput, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """人工复核：确认为真实风险，或解除误报。规则必然有误报，这一步不可省。"""
    auth.require("operating", "EDIT")
    c = db.get(Contract, contract_id)
    if not c or not auth.can_access_park(c.park_id):
        raise HTTPException(404, "合同不存在或无权访问")
    auth.require_enterprise(c.enterprise_id, "企业账号只能复核本企业合同")

    obj = OperatingRiskReview(
        contract_id=c.id, enterprise_id=c.enterprise_id,
        level="", decision=payload.decision, reason=payload.reason,
        snapshot={"contract_code": c.contract_code, "end_date": c.end_date.isoformat() if c.end_date else None},
        decided_by_id=auth.user.id, decided_by_name=auth.user.real_name, is_demo=True,
    )
    db.add(obj)
    db.flush()
    write_audit(db, module="operating", action="EDIT", auth=auth, object_type="Contract",
                object_id=c.id, object_name=c.contract_code,
                change_summary=f"续租风险复核：{payload.decision}"
                               + (f"；理由：{payload.reason}" if payload.reason else ""))
    db.commit()
    return {"success": True, "decision": payload.decision, "contract_id": c.id}


# --------------------------------------------------------------------------- 任务
@router.get("/actions")
def list_actions(db: DbSession, auth: CurrentAuth, status: str | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("operating", "VIEW")
    q = _ent_scope(_scope(select(OperatingAction), auth, OperatingAction),
                   auth, OperatingAction.enterprise_id)
    if status:
        q = q.where(OperatingAction.status == status)
    rows = list(db.scalars(q.order_by(OperatingAction.id.desc())).all())
    items = [{
        "id": a.id, "action_code": a.action_code, "title": a.title,
        "status": a.status, "status_label": STATUS_LABELS.get(a.status, a.status),
        "priority": a.priority, "source_type": a.source_type, "source_id": a.source_id,
        "task_template": a.task_template,
        "enterprise_id": a.enterprise_id, "contract_id": a.contract_id, "park_id": a.park_id,
        "owner_name": a.owner_name, "owner_role": a.owner_role,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "sla_hours": a.sla_hours,
        "created_by_name": a.created_by_name,
        "approved_by_name": a.approved_by_name,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "closed_at": a.closed_at.isoformat() if a.closed_at else None,
        "result_note": a.result_note,
        "timeline": a.timeline or [],
    } for a in rows]
    return {**paginate(items, page, page_size), "data_label": "演示数据",
            "transition_rules": {k: list(v) for k, v in TRANSITIONS.items()}}


@router.post("/actions")
def create_action(payload: ActionCreate, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """创建建议任务。创建即草稿，必须经审批才能进入执行（AI 不代批）。"""
    auth.require("operating", "ADD")
    park_id = resolve_park(auth, None)

    contract = db.get(Contract, payload.contract_id) if payload.contract_id else None
    if contract and not auth.can_access_park(contract.park_id):
        raise HTTPException(404, "合同不存在或无权访问")
    if contract:
        auth.require_enterprise(contract.enterprise_id, "企业账号只能为本企业创建任务")
        park_id = contract.park_id

    template = TASK_TEMPLATES.get(payload.task_template or "")
    sla = payload.sla_hours or (template[2] if template else 48)
    # 截止日：未显式指定时按 SLA 折算成天（向上取整），至少 1 天
    due = dt.date.fromisoformat(payload.due_date) if payload.due_date else \
        dt.date.today() + dt.timedelta(days=max(1, -(-sla // 24)))
    if due < dt.date.today():
        raise HTTPException(422, "截止日期不能早于今天")

    seq = (db.scalar(select(func.count(OperatingAction.id))) or 0) + 1
    now = dt.datetime.now()
    obj = OperatingAction(
        action_code=f"ACT{now:%Y%m%d}{seq:04d}",
        title=payload.title,
        source_type=payload.source_type, source_id=payload.source_id,
        task_template=payload.task_template,
        park_id=park_id,
        enterprise_id=(contract.enterprise_id if contract else payload.enterprise_id),
        contract_id=payload.contract_id,
        status="DRAFT", priority=payload.priority,
        owner_name=payload.owner_name, owner_role=payload.owner_role or (template[1] if template else None),
        due_date=due, sla_hours=sla,
        created_by_id=auth.user.id, created_by_name=auth.user.real_name,
        timeline=[{"at": now.isoformat(timespec="seconds"), "from": None, "to": "DRAFT",
                   "by": auth.user.real_name, "note": "创建建议任务"}],
        is_demo=True,
    )
    db.add(obj)
    db.flush()
    write_audit(db, module="operating", action="ADD", auth=auth, object_type="OperatingAction",
                object_id=obj.id, object_name=obj.title, change_summary="创建经营建议任务")
    db.commit()
    return {"id": obj.id, "action_code": obj.action_code, "status": obj.status}


@router.post("/actions/{action_id}/transition")
def transition_action(action_id: int, payload: TransitionInput, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """推进任务状态。非法迁移、越权、自审一律拒绝。"""
    auth.require("operating", "VIEW")
    a = db.get(OperatingAction, action_id)
    if not a or not auth.can_access_park(a.park_id):
        raise HTTPException(404, "任务不存在或无权访问")
    auth.require_enterprise(a.enterprise_id, "企业账号只能处理本企业任务")

    allowed = TRANSITIONS.get(a.status, ())
    if payload.to_status not in allowed:
        raise HTTPException(422, f"不允许从「{STATUS_LABELS.get(a.status, a.status)}」"
                                 f"直接流转到「{STATUS_LABELS.get(payload.to_status, payload.to_status)}」；"
                                 f"当前可选：{'、'.join(STATUS_LABELS.get(s, s) for s in allowed) or '无'}")

    if payload.to_status in NEED_APPROVE_PERM:
        auth.require("operating", "APPROVE")
        # 双人原则：审批人不能是创建人
        if a.created_by_id == auth.user.id:
            raise HTTPException(403, "不能审批自己创建的任务（双人原则）")

    now = dt.datetime.now()
    timeline = list(a.timeline or [])
    timeline.append({
        "at": now.isoformat(timespec="seconds"),
        "from": a.status, "to": payload.to_status,
        "by": auth.user.real_name, "note": payload.note or "",
    })
    prev = a.status
    a.status = payload.to_status
    a.timeline = timeline
    if payload.to_status == "APPROVED":
        a.approved_by_id = auth.user.id
        a.approved_by_name = auth.user.real_name
        a.approved_at = now
    if payload.to_status == "CLOSED":
        a.closed_at = now
        a.result_note = payload.result_note or a.result_note

    write_audit(db, module="operating", action="EDIT", auth=auth, object_type="OperatingAction",
                object_id=a.id, object_name=a.title,
                change_summary=f"任务状态 {STATUS_LABELS.get(prev, prev)} → "
                               f"{STATUS_LABELS.get(a.status, a.status)}")
    db.commit()
    return {"id": a.id, "status": a.status, "status_label": STATUS_LABELS.get(a.status, a.status),
            "timeline": timeline}

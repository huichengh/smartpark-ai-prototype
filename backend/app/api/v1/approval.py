"""审批中心：待办、审批流程、多步审批、AI 生成审批。

AI 权限体系落地：
  - Level 1 信息查询：AI 直接回答
  - Level 2 分析与建议：AI 给建议，人工采纳
  - Level 3 高影响动作：AI 只生成「审批请求」，绝不能自行执行
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.enums import ENUM_LABELS
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    ApprovalRequest,
    ApprovalStep,
    Contract,
    Enterprise,
    Project,
    ProjectChange,
    User,
)
from app.schemas.common import paginate

router = APIRouter(prefix="/approvals", tags=["审批中心"])


def _step_role_map(db: Session, approval_ids: list[int]) -> dict[int, dict[int, str]]:
    """一次性取回各审批单每一步的审批角色，避免 N+1 查询。"""
    if not approval_ids:
        return {}
    out: dict[int, dict[int, str]] = {}
    for st in db.scalars(select(ApprovalStep).where(
            ApprovalStep.approval_id.in_(approval_ids))).all():
        out.setdefault(st.approval_id, {})[st.step_no] = st.approver_role
    return out


def current_role_of(db: Session, r, role_map: dict) -> str | None:
    return (role_map.get(r.id) or {}).get(r.current_step)


def _step_name_map(db: Session, approval_ids: list[int]) -> dict[int, dict[int, str]]:
    """一次性取回各审批单每一步的步骤名，与 _step_role_map 配套使用（避免 N+1）。"""
    if not approval_ids:
        return {}
    rows = db.execute(
        select(ApprovalStep.approval_id, ApprovalStep.step_no, ApprovalStep.step_name)
        .where(ApprovalStep.approval_id.in_(approval_ids))
    ).all()
    out: dict[int, dict[int, str]] = {}
    for aid, no, name in rows:
        out.setdefault(aid, {})[no] = name
    return out


def _current_step_name(db: Session, r) -> str | None:
    """当前审批步骤名称。

    口径说明：ApprovalRequest 未冗余 current_approver_name 字段，
    因此以当前步骤的「步骤名」+「审批角色」共同表达「现在轮到谁」。
    """
    return db.scalar(
        select(ApprovalStep.step_name).where(
            ApprovalStep.approval_id == r.id,
            ApprovalStep.step_no == r.current_step)
    )


def can_approve(auth, r, role_map: dict) -> bool:
    """当前用户是否可审批该单据。

    口径说明：审批单未记录 current_approver_id，因此以「当前步骤的审批角色」
    与当前用户角色匹配为准；集团管理员与超管视为可审批一切。
    """
    if r.status not in ("PENDING", "IN_REVIEW"):
        return False
    if auth.is_group_admin:
        return True
    role = current_role_of(None, r, role_map)
    return bool(role and role in auth.role_codes)

# 审批类型中文名统一取自 app.core.enums。
# 此前本文件的键（CONTRACT / CHANGE / SPACE …）与数据库实际写入的
# approval_type（CONTRACT_RENEWAL / PROJECT_CHANGE / SPACE_DISCOUNT …）
# 几乎不交集，只有 PURCHASE 命中，导致类型名显示为英文枚举，
# 且 stats.by_type 只统计到 1 类（其余 7 类被静默丢弃）。
TYPE_NAMES = ENUM_LABELS["ApprovalType"]
STATUS_NAMES = ENUM_LABELS["BusinessStatus"]


@router.get("")
def list_approvals(db: DbSession, auth: CurrentAuth,
                   park_id: int | None = None, status: str | None = None,
                   approval_type: str | None = None, only_mine: bool = False,
                   keyword: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("approval", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(ApprovalRequest)
    if park_id:
        q = q.where(ApprovalRequest.park_id == park_id)
    elif vis is not None:
        q = q.where(ApprovalRequest.park_id.in_(vis)) if vis else q.where(ApprovalRequest.id == -1)
    if status:
        q = q.where(ApprovalRequest.status == status)
    if approval_type:
        q = q.where(ApprovalRequest.approval_type == approval_type)
    if only_mine:
        # 我发起 或 我需要审批（后者在内存里按审批角色匹配，见 can_i_approve）
        q = q.where(or_(ApprovalRequest.applicant_id == auth.user.id,
                        ApprovalRequest.status.in_(["PENDING", "IN_REVIEW"])))
    if keyword:
        q = q.where(or_(ApprovalRequest.approval_code.contains(keyword),
                        ApprovalRequest.title.contains(keyword)))
    rows = list(db.scalars(q.order_by(ApprovalRequest.apply_at.desc())).all())
    users = {u.id: u for u in db.scalars(select(User)).all()}
    role_map = _step_role_map(db, [r.id for r in rows])
    items = [{
        "id": r.id, "approval_code": r.approval_code, "title": r.title,
        "approval_type": r.approval_type,
        "approval_type_name": TYPE_NAMES.get(r.approval_type, r.approval_type),
        "status": r.status, "status_name": STATUS_NAMES.get(r.status, r.status),
        "park_id": r.park_id,
        "applicant_id": r.applicant_id,
        "applicant_name": r.applicant_name
        or (users[r.applicant_id].real_name if r.applicant_id in users else None),
        "apply_at": r.apply_at.isoformat() if r.apply_at else None,
        "related_object_type": r.related_object_type,
        "related_object_id": r.related_object_id,
        "enterprise_id": r.enterprise_id, "project_id": r.project_id,
        "amount": r.amount,
        "risk_level": r.risk_level, "urgency": r.urgency,
        "total_steps": r.total_steps, "current_step": r.current_step,
        "current_approver_role": current_role_of(db, r, role_map),
        "current_step_name": _current_step_name(db, r),
        "is_ai_generated": r.is_ai_generated, "source": r.source,
        "is_pending": r.status in ("PENDING", "IN_REVIEW"),
        "can_i_approve": can_approve(auth, r, role_map),
        "finish_at": r.finish_at.isoformat() if r.finish_at else None,
    } for r in rows]
    if only_mine:
        items = [i for i in items if i["applicant_id"] == auth.user.id or i["can_i_approve"]]
    pending = [i for i in items if i["is_pending"]]
    # 按实际数据分组。若改成「遍历 TYPE_NAMES 的键」，映射表里没有的类型会被静默丢弃，
    # 导致各类型数量之和小于总数（此前只有 PURCHASE 被统计到）。
    type_counter: dict[str, int] = {}
    for i in items:
        label = TYPE_NAMES.get(i["approval_type"], i["approval_type"])
        type_counter[label] = type_counter.get(label, 0) + 1
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "pending": len(pending),
        "my_todo": len([i for i in pending if i["can_i_approve"]]),
        "approved": len([i for i in items if i["status"] == "APPROVED"]),
        "rejected": len([i for i in items if i["status"] == "REJECTED"]),
        "ai_generated": len([i for i in items if i["is_ai_generated"]]),
        "by_type": dict(sorted(type_counter.items(), key=lambda kv: kv[1], reverse=True)),
        "total_amount": round(sum(i["amount"] or 0 for i in pending), 2),
    }
    return result


@router.get("/todo")
def my_todo(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """我的待办审批（按当前审批人/角色匹配）。"""
    auth.require("approval", "VIEW")
    q = select(ApprovalRequest).where(ApprovalRequest.status.in_(["PENDING", "IN_REVIEW"]))
    vis = auth.visible_park_ids()
    if vis is not None:
        q = q.where(ApprovalRequest.park_id.in_(vis)) if vis else q.where(ApprovalRequest.id == -1)
    rows = list(db.scalars(q.order_by(ApprovalRequest.apply_at)).all())
    role_map = _step_role_map(db, [r.id for r in rows])
    mine = [r for r in rows if can_approve(auth, r, role_map)]
    today = dt.date.today()
    return {
        "items": [{
            "id": r.id, "approval_code": r.approval_code, "title": r.title,
            "approval_type": r.approval_type,
            "approval_type_name": TYPE_NAMES.get(r.approval_type, r.approval_type),
            "applicant_name": r.applicant_name, "amount": r.amount,
            "apply_at": r.apply_at.isoformat() if r.apply_at else None,
            "pending_days": (dt.datetime.now() - r.apply_at).days if r.apply_at else None,
            "risk_level": r.risk_level, "urgency": r.urgency,
            "current_step": r.current_step, "total_steps": r.total_steps,
            "current_approver_role": current_role_of(None, r, role_map),
            "current_step_name": _current_step_name(db, r),
            "is_ai_generated": r.is_ai_generated,
            "ai_analysis": r.ai_analysis,
            "related_object_type": r.related_object_type,
        } for r in mine],
        "total": len(mine),
        "overdue_3days": len([r for r in mine if r.apply_at
                              and (dt.datetime.now() - r.apply_at).days >= 3]),
        "basis": "匹配规则：当前步骤审批角色 ∈ 本人角色；集团管理员可见全部",
        "data_label": "演示数据",
    }


@router.get("/{approval_id}")
def approval_detail(approval_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("approval", "VIEW")
    r = db.get(ApprovalRequest, approval_id)
    if not r or not auth.can_access_park(r.park_id):
        raise HTTPException(404, "审批单不存在或无权访问")
    steps = list(db.scalars(select(ApprovalStep).where(ApprovalStep.approval_id == approval_id)
                            .order_by(ApprovalStep.step_no)).all())
    obj = None
    if r.related_object_type == "Contract" and r.related_object_id:
        c = db.get(Contract, r.related_object_id)
        obj = {"type": "Contract", "contract_code": c.contract_code,
               "contract_name": c.contract_name, "monthly_rent": c.monthly_rent,
               "end_date": c.end_date.isoformat() if c.end_date else None} if c else None
    elif r.related_object_type == "ProjectChange" and r.related_object_id:
        c = db.get(ProjectChange, r.related_object_id)
        obj = {"type": "ProjectChange", "change_code": c.change_code,
               "change_title": c.change_title, "change_reason": c.change_reason,
               "change_type": c.change_type,
               "impact_schedule_days": c.impact_schedule_days,
               "impact_cost": c.impact_cost,
               "impact_risk": c.impact_risk,
               "is_baseline_change": c.is_baseline_change,
               "applicant_name": c.applicant_name} if c else None
    elif r.related_object_type == "Project" and r.related_object_id:
        p = db.get(Project, r.related_object_id)
        obj = {"type": "Project", "project_code": p.project_code,
               "project_name": p.project_name, "budget": p.budget,
               "progress": p.progress} if p else None

    return {
        "approval": {
            "id": r.id, "approval_code": r.approval_code, "title": r.title,
            "approval_type": r.approval_type,
            "approval_type_name": TYPE_NAMES.get(r.approval_type, r.approval_type),
            "status": r.status, "status_name": STATUS_NAMES.get(r.status, r.status),
            "content": r.content, "remark": r.remark,
            "applicant_id": r.applicant_id, "applicant_name": r.applicant_name,
            "apply_at": r.apply_at.isoformat() if r.apply_at else None,
            "related_object_type": r.related_object_type,
            "related_object_id": r.related_object_id,
            "amount": r.amount, "risk_level": r.risk_level, "urgency": r.urgency,
            "total_steps": r.total_steps, "current_step": r.current_step,
            "current_approver_role": current_role_of(None, r, _step_role_map(db, [r.id])),
            "current_step_name": _current_step_name(db, r),
            "is_ai_generated": r.is_ai_generated,
            "ai_analysis": r.ai_analysis, "source": r.source,
            "finish_at": r.finish_at.isoformat() if r.finish_at else None,
        },
        "related_object": obj,
        "steps": [{
            "id": s.id, "step_no": s.step_no, "step_name": s.step_name,
            "approver_role": s.approver_role,
            "approver_name": s.approver_name, "status": s.status,
            "comment": s.comment,
            "approve_at": s.approve_at.isoformat() if s.approve_at else None,
            "duration_hours": s.duration_hours,
        } for s in steps],
        "can_i_approve": can_approve(auth, r, _step_role_map(db, [r.id])),
        "data_label": "演示数据",
    }


@router.post("/{approval_id}/decision")
def decide(approval_id: int, decision: str, db: DbSession, auth: CurrentAuth,
           comment: str | None = None) -> dict[str, Any]:
    """审批决策（逐级推进；全部通过才最终批准）。"""
    auth.require("approval", "APPROVE")
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(400, "decision 必须为 APPROVE 或 REJECT")
    r = db.get(ApprovalRequest, approval_id)
    if not r or not auth.can_access_park(r.park_id):
        raise HTTPException(404, "审批单不存在或无权访问")
    if r.status not in ("PENDING", "IN_REVIEW"):
        raise HTTPException(400, f"审批单状态为「{STATUS_NAMES.get(r.status, r.status)}」，不可再决策")
    steps = list(db.scalars(select(ApprovalStep).where(ApprovalStep.approval_id == approval_id)
                            .order_by(ApprovalStep.step_no)).all())
    cur = next((s for s in steps if s.step_no == r.current_step), None)
    cur_role = cur.approver_role if cur else None
    if not (auth.is_group_admin or (cur_role and cur_role in auth.role_codes)):
        raise HTTPException(403, f"当前审批环节为「{cur_role or '未指定角色'}」，"
                                 f"您的角色为「{auth.role_label}」，无权审批该环节")
    now = dt.datetime.now()

    if cur:
        cur.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        cur.comment = ((comment or "") + f"（审批人：{auth.user.real_name}）").strip("（）") or None
        cur.approve_at = now
        cur.approver_name = auth.user.real_name
        cur.duration_hours = round((now - r.apply_at).total_seconds() / 3600, 2) if r.apply_at else None

    before = r.status
    nxt = None
    if decision == "REJECT":
        r.status = "REJECTED"
        r.finish_at = now
        r.remark = comment
    else:
        nxt = next((s for s in steps if s.step_no == r.current_step + 1), None)
        if nxt:
            r.status = "IN_REVIEW"
            r.current_step = nxt.step_no
            nxt.status = "PENDING"
        else:
            r.status = "APPROVED"
            r.finish_at = now
            r.remark = comment

    write_audit(db, module="approval", action="APPROVE", auth=auth,
                object_type="ApprovalRequest", object_id=r.id, object_name=r.approval_code,
                before_value={"status": before, "current_step": r.current_step},
                after_value={"status": r.status},
                change_summary=(f"审批决策：{'同意' if decision == 'APPROVE' else '驳回'}"
                                f"（{TYPE_NAMES.get(r.approval_type, r.approval_type)}"
                                f"｜第 {cur.step_no if cur else '-'} 步）"
                                + (f"；意见：{comment}" if comment else "")),
                approval_info=f"审批人：{auth.user.real_name}（{auth.role_label}）",
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": f"{'已同意' if decision == 'APPROVE' else '已驳回'}审批单 {r.approval_code}"
                   + (f"，流转至第 {r.current_step} 步（{nxt.step_name or '待指派'}）"
                      if r.status == "IN_REVIEW" and nxt else "，流程结束"),
        "status": r.status, "status_name": STATUS_NAMES.get(r.status, r.status),
        "current_step": r.current_step,
        "current_approver_role": current_role_of(None, r, _step_role_map(db, [r.id])),
    }


@router.post("/{approval_id}/withdraw")
def withdraw(approval_id: int, db: DbSession, auth: CurrentAuth,
             reason: str | None = None) -> dict[str, Any]:
    """撤回审批（仅申请人本人或集团管理员）。"""
    r = db.get(ApprovalRequest, approval_id)
    if not r:
        raise HTTPException(404, "审批单不存在")
    if r.applicant_id != auth.user.id and not auth.is_group_admin:
        raise HTTPException(403, "只有申请人本人或集团管理员可以撤回")
    if r.status not in ("PENDING", "IN_REVIEW"):
        raise HTTPException(400, "该审批单已结束，不可撤回")
    before = r.status
    r.status = "WITHDRAWN"
    r.finish_at = dt.datetime.now()
    r.remark = reason or "申请人撤回"
    write_audit(db, module="approval", action="EDIT", auth=auth,
                object_type="ApprovalRequest", object_id=r.id, object_name=r.approval_code,
                before_value={"status": before}, after_value={"status": "WITHDRAWN"},
                change_summary=f"撤回审批：{reason or '无说明'}", source="USER")
    db.commit()
    return {"success": True, "message": f"审批单 {r.approval_code} 已撤回"}

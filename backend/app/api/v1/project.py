"""项目管理中心：瀑布 / 敏捷 / 混合三种管理方式统一入口。

核心能力：
  - 项目组合视图与多维度筛选
  - WBS 树 + 甘特图数据（含关键路径高亮）
  - 关键路径（CPM）计算，结果写回 wbs_items.slack_days / is_critical
  - 成本执行与挣值分析（EV / PV / AC / CPI / SPI / EAC / VAC）
  - 风险登记册（5×5 概率影响矩阵）
  - 里程碑、问题、变更
  - 敏捷体系：Epic / Feature / User Story / Sprint / 看板 / 燃尽图
  - AI 项目经理诊断（可解释、带证据链）
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.core.audit import write_audit
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import (
    Epic,
    Feature,
    Milestone,
    Project,
    ProjectChange,
    ProjectCost,
    ProjectIssue,
    ProjectPhase,
    ProjectRisk,
    Sprint,
    SprintTask,
    TaskDependency,
    UserStory,
    WbsItem,
)
from app.schemas.common import paginate
from app.services import project_engine

router = APIRouter(prefix="/projects", tags=["项目管理"])

METHOD_NAMES = {"WATERFALL": "瀑布式", "AGILE": "敏捷式", "HYBRID": "混合式"}
STATUS_NAMES = {"PLANNED": "计划中", "IN_PROGRESS": "进行中", "ON_HOLD": "已暂停",
                "DELAYED": "已延期", "COMPLETED": "已完成", "CLOSED": "已关闭"}
RISK_NAMES = {"LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "重大"}


def _project_row(p: Project, ms: tuple[int, int] | None = None) -> dict[str, Any]:
    """项目列表/详情行。

    ms 为 (里程碑总数, 已完成数)，由 project_engine.milestone_stats() 从
    milestones 表实时聚合得到。不传时回落到列值——但 projects.milestone_*
    两列从未被写入（恒为 0），批量场景务必传入。
    """
    ms_total, ms_done = ms if ms is not None else (p.milestone_total or 0, p.milestone_done or 0)
    return {
        "id": p.id, "project_code": p.project_code, "project_name": p.project_name,
        "park_id": p.park_id, "parent_project_id": p.parent_project_id,
        "project_type": p.project_type, "management_method": p.management_method,
        "management_method_name": METHOD_NAMES.get(p.management_method, p.management_method),
        "project_manager_name": p.project_manager_name, "department": p.department,
        "status": p.status, "status_name": STATUS_NAMES.get(p.status, p.status),
        "risk_level": p.risk_level, "risk_level_name": RISK_NAMES.get(p.risk_level, p.risk_level),
        "priority": p.priority, "health": p.health, "progress": p.progress,
        "planned_progress": p.planned_progress,
        "progress_variance": round((p.progress or 0) - (p.planned_progress or 0), 2),
        "budget": p.budget, "approved_budget": p.approved_budget, "actual_cost": p.actual_cost,
        "committed_cost": p.committed_cost, "paid_amount": p.paid_amount,
        "execution_rate": round((p.actual_cost or 0) / (p.approved_budget or p.budget or 1) * 100, 2),
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "planned_end_date": p.planned_end_date.isoformat() if p.planned_end_date else None,
        "actual_end_date": p.actual_end_date.isoformat() if p.actual_end_date else None,
        "baseline_end_date": p.baseline_end_date.isoformat() if p.baseline_end_date else None,
        "delay_days": p.delay_days, "team_size": p.team_size,
        "milestone_done": ms_done, "milestone_total": ms_total,
        "milestone_rate": round(ms_done / ms_total * 100, 2) if ms_total else 0.0,
        "objective": p.objective,
    }


@router.get("")
def list_projects(db: DbSession, auth: CurrentAuth,
                  park_id: int | None = None, management_method: str | None = None,
                  status: str | None = None, risk_level: str | None = None,
                  keyword: str | None = None, only_delayed: bool = False,
                  only_parent: bool = False,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("project", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Project)
    if park_id:
        q = q.where(Project.park_id == park_id)
    elif vis is not None:
        q = q.where(Project.park_id.in_(vis)) if vis else q.where(Project.id == -1)
    proj_vis = auth.visible_project_ids()
    if proj_vis is not None:
        q = q.where(Project.id.in_(proj_vis)) if proj_vis else q.where(Project.id == -1)
    if management_method:
        q = q.where(Project.management_method == management_method)
    if status:
        q = q.where(Project.status == status)
    if risk_level:
        q = q.where(Project.risk_level == risk_level)
    if only_parent:
        q = q.where(Project.parent_project_id.is_(None))
    if keyword:
        q = q.where(or_(Project.project_name.contains(keyword),
                        Project.project_code.contains(keyword),
                        Project.project_manager_name.contains(keyword)))
    projects = list(db.scalars(q.order_by(Project.project_code)).all())
    ms_map = project_engine.milestone_stats(db, [p.id for p in projects])
    today = dt.date.today()
    items = []
    for p in projects:
        row = _project_row(p, ms_map.get(p.id))
        row["is_delayed"] = bool(
            p.status == "DELAYED" or
            (p.planned_end_date and p.planned_end_date < today
             and p.status not in ("COMPLETED", "CLOSED")))
        if only_delayed and not row["is_delayed"]:
            continue
        items.append(row)
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "by_method": {k: len([i for i in items if i["management_method"] == k])
                      for k in METHOD_NAMES},
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in STATUS_NAMES if len([i for i in items if i["status"] == k])},
        "by_risk": {k: len([i for i in items if i["risk_level"] == k])
                    for k in RISK_NAMES if len([i for i in items if i["risk_level"] == k])},
        "in_progress": len([i for i in items if i["status"] == "IN_PROGRESS"]),
        "delayed": len([i for i in items if i["is_delayed"]]),
        "high_risk": len([i for i in items if i["risk_level"] in ("HIGH", "CRITICAL")]),
        "total_budget": round(sum(i["approved_budget"] or i["budget"] or 0 for i in items), 2),
        "total_actual": round(sum(i["actual_cost"] or 0 for i in items), 2),
        "avg_progress": round(sum(i["progress"] or 0 for i in items) / len(items), 2) if items else 0.0,
    }
    return result


@router.get("/portfolio")
def portfolio(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """项目组合视图：按园区 / 类型 / 管理方式 / 风险 多维聚合。"""
    auth.require("project", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Project)
    if park_id:
        q = q.where(Project.park_id == park_id)
    elif vis is not None:
        q = q.where(Project.park_id.in_(vis)) if vis else q.where(Project.id == -1)
    proj_vis = auth.visible_project_ids()
    if proj_vis is not None:
        q = q.where(Project.id.in_(proj_vis)) if proj_vis else q.where(Project.id == -1)
    projects = list(db.scalars(q).all())
    ms_map = project_engine.milestone_stats(db, [p.id for p in projects])
    today = dt.date.today()

    def agg(key_fn, label_fn=None):
        d: dict[str, list[Project]] = {}
        for p in projects:
            d.setdefault(key_fn(p) or "未填写", []).append(p)
        return [{
            "key": k, "name": (label_fn(k) if label_fn else k),
            "count": len(v),
            "budget": round(sum(x.approved_budget or x.budget or 0 for x in v), 2),
            "actual": round(sum(x.actual_cost or 0 for x in v), 2),
            "avg_progress": round(sum(x.progress or 0 for x in v) / len(v), 2),
            "delayed": len([x for x in v if x.status == "DELAYED" or (
                x.planned_end_date and x.planned_end_date < today
                and x.status not in ("COMPLETED", "CLOSED"))]),
            "high_risk": len([x for x in v if x.risk_level in ("HIGH", "CRITICAL")]),
        } for k, v in d.items()]

    tb = round(sum(p.approved_budget or p.budget or 0 for p in projects), 2)
    ta = round(sum(p.actual_cost or 0 for p in projects), 2)

    # 四象限：进度 vs 成本（用于组合健康度定位）
    scatter = [{
        "id": p.id, "project_name": p.project_name, "project_code": p.project_code,
        "x": round((p.actual_cost or 0) / (p.approved_budget or p.budget or 1) * 100, 2),
        "y": p.progress or 0,
        "size": p.approved_budget or p.budget or 0,
        "risk_level": p.risk_level, "status": p.status,
        "management_method": p.management_method,
    } for p in projects]

    return {
        "items": [_project_row(p, ms_map.get(p.id)) for p in projects],
        "summary": {
            "project_count": len(projects),
            "total_budget": tb, "total_actual": ta,
            "budget_execution_rate": round(ta / tb * 100, 2) if tb else 0.0,
            "avg_progress": round(sum(p.progress or 0 for p in projects) / len(projects), 2)
            if projects else 0.0,
            "in_progress": len([p for p in projects if p.status == "IN_PROGRESS"]),
            "delayed": len([p for p in projects if p.status == "DELAYED" or (
                p.planned_end_date and p.planned_end_date < today
                and p.status not in ("COMPLETED", "CLOSED"))]),
            "high_risk": len([p for p in projects if p.risk_level in ("HIGH", "CRITICAL")]),
        },
        "by_park": agg(lambda p: str(p.park_id)),
        "by_type": agg(lambda p: p.project_type),
        "by_method": agg(lambda p: p.management_method, lambda k: METHOD_NAMES.get(k, k)),
        "by_risk": agg(lambda p: p.risk_level, lambda k: RISK_NAMES.get(k, k)),
        "scatter": scatter,
        "basis": "预算执行率 = Σ实际成本 ÷ Σ批准预算；进度偏差 = 实际进度 − 计划进度",
        "data_label": "演示数据",
    }


@router.get("/{project_id}")
def project_detail(project_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """项目详情 + 全套指标（含 CPM 关键路径、EVM 挣值）。"""
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if not auth.can_access_park(p.park_id):
        raise HTTPException(403, "无权访问该项目数据")
    if not auth.can_access_project(project_id):
        raise HTTPException(403, "您的项目数据权限不包含该项目")

    diag = project_engine.diagnose_project(db, p)
    cpm = project_engine.compute_critical_path(db, project_id)
    phases = list(db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id)
                             .order_by(ProjectPhase.phase_order)).all())
    wbs = list(db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)
                          .order_by(WbsItem.sort_order)).all())
    milestones = list(db.scalars(select(Milestone).where(Milestone.project_id == project_id)
                                 .order_by(Milestone.sort_order)).all())
    risks = list(db.scalars(select(ProjectRisk).where(ProjectRisk.project_id == project_id)).all())
    issues = list(db.scalars(select(ProjectIssue).where(ProjectIssue.project_id == project_id)
                             .order_by(ProjectIssue.raised_date.desc())).all())
    changes = list(db.scalars(select(ProjectChange).where(ProjectChange.project_id == project_id)
                              .order_by(ProjectChange.apply_date.desc())).all())
    costs = list(db.scalars(select(ProjectCost).where(ProjectCost.project_id == project_id)
                            .order_by(ProjectCost.occur_date)).all())
    children = list(db.scalars(select(Project).where(Project.parent_project_id == project_id)).all())
    ms_map = project_engine.milestone_stats(db, [p.id, *[c.id for c in children]])

    agile = None
    if p.management_method in ("AGILE", "HYBRID"):
        agile = project_engine.compute_agile_metrics(db, project_id)

    return {
        "project": _project_row(p, ms_map.get(p.id)),
        "description": p.description, "scope": p.scope, "charter": p.charter,
        "ai_summary": p.ai_summary,
        "diagnosis": diag,
        "critical_path": cpm,
        "phases": [{
            "id": ph.id, "phase_code": ph.phase_code, "phase_name": ph.phase_name,
            "phase_order": ph.phase_order, "progress": ph.progress, "status": ph.status,
            "owner": ph.owner, "deliverable": ph.deliverable,
            "start_date": ph.start_date.isoformat() if ph.start_date else None,
            "end_date": ph.end_date.isoformat() if ph.end_date else None,
            "task_count": len([w for w in wbs if w.phase_id == ph.id]),
        } for ph in phases],
        "wbs": [{
            "id": w.id, "wbs_code": w.wbs_code, "item_name": w.item_name,
            "parent_id": w.parent_id, "phase_id": w.phase_id,
            "item_level": w.item_level, "item_type": w.item_type,
            "owner_name": w.owner_name, "responsible_role": w.responsible_role,
            "plan_start": w.plan_start.isoformat() if w.plan_start else None,
            "plan_end": w.plan_end.isoformat() if w.plan_end else None,
            "actual_start": w.actual_start.isoformat() if w.actual_start else None,
            "actual_end": w.actual_end.isoformat() if w.actual_end else None,
            "duration_days": w.duration_days, "progress": w.progress,
            "weight": w.weight, "budget": w.budget, "actual_cost": w.actual_cost,
            "status": w.status, "risk_level": w.risk_level,
            "is_critical": w.is_critical, "slack_days": w.slack_days,
            "predecessors": w.predecessors, "successors": w.successors,
            "deliverable": w.deliverable,
        } for w in wbs],
        "milestones": [{
            "id": m.id, "milestone_code": m.milestone_code,
            "milestone_name": m.milestone_name, "status": m.status,
            "plan_date": m.plan_date.isoformat() if m.plan_date else None,
            "actual_date": m.actual_date.isoformat() if m.actual_date else None,
            "delay_days": m.delay_days, "owner": m.owner,
            "deliverable": m.deliverable, "is_key": m.is_key,
        } for m in milestones],
        "risks": [_risk_row(r) for r in risks],
        "issues": [{
            "id": i.id, "issue_code": i.issue_code, "issue_title": i.issue_title,
            "issue_description": i.issue_description,
            "severity": i.severity, "status": i.status, "owner": i.owner,
            "raised_by": i.raised_by,
            "raised_date": i.raised_date.isoformat() if i.raised_date else None,
            "due_date": i.due_date.isoformat() if i.due_date else None,
            "closed_date": i.closed_date.isoformat() if i.closed_date else None,
            "solution": i.solution,
        } for i in issues],
        "changes": [{
            "id": c.id, "change_code": c.change_code, "change_title": c.change_title,
            "change_type": c.change_type, "status": c.status,
            "change_reason": c.change_reason,
            "impact_schedule_days": c.impact_schedule_days, "impact_cost": c.impact_cost,
            "impact_scope": c.impact_scope, "impact_risk": c.impact_risk,
            "is_baseline_change": c.is_baseline_change,
            "new_baseline_version": c.new_baseline_version,
            "applicant_name": c.applicant_name,
            "apply_date": c.apply_date.isoformat() if c.apply_date else None,
            "approver_name": c.approver_name,
            "approve_date": c.approve_date.isoformat() if c.approve_date else None,
            "ai_analysis": c.ai_analysis,
            "before_snapshot": c.before_snapshot, "after_snapshot": c.after_snapshot,
        } for c in changes],
        "costs": [{
            "id": c.id, "cost_code": c.cost_code, "cost_subject": c.cost_subject,
            "cost_type": c.cost_type, "budget_amount": c.budget_amount,
            "planned_cost": c.planned_cost, "actual_amount": c.actual_amount,
            "contract_amount": c.contract_amount, "purchase_amount": c.purchase_amount,
            "paid_amount": c.paid_amount, "supplier": c.supplier,
            "occur_date": c.occur_date.isoformat() if c.occur_date else None,
        } for c in costs],
        "children": [_project_row(c, ms_map.get(c.id)) for c in children],
        "agile": agile,
        "data_label": "演示数据",
    }


def _risk_row(r: ProjectRisk) -> dict[str, Any]:
    prob = r.probability or 3
    impact = r.impact or 3
    return {
        "id": r.id, "risk_code": r.risk_code, "risk_title": r.risk_title,
        "risk_description": r.risk_description, "risk_category": r.risk_category,
        "risk_level": r.risk_level, "status": r.status,
        "probability": prob, "impact": impact, "risk_score": prob * impact,
        "risk_owner": r.risk_owner, "strategy": r.strategy,
        "response_plan": r.response_plan, "trigger_condition": r.trigger_condition,
        "identified_date": r.identified_date.isoformat() if r.identified_date else None,
        "due_date": r.due_date.isoformat() if r.due_date else None,
        "is_ai_identified": r.ai_identified,
    }


@router.get("/{project_id}/gantt")
def project_gantt(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    """甘特图数据：WBS 任务 + 依赖关系 + 关键路径。"""
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    cpm = project_engine.compute_critical_path(db, project_id)
    wbs = list(db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)
                          .order_by(WbsItem.sort_order)).all())
    deps = list(db.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id)).all())
    phases = {ph.id: ph for ph in db.scalars(select(ProjectPhase).where(
        ProjectPhase.project_id == project_id)).all()}
    today = dt.date.today()

    def off(d):
        return (d - p.start_date).days if d and p.start_date else None

    tasks = []
    for w in wbs:
        tasks.append({
            "id": w.id, "wbs_code": w.wbs_code, "item_name": w.item_name,
            "parent_id": w.parent_id, "phase_id": w.phase_id,
            "phase_name": phases[w.phase_id].phase_name if w.phase_id in phases else None,
            "item_level": w.item_level, "owner_name": w.owner_name,
            "plan_start": w.plan_start.isoformat() if w.plan_start else None,
            "plan_end": w.plan_end.isoformat() if w.plan_end else None,
            "actual_start": w.actual_start.isoformat() if w.actual_start else None,
            "actual_end": w.actual_end.isoformat() if w.actual_end else None,
            "offset_start": off(w.plan_start), "offset_end": off(w.plan_end),
            "offset_today": off(today),
            "duration_days": w.duration_days, "progress": w.progress,
            "is_critical": w.is_critical, "slack_days": w.slack_days,
            "status": w.status, "risk_level": w.risk_level,
            "overdue": bool(w.plan_end and w.plan_end < today
                            and w.status not in ("COMPLETED", "CLOSED")),
        })
    return {
        "project": {"id": p.id, "project_code": p.project_code,
                    "project_name": p.project_name,
                    "start_date": p.start_date.isoformat() if p.start_date else None,
                    "planned_end_date": p.planned_end_date.isoformat() if p.planned_end_date else None,
                    "today": today.isoformat(), "progress": p.progress},
        "tasks": tasks,
        "dependencies": [{
            "id": d.id, "predecessor_id": d.predecessor_id,
            "successor_id": d.successor_id, "dep_type": d.dep_type,
            "lag_days": d.lag_days,
        } for d in deps],
        "critical_path": cpm.get("critical_path", []),
        "critical_task_count": cpm.get("critical_task_count", 0),
        "project_duration_days": cpm.get("project_duration_days", 0),
        "basis": cpm.get("basis"),
        "data_label": "演示数据",
    }


@router.get("/{project_id}/evm")
def project_evm(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    """挣值分析（EVM）：EV / PV / AC / CPI / SPI / EAC / VAC + 12 个月趋势。"""
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    diag = project_engine.diagnose_project(db, p)
    cost = diag["cost"]
    costs = list(db.scalars(select(ProjectCost).where(ProjectCost.project_id == project_id)
                            .order_by(ProjectCost.occur_date)).all())

    # 按月汇总计划成本 / 实际成本，并计算累计 EV / PV / AC
    months: dict[str, dict[str, float]] = {}
    for c in costs:
        if not c.occur_date:
            continue
        k = f"{c.occur_date.year}-{c.occur_date.month:02d}"
        m = months.setdefault(k, {"planned": 0.0, "actual": 0.0})
        m["planned"] += c.planned_cost or 0
        m["actual"] += c.actual_amount or 0

    budget = cost.get("budget") or 0
    total_planned = sum(m["planned"] for m in months.values()) or budget
    trend = []
    cum_pv = cum_ac = 0.0
    progress = (p.progress or 0) / 100
    for k in sorted(months):
        cum_pv += months[k]["planned"]
        cum_ac += months[k]["actual"]
        pv_ratio = cum_pv / total_planned if total_planned else 0
        cum_ev = budget * progress * pv_ratio
        trend.append({
            "month": k,
            "pv": round(cum_pv, 2), "ac": round(cum_ac, 2), "ev": round(cum_ev, 2),
            "sv": round(cum_ev - cum_pv, 2), "cv": round(cum_ev - cum_ac, 2),
            "spi": round(cum_ev / cum_pv, 3) if cum_pv else None,
            "cpi": round(cum_ev / cum_ac, 3) if cum_ac else None,
        })

    return {
        "project": {"id": p.id, "project_code": p.project_code,
                    "project_name": p.project_name, "progress": p.progress},
        "evm": cost,
        "trend": trend,
        "basis": {
            "ev": "EV = 批准预算 × 实际进度",
            "pv": "PV = 按月度计划成本累加（计划价值）",
            "ac": "AC = 项目实际成本累计",
            "cpi": "CPI = EV ÷ AC，< 1 表示成本超支",
            "spi": "SPI = EV ÷ PV，< 1 表示进度落后",
            "eac": "EAC = 批准预算 ÷ CPI（按当前成本效率外推）",
            "vac": "VAC = 批准预算 − EAC，负数表示预计超支",
        },
        "data_sufficient": cost.get("data_sufficient", True),
        "missing_data": cost.get("missing_data", []),
        "data_label": "演示数据",
    }


@router.get("/{project_id}/risks")
def project_risks(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    """风险登记册 + 5×5 概率影响矩阵。"""
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    risks = list(db.scalars(select(ProjectRisk).where(ProjectRisk.project_id == project_id)).all())
    matrix = [[0] * 5 for _ in range(5)]   # matrix[impact-1][prob-1]
    for r in risks:
        prob = min(max(r.probability or 3, 1), 5)
        impact = min(max(r.impact or 3, 1), 5)
        matrix[impact - 1][prob - 1] += 1
    return {
        "items": [_risk_row(r) for r in risks],
        "matrix": matrix,
        "matrix_axis": {
            "x": "发生概率（1 极低 ~ 5 极高）",
            "y": "影响程度（1 轻微 ~ 5 严重）",
        },
        "level_zones": [
            {"name": "低风险", "score_min": 1, "score_max": 4, "color": "#1FB6A6"},
            {"name": "中风险", "score_min": 5, "score_max": 9, "color": "#F2C94C"},
            {"name": "高风险", "score_min": 10, "score_max": 16, "color": "#F2994A"},
            {"name": "重大风险", "score_min": 17, "score_max": 25, "color": "#EB5757"},
        ],
        "data_label": "演示数据",
    }


@router.patch("/{project_id}/tasks/{task_id}")
def update_task_progress(project_id: int, task_id: int, progress: float,
                         db: DbSession, auth: CurrentAuth,
                         actual_start: str | None = None, actual_end: str | None = None,
                         note: str | None = None) -> dict[str, Any]:
    """更新 WBS 任务进度（联动项目进度、重算关键路径、写审计）。"""
    auth.require("project", "EDIT")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    if not auth.can_access_project(project_id):
        raise HTTPException(403, "无该项目的数据权限")
    if not 0 <= progress <= 100:
        raise HTTPException(400, "进度必须在 0~100 之间")
    w = db.get(WbsItem, task_id)
    if not w or w.project_id != project_id:
        raise HTTPException(404, "任务不存在或不属于该项目")

    before = w.progress
    w.progress = round(progress, 2)
    if actual_start:
        w.actual_start = dt.date.fromisoformat(actual_start)
    if actual_end:
        w.actual_end = dt.date.fromisoformat(actual_end)
    if progress >= 100:
        w.status = "COMPLETED"
        if not w.actual_end:
            w.actual_end = dt.date.today()
    elif progress > 0:
        w.status = "IN_PROGRESS"
        if not w.actual_start:
            w.actual_start = dt.date.today()

    # 按权重回算项目整体进度（加权，非算术平均）
    leaves = list(db.scalars(select(WbsItem).where(WbsItem.project_id == project_id,
                                                   WbsItem.item_level == 2)).all())
    tw = sum(x.weight or 0 for x in leaves)
    old_progress = p.progress
    if tw:
        p.progress = round(sum((x.progress or 0) * (x.weight or 0) for x in leaves) / tw, 2)
    else:
        p.progress = round(sum(x.progress or 0 for x in leaves) / len(leaves), 2) if leaves else p.progress
    # 计划进度按时间推进
    if p.start_date and p.planned_end_date:
        total = (p.planned_end_date - p.start_date).days or 1
        elapsed = (dt.date.today() - p.start_date).days
        p.planned_progress = round(min(max(elapsed / total * 100, 0), 100), 2)

    # 重算关键路径（引擎自行写回 slack_days / is_critical）
    cpm = project_engine.compute_critical_path(db, project_id)

    write_audit(db, module="project", action="EDIT", auth=auth, object_type="WbsItem",
                object_id=w.id, object_name=f"{w.wbs_code} {w.item_name}",
                before_value={"progress": before}, after_value={"progress": w.progress},
                change_summary=(f"更新任务进度 {before}% → {w.progress}%；"
                                f"项目整体进度 {old_progress}% → {p.progress}%"
                                + (f"；备注：{note}" if note else "")),
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": f"任务进度已更新为 {w.progress}%，项目整体进度 {p.progress}%",
        "task_progress": w.progress, "project_progress": p.progress,
        "critical_path": cpm.get("critical_path", []),
        "critical_task_count": cpm.get("critical_task_count", 0),
    }


# ---------------------------------------------------------------- 敏捷
@router.get("/{project_id}/agile")
def project_agile(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    """敏捷全景：Epic / Feature / User Story / Sprint / 燃尽图 / Velocity。"""
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    if p.management_method not in ("AGILE", "HYBRID"):
        raise HTTPException(400, f"项目「{p.project_name}」管理方式为 "
                                 f"{METHOD_NAMES.get(p.management_method)}，不适用敏捷视图")
    metrics = project_engine.compute_agile_metrics(db, project_id)
    epics = list(db.scalars(select(Epic).where(Epic.project_id == project_id)).all())
    features = list(db.scalars(select(Feature).where(Feature.project_id == project_id)).all())
    stories = list(db.scalars(select(UserStory).where(UserStory.project_id == project_id)
                              .order_by(UserStory.backlog_order)).all())
    sprints = list(db.scalars(select(Sprint).where(Sprint.project_id == project_id)
                              .order_by(Sprint.sprint_code)).all())
    story_map = {s.id: s for s in stories}
    feat_map = {f.id: f for f in features}
    epic_map = {e.id: e for e in epics}

    return {
        "project": {"id": p.id, "project_code": p.project_code,
                    "project_name": p.project_name,
                    "management_method": p.management_method},
        "metrics": metrics,
        "epics": [{
            "id": e.id, "epic_code": e.epic_code, "epic_title": e.epic_title,
            "status": e.status, "owner": e.owner, "story_points": e.story_points,
            "priority": e.priority, "description": e.description,
            "start_date": e.start_date.isoformat() if e.start_date else None,
            "target_date": e.target_date.isoformat() if e.target_date else None,
            "feature_count": len([f for f in features if f.epic_id == e.id]),
        } for e in epics],
        "features": [{
            "id": f.id, "feature_code": f.feature_code, "feature_title": f.feature_title,
            "epic_id": f.epic_id,
            "epic_title": epic_map[f.epic_id].epic_title if f.epic_id in epic_map else None,
            "status": f.status, "owner": f.owner, "story_points": f.story_points,
            "priority": f.priority,
            "story_count": len([s for s in stories if s.feature_id == f.id]),
        } for f in features],
        "stories": [{
            "id": s.id, "story_code": s.story_code, "story_title": s.story_title,
            "story_point": s.story_point, "status": s.status,
            "priority": s.priority, "feature_id": s.feature_id,
            "feature_title": feat_map[s.feature_id].feature_title if s.feature_id in feat_map else None,
            "sprint_id": s.sprint_id,
            "assignee": s.assignee_name,
            "as_a": s.as_a, "i_want": s.i_want, "so_that": s.so_that,
            "labels": s.labels,
            "acceptance_criteria": s.acceptance_criteria,
            "backlog_order": s.backlog_order,
        } for s in stories],
        "sprints": [{
            "id": s.id, "sprint_code": s.sprint_code, "sprint_name": s.sprint_name,
            "sprint_goal": s.sprint_goal, "status": s.status,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "total_points": s.total_points, "done_points": s.done_points,
            "completed_rate": s.completed_rate, "velocity": s.velocity,
            "burndown": s.burndown,
            "task_count": len(db.scalars(select(SprintTask).where(SprintTask.sprint_id == s.id)).all()),
        } for s in sprints],
        "backlog": [{
            "id": s.id, "story_code": s.story_code, "story_title": s.story_title,
            "story_point": s.story_point, "priority": s.priority,
            "status": s.status, "backlog_order": s.backlog_order,
            "sprint_id": s.sprint_id,
        } for s in stories if not s.sprint_id],
        "data_label": "演示数据",
    }


@router.get("/sprints/{sprint_id}/board")
def sprint_board(sprint_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """Sprint 看板（按 board_column 分列）+ 燃尽图。"""
    auth.require("project", "VIEW")
    s = db.get(Sprint, sprint_id)
    if not s:
        raise HTTPException(404, "Sprint 不存在")
    p = db.get(Project, s.project_id)
    if p and not auth.can_access_park(p.park_id):
        raise HTTPException(403, "无权访问该 Sprint")
    tasks = list(db.scalars(select(SprintTask).where(SprintTask.sprint_id == sprint_id)
                            .order_by(SprintTask.column_order)).all())
    columns_order = ["TODO", "IN_PROGRESS", "TESTING", "DONE"]
    col_names = {"TODO": "待办", "IN_PROGRESS": "进行中", "TESTING": "测试中", "DONE": "已完成"}
    stories = {x.id: x for x in db.scalars(select(UserStory).where(
        UserStory.sprint_id == sprint_id)).all()}
    columns = []
    for c in columns_order:
        ct = [t for t in tasks if t.board_column == c]
        columns.append({
            "column": c, "column_name": col_names[c],
            "count": len(ct),
            "story_points": round(sum(t.story_point or 0 for t in ct), 1),
            "tasks": [{
                "id": t.id, "task_code": t.task_code, "task_title": t.task_title,
                "story_point": t.story_point, "assignee": t.assignee,
                "priority": t.priority, "task_type": t.task_type,
                "status": t.status, "column_order": t.column_order,
                "estimate_hours": t.estimate_hours, "actual_hours": t.actual_hours,
                "story_id": t.story_id,
                "story_title": stories[t.story_id].story_title if t.story_id in stories else None,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "is_blocked": t.is_blocked, "blocked_reason": t.blocked_reason,
            } for t in sorted(ct, key=lambda x: x.column_order or 0)],
        })
    return {
        "sprint": {
            "id": s.id, "sprint_code": s.sprint_code, "sprint_name": s.sprint_name,
            "sprint_goal": s.sprint_goal, "status": s.status,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "total_points": s.total_points, "done_points": s.done_points,
            "completed_rate": s.completed_rate, "velocity": s.velocity,
            "burndown": s.burndown,
        },
        "project": {"id": p.id, "project_name": p.project_name} if p else None,
        "columns": columns,
        "summary": {
            "task_count": len(tasks),
            "done_count": len([t for t in tasks if t.board_column == "DONE"]),
            "blocked_count": len([t for t in tasks if t.is_blocked]),
            "total_points": round(sum(t.story_point or 0 for t in tasks), 1),
            "done_points": round(sum(t.story_point or 0 for t in tasks
                                     if t.board_column == "DONE"), 1),
            "total_estimate_hours": round(sum(t.estimate_hours or 0 for t in tasks), 1),
            "total_actual_hours": round(sum(t.actual_hours or 0 for t in tasks), 1),
        },
        "data_label": "演示数据",
    }


@router.patch("/sprint-tasks/{task_id}/move")
def move_sprint_task(task_id: int, board_column: str, db: DbSession, auth: CurrentAuth,
                     column_order: int | None = None) -> dict[str, Any]:
    """看板拖动：移动 Sprint 任务列（真实写库 + 重算 Sprint 完成率 + 审计）。"""
    auth.require("project", "EDIT")
    if board_column not in ("TODO", "IN_PROGRESS", "TESTING", "DONE"):
        raise HTTPException(400, f"非法看板列：{board_column}")
    t = db.get(SprintTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    s = db.get(Sprint, t.sprint_id)
    if not s:
        raise HTTPException(404, "任务未关联 Sprint")
    p = db.get(Project, s.project_id)
    if p and not auth.can_access_park(p.park_id):
        raise HTTPException(403, "无权访问该任务")
    if not auth.can_access_project(s.project_id):
        raise HTTPException(403, "无该项目的数据权限")

    before = t.board_column
    t.board_column = board_column
    if column_order is not None:
        t.column_order = column_order
    if board_column == "DONE":
        t.status = "DONE"
        if not t.actual_hours:
            t.actual_hours = t.estimate_hours
    else:
        t.status = board_column

    # 重算 Sprint 完成率
    all_tasks = list(db.scalars(select(SprintTask).where(SprintTask.sprint_id == s.id)).all())
    s.done_points = round(sum(x.story_point or 0 for x in all_tasks
                              if x.board_column == "DONE"), 1)
    s.total_points = round(sum(x.story_point or 0 for x in all_tasks), 1)
    s.completed_rate = round(s.done_points / s.total_points * 100, 2) if s.total_points else 0.0

    write_audit(db, module="project", action="EDIT", auth=auth, object_type="SprintTask",
                object_id=t.id, object_name=f"{t.task_code} {t.task_title}",
                before_value={"board_column": before},
                after_value={"board_column": board_column},
                change_summary=f"看板拖动：{before} → {board_column}；Sprint 完成率 {s.completed_rate}%",
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": f"任务「{t.task_title}」已移至 {board_column}",
        "board_column": board_column,
        "sprint_completed_rate": s.completed_rate,
        "sprint_done_points": s.done_points,
    }


# ---------------------------------------------------------------- 里程碑 / 变更
@router.get("/{project_id}/milestones")
def project_milestones(db: DbSession, auth: CurrentAuth, project_id: int) -> dict[str, Any]:
    auth.require("project", "VIEW")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    ms = list(db.scalars(select(Milestone).where(Milestone.project_id == project_id)
                         .order_by(Milestone.sort_order)).all())
    today = dt.date.today()
    return {
        "items": [{
            "id": m.id, "milestone_code": m.milestone_code,
            "milestone_name": m.milestone_name, "status": m.status,
            "plan_date": m.plan_date.isoformat() if m.plan_date else None,
            "actual_date": m.actual_date.isoformat() if m.actual_date else None,
            "delay_days": m.delay_days, "owner": m.owner,
            "deliverable": m.deliverable, "is_key": m.is_key,
            "is_overdue": bool(m.plan_date and m.plan_date < today
                               and m.status not in ("COMPLETED", "ACHIEVED")),
        } for m in ms],
        "summary": {
            "total": len(ms),
            "achieved": len([m for m in ms if m.status in ("COMPLETED", "ACHIEVED")]),
            "delayed": len([m for m in ms if m.status == "DELAYED"
                            or (m.plan_date and m.plan_date < today
                                and m.status not in ("COMPLETED", "ACHIEVED"))]),
            "completion_rate": round(len([m for m in ms if m.status in ("COMPLETED", "ACHIEVED")])
                                     / len(ms) * 100, 2) if ms else 0.0,
        },
        "data_label": "演示数据",
    }


@router.post("/{project_id}/changes/{change_id}/decision")
def decide_change(project_id: int, change_id: int, decision: str, db: DbSession,
                  auth: CurrentAuth, comment: str | None = None) -> dict[str, Any]:
    """项目变更审批决策（高影响动作 → 必须 project:APPROVE 权限 + 审计）。"""
    auth.require("project", "APPROVE")
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, "decision 必须为 APPROVED 或 REJECTED")
    p = db.get(Project, project_id)
    if not p or not auth.can_access_park(p.park_id):
        raise HTTPException(404, "项目不存在或无权访问")
    c = db.get(ProjectChange, change_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "变更记录不存在或不属于该项目")
    if c.status not in ("PENDING", "IN_REVIEW"):
        raise HTTPException(400, f"变更当前状态为 {c.status}，不可重复决策")

    before = c.status
    c.status = decision
    c.approve_date = dt.date.today()
    c.approver_name = auth.user.real_name
    c.approve_comment = comment

    # 变更批准 → 真实影响项目基线与预算
    impact_note = ""
    if decision == "APPROVED":
        if c.impact_schedule_days:
            base = p.baseline_end_date or p.planned_end_date
            if base:
                p.baseline_end_date = base
                p.planned_end_date = base + dt.timedelta(days=c.impact_schedule_days)
                impact_note += f"计划完工日期顺延 {c.impact_schedule_days} 天；"
        if c.impact_cost:
            p.budget = round((p.budget or 0) + c.impact_cost, 2)
            impact_note += f"项目预算增加 {c.impact_cost:,.2f} 元；"

    write_audit(db, module="project", action="APPROVE", auth=auth, object_type="ProjectChange",
                object_id=c.id, object_name=f"{c.change_code} {c.change_title}",
                before_value={"status": before}, after_value={"status": decision},
                change_summary=(f"变更审批结论：{'同意' if decision == 'APPROVED' else '驳回'}"
                                f"；{impact_note}{comment or ''}"),
                approval_info=f"审批人：{auth.user.real_name}（{auth.role_label}）",
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": (f"变更「{c.change_title}」已{'批准' if decision == 'APPROVED' else '驳回'}"
                    + (f"。{impact_note}" if impact_note else "")),
        "status": c.status, "impact_note": impact_note,
    }

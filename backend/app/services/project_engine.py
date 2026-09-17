"""项目进度引擎：CPM 关键路径、挣值分析、延期与预算风险、健康度诊断。

所有结果均可解释、可追溯：每个结论都返回其计算依据 (basis)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Milestone,
    Project,
    ProjectCost,
    ProjectRisk,
    ProjectChange,
    TaskDependency,
    WbsItem,
)

# 关键路径计算中用作兜底的任务工期
DEFAULT_DURATION = 5

# 视为「已完成」的里程碑状态。project.py / dashboard / agent 工具共用同一口径。
MILESTONE_DONE_STATUSES = ("COMPLETED", "ACHIEVED")


def milestone_stats(db: Session, project_ids: list[int]) -> dict[int, tuple[int, int]]:
    """批量统计若干项目的里程碑 (总数, 已完成数)。

    以 `milestones` 表为唯一数据源。

    为什么不用 projects.milestone_total / milestone_done：
    这两个冗余列在 seed 阶段从未被写入，全库恒为 0，任何读它的地方都会
    得到 0% —— 驾驶舱「里程碑达成率」、项目列表「里程碑进度」、AI 项目
    洞察三处都曾因此显示 0。
    """
    out: dict[int, tuple[int, int]] = {pid: (0, 0) for pid in project_ids}
    if not project_ids:
        return out
    rows = db.execute(
        select(Milestone.project_id, Milestone.status, func.count())
        .where(Milestone.project_id.in_(project_ids))
        .group_by(Milestone.project_id, Milestone.status)
    ).all()
    for pid, status, cnt in rows:
        total, done = out.get(pid, (0, 0))
        total += int(cnt)
        if status in MILESTONE_DONE_STATUSES:
            done += int(cnt)
        out[pid] = (total, done)
    return out


# --------------------------------------------------------------------------
# 关键路径法 (CPM)
# --------------------------------------------------------------------------


def compute_critical_path(db: Session, project_id: int) -> dict[str, Any]:
    """对项目全部 WBS 叶子任务执行前推/后推，计算关键路径与总时差。

    返回结构：
      tasks: [{id, wbs_code, name, plan_start, plan_end, es, ef, ls, lf, slack, is_critical}]
      critical_path: [wbs_code...]
      project_duration_days: int
      basis: 计算依据说明
    """
    items: list[WbsItem] = list(
        db.scalars(
            select(WbsItem).where(WbsItem.project_id == project_id).order_by(WbsItem.sort_order, WbsItem.id)
        ).all()
    )
    if not items:
        return {
            "tasks": [],
            "critical_path": [],
            "project_duration_days": 0,
            "basis": "该项目尚未建立 WBS，无法计算关键路径。",
            "data_sufficient": False,
        }

    # 只对叶子任务做网络计算（叶子 = 没有子节点的 WBS 项）
    parent_ids = {i.parent_id for i in items if i.parent_id}
    leaves = [i for i in items if i.id not in parent_ids]

    by_code = {i.wbs_code: i for i in leaves}
    by_id = {i.id: i for i in leaves}

    deps = list(
        db.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id)).all()
    )

    # 若没有显式依赖，按 WBS 顺序构造 FS 链（保证可计算，并注明依据）
    implicit_chain = False
    if not deps and len(leaves) > 1:
        ordered = sorted(leaves, key=lambda x: (x.plan_start or dt.date.max, x.sort_order, x.id))
        for a, b in zip(ordered, ordered[1:]):
            deps.append(TaskDependency(project_id=project_id, predecessor_id=a.id, successor_id=b.id,
                                       dep_type="FS", lag_days=0))
        implicit_chain = True

    preds: dict[int, list[TaskDependency]] = {}
    succs: dict[int, list[TaskDependency]] = {}
    for d in deps:
        if d.predecessor_id in by_id and d.successor_id in by_id:
            preds.setdefault(d.successor_id, []).append(d)
            succs.setdefault(d.predecessor_id, []).append(d)

    def dur(it: WbsItem) -> int:
        if it.plan_start and it.plan_end:
            return max((it.plan_end - it.plan_start).days, 1)
        if it.duration_days:
            return max(it.duration_days, 1)
        return DEFAULT_DURATION

    # 拓扑排序（Kahn）
    indeg = {i.id: 0 for i in leaves}
    for d in deps:
        if d.successor_id in indeg:
            indeg[d.successor_id] += 1
    queue = [i.id for i in leaves if indeg[i.id] == 0]
    order: list[int] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for d in succs.get(nid, []):
            indeg[d.successor_id] -= 1
            if indeg[d.successor_id] == 0:
                queue.append(d.successor_id)
    for i in leaves:  # 环形依赖兜底
        if i.id not in order:
            order.append(i.id)

    ES: dict[int, int] = {}
    EF: dict[int, int] = {}
    for nid in order:
        es = 0
        for d in preds.get(nid, []):
            p_ef = EF.get(d.predecessor_id, 0)
            if d.dep_type == "FS":
                es = max(es, p_ef + d.lag_days)
            elif d.dep_type == "SS":
                es = max(es, ES.get(d.predecessor_id, 0) + d.lag_days)
            elif d.dep_type == "FF":
                es = max(es, p_ef + d.lag_days - dur(by_id[nid]))
            else:  # SF
                es = max(es, ES.get(d.predecessor_id, 0) + d.lag_days - dur(by_id[nid]))
        ES[nid] = max(es, 0)
        EF[nid] = ES[nid] + dur(by_id[nid])

    total = max(EF.values()) if EF else 0

    LS: dict[int, int] = {}
    LF: dict[int, int] = {}
    for nid in reversed(order):
        succ = succs.get(nid, [])
        if not succ:
            LF[nid] = total
        else:
            lf = total
            for d in succ:
                s_ls = LS.get(d.successor_id, total)
                if d.dep_type == "FS":
                    lf = min(lf, s_ls - d.lag_days)
                elif d.dep_type == "SS":
                    lf = min(lf, LS.get(d.successor_id, 0) - d.lag_days + dur(by_id[nid]))
                else:
                    lf = min(lf, LS.get(d.successor_id, total) - d.lag_days + dur(by_id[nid]))
            LF[nid] = lf
        LS[nid] = LF[nid] - dur(by_id[nid])

    tasks_out = []
    critical_codes = []
    for i in leaves:
        slack = max((LS.get(i.id, 0) - ES.get(i.id, 0)), 0)
        is_critical = slack == 0
        if is_critical:
            critical_codes.append(i.wbs_code)
        # 回写计算结果，供甘特图直接读取
        i.es = None  # 保留原计划日期，CPM 相对工期以 basis 说明
        i.slack_days = slack
        i.is_critical = is_critical
        tasks_out.append({
            "id": i.id,
            "wbs_code": i.wbs_code,
            "item_name": i.item_name,
            "owner_name": i.owner_name,
            "plan_start": i.plan_start.isoformat() if i.plan_start else None,
            "plan_end": i.plan_end.isoformat() if i.plan_end else None,
            "duration_days": dur(i),
            "progress": i.progress,
            "budget": i.budget,
            "actual_cost": i.actual_cost,
            "status": i.status,
            "risk_level": i.risk_level,
            "early_start_day": ES.get(i.id, 0),
            "early_finish_day": EF.get(i.id, 0),
            "late_start_day": LS.get(i.id, 0),
            "late_finish_day": LF.get(i.id, 0),
            "slack_days": slack,
            "is_critical": is_critical,
            "predecessors": i.predecessors or [],
            "successors": i.successors or [],
        })

    basis = (
        f"基于 {len(leaves)} 个叶子任务、{len(deps)} 条依赖关系执行 CPM 前推/后推计算。"
        + ("（项目未维护显式依赖，已按计划开始时间顺序构造 FS 链，建议补充真实依赖关系）"
           if implicit_chain else "")
    )

    return {
        "tasks": tasks_out,
        "critical_path": critical_codes,
        "project_duration_days": total,
        "critical_task_count": len(critical_codes),
        "basis": basis,
        "data_sufficient": True,
        "implicit_dependency_chain": implicit_chain,
    }


# --------------------------------------------------------------------------
# 进度偏差 / 延期诊断
# --------------------------------------------------------------------------


def compute_schedule_variance(db: Session, project: Project) -> dict[str, Any]:
    """计算进度偏差、延期天数、延期主因（基于真实数据，不做无依据推断）。"""
    today = dt.date.today()
    result: dict[str, Any] = {
        "project_id": project.id,
        "project_name": project.project_name,
        "management_method": project.management_method,
        "data_sufficient": True,
        "missing_data": [],
    }

    has_actual = project.progress is not None and (
        project.actual_cost > 0 or any(
            t.actual_start is not None for t in
            db.scalars(select(WbsItem).where(WbsItem.project_id == project.id)).all()
        )
    )

    planned_progress = project.planned_progress or 0.0
    if project.start_date and project.planned_end_date and project.planned_end_date > project.start_date:
        total_days = (project.planned_end_date - project.start_date).days
        elapsed = (today - project.start_date).days
        planned_progress = round(min(max(elapsed / total_days * 100, 0), 100), 2)
        project.planned_progress = planned_progress

    actual_progress = project.progress or 0.0
    variance = round(actual_progress - planned_progress, 2)

    delay_days = 0
    if project.planned_end_date and today > project.planned_end_date and project.status not in ("COMPLETED", "CLOSED"):
        delay_days = (today - project.planned_end_date).days

    result.update({
        "planned_progress": planned_progress,
        "actual_progress": actual_progress,
        "progress_variance": variance,
        "delay_days": delay_days,
        "is_delayed": delay_days > 0 or variance < -10,
        "actual_progress_available": has_actual,
    })

    if not has_actual and actual_progress == 0:
        result["data_sufficient"] = False
        result["missing_data"].append("缺少实际进度与成本发生记录")
        result["conclusion"] = "缺少实际进度数据，无法判断项目是否延期。"
        return result

    # 逐任务识别延期环节
    today_d = today
    delayed_tasks = []
    wbs_list = list(db.scalars(select(WbsItem).where(WbsItem.project_id == project.id)).all())
    for t in wbs_list:
        if t.plan_end and t.plan_end < today_d and t.progress < 100:
            d = (today_d - t.plan_end).days
            delayed_tasks.append({
                "wbs_code": t.wbs_code,
                "item_name": t.item_name,
                "owner_name": t.owner_name,
                "plan_end": t.plan_end.isoformat(),
                "progress": t.progress,
                "delay_days": d,
                "is_critical": t.is_critical,
                "slack_days": t.slack_days,
                "risk_level": t.risk_level,
            })
    delayed_tasks.sort(key=lambda x: (-x["delay_days"], not x["is_critical"]))
    result["delayed_tasks"] = delayed_tasks[:20]
    result["delayed_task_count"] = len(delayed_tasks)

    # 关键路径上的延期任务 → 直接影响总工期
    critical_delayed = [t for t in delayed_tasks if t["is_critical"]]
    result["critical_delayed_tasks"] = critical_delayed
    result["critical_impact_days"] = max([t["delay_days"] for t in critical_delayed], default=0)

    # 归因：从风险、变更、问题、采购记录中提取
    causes: list[dict[str, Any]] = []

    open_risks = list(db.scalars(
        select(ProjectRisk).where(ProjectRisk.project_id == project.id, ProjectRisk.status == "OPEN")
        .order_by(ProjectRisk.risk_score.desc())
    ).all())
    high_risks = [r for r in open_risks if r.risk_level in ("HIGH", "CRITICAL")]
    if high_risks:
        causes.append({
            "category": "已发生/高风险项",
            "detail": f"存在 {len(high_risks)} 项高等级未关闭风险，最高为「{high_risks[0].risk_title}」（等级 {high_risks[0].risk_level}，评分 {high_risks[0].risk_score}）",
            "weight": "高",
            "evidence": [r.risk_code for r in high_risks[:5]],
        })

    approved_changes = list(db.scalars(
        select(ProjectChange).where(ProjectChange.project_id == project.id,
                                    ProjectChange.status == "APPROVED")
    ).all())
    if approved_changes:
        total_schedule_impact = sum(c.impact_schedule_days or 0 for c in approved_changes)
        total_cost_impact = sum(c.impact_cost or 0 for c in approved_changes)
        causes.append({
            "category": "已批准变更",
            "detail": f"{len(approved_changes)} 项已批准变更累计工期影响 {total_schedule_impact} 天、成本影响 {total_cost_impact:,.0f} 元",
            "weight": "高" if total_schedule_impact >= 15 else "中",
            "evidence": [c.change_code for c in approved_changes],
        })
        result["change_schedule_impact_days"] = total_schedule_impact
        result["change_cost_impact"] = total_cost_impact

    pending_changes = list(db.scalars(
        select(ProjectChange).where(ProjectChange.project_id == project.id,
                                    ProjectChange.status.in_(["PENDING", "IN_REVIEW"]))
    ).all())
    if pending_changes:
        causes.append({
            "category": "待审批变更",
            "detail": f"{len(pending_changes)} 项变更尚未完成审批，工期存在不确定性",
            "weight": "中",
            "evidence": [c.change_code for c in pending_changes],
        })

    # 采购/供应商环节：从成本科目中查找
    purchase_rows = list(db.scalars(
        select(ProjectCost).where(ProjectCost.project_id == project.id,
                                  ProjectCost.cost_type.in_(["采购", "合同"]))
    ).all())
    if purchase_rows:
        unpaid = [r for r in purchase_rows if (r.contract_amount or 0) > (r.paid_amount or 0)]
        if unpaid:
            gap = sum((r.contract_amount or 0) - (r.paid_amount or 0) for r in unpaid)
            causes.append({
                "category": "采购/合同支付",
                "detail": f"{len(unpaid)} 项采购/合同尚未完成支付，合同额与已支付差额 {gap:,.0f} 元，可能影响供应商履约进度",
                "weight": "中",
                "evidence": [r.cost_subject for r in unpaid[:5]],
            })

    # 进度落后最多的非关键任务（说明资源投入可能不足）
    slow_tasks = sorted([t for t in wbs_list if t.progress < (t.weight * 0 + 60) and t.plan_start
                         and t.plan_start <= today_d and t.progress < 100],
                        key=lambda x: x.progress)[:5]
    if slow_tasks:
        causes.append({
            "category": "执行进度落后任务",
            "detail": "以下任务已到计划执行期但完成率偏低：" + "；".join(
                f"{t.wbs_code} {t.item_name}（{t.progress:.0f}%）" for t in slow_tasks),
            "weight": "中",
            "evidence": [t.wbs_code for t in slow_tasks],
        })

    if not causes:
        causes.append({
            "category": "数据说明",
            "detail": "当前数据库中该项目未登记高风险项、已批准变更或采购缺口记录，延期原因无法从现有数据归因。建议补充风险登记册、变更记录与采购台账。",
            "weight": "低",
            "evidence": [],
        })

    result["causes"] = causes
    result["basis"] = (
        f"依据：项目计划起止日期、{len(wbs_list)} 项 WBS 任务的计划/实际日期与完成率、"
        f"{len(open_risks)} 条未关闭风险、{len(approved_changes)} 条已批准变更、{len(purchase_rows)} 条成本记录。"
    )
    return result


# --------------------------------------------------------------------------
# 挣值 / 成本分析
# --------------------------------------------------------------------------


def compute_cost_analysis(db: Session, project: Project) -> dict[str, Any]:
    today = dt.date.today()
    costs = list(db.scalars(select(ProjectCost).where(ProjectCost.project_id == project.id)).all())

    budget = project.approved_budget or project.budget or 0.0
    actual = project.actual_cost or 0.0
    committed = project.committed_cost or 0.0
    paid = project.paid_amount or 0.0

    if budget == 0 and costs:
        budget = sum(c.budget_amount or 0 for c in costs)
    if budget == 0 and actual == 0:
        return {
            "project_id": project.id,
            "data_sufficient": False,
            "conclusion": "该项目尚未登记预算与实际成本数据，无法进行成本分析。",
            "missing_data": ["项目预算", "实际成本发生记录"],
            "budget": 0, "actual_cost": 0,
        }

    progress = (project.progress or 0) / 100
    planned_progress = (project.planned_progress or 0) / 100
    ev = budget * progress                       # 挣值
    pv = budget * planned_progress               # 计划价值
    ac = actual                                  # 实际成本
    cpi = round(ev / ac, 3) if ac > 0 else None
    spi = round(ev / pv, 3) if pv > 0 else None
    eac = round(budget / cpi, 2) if cpi else None    # 预计完工成本
    vac = round(budget - eac, 2) if eac else None    # 完工偏差
    execution_rate = round(actual / budget * 100, 2) if budget else 0.0
    cost_variance = round(ev - ac, 2)

    # 按科目汇总
    subjects: dict[str, dict[str, float]] = {}
    for c in costs:
        s = subjects.setdefault(c.cost_subject, {
            "budget": 0.0, "contract": 0.0, "purchase": 0.0,
            "planned": 0.0, "actual": 0.0, "paid": 0.0,
        })
        s["budget"] += c.budget_amount or 0
        s["contract"] += c.contract_amount or 0
        s["purchase"] += c.purchase_amount or 0
        s["planned"] += c.planned_cost or 0
        s["actual"] += c.actual_amount or 0
        s["paid"] += c.paid_amount or 0
    subject_list = [
        {"cost_subject": k, **{kk: round(vv, 2) for kk, vv in v.items()},
         "execution_rate": round(v["actual"] / v["budget"] * 100, 2) if v["budget"] else 0.0,
         "variance": round(v["budget"] - v["actual"], 2)}
        for k, v in subjects.items()
    ]
    subject_list.sort(key=lambda x: -x["budget"])

    # 成本趋势曲线（按发生日期聚合实际 + 按科目计划累加）
    curve: dict[str, dict[str, float]] = {}
    cumulative = 0.0
    for c in sorted(costs, key=lambda x: (x.occur_date or dt.date.max, x.id)):
        if c.occur_date:
            key = c.occur_date.isoformat()
            cumulative += c.actual_amount or 0
            row = curve.setdefault(key, {"date": key, "actual_cum": 0.0, "planned_cum": 0.0})
            row["actual_cum"] = round(cumulative, 2)

    # 计划成本基线（线性分摊），仅在有起止日期时生成
    planned_curve: list[dict[str, Any]] = []
    if project.start_date and project.planned_end_date and budget:
        total_days = max((project.planned_end_date - project.start_date).days, 1)
        steps = min(total_days, 30)
        for i in range(steps + 1):
            d = project.start_date + dt.timedelta(days=int(total_days * i / steps))
            planned_curve.append({
                "date": d.isoformat(),
                "planned_cum": round(budget * i / steps, 2),
                "progress_pct": round(100 * i / steps, 1),
            })

    overspend_risk = None
    if eac and budget:
        gap = eac - budget
        if gap > 0:
            overspend_risk = {
                "level": "HIGH" if gap / budget > 0.1 else "MEDIUM",
                "forecast_overrun": round(gap, 2),
                "ratio": round(gap / budget * 100, 2),
                "basis": f"以当前成本绩效指数 CPI={cpi} 推算，预计完工成本 {eac:,.0f} 元，超出批准预算 {gap:,.0f} 元。",
            }

    return {
        "project_id": project.id,
        "data_sufficient": True,
        "budget": round(budget, 2),
        "approved_budget": round(project.approved_budget or 0, 2),
        "contract_amount": round(sum(c.contract_amount or 0 for c in costs), 2),
        "purchase_amount": round(sum(c.purchase_amount or 0 for c in costs), 2),
        "planned_cost": round(sum(c.planned_cost or 0 for c in costs), 2),
        "actual_cost": round(actual, 2),
        "committed_cost": round(committed, 2),
        "unpaid": round(max(committed - paid, 0), 2),
        "paid_amount": round(paid, 2),
        "execution_rate": execution_rate,
        "ev": round(ev, 2),
        "pv": round(pv, 2),
        "ac": round(ac, 2),
        "cpi": cpi,
        "spi": spi,
        "cost_variance": cost_variance,
        "eac": eac,
        "vac": vac,
        "overspend_risk": overspend_risk,
        "subjects": subject_list,
        "actual_curve": sorted(curve.values(), key=lambda x: x["date"]),
        "planned_curve": planned_curve,
        "basis": f"依据：项目预算 {budget:,.0f} 元、实际成本 {actual:,.0f} 元、完成率 {project.progress or 0}%、"
                 f"{len(costs)} 条成本科目记录。",
    }


# --------------------------------------------------------------------------
# 风险分析
# --------------------------------------------------------------------------


def compute_risk_analysis(db: Session, project_id: int) -> dict[str, Any]:
    risks = list(db.scalars(
        select(ProjectRisk).where(ProjectRisk.project_id == project_id).order_by(ProjectRisk.risk_score.desc())
    ).all())

    if not risks:
        return {
            "risks": [],
            "data_sufficient": False,
            "conclusion": "该项目风险登记册为空，无法进行风险分析。建议先补充风险识别记录。",
            "matrix": [],
        }

    matrix = [[0] * 5 for _ in range(5)]   # matrix[impact-1][prob-1]
    points = []
    for r in risks:
        p = min(max(r.probability, 1), 5)
        i = min(max(r.impact, 1), 5)
        matrix[i - 1][p - 1] += 1
        if r.status == "OPEN":
            points.append({
                "id": r.id,
                "risk_code": r.risk_code,
                "risk_title": r.risk_title,
                "category": r.risk_category,
                "probability": p,
                "impact": i,
                "score": r.risk_score,
                "level": r.risk_level,
                "owner": r.risk_owner,
                "strategy": r.strategy,
                "status": r.status,
                "ai_identified": r.ai_identified,
            })

    summary: dict[str, int] = {}
    for r in risks:
        summary[r.risk_level] = summary.get(r.risk_level, 0) + 1

    return {
        "risks": [
            {
                "id": r.id, "risk_code": r.risk_code, "risk_title": r.risk_title,
                "risk_description": r.risk_description, "risk_category": r.risk_category,
                "probability": r.probability, "impact": r.impact, "risk_score": r.risk_score,
                "risk_level": r.risk_level, "risk_owner": r.risk_owner, "strategy": r.strategy,
                "response_plan": r.response_plan, "trigger_condition": r.trigger_condition,
                "status": r.status, "due_date": r.due_date.isoformat() if r.due_date else None,
                "identified_date": r.identified_date.isoformat() if r.identified_date else None,
                "ai_identified": r.ai_identified, "related_wbs_code": r.related_wbs_code,
            } for r in risks
        ],
        "matrix": matrix,
        "points": points,
        "summary": summary,
        "avg_score": round(sum(r.risk_score for r in risks) / len(risks), 1),
        "data_sufficient": True,
        "basis": f"基于风险登记册 {len(risks)} 条风险记录（概率 × 影响 5×5 矩阵计算）。",
    }


# --------------------------------------------------------------------------
# 项目健康度诊断（AI 项目周报 / 复盘的数据基础）
# --------------------------------------------------------------------------


def diagnose_project(db: Session, project: Project) -> dict[str, Any]:
    schedule = compute_schedule_variance(db, project)
    cost = compute_cost_analysis(db, project)
    risk = compute_risk_analysis(db, project.id)

    milestones = list(db.scalars(
        select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.sort_order)
    ).all())
    ms_delayed = [m for m in milestones if m.status == "DELAYED"]
    ms_done = [m for m in milestones if m.status == "COMPLETED"]

    signals: list[dict[str, Any]] = []
    if schedule.get("is_delayed"):
        signals.append({"type": "进度", "level": "HIGH", "text": f"项目已延期 {schedule.get('delay_days', 0)} 天，进度偏差 {schedule.get('progress_variance', 0)}%"})
    if cost.get("overspend_risk"):
        signals.append({"type": "成本", "level": cost["overspend_risk"]["level"],
                        "text": cost["overspend_risk"]["basis"]})
    if risk.get("summary", {}).get("CRITICAL"):
        signals.append({"type": "风险", "level": "CRITICAL",
                        "text": f"存在 {risk['summary']['CRITICAL']} 项重大风险"})
    if risk.get("summary", {}).get("HIGH"):
        signals.append({"type": "风险", "level": "HIGH",
                        "text": f"存在 {risk['summary']['HIGH']} 项高风险"})
    if ms_delayed:
        signals.append({"type": "里程碑", "level": "HIGH",
                        "text": f"{len(ms_delayed)} 个里程碑延期：" + "、".join(m.milestone_name for m in ms_delayed[:4])})

    if not signals:
        level = "GREEN"
        conclusion = "项目进度、成本、风险三项指标均在可控范围内。" if schedule.get("data_sufficient") else \
            "现有数据未显示异常，但存在数据缺口，健康度结论置信度受限。"
    elif any(s["level"] in ("CRITICAL", "HIGH") for s in signals):
        level = "RED" if sum(1 for s in signals if s["level"] in ("CRITICAL", "HIGH")) >= 2 else "YELLOW"
        conclusion = "项目存在明确的进度或成本偏差，建议立即介入。"
    else:
        level = "YELLOW"
        conclusion = "项目存在需要关注的风险信号，建议加强跟踪。"

    return {
        "project_id": project.id,
        "project_name": project.project_name,
        "health": level,
        "conclusion": conclusion,
        "signals": signals,
        "schedule": schedule,
        "cost": cost,
        "risk": risk,
        "milestone": {
            "total": len(milestones),
            "done": len(ms_done),
            "delayed": len(ms_delayed),
            "completion_rate": round(len(ms_done) / len(milestones) * 100, 1) if milestones else 0.0,
            "items": [
                {"milestone_name": m.milestone_name,
                 "plan_date": m.plan_date.isoformat() if m.plan_date else None,
                 "actual_date": m.actual_date.isoformat() if m.actual_date else None,
                 "status": m.status, "delay_days": m.delay_days, "is_key": m.is_key}
                for m in milestones
            ],
        },
        "data_sufficient": schedule.get("data_sufficient", True) and cost.get("data_sufficient", True),
    }


def compute_agile_metrics(db: Session, project_id: int) -> dict[str, Any]:
    """敏捷指标：Velocity、燃尽、Sprint 完成率、Backlog 健康度。"""
    from app.models import Sprint, SprintTask, UserStory, Epic, Feature

    sprints = list(db.scalars(
        select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.start_date)
    ).all())
    stories = list(db.scalars(select(UserStory).where(UserStory.project_id == project_id)).all())
    tasks = list(db.scalars(select(SprintTask).where(SprintTask.project_id == project_id)).all())
    epics = list(db.scalars(select(Epic).where(Epic.project_id == project_id)).all())
    features = list(db.scalars(select(Feature).where(Feature.project_id == project_id)).all())

    done_sprints = [s for s in sprints if s.status == "COMPLETED"]
    velocity = round(sum(s.done_points or 0 for s in done_sprints) / len(done_sprints), 1) if done_sprints else 0.0

    board: dict[str, list[dict[str, Any]]] = {
        "BACKLOG": [], "TODO": [], "IN_PROGRESS": [], "TESTING": [], "DONE": []
    }
    for t in tasks:
        col = t.board_column if t.board_column in board else "BACKLOG"
        board[col].append({
            "id": t.id, "task_code": t.task_code, "task_title": t.task_title,
            "assignee_name": t.assignee_name, "story_point": t.story_point,
            "priority": t.priority, "labels": t.labels or [], "risk_level": t.risk_level,
            "is_blocked": t.is_blocked, "due_date": t.due_date.isoformat() if t.due_date else None,
            "sprint_id": t.sprint_id, "column_order": t.column_order,
        })

    total_sp = sum(s.story_point or 0 for s in stories)
    done_sp = sum(s.story_point or 0 for s in stories if s.status == "DONE")
    backlog_health = "健康"
    if len(stories) and total_sp and done_sp / total_sp < 0.3 and not sprints:
        backlog_health = "存在风险：需求池中已完成比例偏低，尚未进入迭代执行"

    return {
        "project_id": project_id,
        "data_sufficient": bool(sprints or stories),
        "epics": [{"id": e.id, "epic_code": e.epic_code, "epic_title": e.epic_title,
                   "status": e.status, "priority": e.priority, "story_points": e.story_points,
                   "owner": e.owner} for e in epics],
        "features": [{"id": f.id, "feature_code": f.feature_code, "feature_title": f.feature_title,
                      "epic_id": f.epic_id, "status": f.status, "story_points": f.story_points,
                      "priority": f.priority, "owner": f.owner} for f in features],
        "stories": [{"id": s.id, "story_code": s.story_code, "story_title": s.story_title,
                     "as_a": s.as_a, "i_want": s.i_want, "so_that": s.so_that,
                     "acceptance_criteria": s.acceptance_criteria, "story_point": s.story_point,
                     "priority": s.priority, "status": s.status, "assignee_name": s.assignee_name,
                     "sprint_id": s.sprint_id, "labels": s.labels or [],
                     "feature_id": s.feature_id, "backlog_order": s.backlog_order} for s in stories],
        "sprints": [{
            "id": s.id, "sprint_code": s.sprint_code, "sprint_name": s.sprint_name,
            "sprint_goal": s.sprint_goal,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "owner": s.owner, "story_count": s.story_count, "total_points": s.total_points,
            "done_points": s.done_points, "completed_rate": s.completed_rate,
            "velocity": s.velocity, "status": s.status, "burndown": s.burndown or [],
            "review_summary": s.review_summary, "retro_summary": s.retro_summary,
        } for s in sprints],
        "board": board,
        "velocity": velocity,
        "velocity_trend": [{"sprint": s.sprint_name, "points": s.done_points or 0,
                            "total": s.total_points or 0} for s in sprints],
        "total_story_points": total_sp,
        "done_story_points": done_sp,
        "backlog_health": backlog_health,
        "basis": f"依据：{len(epics)} 个 Epic、{len(features)} 个 Feature、{len(stories)} 条 User Story、"
                 f"{len(tasks)} 个 Sprint 任务、{len(sprints)} 个 Sprint。",
    }

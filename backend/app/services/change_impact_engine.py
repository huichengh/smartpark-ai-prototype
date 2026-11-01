"""项目变更影响分析 —— 在**不改动正式计划**的前提下推演工期、成本与关键路径变化。

三条底线（来自提示词 08 与建议书 3.5）：

1. **模拟不覆盖基线**。所有计算只读数据库、只在内存里重算一遍 CPM，
   不写 `wbs_items`、不写 `projects`。要落地必须先建变更申请、经人工审批，
   再由审批流程去改计划——这一层不给"直接生效"的口子。
2. **不输出"延期概率"**。没有带标签的历史延期样本，任何"延期 73% 的概率"都是编的。
   这里只给确定性的天数与成本，以及规则性的风险因素。
3. **假设必须写出来**。日成本、里程碑顺移规则、风险模板都随结果返回，
   并明确标注"需项目人员确认"。

计算复用 `project_engine.compute_cpm`（与甘特图同源），保证"同一个计划不会算出两个工期"。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.services.project_engine import compute_cpm

#: 可模拟的变更类型 → 对工期的默认处理
SCENARIO_TYPES: dict[str, dict[str, Any]] = {
    "APPROVAL_DELAY": {"label": "审批延误", "note": "审批卡住期间任务无法开工，按顺延处理"},
    "SHUTDOWN": {"label": "停工", "note": "现场停工，任务工期整体后移"},
    "RESOURCE_CONFLICT": {"label": "资源冲突", "note": "资源被占用，该任务工期延长"},
    "DESIGN_CHANGE": {"label": "设计变更", "note": "方案调整导致返工或等待，工期延长"},
}

#: 通用风险模板：**仅为示例**，须项目人员按实际确认（提示词 08 明确要求）
RISK_TEMPLATES: dict[str, dict[str, Any]] = {
    "DESIGN_APPROVAL": {
        "label": "设计审批阶段",
        "factors": ["图纸会审未闭环导致返工", "审批链条跨部门、缺少时限约束", "设计变更未同步到施工组织"],
        "checks": ["是否已明确各审批节点的时限与责任人", "变更是否走正式变更单而非口头确认"],
    },
    "CONSTRUCTION": {
        "label": "施工组织阶段",
        "factors": ["关键工序资源冲突", "材料设备到场滞后", "天气/外部条件导致停工"],
        "checks": ["关键路径任务是否配置了备用资源", "到场计划是否与施工计划对齐"],
    },
    "HANDOVER": {
        "label": "验收移交阶段",
        "factors": ["验收资料不齐导致无法移交", "缺陷整改未闭环", "结算依据缺失"],
        "checks": ["移交清单是否在施工阶段同步维护", "整改闭环是否有验收人签字"],
    },
}

MAX_DELAY_DAYS = 365

#: 已达成的里程碑不顺移（既成事实）
ACHIEVED_STATUSES = ("ACHIEVED", "COMPLETED", "DONE", "CLOSED")


class ScenarioInputError(ValueError):
    """输入不合法 —— 拒算并说明原因，不返回兜底数字。"""

    def __init__(self, message: str):
        super().__init__(message)


def simulate(
    tasks: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    *,
    daily_cost: float | None = None,
    milestones: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """推演一组变更对项目的影响。

    tasks:    [{id, wbs_code, name, duration, owner_name, budget, progress}]
    edges:    [{pred, succ, dep_type, lag}]
    scenarios:[{task_id, delay_days, type, note}]
    daily_cost: 日管理成本（元/天）；不提供则不出成本数字，不猜。
    """
    if not tasks:
        raise ScenarioInputError("项目没有可计算的叶子任务（WBS 为空），无法做影响分析")
    if not scenarios:
        raise ScenarioInputError("请至少给出一个变更情景（任务 + 顺延天数）")

    id_set = {t["id"] for t in tasks}
    clean: list[dict[str, Any]] = []
    for idx, sc in enumerate(scenarios):
        tid = sc.get("task_id")
        if tid not in id_set:
            raise ScenarioInputError(f"第 {idx + 1} 个情景引用了不存在的任务 id={tid}")
        days = sc.get("delay_days")
        if days is None or int(days) < 0:
            raise ScenarioInputError(f"第 {idx + 1} 个情景的顺延天数必须为非负整数")
        if int(days) > MAX_DELAY_DAYS:
            raise ScenarioInputError(f"第 {idx + 1} 个情景顺延 {days} 天超过 {MAX_DELAY_DAYS} 天上限，请先核实")
        stype = sc.get("type") or "SHUTDOWN"
        if stype not in SCENARIO_TYPES:
            raise ScenarioInputError(f"未知的变更类型：{stype}")
        clean.append({"task_id": tid, "delay_days": int(days), "type": stype,
                      "note": sc.get("note")})

    nodes = [{"id": t["id"], "duration": max(int(t.get("duration") or 1), 1)} for t in tasks]
    baseline = compute_cpm(nodes, edges)

    # 叠加顺延（同一任务多个情景累加）
    delta: dict[int, int] = {}
    for sc in clean:
        delta[sc["task_id"]] = delta.get(sc["task_id"], 0) + sc["delay_days"]
    adjusted_nodes = [{"id": n["id"], "duration": n["duration"] + delta.get(n["id"], 0)}
                      for n in nodes]
    adjusted = compute_cpm(adjusted_nodes, edges)

    by_id = {t["id"]: t for t in tasks}
    changed = []
    for nid in baseline["es"]:
        b_es, a_es = baseline["es"].get(nid, 0), adjusted["es"].get(nid, 0)
        b_ef, a_ef = baseline["ef"].get(nid, 0), adjusted["ef"].get(nid, 0)
        b_sl, a_sl = baseline["slack"].get(nid, 0), adjusted["slack"].get(nid, 0)
        if (b_es, b_ef, b_sl) == (a_es, a_ef, a_sl):
            continue
        t = by_id.get(nid, {})
        became_critical = (nid in adjusted["critical"]) and (nid not in baseline["critical"])
        # 区分"工期真的顺延了"与"只是时差变了"：两者都算受影响，但含义完全不同，
        # 混在一张表里会让人以为这条任务也要加人加钱。
        if a_ef != b_ef:
            kind = "FINISH_SHIFT"
            kind_label = f"完工顺延 {a_ef - b_ef} 天"
        elif became_critical:
            kind = "BECAME_CRITICAL"
            kind_label = "时差被吃满，转为关键任务"
        elif a_sl > b_sl:
            kind = "FLOAT_GAINED"
            kind_label = f"时差增加 {a_sl - b_sl} 天"
        else:
            kind = "FLOAT_LOST"
            kind_label = f"时差减少 {b_sl - a_sl} 天"
        changed.append({
            "change_kind": kind, "change_kind_label": kind_label,
            "task_id": nid,
            "wbs_code": t.get("wbs_code"),
            "name": t.get("name"),
            "owner_name": t.get("owner_name"),
            "baseline_es": b_es, "baseline_ef": b_ef,
            "adjusted_es": a_es, "adjusted_ef": a_ef,
            "start_shift_days": a_es - b_es,
            "finish_shift_days": a_ef - b_ef,
            "baseline_slack": b_sl, "adjusted_slack": a_sl,
            "became_critical": became_critical,
            "direct_change": nid in delta,
            "delay_days": delta.get(nid, 0),
        })
    changed.sort(key=lambda x: (x["change_kind"] != "FINISH_SHIFT",
                                -x["finish_shift_days"], x["baseline_es"]))
    shifted = [x for x in changed if x["change_kind"] == "FINISH_SHIFT"]

    total_shift = adjusted["total"] - baseline["total"]
    new_critical_codes: list[str] = []
    for nid in adjusted["order"]:
        if nid in adjusted["critical"] and nid not in baseline["critical"]:
            code = by_id.get(nid, {}).get("wbs_code")
            if code:
                new_critical_codes.append(code)

    cost_impact = None
    cost_note = "未提供日成本，故不输出成本影响（不猜测金额）"
    if daily_cost is not None:
        if daily_cost < 0:
            raise ScenarioInputError("日成本不能为负")
        cost_impact = round(total_shift * float(daily_cost), 2)
        cost_note = f"按日成本 {float(daily_cost):,.2f} 元 × 顺延 {total_shift} 天计算，仅含管理与资源占用成本"

    # 里程碑：按 FS 逻辑整体顺移（下游活动整体后移）；这是推定，不是预测。
    # **已完成/已达成的里程碑不顺移**——那是既成事实，改动它等于篡改历史。
    ms_out = []
    for m in (milestones or []):
        status = m.get("status")
        achieved = status in ACHIEVED_STATUSES
        shift = 0 if achieved else total_shift
        projected = m.get("plan_date")
        if projected and shift:
            try:
                projected = (dt.date.fromisoformat(projected)
                             + dt.timedelta(days=shift)).isoformat()
            except ValueError:
                projected = None
        ms_out.append({
            "milestone_code": m.get("milestone_code"),
            "milestone_name": m.get("milestone_name"),
            "plan_date": m.get("plan_date"),
            "status": status,
            "achieved": achieved,
            "projected_shift_days": shift,
            "projected_date": projected,
        })

    return {
        "baseline": {
            "duration_days": baseline["total"],
            "critical_path": [by_id.get(n, {}).get("wbs_code") for n in
                             [i for i in baseline["order"] if i in baseline["critical"]]],
            "critical_count": len(baseline["critical"]),
        },
        "adjusted": {
            "duration_days": adjusted["total"],
            "critical_path": [by_id.get(n, {}).get("wbs_code") for n in
                             [i for i in adjusted["order"] if i in adjusted["critical"]]],
            "critical_count": len(adjusted["critical"]),
        },
        "schedule_shift_days": total_shift,
        "shift_ratio": round(total_shift / baseline["total"] * 100, 2) if baseline["total"] else None,
        "affected_tasks": changed,
        "affected_count": len(changed),
        "schedule_shifted_count": len(shifted),
        "new_critical_tasks": new_critical_codes,
        "cost_impact": cost_impact,
        "cost_note": cost_note,
        "milestones": ms_out,
        "scenarios": [{**sc, "type_label": SCENARIO_TYPES[sc["type"]]["label"],
                       "task_name": by_id.get(sc["task_id"], {}).get("name"),
                       "wbs_code": by_id.get(sc["task_id"], {}).get("wbs_code")}
                      for sc in clean],
        "assumptions": {
            "critical_path_basis": "同一份 CPM 实现（project_engine.compute_cpm），与甘特图同源",
            "milestone_rule": "按 FS 依赖逻辑将未完成里程碑整体顺移；实际项目可能存在搭接关系，需项目人员确认",
            "cost_basis": cost_note,
            "probabilistic_claim": False,
            "statement": "这是确定性推演，不是延期概率预测；结果不构成对工期的承诺。",
        },
        "requires_approval": True,
        "baseline_untouched": True,
        "data_label": "演示数据·推演结果",
    }

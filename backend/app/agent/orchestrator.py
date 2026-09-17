"""园智AI 多智能体编排（对应需求书第 33-37 节）。

架构：
  主 Agent「园智AI总管」
    ├─ 意图识别 (intent routing)
    ├─ 任务路由 (dispatch to sub-agent)
    ├─ 数据调用 (invoke agent tools)
    └─ 结果汇总 (unified output format)

子 Agent（11 个）：
  招商AI / 企业画像AI / 空间资产AI / AI项目经理 / 合同AI /
  物业AI / 能源AI / 安全AI / 政策AI / 财务AI / 经营分析AI

统一输出格式（第 36 节）：
  【结论】【关键数据】【原因分析】【建议措施】【影响范围】【风险】【责任部门/角色】【决策状态】
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agent import tools as T
from app.core.enums import AIPermissionLevel, DecisionStatus, enum_label
from app.core.security import AuthContext

DATA_LABEL = "演示数据"


# ==========================================================================
# 子 Agent 定义
# ==========================================================================

SUB_AGENTS: dict[str, dict[str, Any]] = {
    "leasing": {
        "key": "leasing", "name": "招商AI", "icon": "target",
        "description": "招商线索分析、商机评分、企业与房源智能匹配、跟进建议、招商周报",
        "tools": ["get_leasing_pipeline", "get_space_status", "get_enterprise_profile",
                  "get_park_profile", "create_ai_recommendation"],
        "keywords": ["招商", "线索", "商机", "意向", "客户", "签约", "转化", "漏斗", "渠道",
                     "选址", "看房", "谈判", "跟进", "拓客", "招租"],
    },
    "enterprise": {
        "key": "enterprise", "name": "企业画像AI", "icon": "building",
        "description": "企业全生命周期画像、风险识别、成长趋势、续租与扩租机会",
        "tools": ["get_enterprise_profile", "get_contract_expiry", "get_financial_summary",
                  "get_policy_matches"],
        "keywords": ["企业", "公司", "画像", "档案", "风险企业", "成长", "续租", "扩租", "退园",
                     "工商", "注册资本", "高企", "专精特新"],
    },
    "space": {
        "key": "space", "name": "空间资产AI", "icon": "layout-grid",
        "description": "空间出租率、空置分析、房源推荐、资产效率诊断",
        "tools": ["get_space_status", "get_contract_expiry", "get_park_profile",
                  "get_enterprise_profile", "create_ai_recommendation"],
        "keywords": ["空间", "楼层", "房间", "楼栋", "出租率", "空置", "面积", "工位",
                     "厂房", "仓库", "商铺", "会议室", "房源", "一房", "一楼"],
    },
    "project": {
        "key": "project", "name": "AI项目经理", "icon": "kanban",
        "description": "瀑布/敏捷/混合项目管理：WBS、甘特、关键路径、风险、成本、变更、Sprint",
        "tools": ["get_project_summary", "get_project_schedule", "get_project_wbs",
                  "get_project_risks", "get_project_costs", "get_project_changes",
                  "get_sprint_status", "generate_project_report", "create_approval_request"],
        "keywords": ["项目", "WBS", "甘特", "关键路径", "里程碑", "延期", "进度", "预算",
                     "超支", "风险", "变更", "Sprint", "敏捷", "瀑布", "混合", "看板",
                     "Backlog", "迭代", "Story", "Epic", "燃尽", "PM", "改造", "施工",
                     "工期", "验收", "复盘", "周报", "月报"],
    },
    "contract": {
        "key": "contract", "name": "合同AI", "icon": "file-text",
        "description": "合同到期预警、续租机会、合同风险条款分析",
        "tools": ["get_contract_expiry", "get_enterprise_profile", "get_financial_summary",
                  "create_approval_request"],
        "keywords": ["合同", "续租", "退租", "租约", "到期", "租赁", "押金", "免租",
                     "递增", "付款周期", "签约"],
    },
    "property": {
        "key": "property", "name": "物业AI", "icon": "wrench",
        "description": "工单分类派单、SLA监控、超时分析、服务质量评价",
        "tools": ["get_work_orders", "get_device_status", "create_ai_recommendation"],
        "keywords": ["工单", "报修", "投诉", "保洁", "巡检", "派单", "SLA", "超时",
                     "物业", "维修", "评价", "服务"],
    },
    "energy": {
        "key": "energy", "name": "能源AI", "icon": "zap",
        "description": "能耗异常识别、能效对标、节能建议、碳排放核算",
        "tools": ["get_energy_summary", "get_device_status", "create_ai_recommendation"],
        "keywords": ["能耗", "用电", "用水", "燃气", "光伏", "充电桩", "碳排放", "低碳",
                     "节能", "电费", "水费", "异常用电", "基线"],
    },
    "safety": {
        "key": "safety", "name": "安全AI", "icon": "shield-alert",
        "description": "安全隐患识别、闭环跟踪、风险分级、应急建议",
        "tools": ["get_safety_risks", "get_device_status", "create_ai_recommendation"],
        "keywords": ["安全", "隐患", "消防", "危险源", "应急", "整改", "复查", "闭环",
                     "安全指数", "事故", "门禁", "访客", "视频"],
    },
    "policy": {
        "key": "policy", "name": "政策AI", "icon": "award",
        "description": "政策知识库匹配、申报条件核验、材料清单、截止日期提醒",
        "tools": ["get_policy_matches", "get_enterprise_profile", "create_ai_recommendation"],
        "keywords": ["政策", "申报", "补贴", "高企", "高新技术", "专精特新", "人才",
                     "研发", "知识产权", "材料", "截止", "资金扶持", "兑现"],
    },
    "finance": {
        "key": "finance", "name": "财务AI", "icon": "coins",
        "description": "收费、欠费催缴、账龄分析、收入趋势、退款减免测算",
        "tools": ["get_financial_summary", "get_contract_expiry", "get_enterprise_profile",
                  "create_ai_recommendation", "create_approval_request"],
        "keywords": ["财务", "收费", "账单", "应收", "实收", "欠费", "缴费", "催缴",
                     "发票", "租金", "物业费", "收入", "账龄", "退款", "减免", "回款",
                     "收缴", "收缴率", "到账"],
    },
    "operations": {
        "key": "operations", "name": "经营分析AI", "icon": "bar-chart-3",
        "description": "跨模块经营分析、KPI 诊断、综合月报、管理建议",
        "tools": ["get_dashboard_summary", "get_park_profile", "get_financial_summary",
                  "get_leasing_pipeline", "get_space_status", "get_project_summary",
                  "get_work_orders", "get_energy_summary", "get_safety_risks",
                  "get_enterprise_profile", "generate_operating_report",
                  "create_ai_recommendation", "create_approval_request"],
        "keywords": ["经营", "整体", "综合", "概览", "总结", "月报", "年报", "KPI", "指标",
                     "分析", "问题", "建议", "诊断", "驾驶舱", "汇报", "最重要"],
    },
}

MAIN_AGENT = {
    "key": "chief", "name": "园智AI总管", "icon": "sparkles",
    "description": "意图识别、任务路由、数据调用、结果汇总",
}


def list_agents() -> list[dict[str, Any]]:
    return [MAIN_AGENT] + [{k: v[k] for k in ("key", "name", "icon", "description")}
                           for v in SUB_AGENTS.values()]


# ==========================================================================
# 意图识别
# ==========================================================================

# 泛化词（弱信号）：跨业务域高频出现，**单独命中不足以判定意图**。
# 例如「风险」「问题」「分析」「整体」在经营、项目、财务、安全语境里都会出现，
# 若参与打分会让「本月园区经营情况如何？有哪些风险需要关注？」被判成项目分析。
# 规则：这类词不计分；若整句只命中这类词，则交给经营分析AI做跨模块兜底扫描。
WEAK_KEYWORDS: frozenset[str] = frozenset({
    "风险", "问题", "情况", "现状", "分析", "建议", "异常", "预警", "趋势",
    "对比", "排名", "指标", "数据", "诊断", "总结", "整体", "综合", "概览",
    "汇报", "如何", "怎么", "是否",
})

# 通用名词（中信号）：跨域复用但仍有业务指向，按折扣权重计分。
# 例如「企业」在财务（哪家企业欠费）与招商（客户）语境里都出现，
# 一旦与「欠费」这类强特征词同时命中，应让强特征词所属的 Agent 胜出。
MILD_KEYWORDS: frozenset[str] = frozenset({"企业", "公司", "面积", "服务", "评价"})
MILD_WEIGHT = 0.6

# 同分时的稳定排序（越靠前越"专"），避免依赖 dict 插入顺序引发隐性误判
TIE_ORDER: tuple[str, ...] = (
    "leasing", "project", "energy", "safety", "finance", "contract",
    "space", "policy", "property", "enterprise", "operations",
)


def score_intents(question: str) -> dict[str, float]:
    """对问题打分，返回 {agent_key: score}（仅含得分 > 0 的 Agent）。

    只有**强特征词**（业务域身份词/动作词）计满分；通用名词按 MILD_WEIGHT 折扣；
    泛化词不计分。得分口径：1.0 + 关键词长度 × 0.12（长词更具体，权重更高）。
    """
    q = question.lower()
    scores: dict[str, float] = {}
    for key, agent in SUB_AGENTS.items():
        score = 0.0
        for kw in agent["keywords"]:
            k = kw.lower()
            if k in WEAK_KEYWORDS or k not in q:
                continue
            w = 1.0 + len(kw) * 0.12
            if k in MILD_KEYWORDS:
                w *= MILD_WEIGHT
            score += w
        if score:
            scores[key] = round(score, 4)
    return scores


def classify_intent(question: str) -> list[str]:
    """返回命中的子 Agent key 列表（按命中权重降序，可多命中）。

    只命中泛化词（或完全无命中）时返回经营分析AI——它是跨模块的兜底分析能力，
    这类问句本质是"综合扫描我是谁"的问题，而非某个业务域的专问。
    """
    scores = score_intents(question)
    if not scores:
        return ["operations"]
    order = {k: i for i, k in enumerate(TIE_ORDER)}
    ordered = sorted(scores.items(), key=lambda x: (-x[1], order.get(x[0], 99)))
    # 多意图：取前 3 个得分达到最高分 50% 以上的意图
    top = ordered[0][1]
    return [k for k, v in ordered if v >= top * 0.5][:3]


# ==========================================================================
# 统一输出结构
# ==========================================================================


def _block(conclusion: str, key_data: list[dict], reasons: list[str], suggestions: list[str],
           impact: str, risks: list[str], owners: list[str], decision: str,
           data_sufficient: bool = True, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "结论": conclusion,
        "关键数据": key_data,
        "原因分析": reasons,
        "建议措施": suggestions,
        "影响范围": impact,
        "风险": risks,
        "责任部门/角色": owners,
        "决策状态": decision,
        "data_sufficient": data_sufficient,
        "missing_data": missing or [],
    }


# 问句里的动词/礼貌用语前缀：正则从句子首字开始贪心匹配，会把
# "帮我查一下星海科技" 整体当成企业名，命中不了任何库内记录。
_NAME_STOP_PREFIXES: tuple[str, ...] = tuple(sorted({
    "帮我", "麻烦", "请", "查一下", "查询", "看一下", "看看", "了解", "分析", "关于",
    "介绍一下", "介绍", "这家", "那家", "这间", "那间", "查", "的", "下",
}, key=len, reverse=True))


def _extract_enterprise_name(q: str) -> str | None:
    """从问句里提取企业名：先按公司后缀抓，再剥掉动词/礼貌用语前缀。"""
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:公司|集团|科技|股份|有限))", q)
    if not m:
        return None
    name = m.group(1)
    changed = True
    while changed:
        changed = False
        for p in _NAME_STOP_PREFIXES:
            if name.startswith(p) and len(name) - len(p) >= 2:
                name = name[len(p):]
                changed = True
                break
    return name or None


def _kv(label: str, value: Any, unit: str = "", basis: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "basis": basis}


def _subsidy_text(v: Any) -> str:
    """补贴金额统一格式化为「万元 / 元」；0 或缺失表示无固定金额（按比例 / 以指南为准），不输出。

    直接拼 f"{v}" 会渲染成「补贴：300000.0」这种未格式化文本。
    """
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{n / 10000:,.0f} 万元" if n >= 10000 else f"{n:,.0f} 元"


# ==========================================================================
# 各子 Agent 的推理逻辑（基于工具真实数据）
# ==========================================================================


def _run_leasing(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    pipeline = T.call_tool("get_leasing_pipeline", db, auth, park_id=park_id)
    if not pipeline.get("data"):
        return {"response": _block(
            "当前数据不足以支持招商分析。", [], [], [], "招商管理",
            ["数据缺失：招商线索表为空或无权限"], ["招商主管"],
            DecisionStatus.INFO, False, pipeline.get("missing_data", ["招商线索数据"])),
            "evidence": pipeline.get("evidence")}

    d = pipeline["data"]
    key_data = [
        _kv("累计线索", d["total_leads"], "条"),
        _kv("在跟进线索", d["active_leads"], "条"),
        _kv("已签约", d["signed_leads"], "条"),
        _kv("招商转化率", d["conversion_rate"], "%", "签约线索 ÷ 已进入有效商机及以后的线索"),
        _kv("意向面积合计", d["total_demand_area"], "㎡"),
        _kv("意向投资规模", d["total_investment"], "万元"),
    ]

    reasons, suggestions, risks = [], [], []
    lowest = d.get("lowest_conversion_park")
    if lowest:
        reasons.append(
            f"{lowest['park_name']} 招商转化率最低（{lowest['conversion_rate']}%），"
            f"累计线索 {lowest['total']} 条，其中有效商机及以后 {lowest['matured']} 条，签约 {lowest['signed']} 条，流失 {lowest['lost']} 条。")
    if d["funnel"]:
        weakest = None
        for f in d["funnel"][1:]:
            if f["conversion_from_prev"] is not None:
                if weakest is None or f["conversion_from_prev"] < weakest["conversion_from_prev"]:
                    weakest = f
        if weakest:
            idx = [x["stage"] for x in d["funnel"]].index(weakest["stage"])
            prev_name = d["funnel"][idx - 1]["stage_name"]
            reasons.append(
                f"漏斗最大流失发生在「{prev_name} → {weakest['stage_name']}」，"
                f"环节转化率仅 {weakest['conversion_from_prev']}%，是当前招商效率的瓶颈环节。")
            suggestions.append(f"针对「{prev_name} → {weakest['stage_name']}」环节制定专项改进措施，明确该环节的标准动作与时限要求。")

    if d["stagnant_count"]:
        top = d["stagnant_leads"][0]
        reasons.append(
            f"存在 {d['stagnant_count']} 条线索跟进停滞，最久已 {top['days_since_followup']} 天未跟进"
            f"（{top['company_name']}，当前阶段：{top['stage_name']}）。")
        suggestions.append(f"优先激活 {d['stagnant_count']} 条停滞线索，按成交可能性排序后 3 个工作日内完成一轮触达。")
        risks.append(f"{d['stagnant_count']} 条停滞线索存在流失风险，涉及意向面积约 "
                     f"{sum(s['demand_area'] or 0 for s in d['stagnant_leads']):,.0f} ㎡。")

    top_ops = d.get("top_opportunities", [])
    if top_ops:
        o = top_ops[0]
        suggestions.append(
            f"高优先级商机：「{o['company_name']}」（成交可能性 {o['win_probability']}%，意向面积 {o['demand_area']} ㎡，"
            f"投资规模 {o['investment_amount']} 万元），建议安排园区负责人参与商务谈判。")

    space = T.call_tool("get_space_status", db, auth, park_id=park_id)
    if space.get("data") and space["data"]["vacant_count"]:
        long_v = space["data"]["long_vacant"]
        suggestions.append(
            f"当前可租空间 {space['data']['vacant_count']} 处、合计 {space['data']['vacant_area']:,.0f} ㎡"
            + (f"，其中 {len(long_v)} 处空置超过 90 天，建议纳入重点推介清单并配套价格策略。" if long_v else "，建议同步至招商推介清单。"))

    conclusion = (
        f"当前招商漏斗共 {d['total_leads']} 条线索，在跟进 {d['active_leads']} 条，"
        f"整体转化率 {d['conversion_rate']}%"
        + (f"，{lowest['park_name']} 转化率最低（{lowest['conversion_rate']}%）" if lowest else "")
        + f"；{d['stagnant_count']} 条线索跟进停滞需优先激活。")

    return {
        "response": _block(conclusion, key_data, reasons or ["线索推进节奏正常，未发现明显瓶颈环节。"],
                           suggestions or ["保持现有跟进节奏，持续监控漏斗各环节转化率。"],
                           f"涉及 {d['total_leads']} 条招商线索、意向面积 {d['total_demand_area']:,.0f} ㎡",
                           risks, ["招商主管", "招商专员"], DecisionStatus.AI_SUGGESTION),
        "evidence": pipeline.get("evidence"),
    }


def _run_project(db: Session, auth: AuthContext, q: str, park_id: int | None,
                 project_id: int | None = None) -> dict[str, Any]:
    # 尝试从问题中提取项目名（如 "A栋改造项目"）
    name_hint = None
    m = re.search(r"([A-Za-z0-9０-９\u4e00-\u9fa5]{1,20}?(?:项目|工程|改造|建设|平台|系统|中心))", q)
    if m:
        name_hint = m.group(1)

    projects = T._resolve_projects(db, auth, project_id, name_hint) if name_hint else []
    if not projects:
        summary = T.call_tool("get_project_summary", db, auth, park_id=park_id)
        if not summary.get("data"):
            return {"response": _block(
                "当前数据不足以支持项目分析。", [], [], [], "项目管理中心",
                ["数据缺失：项目数据为空或无项目权限"], ["项目经理"],
                DecisionStatus.INFO, False, summary.get("missing_data", ["项目数据"])),
                "evidence": summary.get("evidence")}
        s = summary["data"]
        reasons, suggestions, risks = [], [], []

        if s["delayed"]:
            dp = s["delayed_projects"]
            reasons.append(
                f"{s['delayed']} 个项目已超计划结束日期未完成，延期最久为「{dp[0]['project_name']}」"
                f"（延期 {dp[0]['delay_days']} 天，当前进度 {dp[0]['progress']}%，风险等级 {dp[0]['risk_level']}）。")
            suggestions.append(f"对 {s['delayed']} 个延期项目逐项启动进度复核，明确剩余工作量与补救措施。")
            risks.append(f"延期项目合计预算 {sum(p['budget'] for p in dp):,.0f} 元，存在成本超支与交付延误风险。")
        if s["high_risk"]:
            hp = s["high_risk_projects"]
            reasons.append(f"{s['high_risk']} 个项目被标记为高/重大风险等级："
                           + "、".join(f"{p['project_name']}（{p['risk_level']}）" for p in hp[:5]))
            risks.append("高风险项目需重点跟踪，建议纳入项目管理委员会例会议题。")
        if s["total_budget"] and s["budget_execution_rate"] > 85:
            reasons.append(f"项目预算执行率已达 {s['budget_execution_rate']}%，接近预算上限。")
            suggestions.append("对预算执行率超过 85% 的项目开展成本复核，防止年末集中超支。")
        elif not s["total_budget"]:
            reasons.append("项目尚未登记预算数据，预算执行率不可计算。")
            suggestions.append("补录各项目批准预算，以启用预算执行率与超支预警能力。")

        by_method = s["by_management_method"]
        suggestions.append(
            f"项目组合管理方式分布：瀑布 {by_method['WATERFALL']} 个、敏捷 {by_method['AGILE']} 个、"
            f"混合 {by_method['HYBRID']} 个；平均进度 {s['avg_progress']}%，里程碑完成率 {s['milestone_completion_rate']}%。")

        conclusion = (
            f"当前共 {s['total']} 个项目：在建 {s['in_progress']} 个、延期 {s['delayed']} 个、"
            f"高风险 {s['high_risk']} 个、已完成 {s['completed']} 个；"
            f"总投资 {s['total_investment']:,.0f} 元，预算执行率 {s['budget_execution_rate']}%，"
            f"里程碑完成率 {s['milestone_completion_rate']}%。")

        return {
            "response": _block(conclusion, [
                _kv("项目总数", s["total"], "个"),
                _kv("在建项目", s["in_progress"], "个"),
                _kv("延期项目", s["delayed"], "个"),
                _kv("高风险项目", s["high_risk"], "个"),
                _kv("项目总投资", s["total_investment"], "元"),
                _kv("预算执行率", s["budget_execution_rate"], "%", "实际成本 ÷ 批准预算"),
                _kv("里程碑完成率", s["milestone_completion_rate"], "%"),
                _kv("平均项目进度", s["avg_progress"], "%"),
            ], reasons or ["项目组合整体运行平稳，未发现延期或超支信号。"],
                suggestions, f"覆盖 {s['total']} 个项目、总投资 {s['total_investment']:,.0f} 元",
                risks, ["项目管理办公室（PMO）", "各项目经理"], DecisionStatus.AI_SUGGESTION),
            "evidence": summary.get("evidence"),
        }

    # 单车项目深度诊断
    p = projects[0]
    diag = T.project_engine.diagnose_project(db, p)
    sched = diag["schedule"]
    cost = diag["cost"]
    rk = diag["risk"]

    key_data = [
        _kv("项目编号", p.project_code),
        _kv("管理方式", enum_label(p.management_method, "ManagementMethod")),
        _kv("计划工期", f"{p.start_date} ~ {p.planned_end_date}" if p.start_date else "未设定"),
        _kv("计划进度", sched.get("planned_progress"), "%"),
        _kv("实际进度", sched.get("actual_progress"), "%"),
        _kv("进度偏差", sched.get("progress_variance"), "%"),
        _kv("延期天数", sched.get("delay_days"), "天"),
        _kv("预算", cost.get("budget", p.budget), "元"),
        _kv("实际成本", cost.get("actual_cost", p.actual_cost), "元"),
        _kv("成本绩效指数 CPI", cost.get("cpi"), "", "挣值 EV ÷ 实际成本 AC，<1 表示成本超支"),
        _kv("进度绩效指数 SPI", cost.get("spi"), "", "挣值 EV ÷ 计划价值 PV，<1 表示进度落后"),
        _kv("风险数量", len(rk.get("risks", [])), "条"),
    ]

    if not sched.get("data_sufficient", True):
        return {
            "response": _block(
                f"项目「{p.project_name}」缺少实际进度数据，无法判断是否延期。",
                key_data, ["缺少实际进度与成本发生记录"], 
                ["补录 WBS 任务的实际开始/结束日期与完成率，以及成本发生记录，以启用进度与成本偏差分析。"],
                f"项目「{p.project_name}」", ["数据不足导致延期风险无法评估"], 
                ["项目经理", "项目助理"], DecisionStatus.INFO, False,
                sched.get("missing_data", [])),
            "evidence": T.call_tool("get_project_schedule", db, auth, project_id=p.id).get("evidence"),
        }

    reasons, suggestions, risks = [], [], []
    delayed_tasks = sched.get("delayed_tasks", [])
    if delayed_tasks:
        reasons.append(
            f"共 {len(delayed_tasks)} 项 WBS 任务超期未完成。最严重：{delayed_tasks[0]['wbs_code']} "
            f"{delayed_tasks[0]['item_name']}（超期 {delayed_tasks[0]['delay_days']} 天，完成率 {delayed_tasks[0]['progress']:.0f}%，"
            f"责任人：{delayed_tasks[0]['owner_name'] or '未指定'}）。")
    crit = sched.get("critical_delayed_tasks", [])
    if crit:
        reasons.append(
            f"其中 {len(crit)} 项位于关键路径上，直接影响总工期，累计关键延期 {sched.get('critical_impact_days')} 天："
            + "、".join(t["wbs_code"] for t in crit[:5]) + "。")
    for c in sched.get("causes", []):
        reasons.append(f"【{c['category']}】{c['detail']}")

    if crit:
        suggestions.append(f"优先压缩关键路径任务（{', '.join(t['wbs_code'] for t in crit[:3])}）：增加资源投入或采用并行作业，可最快缩短总工期。")
    if delayed_tasks:
        suggestions.append(f"对 {len(delayed_tasks)} 项超期任务重置剩余工期并纳入周度跟踪；若无法追回，应提交进度变更申请建立新基线。")
    if cost.get("overspend_risk"):
        suggestions.append("开展成本专项复核，识别超前采购与返工成本；必要时启动预算变更审批。")

    if sched.get("is_delayed"):
        risks.append(f"项目已延期 {sched.get('delay_days', 0)} 天，进度偏差 {sched.get('progress_variance')}%。")
    for ar in rk.get("ai_identified_risks", []):
        risks.append(f"[{ar['level']}] {ar['title']}：{ar['detail']}")

    plan_end = p.planned_end_date
    if plan_end and sched.get("critical_impact_days"):
        est = plan_end + dt.timedelta(days=int(sched["critical_impact_days"] or 0))
        suggestions.append(f"按当前关键路径延期 {sched['critical_impact_days']} 天推算，预计完成时间约为 {est.isoformat()}（原计划 {plan_end.isoformat()}）。")

    needs_approval = bool(crit) and (sched.get("critical_impact_days", 0) or 0) > 5
    decision = DecisionStatus.NEED_APPROVAL if needs_approval else DecisionStatus.AI_SUGGESTION
    if needs_approval:
        suggestions.append("关键路径延期超过 5 天，建议提交「项目进度变更审批」以更新项目基线。")

    conclusion = (
        f"项目「{p.project_name}」当前进度 {sched.get('actual_progress')}%（计划 {sched.get('planned_progress')}%），"
        f"偏差 {sched.get('progress_variance')}%"
        + (f"，已延期 {sched.get('delay_days')} 天" if sched.get("delay_days") else "")
        + f"；健康度评级 {diag['health']}。"
        + (f"延期主要原因：{sched['causes'][0]['detail'][:80]}" if sched.get("is_delayed") and sched.get("causes") else ""))

    return {
        "response": _block(conclusion, key_data, reasons or ["项目各项指标均在正常范围。"],
                           suggestions, f"项目「{p.project_name}」全生命周期",
                           risks or ["未识别到显著风险"], 
                           ["项目经理：" + (p.project_manager_name or "未指定"), "PMO"],
                           decision),
        "evidence": {
            "data_source": "平台业务数据库",
            "tables": ["projects", "wbs_items", "task_dependencies", "milestones",
                       "project_costs", "project_risks", "project_changes"],
            "record_count": len(T.call_tool("get_project_wbs", db, auth, project_id=p.id)
                                .get("data", [{}])[0].get("wbs", [])) if True else 0,
            "filters": {"project_id": p.id},
            "formula": "CPM 关键路径法 + 挣值分析（CPI/SPI）+ 风险矩阵",
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data_label": DATA_LABEL,
        },
    }


def _run_energy(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    e = T.call_tool("get_energy_summary", db, auth, park_id=park_id)
    if not e.get("data"):
        return {"response": _block(
            "能耗设备尚未接入，无法进行能耗分析。", [], [], 
            ["接入 IoT 能耗采集设备并配置数据上报接口。"], "能源与低碳中心",
            ["能耗数据缺失，无法识别异常用能"], ["能源管理岗", "设备运维团队"],
            DecisionStatus.INFO, False, e.get("missing_data", ["能耗数据"])),
            "evidence": e.get("evidence")}

    d = e["data"]
    key_data = [_kv(f"{x['label']}消耗", x["consumption"], x["unit"],
                    f"较上一周期 {x['mom']}%" if x["mom"] is not None else "无上一周期数据")
                for x in d["by_type"]]
    key_data.append(_kv("碳排放估算", d["total_carbon_ton"], "吨CO₂"))
    if d["unit_area_consumption"]:
        key_data.append(_kv("单位面积电耗", d["unit_area_consumption"], "kWh/㎡"))
    if d["night_consumption_ratio"] is not None:
        key_data.append(_kv("夜间用电占比", d["night_consumption_ratio"], "%",
                            "夜间(0-5时)用电量 ÷ (夜间+日间)用电量"))

    reasons, suggestions, risks = [], [], []
    for x in d["by_type"]:
        if x["mom"] is not None and x["mom"] > 10:
            reasons.append(f"{x['label']}消耗较上一同期上升 {x['mom']}%（{x['prev_consumption']} → {x['consumption']} {x['unit']}）。")

    if d["anomaly_count"]:
        a = d["anomalies"][0]
        who = a.get("enterprise_name") or a.get("building_name") or "未知位置"
        reasons.append(
            f"AI 识别出 {d['anomaly_count']} 条能耗异常记录。最显著：{who} 于 {a['record_date']}"
            + (f" {a['record_hour']}:00" if a.get("record_hour") is not None else "")
            + f" 的{a['label']}用量 {a['consumption']}，偏离基线 {a['baseline']} 达 {a['anomaly_ratio']}%。"
            + (f"（{a['note']}）" if a.get("note") else ""))
        suggestions.append(f"对 {d['anomaly_count']} 条异常记录逐条现场核查，重点排查设备空转、管线泄漏或计量故障。")
        risks.append(f"异常用能涉及 {d['anomaly_count']} 处，按当前用量估算存在持续成本浪费风险。")

    if d["night_consumption_ratio"] is not None and d["night_consumption_ratio"] > 25:
        reasons.append(f"夜间用电占比达 {d['night_consumption_ratio']}%，高于常规园区水平（通常 <20%），可能存在非工作时段设备未关停。")
        suggestions.append("排查夜间运行设备清单，对非必要设备设置定时断电或智能控制策略。")

    if d["by_enterprise"]:
        top = d["by_enterprise"][0]
        if top.get("unit_consumption"):
            suggestions.append(
                f"单位面积电耗最高的企业为「{top['enterprise_name']}」（{top['unit_consumption']} kWh/㎡"
                + (f"，行业：{top['industry']}" if top.get("industry") else "") + "），建议开展能效对标诊断。")

    if d["by_building"]:
        tb = [b for b in d["by_building"] if b.get("unit_consumption")]
        if tb:
            suggestions.append(f"楼栋单位面积电耗最高：「{tb[0]['building_name']}」{tb[0]['unit_consumption']} kWh/㎡，建议纳入节能改造候选范围。")

    conclusion = (
        f"近 {d['window_days']} 天园区能耗情况："
        + "；".join(f"{x['label']} {x['consumption']:,.0f} {x['unit']}" for x in d["by_type"][:4])
        + f"；碳排放约 {d['total_carbon_ton']} 吨CO₂"
        + (f"；发现 {d['anomaly_count']} 条能耗异常" if d["anomaly_count"] else "；未发现能耗异常"))

    return {
        "response": _block(conclusion, key_data,
                           reasons or ["各类能耗环比波动在正常范围内，未发现异常用能。"],
                           suggestions or ["维持现有用能管理，持续监控异常。"],
                           f"近 {d['window_days']} 天全园区用能", risks, ["能源管理岗", "设备运维团队"],
                           DecisionStatus.AI_SUGGESTION),
        "evidence": e.get("evidence"),
    }


def _run_safety(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    s = T.call_tool("get_safety_risks", db, auth, park_id=park_id)
    if not s.get("data"):
        return {"response": _block("当前数据不足以支持安全分析。", [], [], [], "安全风险管理",
                                   ["数据缺失：安全事件与隐患台账为空"], ["安全管理岗"],
                                   DecisionStatus.INFO, False, s.get("missing_data", ["安全数据"])),
                "evidence": s.get("evidence")}
    d = s["data"]
    key_data = [
        _kv("安全指数", d["safety_score"], "分", "100 分制扣减模型"),
        _kv("安全状态", d["safety_status"]),
        _kv("事件总数", d["total_incidents"], "起"),
        _kv("未闭环", d["open_incidents"], "起"),
        _kv("重大/紧急未闭环", d["critical_open"], "起"),
        _kv("整改逾期", d["overdue_rectify"], "起"),
        _kv("闭环率", d["closure_rate"], "%"),
        _kv("未闭环隐患", d["hazard_open"], "项"),
    ]
    reasons, suggestions, risks = [], [], []
    if d["critical_incidents"]:
        ci = d["critical_incidents"][0]
        reasons.append(f"存在 {len(d['critical_incidents'])} 起重大/紧急安全事件，首要为「{ci['title']}」"
                       f"（{ci['incident_type']}，位置：{ci['location']}，状态：{ci['status']}，责任部门：{ci['responsible_dept']}）。")
        suggestions.append("重大安全事件立即启动应急处置，责任部门 24 小时内反馈整改方案。")
        risks.append(f"{d['critical_open']} 起重大事件尚未闭环，直接拉低安全指数。")
    if d["overdue_rectify"]:
        reasons.append(f"{d['overdue_rectify']} 起事件整改已超期，最长逾期 "
                       f"{max((x['overdue_days'] for x in d['overdue_list']), default=0)} 天。")
        suggestions.append("对逾期整改项下发督办单，纳入部门安全考核。")
    if d["hazard_open"]:
        reasons.append(f"隐患排查台账中 {d['hazard_open']} 项未闭环。")
        suggestions.append(f"组织专项排查复查，确保 {d['hazard_open']} 项隐患完成「发现→整改→复查→关闭」闭环。")
    by_type = d["by_type"]
    if by_type:
        top = max(by_type.items(), key=lambda x: x[1]["total"])
        suggestions.append(f"事件类型以「{top[0]}」为主（共 {top[1]['total']} 起，未闭环 {top[1]['open']} 起），建议开展针对性专项治理。")

    conclusion = (f"当前安全指数 {d['safety_score']} 分（{d['safety_status']}），"
                  f"事件总数 {d['total_incidents']} 起、未闭环 {d['open_incidents']} 起、"
                  f"重大/紧急 {d['critical_open']} 起、整改逾期 {d['overdue_rectify']} 起。")
    return {
        "response": _block(conclusion, key_data,
                           reasons or ["未发现重大安全隐患，未闭环事件均在整改期限内。"],
                           suggestions or ["保持现有安全巡检频次与闭环流程。"],
                           "全园区安全生产、消防、隐患、危险源",
                           risks, ["安全管理岗", "物业运营团队"], DecisionStatus.AI_SUGGESTION),
        "evidence": s.get("evidence"),
    }


def _run_finance(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    f = T.call_tool("get_financial_summary", db, auth, park_id=park_id)
    if not f.get("data"):
        return {"response": _block("当前数据不足以支持财务分析。", [], [], [], "财务收费中心",
                                   ["数据缺失：账单数据为空"], ["财务人员"],
                                   DecisionStatus.INFO, False, f.get("missing_data", ["账单数据"])),
                "evidence": f.get("evidence")}
    d = f["data"]
    key_data = [
        _kv("本月应收", d["month_receivable"], "元"),
        _kv("本月实收", d["month_received"], "元"),
        _kv("累计实收（年初至今）", d["ytd_received"], "元"),
        _kv("收缴率", d["collection_rate"], "%", "已到期账单实收 ÷ 已到期账单应收"),
        _kv("欠费总额", d["total_arrears"], "元"),
        _kv("逾期欠费", d["overdue_arrears"], "元"),
        _kv("逾期账单数", d["overdue_count"], "张"),
    ]
    reasons, suggestions, risks = [], [], []
    if d["total_arrears"]:
        top = d["top_arrears"][0]
        reasons.append(f"当前欠费总额 {d['total_arrears']:,.0f} 元，其中逾期 {d['overdue_arrears']:,.0f} 元。"
                       f"欠费最多的企业为「{top['enterprise_name']}」，欠费 {top['arrears']:,.0f} 元"
                       f"（{top['bill_count']} 张账单，最长逾期 {top['max_overdue_days']} 天）。")
        suggestions.append(f"对欠费 TOP5 企业开展分级催缴：「{top['enterprise_name']}」欠费金额最大，建议园区负责人直接对接。")
        if d["overdue_arrears"] > 0:
            risks.append(f"逾期欠费 {d['overdue_arrears']:,.0f} 元，存在坏账风险。")
    age = [a for a in d["arrears_age"] if a["amount"] > 0]
    if age:
        worst = max(age, key=lambda x: x["amount"])
        reasons.append(f"账龄分布中「{worst['name']}」占比最高（{worst['amount']:,.0f} 元，{worst['count']} 张账单），"
                       "账龄越长回收难度越大。")
        # 账龄桶键与 core/enums.AGE_BUCKETS 对齐（D91_180 / OVER_365 = 超过 90 天）
        long_age = [a for a in d["arrears_age"]
                    if a["bucket"] in ("D91_180", "D181_365", "OVER_365") and a["amount"] > 0]
        if long_age:
            risks.append(f"{sum(a['amount'] for a in long_age):,.0f} 元欠费账龄超过 90 天，建议启动法务催收评估。")
            suggestions.append("对账龄超过 90 天的欠费启动法务介入评估，并同步核查押金抵扣可行性。")
    if d["collection_rate"] < 95:
        suggestions.append(f"收缴率 {d['collection_rate']}% 低于目标值 95%，建议优化账单推送与在线缴费入口，缩短缴费路径。")

    conclusion = (f"本月应收 {d['month_receivable']:,.0f} 元、实收 {d['month_received']:,.0f} 元，"
                  f"收缴率 {d['collection_rate']}%；累计欠费 {d['total_arrears']:,.0f} 元"
                  + (f"，其中逾期 {d['overdue_arrears']:,.0f} 元" if d["overdue_arrears"] else ""))
    return {
        "response": _block(conclusion, key_data,
                           reasons or ["当前无欠费，收费情况正常。"],
                           suggestions or ["保持现有收费与催缴节奏。"],
                           f"覆盖 {d['total_bills']} 张账单、{len(d['arrears_by_enterprise'])} 家欠费企业",
                           risks, ["财务人员", "园区负责人", "招商主管"], DecisionStatus.AI_SUGGESTION),
        "evidence": f.get("evidence"),
    }


def _run_space(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    s = T.call_tool("get_space_status", db, auth, park_id=park_id)
    if not s.get("data"):
        return {"response": _block("当前数据不足以支持空间分析。", [], [], [], "空间与资产管理",
                                   ["数据缺失：空间数据为空"], ["运营人员"],
                                   DecisionStatus.INFO, False, s.get("missing_data", ["空间数据"])),
                "evidence": s.get("evidence")}
    d = s["data"]
    key_data = [
        _kv("可租空间总数", d["total_space"], "个"),
        _kv("可租面积", d["total_area"], "㎡"),
        _kv("已出租面积", d["rented_area"], "㎡"),
        _kv("出租率", d["occupancy_rate"], "%", "已出租面积 ÷ 可租面积"),
        _kv("空置空间", d["vacant_count"], "个"),
        _kv("空置面积", d["vacant_area"], "㎡"),
    ]
    reasons, suggestions, risks = [], [], []
    rank = d["building_rank"]
    if rank:
        worst = rank[0]
        best = rank[-1]
        reasons.append(f"出租率最低楼栋为「{worst['building_name']}」（{worst['occupancy_rate']}%，"
                       f"空置 {worst['vacant_area']:,.0f} ㎡）；最高为「{best['building_name']}」（{best['occupancy_rate']}%）。")
        suggestions.append(f"针对「{worst['building_name']}」制定去化方案，可考虑调整租金定价策略或引进差异化业态。")

    long_v = d["long_vacant"]
    if long_v:
        reasons.append(f"存在 {len(long_v)} 处空间空置超过 90 天，最久 {long_v[0]['vacant_days']} 天"
                       f"（{long_v[0]['space_name']}，{long_v[0]['area']:,.0f} ㎡）。")
        suggestions.append("对超 90 天空置空间启动专项去化，考虑短租、联合办公或临时活动场地等灵活方案。")
        lost = sum((v["area"] or 0) * (v["rent_price"] or 0) for v in long_v)
        risks.append(f"长期空置空间按当前租金水平估算，月租金损失约 {lost:,.0f} 元。")

    if d["by_type"]:
        worst_type = min(d["by_type"].items(),
                         key=lambda x: (x[1]["rented_area"] / x[1]["area"]) if x[1]["area"] else 1)
        if worst_type[1]["area"]:
            r = worst_type[1]["rented_area"] / worst_type[1]["area"] * 100
            suggestions.append(f"空间类型中「{worst_type[0]}」出租率最低（{r:.1f}%），建议核查定价与招商推介力度。")

    conclusion = (f"当前可租空间 {d['total_space']} 个、合计 {d['total_area']:,.0f} ㎡，"
                  f"出租率 {d['occupancy_rate']}%，空置 {d['vacant_count']} 处、{d['vacant_area']:,.0f} ㎡"
                  + (f"，其中 {len(long_v)} 处空置超 90 天" if long_v else ""))
    return {
        "response": _block(conclusion, key_data,
                           reasons or ["空间出租情况良好，各楼栋出租率均衡。"],
                           suggestions or ["维持现有招商与空间运营策略。"],
                           f"覆盖 {d['total_space']} 个空间单元、{len(rank)} 栋楼宇",
                           risks, ["运营人员", "招商主管"], DecisionStatus.AI_SUGGESTION),
        "evidence": s.get("evidence"),
    }


def _run_policy(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    name_hint = _extract_enterprise_name(q)
    p = T.call_tool("get_policy_matches", db, auth, enterprise_name=name_hint, park_id=park_id)
    if not p.get("data"):
        # 原因直接取工具的真实缺失原因：写死"政策库或企业档案为空"会在
        # "用户点名的企业不存在"时误导成"园区没有政策数据"。
        missing = list(p.get("missing_data") or ["政策匹配数据"])
        cand = p.get("candidates") or []
        sugg = ["补充上述数据后重新发起政策匹配，以获得可追溯的结论。"]
        if cand:
            sugg.insert(0, "若为口语简称，可改用库内企业全称重试：" + "、".join(cand) + "。")
        return {"response": _block("当前数据不足以进行政策匹配。", [],
                                   [f"数据缺失：{m}" for m in missing], sugg,
                                   "企业服务中心", ["数据不足，匹配结论不可用"],
                                   ["企业服务专员"], DecisionStatus.INFO, False, missing),
                "evidence": p.get("evidence")}
    results = p["data"]
    # 只有"点名到唯一一家企业"才做企业级深度诊断；
    # 未点名或命中多家时，若无脑取 results[0]，就会答成"某一家企业"，
    # 与用户问的"园区有哪些政策可以申报"完全不是同一个问题。
    if name_hint and len(results) == 1:
        return _policy_enterprise(p, results[0])
    return _policy_portfolio(p, results, name_hint)


def _policy_enterprise(p: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """单企业政策匹配深度诊断。"""
    key_data = [
        _kv("匹配企业", r["enterprise_name"]),
        _kv("所属行业", r["industry"] or "未填写"),
        _kv("员工人数", r["employee_count"] or "未填写", "人"),
        _kv("年度营收", r["annual_revenue"] or "未填写", "万元"),
        _kv("知识产权", r["ip_count"], "项"),
        _kv("高企/专精特新", f"{'高企' if r['is_high_tech'] else '非高企'} / {'专精特新' if r['is_specialized'] else '非专精特新'}"),
        _kv("匹配政策数", len(r["matches"]), "条"),
    ]
    reasons, suggestions, risks = [], [], []
    possible = [x for x in r["matches"] if x["match_level"] == "可能符合"]
    verify = [x for x in r["matches"] if x["match_level"] == "建议核验"]
    insufficient = [x for x in r["matches"] if x["match_level"] == "数据不足"]

    for x in possible[:4]:
        sub = _subsidy_text(x.get("subsidy_amount"))
        reasons.append(f"政策「{x['policy_name']}」（{x['policy_level']}）：匹配度 {x['match_score']}%，"
                       f"{x['match_reason']}" + (f"，最高补贴 {sub}" if sub else ""))
    for x in verify[:3]:
        reasons.append(f"政策「{x['policy_name']}」匹配度 {x['match_score']}%，需核验：{x['match_reason']}")

    upcoming = [x for x in r["matches"] if x.get("days_to_deadline") is not None and 0 <= x["days_to_deadline"] <= 60]
    if upcoming:
        upcoming.sort(key=lambda x: x["days_to_deadline"])
        suggestions.append(f"「{upcoming[0]['policy_name']}」申报截止仅剩 {upcoming[0]['days_to_deadline']} 天"
                           f"（{upcoming[0]['deadline']}），建议立即启动材料准备。")
    if possible:
        suggestions.append(f"优先推进 {len(possible)} 条「可能符合」政策申报，按截止日期倒排材料准备计划。")
    if r["missing_data"]:
        risks.append("企业数据不足，匹配结论仅为初步参考：" + "、".join(r["missing_data"]))
        suggestions.append("补录企业缺失字段（" + "、".join(r["missing_data"]) + "）后重新执行匹配，以提升结论置信度。")
    if r.get("confidence_note"):
        risks.append(r["confidence_note"])

    conclusion = (f"企业「{r['enterprise_name']}」共匹配到 {len(r['matches'])} 条政策："
                  f"可能符合 {len(possible)} 条、建议核验 {len(verify)} 条"
                  + (f"、数据不足 {len(insufficient)} 条" if insufficient else "")
                  + "。匹配结论仅供参考，不构成申报资格确认。")

    return {
        "response": _block(conclusion, key_data,
                           reasons or ["未匹配到适用政策，或政策库中缺少对应条件配置。"],
                           suggestions or ["建议联系园区企业服务专员人工核实政策适用性。"],
                           f"企业「{r['enterprise_name']}」政策服务",
                           risks, ["企业服务专员", "政策申报对接人"],
                           DecisionStatus.NEED_CONFIRM if r["missing_data"] else DecisionStatus.AI_SUGGESTION,
                           not bool(r["missing_data"]), r["missing_data"]),
        "evidence": p.get("evidence"),
    }


def _policy_portfolio(p: dict[str, Any], results: list[dict[str, Any]],
                      name_hint: str | None) -> dict[str, Any]:
    """园区级政策匹配总览：按政策维度聚合「多少家企业可能符合」。"""
    all_matches: list[dict[str, Any]] = []
    scanned = len(results)
    data_gap_ents = 0
    for row in results:
        if row.get("missing_data"):
            data_gap_ents += 1
        for x in row["matches"]:
            all_matches.append({**x, "enterprise_name": row["enterprise_name"]})

    possible = [x for x in all_matches if x["match_level"] == "可能符合"]
    verify = [x for x in all_matches if x["match_level"] == "建议核验"]

    def _agg(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for x in items:
            s = out.setdefault(x["policy_code"], {
                "name": x["policy_name"], "level": x["policy_level"],
                "subsidy": x.get("subsidy_amount"), "deadline": x.get("deadline"),
                "days": x.get("days_to_deadline"), "count": 0,
                "sample_enterprises": [],
            })
            s["count"] += 1
            if len(s["sample_enterprises"]) < 3:
                s["sample_enterprises"].append(x["enterprise_name"])
        return out

    by_policy = _agg(possible)
    ranked = sorted(by_policy.values(), key=lambda x: (-x["count"],
                                                       x["days"] if x["days"] is not None else 9999))
    upcoming = [x for x in ranked if x["days"] is not None and 0 <= x["days"] <= 90]
    urgent = min(upcoming, key=lambda x: x["days"]) if upcoming else None

    key_data = [
        _kv("纳入匹配企业", scanned, "家"),
        _kv("匹配机会总数", len(all_matches), "条", "逐条政策公开条件与企业档案字段比对"),
        _kv("可能符合", len(possible), "条"),
        _kv("建议核验", len(verify), "条"),
        _kv("命中政策数", len(by_policy), "条", f"政策库共 {len({x['policy_code'] for x in all_matches})} 条被命中"),
        _kv("90 天内截止机会", len(upcoming), "条"),
    ]
    if urgent:
        key_data.append(_kv("最紧急申报", f"{urgent['name']}（{urgent['days']} 天后截止）"))

    reasons = [
        f"「{x['name']}」（{x['level']}）：{x['count']} 家企业可能符合"
        + (f"，最高补贴 {_subsidy_text(x['subsidy'])}" if _subsidy_text(x["subsidy"]) else "")
        + f"，例如 {'、'.join(x['sample_enterprises'])}。"
        for x in ranked[:5]
    ]
    suggestions = []
    if urgent:
        suggestions.append(f"「{urgent['name']}」将在 {urgent['days']} 天后截止（{urgent['deadline']}），"
                           f"涉及 {urgent['count']} 家可能符合企业，建议立即下发申报提醒并启动材料准备。")
    if ranked:
        suggestions.append(f"按「可能符合企业数」排序，优先推进 {ranked[0]['name']}"
                           f"（{ranked[0]['count']} 家）等 Top5 政策的集中申报辅导。")
    suggestions.append("对「建议核验」的机会逐家核对缺失字段（营收/人数/知识产权），补齐后重新匹配以提升结论置信度。")

    risks = []
    if data_gap_ents:
        risks.append(f"{data_gap_ents} 家企业档案存在字段缺失，其匹配结论仅为初步参考，需补充数据后核验。")
    if not possible:
        risks.append("当前无「可能符合」级别机会，政策库条件可能偏严或企业档案数据不足。")

    if name_hint and scanned > 1:
        scope_txt = f"名称含「{name_hint}」的 {scanned} 家企业"
    elif name_hint:
        scope_txt = f"企业「{name_hint}」"
    else:
        scope_txt = f"{scanned} 家入驻企业"
    conclusion = (
        f"对{scope_txt}逐条比对政策库条件，共识别 {len(all_matches)} 条匹配机会："
        f"可能符合 {len(possible)} 条、建议核验 {len(verify)} 条，涉及 {len(by_policy)} 条政策"
        + (f"；最紧急为「{urgent['name']}」（{urgent['days']} 天后截止）" if urgent else "")
        + "。匹配结论仅供参考，不构成申报资格确认。")

    return {
        "response": _block(conclusion, key_data,
                           reasons or ["未匹配到适用政策，或政策库中缺少对应条件配置。"],
                           suggestions, f"{scope_txt}的政策申报机会",
                           risks, ["企业服务专员", "政策申报对接人", "招商主管"],
                           DecisionStatus.NEED_CONFIRM
                           if data_gap_ents else DecisionStatus.AI_SUGGESTION,
                           # data_sufficient 表示"这个问题能否被回答"，而不是"数据是否完美"。
                           # 已给出完整的匹配统计与排序，缺字段的企业只作为风险提示，
                           # 若标成 False，前端会整体打上"数据不足"，与已给出的结论自相矛盾。
                           True),
        "evidence": p.get("evidence"),
    }


def _run_property(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    w = T.call_tool("get_work_orders", db, auth, park_id=park_id)
    if not w.get("data"):
        return {"response": _block("当前数据不足以支持物业分析。", [], [], [], "物业服务中心",
                                   ["数据缺失：工单数据为空"], ["物业人员"],
                                   DecisionStatus.INFO, False, w.get("missing_data", ["工单数据"])),
                "evidence": w.get("evidence")}
    d = w["data"]
    key_data = [
        _kv("工单总数", d["total"], "张"),
        _kv("未完成", d["open"], "张"),
        _kv("完成率", d["completion_rate"], "%"),
        _kv("超时工单", d["timeout_count"], "张", f"超时率 {d['timeout_rate']}%"),
        _kv("平均响应时长", d["avg_response_minutes"], "分钟"),
        _kv("平均处理时长", d["avg_handle_hours"], "小时"),
        _kv("平均满意度", d["avg_rating"] if d["avg_rating"] else "暂无评价", "分"),
    ]
    reasons, suggestions, risks = [], [], []
    if d["timeout_count"]:
        worst = None
        for t in d["timeout_orders"]:
            if worst is None or (t["handle_hours"] or 0) > (worst["handle_hours"] or 0):
                worst = t
        if worst:
            reasons.append(f"存在 {d['timeout_count']} 张超时工单，最严重为「{worst['title']}」"
                           f"（{worst['order_type']}，优先级 {worst['priority']}，"
                           f"SLA {worst['sla_hours']} 小时，实际处理 {worst['handle_hours']} 小时"
                           + (f"，负责人 {worst['assignee_name']}" if worst.get("assignee_name") else "") + "）。")
        suggestions.append(f"对 {d['timeout_count']} 张超时工单逐单复盘，核查派单及时性与人员配置。")
        risks.append(f"超时率 {d['timeout_rate']}%，影响企业服务满意度。")
    by_type = d["by_type"]
    if by_type:
        worst_type = max(by_type.items(), key=lambda x: x[1]["timeout"])
        if worst_type[1]["timeout"]:
            reasons.append(f"「{worst_type[0]}」类工单超时最多（{worst_type[1]['timeout']}/{worst_type[1]['total']} 张），是主要效率瓶颈。")
            suggestions.append(f"针对「{worst_type[0]}」类工单优化处置流程与备件储备，压缩处理时长。")

    conclusion = (f"当前工单总数 {d['total']} 张，完成率 {d['completion_rate']}%，"
                  f"未完成 {d['open']} 张，超时 {d['timeout_count']} 张（超时率 {d['timeout_rate']}%）")
    return {
        "response": _block(conclusion, key_data,
                           reasons or ["工单处理及时，未出现超时情况。"],
                           suggestions or ["保持现有派单与处置流程。"],
                           f"覆盖 {d['total']} 张物业工单", risks, ["物业人员", "物业运营团队"],
                           DecisionStatus.AI_SUGGESTION),
        "evidence": w.get("evidence"),
    }


def _run_contract(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    c = T.call_tool("get_contract_expiry", db, auth, park_id=park_id)
    if not c.get("data"):
        return {"response": _block("当前数据不足以支持合同分析。", [], [], [], "租赁与合同管理",
                                   ["数据缺失：合同数据为空"], ["运营人员"],
                                   DecisionStatus.INFO, False, c.get("missing_data", ["合同数据"])),
                "evidence": c.get("evidence")}
    d = c["data"]
    key_data = [
        _kv("合同总数", d["total_contracts"], "份"),
        _kv("生效中合同", d["active_contracts"], "份"),
        _kv("90天内到期", d["expiring_count"], "份", f"30天内 {len(d['grouped']['30天内'])} 份"),
        _kv("月租金影响面", d["total_monthly_rent_at_risk"], "元"),
        _kv("年租金影响面", d["total_annual_rent_at_risk"], "元"),
        _kv("涉及租赁面积", d["total_leased_area_at_risk"], "㎡"),
    ]
    reasons, suggestions, risks = [], [], []
    g30 = d["grouped"]["30天内"]
    if g30:
        reasons.append(f"{len(g30)} 份合同将在 30 天内到期，其中最紧急为「{g30[0]['enterprise_name']}」"
                       f"（{g30[0]['space_name']}，{g30[0]['end_date']}，仅剩 {g30[0]['days_left']} 天），"
                       f"月租金 {g30[0]['monthly_rent']:,.0f} 元。")
        suggestions.append(f"立即启动 {len(g30)} 份 30 天内到期合同的续租谈判，明确续租意愿与租金调整方案。")
    if d["grouped"]["31-60天"]:
        reasons.append(f"另有 {len(d['grouped']['31-60天'])} 份合同将在 31-60 天内到期。")
    if d["expired_not_closed"]:
        reasons.append(f"{d['expired_not_closed']} 份合同已过结束日期但状态未更新，需核实是否已实际续签或退租。")
        suggestions.append("核查超期未处理合同的实际履约状态，及时更新合同状态或办理续签/退租手续。")
        risks.append(f"{d['expired_not_closed']} 份合同状态异常，可能导致租金收取依据缺失。")
    if d["total_annual_rent_at_risk"] > 0:
        risks.append(f"90 天内到期合同涉及年租金 {d['total_annual_rent_at_risk']:,.0f} 元，"
                     f"续租失败将直接影响园区收入。")
    suggestions.append(f"按到期时间倒排续租工作计划，优先处理 30 天内到期的 {len(g30)} 份合同。")

    conclusion = (f"生效中合同 {d['active_contracts']} 份，其中 {d['expiring_count']} 份将在 90 天内到期"
                  + (f"（30 天内 {len(g30)} 份需立即处理）" if g30 else "")
                  + f"，涉及年租金 {d['total_annual_rent_at_risk']:,.0f} 元。")
    return {
        "response": _block(conclusion, key_data,
                           reasons or ["暂无临近到期的合同。"],
                           suggestions, f"覆盖 {d['total_contracts']} 份合同",
                           risks, ["运营人员", "招商主管", "财务人员"],
                           DecisionStatus.AI_SUGGESTION),
        "evidence": c.get("evidence"),
    }


def _run_enterprise(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    name_hint = _extract_enterprise_name(q)
    e = T.call_tool("get_enterprise_profile", db, auth, enterprise_name=name_hint, park_id=park_id)
    if not e.get("data"):
        return {"response": _block("当前数据不足以支持企业分析。", [], [], [], "企业全生命周期",
                                   ["数据缺失：未找到企业或无权限"], ["运营人员"],
                                   DecisionStatus.INFO, False, e.get("missing_data", ["企业数据"])),
                "evidence": e.get("evidence")}
    rows = e["data"]
    # 只有点名到唯一一家企业才做单企业画像；否则做企业群体总览。
    # 原实现无条件取 rows[0]，问"有哪些风险企业"会答成"某一家企业"的档案。
    if name_hint and len(rows) == 1:
        return _enterprise_detail(e, rows[0])
    return _enterprise_portfolio(e, rows, name_hint)


def _enterprise_detail(e: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """单企业全生命周期画像。"""
    state = enum_label(r["status"], "EnterpriseStatus")
    key_data = [
        _kv("企业名称", r["enterprise_name"]),
        _kv("企业状态", state),
        _kv("行业", r["industry"] or "未填写"),
        _kv("注册资本", r["register_capital"], "万元"),
        _kv("员工人数", r["employee_count"] or "未填写", "人"),
        _kv("年度营收", r["annual_revenue"] or "未填写", "万元"),
        _kv("知识产权", r["ip_count"], "项"),
        _kv("租赁面积", r["leased_area"], "㎡"),
        _kv("合同数", len(r["contracts"]), "份"),
        _kv("累计应收", r["finance"]["total_billed"], "元"),
        _kv("累计实收", r["finance"]["total_paid"], "元"),
        _kv("欠费", r["finance"]["arrears"], "元"),
    ]
    reasons, suggestions, risks = [], [], []
    for sig in r["risk_signals"]:
        reasons.append(f"【{sig['type']}】{sig['text']}")
        if sig["level"] in ("RISK", "CRITICAL"):
            risks.append(sig["text"])
    expiring = [c for c in r["contracts"] if c["end_date"] and c["status"] in ("ACTIVE", "EXPIRING")]
    if expiring:
        suggestions.append(f"该企业有 {len(expiring)} 份生效中合同，建议在合同到期前 60 天启动续租沟通。")
    if r["finance"]["arrears"] > 0:
        suggestions.append(f"针对欠费 {r['finance']['arrears']:,.0f} 元制定催缴计划，避免影响续租评估。")
    if r["is_high_tech"] or r["is_specialized"] or r["ip_count"] > 0:
        suggestions.append("企业具备政策申报基础（" + "、".join(filter(None, [
            "高新技术企业" if r["is_high_tech"] else None,
            "专精特新" if r["is_specialized"] else None,
            f"知识产权 {r['ip_count']} 项" if r["ip_count"] else None,
        ])) + "），建议推送匹配的扶持政策。")

    if not reasons:
        reasons.append("企业档案未记录风险信号，当前经营与履约状态正常。")

    conclusion = (f"企业「{r['enterprise_name']}」（{state}，{r['industry'] or '行业未填写'}）"
                  f"租赁面积 {r['leased_area']:,.0f} ㎡，{len(r['contracts'])} 份合同，"
                  f"累计应收 {r['finance']['total_billed']:,.0f} 元、欠费 {r['finance']['arrears']:,.0f} 元"
                  + (f"；识别到 {len(r['risk_signals'])} 项风险信号" if r["risk_signals"] else "；未发现风险信号"))

    return {
        "response": _block(conclusion, key_data, reasons,
                           suggestions or ["保持常规服务与企业走访节奏。"],
                           f"企业「{r['enterprise_name']}」全生命周期档案",
                           risks, ["运营人员", "企业服务专员", "财务人员"],
                           DecisionStatus.NEED_CONFIRM if r["missing_data"] else DecisionStatus.AI_SUGGESTION,
                           not bool(r["missing_data"]), r["missing_data"]),
        "evidence": e.get("evidence"),
    }


def _enterprise_portfolio(e: dict[str, Any], rows: list[dict[str, Any]],
                          name_hint: str | None) -> dict[str, Any]:
    """企业群体画像总览：状态结构、风险企业、资质结构、欠费与续租面。"""
    total = len(rows)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    settled = sum(v for k, v in by_status.items() if k in ("SETTLED", "GROWING"))
    risk_rows = [r for r in rows if r["status"] == "RISK" or r["risk_level"] in ("HIGH", "CRITICAL")]
    arrears_rows = [r for r in rows if (r["finance"]["arrears"] or 0) > 0]
    arrears_total = sum(r["finance"]["arrears"] or 0 for r in arrears_rows)
    hitech = [r for r in rows if r["is_high_tech"]]
    specialized = [r for r in rows if r["is_specialized"]]
    tech_sme = [r for r in rows if r["is_tech_sme"]]
    leased_area = sum(r["leased_area"] or 0 for r in rows)
    expiring_rows = [r for r in rows
                     if any(c["end_date"] and c["status"] in ("ACTIVE", "EXPIRING")
                            for c in r["contracts"])]

    key_data = [
        _kv("企业总数", total, "家"),
        _kv("已入驻/成长企业", settled, "家",
            " + ".join(f"{enum_label(k, 'EnterpriseStatus')} {v}" for k, v in sorted(by_status.items())
                       if k in ("SETTLED", "GROWING")) or "状态分布见下"),
        _kv("风险企业", len(risk_rows), "家", "状态为风险企业 或 风险等级为 HIGH/CRITICAL"),
        _kv("存在欠费企业", len(arrears_rows), "家"),
        _kv("欠费总额", round(arrears_total, 2), "元"),
        _kv("租赁面积合计", round(leased_area, 2), "㎡"),
        _kv("高新技术企业", len(hitech), "家"),
        _kv("专精特新企业", len(specialized), "家"),
        _kv("科技型中小企业", len(tech_sme), "家"),
        _kv("有生效合同企业", len(expiring_rows), "家"),
    ]
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        key_data.append(_kv(f"状态·{enum_label(k, 'EnterpriseStatus') or k}", v, "家"))

    reasons, suggestions, risks = [], [], []
    if risk_rows:
        risk_rows.sort(key=lambda r: -(r["finance"]["arrears"] or 0))
        risks.append(f"{len(risk_rows)} 家企业处于风险状态，合计欠费 "
                     f"{sum(r['finance']['arrears'] or 0 for r in risk_rows):,.0f} 元。")
        for r in risk_rows[:5]:
            top_sig = (r["risk_signals"] or [{}])[0]
            reasons.append(f"风险企业「{r['enterprise_name']}」（{r['industry'] or '行业未填写'}，"
                           f"风险等级 {r['risk_level']}）：欠费 {r['finance']['arrears']:,.0f} 元、"
                           f"租赁面积 {r['leased_area']:,.0f} ㎡"
                           + (f"；{top_sig.get('text')}" if top_sig.get("text") else "") + "。")
        suggestions.append(f"对 {len(risk_rows)} 家风险企业逐户走访，优先处理欠费金额最高的企业，"
                           "评估续租意愿与退园风险，必要时纳入招商补位预案。")
    if arrears_rows:
        reasons.append(f"{len(arrears_rows)} 家企业存在欠费，合计 {arrears_total:,.0f} 元，"
                       f"占全部 {total} 家企业的 {len(arrears_rows) / total * 100:.1f}%。")
        suggestions.append("按欠费金额与账龄分级催缴，账龄超过 90 天的启动法务评估。")
    if hitech or specialized:
        reasons.append(f"资质结构：高新技术企业 {len(hitech)} 家、专精特新 {len(specialized)} 家、"
                       f"科技型中小企业 {len(tech_sme)} 家；"
                       f"高企占比 {len(hitech) / total * 100:.1f}%。")
        suggestions.append(f"对尚未取得资质的 {total - len(hitech)} 家企业开展高企/专精特新申报培育辅导，"
                           "优先筛选知识产权 3 项以上的企业。")
    if expiring_rows:
        suggestions.append(f"对 {len(expiring_rows)} 家持有生效合同的企业按到期时间倒排续租沟通计划。")

    if not reasons:
        reasons.append("企业群体未发现风险企业与欠费记录，整体经营与履约状态正常。")

    scope_txt = f"名称含「{name_hint}」的 {total} 家企业" if name_hint else f"{total} 家企业"
    top_states = "、".join(f"{enum_label(k, 'EnterpriseStatus') or k} {v} 家"
                           for k, v in sorted(by_status.items(), key=lambda x: -x[1])[:4])
    conclusion = (f"当前范围共 {scope_txt}：{top_states}；"
                  f"其中风险企业 {len(risk_rows)} 家、存在欠费企业 {len(arrears_rows)} 家"
                  f"（合计 {arrears_total:,.0f} 元）、高新技术企业 {len(hitech)} 家。")

    return {
        "response": _block(conclusion, key_data, reasons,
                           suggestions or ["保持常规企业服务与走访节奏。"],
                           f"{scope_txt}的全生命周期档案",
                           risks, ["运营人员", "企业服务专员", "财务人员"],
                           DecisionStatus.NEED_APPROVAL if len(risk_rows) and
                           sum(r["finance"]["arrears"] or 0 for r in risk_rows) > 1_000_000
                           else DecisionStatus.AI_SUGGESTION),
        "evidence": e.get("evidence"),
    }


def _run_operations(db: Session, auth: AuthContext, q: str, park_id: int | None) -> dict[str, Any]:
    """经营分析 AI：跨模块综合诊断 + 最重要问题排序。"""
    dash = T.call_tool("get_dashboard_summary", db, auth, park_id=park_id)
    if not dash.get("data"):
        return {"response": _block("当前数据不足以支持经营分析。", [], [], [], "经营分析",
                                   ["数据缺失"], ["园区负责人"], DecisionStatus.INFO, False),
                "evidence": dash.get("evidence")}
    d = dash["data"]
    kpi_map = {k["key"]: k for k in d["kpis"]}
    s = d["summary"]

    key_data = [_kv(k["label"], k["value"], k["unit"], k["basis"]) for k in d["kpis"]
                if k["key"] in ("enterprise_count", "occupancy_rate", "conversion_rate",
                                "collection_rate", "arrears_amount", "project_delayed",
                                "safety_risk", "monthly_income")]

    # 综合采集各模块数据，形成"最重要的问题"排序
    issues: list[dict[str, Any]] = []
    module_data: dict[str, Any] = {}

    fin = T.call_tool("get_financial_summary", db, auth, park_id=park_id)
    if fin.get("data"):
        module_data["finance"] = fin["data"]
        fd = fin["data"]
        if fd["overdue_arrears"] > 0:
            top = fd["top_arrears"][0] if fd["top_arrears"] else None
            issues.append({
                "priority": 1, "category": "财务收费", "level": "HIGH" if fd["overdue_arrears"] > 100000 else "MEDIUM",
                "title": f"逾期欠费 {fd['overdue_arrears']:,.0f} 元未收回",
                "detail": (f"累计欠费 {fd['total_arrears']:,.0f} 元，其中已逾期 {fd['overdue_arrears']:,.0f} 元"
                           f"（{fd['overdue_count']} 张账单）。"
                           + (f"欠费最多：「{top['enterprise_name']}」{top['arrears']:,.0f} 元，最长逾期 {top['max_overdue_days']} 天。" if top else "")),
                "suggestion": "启动分级催缴，对账龄超 90 天欠费评估法务介入。",
                "owner": "财务人员 / 园区负责人",
                "evidence": f"来源：bills 表 {fd['total_bills']} 条账单记录",
            })
        if fd["collection_rate"] < 95:
            issues.append({
                "priority": 6, "category": "财务收费", "level": "MEDIUM",
                "title": f"租金收缴率 {fd['collection_rate']}% 低于目标 95%",
                "detail": f"已到期账单应收 {fd['ytd_receivable']:,.0f} 元，实收率不足目标值。",
                "suggestion": "优化账单推送与在线缴费入口，缩短缴费路径。",
                "owner": "财务人员",
                "evidence": "来源：bills 表已到期账单实收/应收比",
            })

    prj = T.call_tool("get_project_summary", db, auth, park_id=park_id)
    if prj.get("data") and prj["data"]["delayed"]:
        pd = prj["data"]
        dp = pd["delayed_projects"][0]
        issues.append({
            "priority": 2, "category": "项目管理", "level": "HIGH",
            "title": f"{pd['delayed']} 个项目延期，最长延误 {dp['delay_days']} 天",
            "detail": "、".join(f"{p['project_name']}（延期 {p['delay_days']} 天，进度 {p['progress']}%）"
                              for p in pd["delayed_projects"][:3]),
            "suggestion": "召开项目专项复盘会，重排剩余工期并评估是否需要变更基线。",
            "owner": "PMO / 各项目经理",
            "evidence": f"来源：projects 表 {pd['total']} 条项目记录",
        })
    if prj.get("data") and prj["data"]["total_budget"] and prj["data"]["budget_execution_rate"] > 88:
        pd = prj["data"]
        issues.append({
            "priority": 7, "category": "项目管理", "level": "MEDIUM",
            "title": f"项目预算执行率已达 {pd['budget_execution_rate']}%",
            "detail": f"实际成本 {pd['total_actual_cost']:,.0f} 元 / 批准预算 {pd['total_budget']:,.0f} 元。",
            "suggestion": "开展成本复核，防止年末集中超支。",
            "owner": "PMO / 财务人员",
            "evidence": "来源：projects 表预算与实际成本字段",
        })

    saf = T.call_tool("get_safety_risks", db, auth, park_id=park_id)
    if saf.get("data"):
        module_data["safety"] = saf["data"]
        sd = saf["data"]
        if sd["critical_open"] or sd["overdue_rectify"]:
            issues.append({
                "priority": 3, "category": "安全管理",
                "level": "CRITICAL" if sd["critical_open"] else "HIGH",
                "title": (f"{sd['critical_open']} 起重大安全事件未闭环" if sd["critical_open"]
                          else f"{sd['overdue_rectify']} 起隐患整改逾期"),
                "detail": (f"安全指数 {sd['safety_score']} 分（{sd['safety_status']}）；"
                           f"事件总数 {sd['total_incidents']} 起、未闭环 {sd['open_incidents']} 起、"
                           f"逾期整改 {sd['overdue_rectify']} 起、未闭环隐患 {sd['hazard_open']} 项。"),
                "suggestion": "重大事件启动应急处置并督办闭环；逾期项纳入部门安全考核。",
                "owner": "安全管理岗 / 物业运营团队",
                "evidence": f"来源：safety_incidents {sd['total_incidents']} 条 + safety_hazards {sd['hazard_total']} 条",
            })

    lz = T.call_tool("get_leasing_pipeline", db, auth, park_id=park_id)
    if lz.get("data"):
        module_data["leasing"] = lz["data"]
        ld = lz["data"]
        if ld["stagnant_count"]:
            issues.append({
                "priority": 4, "category": "招商管理", "level": "HIGH",
                "title": f"{ld['stagnant_count']} 条招商线索跟进停滞",
                "detail": (f"最久 {ld['stagnant_leads'][0]['days_since_followup']} 天未跟进"
                           f"（{ld['stagnant_leads'][0]['company_name']}）。"
                           f"招商转化率 {ld['conversion_rate']}%"
                           + (f"，{ld['lowest_conversion_park']['park_name']} 最低（{ld['lowest_conversion_park']['conversion_rate']}%）"
                              if ld.get("lowest_conversion_park") else "") + "。"),
                "suggestion": "按成交可能性排序，3 个工作日内完成停滞线索批量激活。",
                "owner": "招商主管 / 招商专员",
                "evidence": f"来源：leasing_leads {ld['total_leads']} 条线索",
            })
        if ld["funnel"]:
            weakest = None
            for f in ld["funnel"][1:]:
                if f["conversion_from_prev"] is not None and (weakest is None or
                                                              f["conversion_from_prev"] < weakest["conversion_from_prev"]):
                    weakest = f
            if weakest and weakest["conversion_from_prev"] < 60:
                idx = [x["stage"] for x in ld["funnel"]].index(weakest["stage"])
                issues.append({
                    "priority": 8, "category": "招商管理", "level": "MEDIUM",
                    "title": f"招商漏斗瓶颈：{ld['funnel'][idx-1]['stage_name']} → {weakest['stage_name']} 转化率仅 {weakest['conversion_from_prev']}%",
                    "detail": f"该环节是漏斗中流失最严重的节点（上一环节 {ld['funnel'][idx-1]['reached']} 条 → 本环节 {weakest['reached']} 条）。",
                    "suggestion": "针对瓶颈环节制定标准动作清单与时限要求。",
                    "owner": "招商主管",
                    "evidence": "来源：leasing_leads 表 stage 字段分布",
                })

    sp = T.call_tool("get_space_status", db, auth, park_id=park_id)
    if sp.get("data"):
        module_data["space"] = sp["data"]
        spd = sp["data"]
        if spd["long_vacant"]:
            lost = sum((v["area"] or 0) * (v["rent_price"] or 0) for v in spd["long_vacant"])
            issues.append({
                "priority": 5, "category": "空间资产", "level": "MEDIUM",
                "title": f"{len(spd['long_vacant'])} 处空间空置超 90 天",
                "detail": (f"最长空置 {spd['long_vacant'][0]['vacant_days']} 天"
                           f"（{spd['long_vacant'][0]['space_name']}）。整体出租率 {spd['occupancy_rate']}%，"
                           f"空置面积 {spd['vacant_area']:,.0f} ㎡，估算月租金损失约 {lost:,.0f} 元。"),
                "suggestion": "启动专项去化，考虑短租、联合办公或调整定价策略。",
                "owner": "运营人员 / 招商主管",
                "evidence": f"来源：spaces 表 {spd['total_space']} 个空间单元",
            })

    eng = T.call_tool("get_energy_summary", db, auth, park_id=park_id)
    if eng.get("data") and eng["data"]["anomaly_count"]:
        module_data["energy"] = eng["data"]
        ed = eng["data"]
        a = ed["anomalies"][0]
        who = a.get("enterprise_name") or a.get("building_name") or "未知位置"
        issues.append({
            "priority": 9, "category": "能源低碳", "level": "MEDIUM",
            "title": f"{ed['anomaly_count']} 条能耗异常待核查",
            "detail": f"最显著：{who} {a['record_date']} 的{a['label']}用量偏离基线 {a['anomaly_ratio']}%。",
            "suggestion": "逐条现场核查，排查设备空转、管线泄漏或计量故障。",
            "owner": "能源管理岗 / 设备运维团队",
            "evidence": f"来源：energy_records 表，异常标记 is_anomaly=True",
        })

    con = T.call_tool("get_contract_expiry", db, auth, park_id=park_id)
    if con.get("data") and con["data"]["grouped"]["30天内"]:
        cd = con["data"]
        g30 = cd["grouped"]["30天内"]
        issues.append({
            "priority": 10, "category": "租赁合同", "level": "HIGH",
            "title": f"{len(g30)} 份合同 30 天内到期",
            "detail": (f"涉及年租金 {cd['total_annual_rent_at_risk']:,.0f} 元、租赁面积 {cd['total_leased_area_at_risk']:,.0f} ㎡。"
                       f"最紧急：「{g30[0]['enterprise_name']}」仅剩 {g30[0]['days_left']} 天。"),
            "suggestion": "立即启动续租谈判，明确续租意愿与租金调整方案。",
            "owner": "运营人员 / 招商主管",
            "evidence": f"来源：contracts 表 {cd['total_contracts']} 份合同",
        })

    issues.sort(key=lambda x: (x["priority"], {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}.get(x["level"], 3)))

    if not issues:
        reasons = ["各业务模块未发现显著异常项。"]
        conclusion = "当前园区各项经营指标整体正常，未识别到需要优先处理的重要问题。"
    else:
        reasons = [f"{i+1}. 【{x['category']}·{x['level']}】{x['title']} —— {x['detail']}"
                   for i, x in enumerate(issues[:5])]
        conclusion = (f"综合各业务模块数据，当前园区识别出 {len(issues)} 项需关注问题，"
                      f"其中优先级最高的 5 项为：" + "；".join(x["title"] for x in issues[:5]) + "。")

    suggestions = [f"{x['title']} → {x['suggestion']}" for x in issues[:5]]
    risks = [f"[{x['level']}] {x['title']}" for x in issues if x["level"] in ("CRITICAL", "HIGH")]

    needs_approval = any(x["level"] == "CRITICAL" for x in issues)
    decision = DecisionStatus.NEED_APPROVAL if needs_approval else DecisionStatus.AI_SUGGESTION

    return {
        "response": _block(conclusion, key_data, reasons,
                           suggestions or ["维持现有经营策略。"],
                           f"覆盖 {s['park_count']} 个园区、{s['enterprise_settled']} 家入驻企业、"
                           f"{s['project_total']} 个项目、{s['active_contracts']} 份生效合同",
                           risks, sorted({x["owner"] for x in issues[:5]}),
                           decision),
        "evidence": {
            "data_source": "平台业务数据库",
            "tables": ["parks", "enterprises", "spaces", "leasing_leads", "contracts",
                       "bills", "projects", "work_orders", "devices", "energy_records",
                       "safety_incidents"],
            "record_count": sum(len(v) if isinstance(v, list) else 1 for v in module_data.values()) + len(d["kpis"]),
            "filters": {"park_id": park_id, "visible_parks": d["scope"]["park_ids"]},
            "formula": "跨模块 KPI 采集 → 阈值规则判定 → 优先级排序",
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data_label": DATA_LABEL,
            "modules_invoked": list(module_data.keys()),
        },
        "issues": issues[:10],
        "key_data": key_data,
        "reasons": reasons,
        "suggestions": suggestions,
        "risks": risks,
        "conclusion": conclusion,
        "decision_status": decision,
    }


AGENT_RUNNERS = {
    "leasing": _run_leasing,
    "project": _run_project,
    "energy": _run_energy,
    "safety": _run_safety,
    "finance": _run_finance,
    "space": _run_space,
    "policy": _run_policy,
    "property": _run_property,
    "contract": _run_contract,
    "enterprise": _run_enterprise,
    "operations": _run_operations,
}


# ==========================================================================
# 主 Agent
# ==========================================================================


def answer(db: Session, auth: AuthContext, question: str,
           park_id: int | None = None, project_id: int | None = None,
           forced_agent: str | None = None) -> dict[str, Any]:
    """园智AI总管：意图识别 → 路由 → 数据调用 → 结果汇总。"""
    started = dt.datetime.now()
    intents = [forced_agent] if forced_agent and forced_agent in SUB_AGENTS else classify_intent(question)

    routes = []
    for key in intents:
        runner = AGENT_RUNNERS.get(key)
        if not runner:
            continue
        try:
            if key == "project":
                res = runner(db, auth, question, park_id, project_id=project_id)
            else:
                res = runner(db, auth, question, park_id)
            routes.append({**res, "agent_key": key, "agent_name": SUB_AGENTS[key]["name"]})
        except Exception as exc:  # noqa: BLE001
            routes.append({
                "agent_key": key, "agent_name": SUB_AGENTS[key]["name"],
                "response": _block(
                    f"{SUB_AGENTS[key]['name']} 执行过程中出现异常：{exc}", [], [], [],
                    "系统", ["分析中断"], ["系统管理员"], DecisionStatus.INFO, False, [str(exc)]),
                "evidence": None,
            })

    if not routes:
        routes = [{
            "agent_key": "operations", "agent_name": "经营分析AI",
            "response": _block("当前问题未匹配到可用的分析能力。", [], [], 
                               ["请补充更具体的业务对象（如园区名称、项目名称、企业名称）。"],
                               "未识别", ["意图识别失败"], ["运营人员"], DecisionStatus.INFO, False,
                               ["无法从问题中识别业务意图"]),
            "evidence": None,
        }]

    primary = routes[0]
    others = routes[1:]

    elapsed = int((dt.datetime.now() - started).total_seconds() * 1000)
    resp = dict(primary["response"])
    resp["agent_key"] = primary["agent_key"]
    resp["agent_name"] = primary["agent_name"]

    if others:
        resp["关联分析"] = [{
            "agent": o["agent_name"],
            "结论": o["response"]["结论"],
            "关键数据": o["response"]["关键数据"][:4],
        } for o in others]

    evidences = [r["evidence"] for r in routes if r.get("evidence")]
    merged_evidence = {
        "data_source": "平台业务数据库",
        "tables": sorted({t for e in evidences for t in (e.get("tables") or [])}),
        "record_count": sum(e.get("record_count") or 0 for e in evidences),
        "filters": {"park_id": park_id, "visible_parks": auth.visible_park_ids(), "project_id": project_id},
        "modules_invoked": [{"key": r["agent_key"], "name": r["agent_name"]} for r in routes],
        "formula": "; ".join(filter(None, [e.get("formula") for e in evidences])),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_label": DATA_LABEL,
        "user_scope": {"role": auth.role_label, "data_scope": auth.data_scope},
    }

    return {
        "question": question,
        "intent": primary["agent_key"],
        "intent_label": primary["agent_name"],
        "intents_all": [{"key": r["agent_key"], "name": r["agent_name"]} for r in routes],
        "response": resp,
        "evidence": merged_evidence,
        "permission_level": (AIPermissionLevel.L3_ACTION
                             if resp["决策状态"] == DecisionStatus.NEED_APPROVAL
                             else AIPermissionLevel.L2_ADVISE),
        "data_sufficient": resp.get("data_sufficient", True),
        "missing_data": resp.get("missing_data", []),
        "latency_ms": elapsed,
        "extra": primary.get("issues"),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


# ==========================================================================
# AI 今日洞察（需求书第 75 节）
# ==========================================================================


def build_daily_insights(db: Session, auth: AuthContext, park_id: int | None = None) -> list[dict[str, Any]]:
    """自动生成驾驶舱右侧「AI今日洞察」条目：经营异常/招商机会/空间异常/
    合同预警/欠费风险/项目风险/设备风险/能耗异常/安全风险/政策机会。"""
    insights: list[dict[str, Any]] = []
    today = dt.date.today()

    def add(category: str, title: str, detail: str, level: str, suggestion: str,
            agent_key: str, evidence: str, action_label: str | None = None,
            action_route: str | None = None, metrics: dict | None = None):
        insights.append({
            "category": category, "title": title, "detail": detail, "level": level,
            "suggestion": suggestion, "agent_key": agent_key, "agent_name":
                SUB_AGENTS.get(agent_key, {}).get("name", "经营分析AI"),
            "evidence": evidence, "action_label": action_label, "action_route": action_route,
            "metrics": metrics or {}, "date": today.isoformat(),
            "decision_status": DecisionStatus.NEED_APPROVAL if level == "CRITICAL" else DecisionStatus.AI_SUGGESTION,
        })

    # 1. 合同预警
    c = T.call_tool("get_contract_expiry", db, auth, park_id=park_id, days=90)
    if c.get("data"):
        cd = c["data"]
        if cd["grouped"]["30天内"]:
            g = cd["grouped"]["30天内"]
            add("合同预警", f"{len(g)} 份合同 30 天内到期",
                f"紧急性最高：「{g[0]['enterprise_name']}」（{g[0]['space_name']}）将于 {g[0]['end_date']} 到期，"
                f"仅剩 {g[0]['days_left']} 天，月租金 {g[0]['monthly_rent']:,.0f} 元。"
                f"90 天内到期合同合计影响年租金 {cd['total_annual_rent_at_risk']:,.0f} 元。",
                "WARNING", "立即启动续租谈判，明确续租意愿与租金调整方案。", "contract",
                f"来源：contracts 表 {cd['total_contracts']} 份合同，到期日筛选 90 天内",
                "查看合同", "/contract",
                {"合同数": len(g), "年租金影响": cd["total_annual_rent_at_risk"]})

    # 2. 欠费风险
    f = T.call_tool("get_financial_summary", db, auth, park_id=park_id)
    if f.get("data") and f["data"]["overdue_arrears"] > 0:
        fd = f["data"]
        top = fd["top_arrears"][0] if fd["top_arrears"] else None
        add("欠费风险", f"逾期欠费 {fd['overdue_arrears']:,.0f} 元",
            (f"欠费最多：「{top['enterprise_name']}」{top['arrears']:,.0f} 元（最长逾期 {top['max_overdue_days']} 天）。" if top else "")
            + f"累计欠费 {fd['total_arrears']:,.0f} 元，涉及 {len(fd['arrears_by_enterprise'])} 家企业，"
              f"收缴率 {fd['collection_rate']}%。",
            "RISK" if fd["overdue_arrears"] > 100000 else "WARNING",
            "启动分级催缴，对账龄超 90 天欠费评估法务介入。", "finance",
            f"来源：bills 表 {fd['total_bills']} 条账单，未结清状态（UNPAID/PARTIAL/OVERDUE）"
            f"且账龄非 NORMAL 筛选",
            "查看财务", "/finance",
            {"逾期欠费": fd["overdue_arrears"], "欠费企业数": len(fd["arrears_by_enterprise"])})

    # 3. 项目风险
    p = T.call_tool("get_project_summary", db, auth, park_id=park_id)
    if p.get("data") and p["data"]["delayed"]:
        pd = p["data"]
        dp = pd["delayed_projects"][0]
        add("项目风险", f"{pd['delayed']} 个项目延期",
            f"最严重：「{dp['project_name']}」延期 {dp['delay_days']} 天（当前进度 {dp['progress']}%，"
            f"风险等级 {dp['risk_level']}，项目经理 {dp['project_manager_name']}）。"
            f"另有 {pd['high_risk']} 个项目处于高/重大风险等级。",
            "HIGH", "召开项目专项复盘会，重排剩余工期；关键路径延期超 5 天需提交变更审批。", "project",
            f"来源：projects 表 {pd['total']} 个项目，计划结束日期 < 今天 且状态未完成",
            "查看项目", f"/project/{dp['id']}",
            {"延期项目": pd["delayed"], "高风险项目": pd["high_risk"]})

    # 4. 招商机会
    lz = T.call_tool("get_leasing_pipeline", db, auth, park_id=park_id)
    if lz.get("data"):
        ld = lz["data"]
        if ld["stagnant_count"]:
            s0 = ld["stagnant_leads"][0]
            add("招商机会", f"{ld['stagnant_count']} 条线索跟进停滞",
                f"最久「{s0['company_name']}」已 {s0['days_since_followup']} 天未跟进"
                f"（阶段：{s0['stage_name']}，成交可能性 {s0['win_probability']}%，意向面积 {s0['demand_area']} ㎡）。"
                f"当前招商转化率 {ld['conversion_rate']}%。",
                "WARNING", "按成交可能性排序，3 个工作日内完成停滞线索批量激活。", "leasing",
                f"来源：leasing_leads 表 {ld['total_leads']} 条线索，最后跟进时间筛选",
                "查看招商", "/leasing",
                {"停滞线索": ld["stagnant_count"], "转化率": ld["conversion_rate"]})
        if ld.get("top_opportunities"):
            o = ld["top_opportunities"][0]
            add("招商机会", f"高价值商机：「{o['company_name']}」",
                f"成交可能性 {o['win_probability']}%，意向面积 {o['demand_area']} ㎡，"
                f"投资规模 {o['investment_amount']} 万元，优先级 {o['priority']}。",
                "INFO", "安排园区负责人参与商务谈判，加快审批流程。", "leasing",
                f"来源：leasing_leads 表，按 win_probability 降序",
                "查看商机", "/leasing")

    # 5. 空间异常
    sp = T.call_tool("get_space_status", db, auth, park_id=park_id)
    if sp.get("data") and sp["data"]["long_vacant"]:
        spd = sp["data"]
        lost = sum((v["area"] or 0) * (v["rent_price"] or 0) for v in spd["long_vacant"])
        add("空间异常", f"{len(spd['long_vacant'])} 处空间空置超 90 天",
            f"最长空置 {spd['long_vacant'][0]['vacant_days']} 天（{spd['long_vacant'][0]['space_name']}，"
            f"{spd['long_vacant'][0]['area']:,.0f} ㎡）。整体出租率 {spd['occupancy_rate']}%，"
            f"空置面积 {spd['vacant_area']:,.0f} ㎡，估算月租金损失约 {lost:,.0f} 元。",
            "WARNING", "启动专项去化，考虑短租、联合办公或调整定价策略。", "space",
            f"来源：spaces 表 {spd['total_space']} 个空间，vacant_since 距今 > 90 天",
            "查看空间", "/space",
            {"长期空置": len(spd["long_vacant"]), "出租率": spd["occupancy_rate"]})

    # 6. 安全风险
    saf = T.call_tool("get_safety_risks", db, auth, park_id=park_id)
    if saf.get("data"):
        sd = saf["data"]
        if sd["critical_open"] or sd["overdue_rectify"] or sd["hazard_open"]:
            add("安全风险", f"安全指数 {sd['safety_score']} 分（{sd['safety_status']}）",
                f"未闭环事件 {sd['open_incidents']} 起，其中重大/紧急 {sd['critical_open']} 起；"
                f"整改逾期 {sd['overdue_rectify']} 起；未闭环隐患 {sd['hazard_open']} 项。",
                "CRITICAL" if sd["critical_open"] else "HIGH",
                "重大事件启动应急处置并督办闭环；逾期项纳入部门安全考核。", "safety",
                f"来源：safety_incidents {sd['total_incidents']} 条 + safety_hazards {sd['hazard_total']} 条",
                "查看安全", "/safety",
                {"安全指数": sd["safety_score"], "未闭环": sd["open_incidents"]})

    # 7. 能耗异常
    eng = T.call_tool("get_energy_summary", db, auth, park_id=park_id)
    if eng.get("data") and eng["data"]["anomaly_count"]:
        ed = eng["data"]
        a = ed["anomalies"][0]
        who = a.get("enterprise_name") or a.get("building_name") or "未知位置"
        add("能耗异常", f"{ed['anomaly_count']} 条能耗异常",
            f"最显著：{who} 在 {a['record_date']} 的{a['label']}用量 {a['consumption']}，"
            f"较基线 {a['baseline']} 偏离 {a['anomaly_ratio']}%。"
            + (f"夜间用电占比 {ed['night_consumption_ratio']}%。" if ed.get("night_consumption_ratio") else ""),
            "WARNING", "逐条现场核查，排查设备空转、管线泄漏或计量故障。", "energy",
            f"来源：energy_records 表，is_anomaly=True 筛选（近 {ed['window_days']} 天）",
            "查看能源", "/energy",
            {"异常记录": ed["anomaly_count"], "碳排放(吨)": ed["total_carbon_ton"]})

    # 8. 设备风险
    dev = T.call_tool("get_device_status", db, auth, park_id=park_id)
    if dev.get("data"):
        dd = dev["data"]
        if dd["fault_count"] or dd["maintain_due"]:
            msg = []
            if dd["fault_count"]:
                msg.append(f"{dd['fault_count']} 台设备处于故障状态")
            if dd["maintain_due"]:
                msg.append(f"{len(dd['maintain_due'])} 台设备 15 天内需保养")
            add("设备风险", "；".join(msg),
                f"设备在线率 {dd['online_rate']}%，平均健康度 {dd['avg_health_score']} 分。"
                + (f"故障设备首台：「{dd['fault_devices'][0]['device_name']}」（{dd['fault_devices'][0]['location']}，"
                   f"健康度 {dd['fault_devices'][0]['health_score']} 分）。" if dd["fault_devices"] else "")
                + (f"最近需保养：「{dd['maintain_due'][0]['device_name']}」{dd['maintain_due'][0]['next_maintain_date']}。"
                   if dd["maintain_due"] else ""),
                "RISK" if dd["fault_count"] else "WARNING",
                "故障设备立即派单维修；临近保养设备提前排期。", "property",
                f"来源：devices 表 {dd['total']} 台设备，status=FAULT 与 next_maintain_date 筛选",
                "查看设备", "/device",
                {"故障设备": dd["fault_count"], "在线率": dd["online_rate"]})

    # 9. 政策机会
    pol = T.call_tool("get_policy_matches", db, auth, park_id=park_id, enterprise_id=None)
    if pol.get("data"):
        all_matches = []
        for r in pol["data"][:30]:
            for m in r["matches"]:
                if m["match_level"] == "可能符合" and m.get("days_to_deadline") is not None and 0 <= m["days_to_deadline"] <= 60:
                    all_matches.append({"enterprise_name": r["enterprise_name"], **m})
        if all_matches:
            all_matches.sort(key=lambda x: x["days_to_deadline"])
            m0 = all_matches[0]
            add("政策机会", f"{len(all_matches)} 条政策申报机会（60天内截止）",
                f"最紧急：「{m0['policy_name']}」（{m0['policy_level']}）将于 {m0['deadline']} 截止，"
                f"仅剩 {m0['days_to_deadline']} 天；匹配企业「{m0['enterprise_name']}」匹配度 {m0['match_score']}%。"
                + (f"补贴 {_subsidy_text(m0.get('subsidy_amount'))}。" if _subsidy_text(m0.get("subsidy_amount")) else ""),
                "INFO", "按截止日期倒排材料准备计划，优先推进高匹配度政策申报。", "policy",
                f"来源：policies × enterprises 结构化条件比对，deadline 筛选 60 天内",
                "查看政策", "/service",
                {"政策机会": len(all_matches)})

    # 10. 经营异常（工单与物业）
    wo = T.call_tool("get_work_orders", db, auth, park_id=park_id)
    if wo.get("data") and wo["data"]["timeout_count"]:
        wd = wo["data"]
        add("经营异常", f"{wd['timeout_count']} 张工单超时未完成",
            f"超时率 {wd['timeout_rate']}%，工单完成率 {wd['completion_rate']}%，"
            f"平均响应 {wd['avg_response_minutes']} 分钟。"
            + (f"最严重：「{wd['timeout_orders'][0]['title']}」SLA {wd['timeout_orders'][0]['sla_hours']} 小时，"
               f"已处理 {wd['timeout_orders'][0]['handle_hours']} 小时。" if wd["timeout_orders"] else ""),
            "WARNING", "逐单复盘超时原因，核查派单及时性与人员配置。", "property",
            f"来源：work_orders 表 {wd['total']} 张工单，is_timeout=True 筛选",
            "查看工单", "/property",
            {"超时工单": wd["timeout_count"], "完成率": wd["completion_rate"]})

    order = {"CRITICAL": 0, "RISK": 1, "HIGH": 1, "WARNING": 2, "INFO": 3}
    insights.sort(key=lambda x: order.get(x["level"], 9))
    return insights

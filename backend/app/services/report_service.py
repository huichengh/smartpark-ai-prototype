"""报表生成服务（对应需求书第 40 节）。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import tools as T
from app.core.enums import ManagementMethod
from app.core.security import AuthContext
from app.models import Project
from app.services import project_engine


def _period_label(period: str | None) -> str:
    if period:
        return period
    t = dt.date.today()
    return f"{t.year}年{t.month}月"


def build_operating_report(db: Session, auth: AuthContext,
                           park_id: int | None = None, period: str | None = None) -> dict[str, Any]:
    label = _period_label(period)
    dash = T.call_tool("get_dashboard_summary", db, auth, park_id=park_id)
    fin = T.call_tool("get_financial_summary", db, auth, park_id=park_id)
    lz = T.call_tool("get_leasing_pipeline", db, auth, park_id=park_id)
    sp = T.call_tool("get_space_status", db, auth, park_id=park_id)
    con = T.call_tool("get_contract_expiry", db, auth, park_id=park_id)
    wo = T.call_tool("get_work_orders", db, auth, park_id=park_id)
    dev = T.call_tool("get_device_status", db, auth, park_id=park_id)
    eng = T.call_tool("get_energy_summary", db, auth, park_id=park_id)
    saf = T.call_tool("get_safety_risks", db, auth, park_id=park_id)
    prj = T.call_tool("get_project_summary", db, auth, park_id=park_id)

    sections: list[dict[str, Any]] = []
    highlights: list[str] = []
    warnings: list[str] = []

    def sec(title: str, status: dict, metrics: list[dict], notes: list[str],
            insufficient: bool = False, missing: list[str] | None = None):
        sections.append({
            "title": title, "metrics": metrics, "notes": notes,
            "data_sufficient": not insufficient,
            "missing_data": missing or [],
        })

    # 一、经营总览
    if dash.get("data"):
        d = dash["data"]
        kpis = {k["key"]: k for k in d["kpis"]}
        sec("一、经营总览", d, [
            {"label": k["label"], "value": k["value"], "unit": k["unit"], "basis": k["basis"],
             "yoy": k.get("yoy"), "mom": k.get("mom")}
            for k in d["kpis"]
            if k["key"] in ("park_count", "enterprise_count", "occupancy_rate", "settle_rate",
                            "available_area", "monthly_income", "collection_rate", "arrears_amount")
        ], [
            f"授权范围内共 {d['summary']['park_count']} 个园区、{d['summary']['building_count']} 栋楼宇，"
            f"可租面积 {d['summary']['total_rentable_area']:,.0f} ㎡，出租率 "
            f"{kpis.get('occupancy_rate', {}).get('value', 0)}%。",
            f"入驻企业 {d['summary']['enterprise_settled']} 家，其中风险企业 "
            f"{d['summary']['enterprise_risk']} 家。",
        ] + (d.get("data_status_notes") or []))
        warnings.extend(d.get("data_status_notes") or [])

        if kpis.get("occupancy_rate", {}).get("value", 0) < 80:
            warnings.append(f"空间出租率 {kpis['occupancy_rate']['value']}% 低于 80%，需加强招商去化。")
        if kpis.get("collection_rate", {}).get("value", 0) < 95:
            warnings.append(f"租金收缴率 {kpis['collection_rate']['value']}% 低于目标 95%。")
        highlights.append(f"本月经营收入 {kpis.get('monthly_income', {}).get('value', 0):,.0f} 元。")
    else:
        sec("一、经营总览", {}, [], ["经营数据获取失败。"], True, ["驾驶舱数据"])

    # 二、招商分析
    if lz.get("data"):
        ld = lz["data"]
        sec("二、招商分析", ld, [
            {"label": "累计线索", "value": ld["total_leads"], "unit": "条"},
            {"label": "在跟进线索", "value": ld["active_leads"], "unit": "条"},
            {"label": "已签约", "value": ld["signed_leads"], "unit": "条"},
            {"label": "流失", "value": ld["lost_leads"], "unit": "条"},
            {"label": "转化率", "value": ld["conversion_rate"], "unit": "%",
             "basis": "签约线索 ÷ 已进入有效商机及以后的线索"},
            {"label": "意向面积", "value": ld["total_demand_area"], "unit": "㎡"},
            {"label": "意向投资", "value": ld["total_investment"], "unit": "万元"},
        ], [
            "漏斗各环节：" + " → ".join(f"{f['stage_name']}({f['count']})" for f in ld["funnel"]),
            (f"转化率最低园区：{ld['lowest_conversion_park']['park_name']} "
             f"{ld['lowest_conversion_park']['conversion_rate']}%" if ld.get("lowest_conversion_park") else ""),
            f"跟进停滞线索 {ld['stagnant_count']} 条（≥30 天未跟进）。",
        ])
        if ld["stagnant_count"]:
            warnings.append(f"招商：{ld['stagnant_count']} 条线索跟进停滞，存在流失风险。")
    else:
        sec("二、招商分析", {}, [], ["招商线索数据为空。"], True, ["招商线索"])

    # 三、空间与资产
    if sp.get("data"):
        sd = sp["data"]
        sec("三、空间与资产", sd, [
            {"label": "可租空间", "value": sd["total_space"], "unit": "个"},
            {"label": "可租面积", "value": sd["total_area"], "unit": "㎡"},
            {"label": "已出租面积", "value": sd["rented_area"], "unit": "㎡"},
            {"label": "出租率", "value": sd["occupancy_rate"], "unit": "%"},
            {"label": "空置空间", "value": sd["vacant_count"], "unit": "个"},
            {"label": "空置面积", "value": sd["vacant_area"], "unit": "㎡"},
            {"label": "超90天空置", "value": len(sd["long_vacant"]), "unit": "个"},
        ], [
            "楼栋出租率排名（升序）：" + "、".join(
                f"{b['building_name']} {b['occupancy_rate']}%" for b in sd["building_rank"][:6]),
        ])
        if sd["long_vacant"]:
            lost = sum((v["area"] or 0) * (v["rent_price"] or 0) for v in sd["long_vacant"])
            warnings.append(f"空间：{len(sd['long_vacant'])} 处空置超 90 天，估算月租金损失约 {lost:,.0f} 元。")
    else:
        sec("三、空间与资产", {}, [], ["空间数据为空。"], True, ["空间数据"])

    # 四、合同与租赁
    if con.get("data"):
        cd = con["data"]
        sec("四、合同与租赁", cd, [
            {"label": "合同总数", "value": cd["total_contracts"], "unit": "份"},
            {"label": "生效中合同", "value": cd["active_contracts"], "unit": "份"},
            {"label": "90天内到期", "value": cd["expiring_count"], "unit": "份"},
            {"label": "30天内到期", "value": len(cd["grouped"]["30天内"]), "unit": "份"},
            {"label": "涉及年租金", "value": cd["total_annual_rent_at_risk"], "unit": "元"},
            {"label": "涉及租赁面积", "value": cd["total_leased_area_at_risk"], "unit": "㎡"},
        ], [
            (f"最紧急到期：「{cd['expiring_list'][0]['enterprise_name']}」"
             f"{cd['expiring_list'][0]['end_date']}（剩 {cd['expiring_list'][0]['days_left']} 天），"
             f"月租金 {cd['expiring_list'][0]['monthly_rent']:,.0f} 元。" if cd["expiring_list"] else "无临近到期合同。"),
            (f"另有 {cd['expired_not_closed']} 份合同已过期但状态未更新，需核实履约状态。"
             if cd["expired_not_closed"] else ""),
        ])
        if cd["grouped"]["30天内"]:
            warnings.append(f"合同：{len(cd['grouped']['30天内'])} 份合同 30 天内到期，涉及年租金 "
                            f"{cd['total_annual_rent_at_risk']:,.0f} 元。")
    else:
        sec("四、合同与租赁", {}, [], ["合同数据为空。"], True, ["合同数据"])

    # 五、财务收费
    if fin.get("data"):
        fd = fin["data"]
        sec("五、财务收费", fd, [
            {"label": "本月应收", "value": fd["month_receivable"], "unit": "元"},
            {"label": "本月实收", "value": fd["month_received"], "unit": "元"},
            {"label": "年初至今实收", "value": fd["ytd_received"], "unit": "元"},
            {"label": "收缴率", "value": fd["collection_rate"], "unit": "%"},
            {"label": "欠费总额", "value": fd["total_arrears"], "unit": "元"},
            {"label": "逾期欠费", "value": fd["overdue_arrears"], "unit": "元"},
        ], [
            "欠费 TOP5：" + "、".join(f"{e['enterprise_name']} {e['arrears']:,.0f} 元"
                                      for e in fd["top_arrears"]),
            "账龄分布：" + "、".join(f"{a['name']} {a['amount']:,.0f} 元" for a in fd["arrears_age"]),
        ])
        if fd["overdue_arrears"]:
            warnings.append(f"财务：逾期欠费 {fd['overdue_arrears']:,.0f} 元，涉及 "
                            f"{fd['overdue_count']} 张账单。")
    else:
        sec("五、财务收费", {}, [], ["账单数据为空。"], True, ["账单数据"])

    # 六、物业服务
    if wo.get("data"):
        wd = wo["data"]
        sec("六、物业服务", wd, [
            {"label": "工单总数", "value": wd["total"], "unit": "张"},
            {"label": "完成率", "value": wd["completion_rate"], "unit": "%"},
            {"label": "未完成", "value": wd["open"], "unit": "张"},
            {"label": "超时工单", "value": wd["timeout_count"], "unit": "张"},
            {"label": "平均响应", "value": wd["avg_response_minutes"], "unit": "分钟"},
            {"label": "平均处理", "value": wd["avg_handle_hours"], "unit": "小时"},
            {"label": "满意度", "value": wd["avg_rating"] or "暂无评价", "unit": "分"},
        ], ["工单类型分布：" + "、".join(f"{k} {v['total']} 张（超时 {v['timeout']}）"
                                       for k, v in wd["by_type"].items())])
        if wd["timeout_count"]:
            warnings.append(f"物业：{wd['timeout_count']} 张工单超时（超时率 {wd['timeout_rate']}%）。")
    else:
        sec("六、物业服务", {}, [], ["工单数据为空。"], True, ["工单数据"])

    # 七、设备设施
    if dev.get("data"):
        dd = dev["data"]
        sec("七、设备设施", dd, [
            {"label": "设备总数", "value": dd["total"], "unit": "台"},
            {"label": "在线率", "value": dd["online_rate"], "unit": "%"},
            {"label": "故障设备", "value": dd["fault_count"], "unit": "台"},
            {"label": "平均健康度", "value": dd["avg_health_score"], "unit": "分"},
            {"label": "IoT 接入", "value": dd["iot_connected"], "unit": "台"},
            {"label": "15天内保养", "value": len(dd["maintain_due"]), "unit": "台"},
        ], ["设备类型分布：" + "、".join(f"{k} {v['total']} 台（故障 {v['fault']}）"
                                       for k, v in dd["by_type"].items())])
        if dd["fault_count"]:
            warnings.append(f"设备：{dd['fault_count']} 台设备故障，在线率 {dd['online_rate']}%。")
    else:
        sec("七、设备设施", {}, [], ["设备台账为空。"], True, ["设备数据"])

    # 八、能源低碳
    if eng.get("data"):
        ed = eng["data"]
        sec("八、能源低碳", ed, [
            *[{"label": f"{x['label']}消耗", "value": x["consumption"], "unit": x["unit"],
               "mom": x.get("mom"), "basis": f"近 {ed['window_days']} 天"} for x in ed["by_type"]],
            {"label": "碳排放", "value": ed["total_carbon_ton"], "unit": "吨CO₂"},
            {"label": "单位面积电耗", "value": ed["unit_area_consumption"] or "数据不足", "unit": "kWh/㎡"},
            {"label": "夜间用电占比", "value": ed["night_consumption_ratio"] or "数据不足", "unit": "%"},
            {"label": "能耗异常", "value": ed["anomaly_count"], "unit": "条"},
        ], [
            "楼栋单位面积电耗排名：" + "、".join(
                f"{b['building_name']} {b['unit_consumption']} kWh/㎡"
                for b in ed["by_building"][:5] if b.get("unit_consumption")),
        ])
        if ed["anomaly_count"]:
            warnings.append(f"能源：{ed['anomaly_count']} 条能耗异常记录待核查。")
    else:
        sec("八、能源低碳", {}, ["能耗设备尚未接入，本期无能耗数据。"], True, ["能耗数据"])

    # 九、安全管理
    if saf.get("data"):
        sd = saf["data"]
        sec("九、安全管理", sd, [
            {"label": "安全指数", "value": sd["safety_score"], "unit": "分", "basis": "100 分制扣减模型"},
            {"label": "安全状态", "value": sd["safety_status"], "unit": ""},
            {"label": "事件总数", "value": sd["total_incidents"], "unit": "起"},
            {"label": "未闭环", "value": sd["open_incidents"], "unit": "起"},
            {"label": "重大/紧急未闭环", "value": sd["critical_open"], "unit": "起"},
            {"label": "整改逾期", "value": sd["overdue_rectify"], "unit": "起"},
            {"label": "闭环率", "value": sd["closure_rate"], "unit": "%"},
            {"label": "未闭环隐患", "value": sd["hazard_open"], "unit": "项"},
        ], ["事件类型分布：" + "、".join(f"{k} {v['total']} 起（未闭环 {v['open']}）"
                                       for k, v in sd["by_type"].items())])
        if sd["critical_open"] or sd["overdue_rectify"]:
            warnings.append(f"安全：{sd['critical_open']} 起重大事件未闭环，{sd['overdue_rectify']} 起整改逾期。")
    else:
        sec("九、安全管理", {}, ["安全事件与隐患台账为空。"], True, ["安全数据"])

    # 十、项目管理
    if prj.get("data"):
        pd = prj["data"]
        sec("十、项目管理", pd, [
            {"label": "项目总数", "value": pd["total"], "unit": "个"},
            {"label": "在建项目", "value": pd["in_progress"], "unit": "个"},
            {"label": "延期项目", "value": pd["delayed"], "unit": "个"},
            {"label": "高风险项目", "value": pd["high_risk"], "unit": "个"},
            {"label": "已完成", "value": pd["completed"], "unit": "个"},
            {"label": "项目总投资", "value": pd["total_investment"], "unit": "元"},
            {"label": "预算执行率", "value": pd["budget_execution_rate"], "unit": "%",
             "basis": "实际成本 ÷ 批准预算"},
            {"label": "里程碑完成率", "value": pd["milestone_completion_rate"], "unit": "%"},
            {"label": "平均进度", "value": pd["avg_progress"], "unit": "%"},
        ], [
            f"管理方式分布：瀑布 {pd['by_management_method']['WATERFALL']} 个、"
            f"敏捷 {pd['by_management_method']['AGILE']} 个、混合 {pd['by_management_method']['HYBRID']} 个。",
            (f"延期项目：" + "、".join(f"{p['project_name']}（延期 {p['delay_days']} 天）"
                                       for p in pd["delayed_projects"][:5]) if pd["delayed_projects"] else "无延期项目。"),
        ])
        if pd["delayed"]:
            warnings.append(f"项目：{pd['delayed']} 个项目延期，{pd['high_risk']} 个高风险。")
    else:
        sec("十、项目管理", {}, ["项目数据为空或无项目权限。"], True, ["项目数据"])

    return {
        "report_type": "园区经营月报",
        "report_name": f"园智汇 · {label}园区经营月报",
        "period": label,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "generated_by": auth.user.real_name,
        "scope": {"park_id": park_id, "role": auth.role_label, "data_scope": auth.data_scope},
        "data_label": "演示数据",
        "executive_summary": {
            "highlights": highlights,
            "warnings": warnings,
            "warning_count": len(warnings),
        },
        "sections": sections,
        "evidence": {
            "data_source": "平台业务数据库",
            "tables": ["parks", "buildings", "spaces", "enterprises", "leasing_leads",
                       "contracts", "bills", "work_orders", "devices", "energy_records",
                       "safety_incidents", "projects"],
            "record_count": sum(1 for s in sections for m in s["metrics"]),
            "filters": {"park_id": park_id, "period": label},
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data_label": "演示数据",
        },
    }


def build_project_report(db: Session, project: Project, report_type: str = "WEEKLY") -> dict[str, Any]:
    diag = project_engine.diagnose_project(db, project)
    cpm = project_engine.compute_critical_path(db, project.id)
    sched = diag["schedule"]
    cost = diag["cost"]
    rk = diag["risk"]

    wbs = list(db.scalars(
        select(__import__("app.models", fromlist=["WbsItem"]).WbsItem)
        .where(__import__("app.models", fromlist=["WbsItem"]).WbsItem.project_id == project.id)
        .order_by(__import__("app.models", fromlist=["WbsItem"]).WbsItem.sort_order)).all())

    agile = None
    if project.management_method in ("AGILE", "HYBRID"):
        agile = project_engine.compute_agile_metrics(db, project.id)

    type_label = {"WEEKLY": "项目周报", "MONTHLY": "项目月报",
                  "RISK": "项目风险报告", "RETRO": "项目复盘报告"}.get(report_type, "项目报告")

    sections = [
        {
            "title": "一、项目概况",
            "metrics": [
                {"label": "项目编号", "value": project.project_code},
                {"label": "项目名称", "value": project.project_name},
                {"label": "管理方式", "value": {"WATERFALL": "瀑布式", "AGILE": "敏捷式",
                                                "HYBRID": "混合式"}[project.management_method]},
                {"label": "项目类型", "value": project.project_type},
                {"label": "项目经理", "value": project.project_manager_name},
                {"label": "项目状态", "value": project.status},
                {"label": "风险等级", "value": project.risk_level},
                {"label": "健康度", "value": diag["health"]},
                {"label": "计划周期", "value": f"{project.start_date} ~ {project.planned_end_date}"},
                {"label": "批准预算", "value": cost.get("budget", project.budget), "unit": "元"},
                {"label": "实际成本", "value": cost.get("actual_cost", project.actual_cost), "unit": "元"},
                {"label": "实际进度", "value": sched.get("actual_progress"), "unit": "%"},
                {"label": "计划进度", "value": sched.get("planned_progress"), "unit": "%"},
                {"label": "进度偏差", "value": sched.get("progress_variance"), "unit": "%"},
                {"label": "延期天数", "value": sched.get("delay_days"), "unit": "天"},
            ],
            "notes": [project.objective or "项目目标未填写。"],
        },
        {
            "title": "二、进度执行情况",
            "metrics": [
                {"label": "关键路径任务数", "value": cpm.get("critical_task_count", 0), "unit": "项"},
                {"label": "计划总工期", "value": cpm.get("project_duration_days", 0), "unit": "天"},
                {"label": "超期未完成任务", "value": len(sched.get("delayed_tasks", [])), "unit": "项"},
                {"label": "关键路径延期", "value": sched.get("critical_impact_days", 0), "unit": "天"},
                {"label": "里程碑完成率", "value": diag["milestone"]["completion_rate"], "unit": "%"},
            ],
            "notes": [
                "关键路径：" + " → ".join(cpm.get("critical_path", [])[:12]) if cpm.get("critical_path") else "未计算关键路径。",
                cpm.get("basis", ""),
                *[f"{i+1}. {t['wbs_code']} {t['item_name']}（超期 {t['delay_days']} 天，完成率 {t['progress']:.0f}%，"
                  f"{'关键路径' if t['is_critical'] else f'总时差 {t[chr(34)+chr(34)] if False else t.get(chr(115)+chr(108)+chr(97)+chr(99)+chr(107)+chr(95)+chr(100)+chr(97)+chr(121)+chr(115),0)} 天'}）"
                  for i, t in enumerate(sched.get("delayed_tasks", [])[:8])],
            ],
        },
        {
            "title": "三、成本执行情况",
            "metrics": [
                {"label": "批准预算", "value": cost.get("budget"), "unit": "元"},
                {"label": "合同金额", "value": cost.get("contract_amount"), "unit": "元"},
                {"label": "采购金额", "value": cost.get("purchase_amount"), "unit": "元"},
                {"label": "计划成本", "value": cost.get("planned_cost"), "unit": "元"},
                {"label": "实际成本", "value": cost.get("actual_cost"), "unit": "元"},
                {"label": "已支付", "value": cost.get("paid_amount"), "unit": "元"},
                {"label": "未支付", "value": cost.get("unpaid"), "unit": "元"},
                {"label": "预算执行率", "value": cost.get("execution_rate"), "unit": "%"},
                {"label": "挣值 EV", "value": cost.get("ev"), "unit": "元"},
                {"label": "计划价值 PV", "value": cost.get("pv"), "unit": "元"},
                {"label": "CPI", "value": cost.get("cpi"), "unit": "", "basis": "EV ÷ AC，<1 成本超支"},
                {"label": "SPI", "value": cost.get("spi"), "unit": "", "basis": "EV ÷ PV，<1 进度落后"},
                {"label": "预计完工成本 EAC", "value": cost.get("eac"), "unit": "元"},
                {"label": "完工偏差 VAC", "value": cost.get("vac"), "unit": "元"},
            ],
            "notes": ([cost["overspend_risk"]["basis"]] if cost.get("overspend_risk")
                      else (["成本执行情况正常。"] if cost.get("data_sufficient") else [cost.get("conclusion", "")])),
            "data_sufficient": cost.get("data_sufficient", True),
            "missing_data": cost.get("missing_data", []),
        },
        {
            "title": "四、风险管理",
            "metrics": [
                {"label": "风险总数", "value": len(rk.get("risks", [])), "unit": "条"},
                {"label": "平均风险分值", "value": rk.get("avg_score"), "unit": "分"},
                *[{"label": f"{k} 风险", "value": v, "unit": "条"}
                  for k, v in (rk.get("summary") or {}).items()],
                {"label": "AI 识别新增风险", "value": len(rk.get("ai_identified_risks", [])), "unit": "条"},
            ],
            "notes": ([f"[{r['level']}] {r['title']}：{r['detail']}（建议：{r['response']}）"
                       for r in rk.get("ai_identified_risks", [])] or
                      [rk.get("conclusion", "风险登记册为空。")]),
            "data_sufficient": rk.get("data_sufficient", True),
        },
        {
            "title": "五、变更管理",
            "metrics": [],
            "notes": [],
        },
    ]

    # 变更明细
    from app.models import ProjectChange

    changes = list(db.scalars(select(ProjectChange).where(ProjectChange.project_id == project.id)).all())
    sections[4]["metrics"] = [
        {"label": "变更总数", "value": len(changes), "unit": "条"},
        {"label": "待审批变更", "value": len([c for c in changes if c.status in ("PENDING", "IN_REVIEW")]), "unit": "条"},
        {"label": "已批准变更", "value": len([c for c in changes if c.status == "APPROVED"]), "unit": "条"},
        {"label": "累计工期影响", "value": sum(c.impact_schedule_days or 0 for c in changes if c.status == "APPROVED"), "unit": "天"},
        {"label": "累计成本影响", "value": round(sum(c.impact_cost or 0 for c in changes if c.status == "APPROVED"), 2), "unit": "元"},
    ]
    sections[4]["notes"] = ([
        f"{c.change_code}【{c.change_type}】{c.change_title}：工期+{c.impact_schedule_days or 0}天、"
        f"成本+{c.impact_cost or 0:,.0f}元，状态 {c.status}（申请人 {c.applicant_name}）"
        for c in changes] or ["本期无变更记录。"])

    if agile:
        sections.append({
            "title": "六、敏捷执行情况",
            "metrics": [
                {"label": "Sprint 数量", "value": len(agile["sprints"]), "unit": "个"},
                {"label": "Epic 数量", "value": len(agile["epics"]), "unit": "个"},
                {"label": "Feature 数量", "value": len(agile["features"]), "unit": "个"},
                {"label": "User Story 数量", "value": len(agile["stories"]), "unit": "条"},
                {"label": "总 Story Point", "value": agile["total_story_points"], "unit": "点"},
                {"label": "已完成 Story Point", "value": agile["done_story_points"], "unit": "点"},
                {"label": "平均 Velocity", "value": agile["velocity"], "unit": "点/迭代"},
                {"label": "Backlog 健康度", "value": agile["backlog_health"]},
            ],
            "notes": [
                "Sprint 详情：" + "；".join(
                    f"{s['sprint_name']}（{s['status']}，{s['done_points']}/{s['total_points']} 点，"
                    f"完成率 {s['completed_rate']}%）" for s in agile["sprints"]),
                agile["basis"],
            ],
            "data_sufficient": agile["data_sufficient"],
        })

    # 结论与建议
    suggestions: list[str] = []
    if sched.get("is_delayed"):
        suggestions.append(f"项目已延期 {sched.get('delay_days', 0)} 天，进度偏差 {sched.get('progress_variance')}%。"
                           + (f"关键路径延期 {sched['critical_impact_days']} 天，建议优先压缩关键任务工期。"
                              if sched.get("critical_impact_days") else "建议重排剩余工期并加强周度跟踪。"))
    if cost.get("overspend_risk"):
        suggestions.append(cost["overspend_risk"]["basis"] + " 建议开展成本专项复核。")
    if diag["milestone"]["delayed"]:
        suggestions.append(f"{diag['milestone']['delayed']} 个里程碑延期，建议重新核定里程碑计划。")
    if not suggestions:
        suggestions.append("项目进度、成本、风险均在可控范围，建议保持现有管理节奏。")

    return {
        "report_type": type_label,
        "report_name": f"{project.project_name} · {type_label}",
        "project_id": project.id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "management_method": project.management_method,
        "period": _period_label(None),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_label": "演示数据",
        "executive_summary": {
            "conclusion": diag["conclusion"],
            "health": diag["health"],
            "signals": diag["signals"],
            "suggestions": suggestions,
        },
        "sections": sections,
        "evidence": {
            "data_source": "平台业务数据库",
            "tables": ["projects", "wbs_items", "task_dependencies", "milestones",
                       "project_costs", "project_risks", "project_changes",
                       "epics", "features", "user_stories", "sprints", "sprint_tasks"],
            "record_count": len(wbs) + len(changes),
            "filters": {"project_id": project.id},
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data_label": "演示数据",
        },
    }

"""经营驾驶舱数据聚合服务。

所有 KPI 均由数据库实时计算，不硬编码。每个指标返回：
  value / unit / 同比(yoy) / 环比(mom) / 趋势(trend) / 计算口径(basis) / 数据状态(data_status)
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Integer, and_, case, cast, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import AGE_BUCKET_LABELS, AGE_BUCKETS
from app.core.security import AuthContext
from app.services import project_engine, safety_engine
from app.models import (
    Bill,
    Building,
    Contract,
    Device,
    Enterprise,
    EnergyRecord,
    Floor,
    LeasingLead,
    Notification,
    Park,
    Payment,
    Project,
    SafetyIncident,
    Space,
    Sprint,
    WbsItem,
    WorkOrder,
)


def _month_range(d: dt.date) -> tuple[dt.date, dt.date]:
    start = d.replace(day=1)
    nxt = (start + dt.timedelta(days=32)).replace(day=1)
    return start, nxt


def _shift_month(d: dt.date, months: int) -> dt.date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return dt.date(y, m, 1)


def _pct(cur: float, prev: float) -> float | None:
    if prev in (0, None):
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def _trend(shares_yoy: float | None) -> str:
    if shares_yoy is None:
        return "flat"
    if shares_yoy > 0.5:
        return "up"
    if shares_yoy < -0.5:
        return "down"
    return "flat"


def _kpi(key: str, label: str, value: Any, *, unit: str = "", yoy: float | None = None,
         mom: float | None = None, basis: str = "", target: float | None = None,
         data_status: str = "正常", link: str | None = None) -> dict[str, Any]:
    return {
        "key": key, "label": label, "value": value, "unit": unit,
        "yoy": yoy, "mom": mom, "trend": _trend(yoy if yoy is not None else mom),
        "basis": basis, "target": target, "data_status": data_status, "link": link,
    }


def _visible_park_ids(auth: AuthContext, db: Session) -> list[int]:
    vis = auth.visible_park_ids()
    if vis is None:
        return list(db.scalars(select(Park.id).order_by(Park.id)).all())
    return vis


def get_dashboard_summary(db: Session, auth: AuthContext, park_id: int | None = None,
                          building_id: int | None = None) -> dict[str, Any]:
    """按 集团 / 园区 / 楼宇 三种视角返回经营 KPI。"""
    today = dt.date.today()
    m_start, m_next = _month_range(today)
    lm_start = _shift_month(m_start, -1)
    # 同比口径 = 「去年同一个月」，而不是「往前 12 个月」。
    # 早期写成 ly_end = m_start，实际把 12 个自然月都算进「去年同期」，
    # 同比基数被放大约 12 倍，所有 yoy 都变成 -9x% 的荒谬值。
    ly_start = _shift_month(m_start, -12)
    ly_end = _shift_month(m_next, -12)
    y_start = dt.date(today.year, 1, 1)

    park_ids = _visible_park_ids(auth, db)
    if park_id is not None:
        park_ids = [pid for pid in park_ids if pid == park_id]
    scope_label = "集团" if park_id is None and auth.is_group_admin else (
        f"园区" if park_id else "授权范围")

    # ---------- 空间集合 ----------
    space_q = select(Space).where(Space.park_id.in_(park_ids)) if park_ids else select(Space).where(Space.id == -1)
    if building_id:
        space_q = space_q.where(Space.building_id == building_id)
    spaces = list(db.scalars(space_q).all())
    rentable = [s for s in spaces if s.space_type != "PARKING"]
    total_rentable_area = sum(s.rentable_area or s.area or 0 for s in rentable)
    total_space_count = len(rentable)
    rented = [s for s in rentable if s.status == "RENTED"]
    rented_area = sum(s.rentable_area or s.area or 0 for s in rented)
    available = [s for s in rentable if s.status == "AVAILABLE"]
    available_area = sum(s.rentable_area or s.area or 0 for s in available)
    occupancy_rate = round(rented_area / total_rentable_area * 100, 2) if total_rentable_area else 0.0
    space_occupancy_rate = round(len(rented) / total_space_count * 100, 2) if total_space_count else 0.0

    # ---------- 企业 ----------
    ent_q = select(Enterprise).where(Enterprise.park_id.in_(park_ids)) if park_ids else select(Enterprise).where(Enterprise.id == -1)
    enterpriss = list(db.scalars(ent_q).all())
    settled = [e for e in enterpriss if e.status in ("SETTLED", "GROWING", "RISK")]
    exited = [e for e in enterpriss if e.status == "EXITED"]
    risk_ent = [e for e in enterpriss if e.status == "RISK" or e.risk_level in ("HIGH", "CRITICAL")]
    # 入驻率 = 已入驻企业数 / 可容纳企业数（按可租面积 / 户均面积 1000 ㎡ 估算容量）
    capacity = int(total_rentable_area / 1000) if total_rentable_area else 0
    settle_rate = round(len(settled) / capacity * 100, 2) if capacity else 0.0

    # ---------- 招商 ----------
    lead_q = select(LeasingLead).where(LeasingLead.park_id.in_(park_ids)) if park_ids else select(LeasingLead).where(LeasingLead.id == -1)
    leads = list(db.scalars(lead_q).all())
    active_leads = [x for x in leads if x.stage not in ("SIGNED", "SETTLED", "LOST")]
    signed_leads = [x for x in leads if x.stage in ("SIGNED", "SETTLED")]
    lost_leads = [x for x in leads if x.stage == "LOST"]
    # 招商转化率 = 签约线索数 / (已进入有效商机及以后的线索数)
    matured = [x for x in leads if x.stage not in ("LEAD", "LOST")]
    conv_rate = round(len(signed_leads) / len(matured) * 100, 2) if matured else 0.0

    funnel_stages = ["LEAD", "CONTACTED", "QUALIFIED", "SITE_VISIT", "NEGOTIATION",
                     "CONTRACT_APPROVAL", "SIGNED", "SETTLED"]
    funnel_names = {
        "LEAD": "潜在线索", "CONTACTED": "已联系", "QUALIFIED": "有效商机",
        "SITE_VISIT": "实地看房", "NEGOTIATION": "商务谈判",
        "CONTRACT_APPROVAL": "合同审批", "SIGNED": "签约", "SETTLED": "入驻",
    }
    funnel = []
    for st in funnel_stages:
        cnt = len([x for x in leads if x.stage == st])
        # 到达该阶段及之后的数量（漏斗递减口径）
        idx = funnel_stages.index(st)
        reached = len([x for x in leads if x.stage in funnel_stages[idx:] and x.stage != "LOST"])
        funnel.append({"stage": st, "stage_name": funnel_names[st], "count": cnt, "reached": reached})

    # ---------- 合同 ----------
    c_q = select(Contract).where(Contract.park_id.in_(park_ids)) if park_ids else select(Contract).where(Contract.id == -1)
    if building_id:
        c_q = c_q.where(Contract.building_id == building_id)
    contracts = list(db.scalars(c_q).all())
    active_contracts = [c for c in contracts if c.status in ("ACTIVE", "EXPIRING")]
    expiring_90 = [c for c in active_contracts
                   if c.end_date and today <= c.end_date <= today + dt.timedelta(days=90)]
    expiring_30 = [c for c in expiring_90 if c.end_date <= today + dt.timedelta(days=30)]

    # ---------- 收费 ----------
    # 账单是全库最大的表（3.5 万行）。这里需要的全是标量汇总，
    # 因此全部下推到 SQL 聚合（配合 bill_date 索引），
    # 不再把整表取回 Python 过滤 —— 旧写法占本函数约 65% 的耗时。
    open_status = ("UNPAID", "PARTIAL", "OVERDUE")

    def bill_sum(expr, *conds) -> float:
        q = select(func.coalesce(func.sum(expr), 0.0))
        q = q.where(Bill.park_id.in_(park_ids)) if park_ids else q.where(Bill.id == -1)
        for c in conds:
            q = q.where(c)
        return round(float(db.scalar(q) or 0.0), 2)

    cur_receivable = bill_sum(Bill.receivable, Bill.bill_date >= m_start, Bill.bill_date < m_next)
    cur_received = bill_sum(Bill.received, Bill.bill_date >= m_start, Bill.bill_date < m_next)
    lm_received = bill_sum(Bill.received, Bill.bill_date >= lm_start, Bill.bill_date < m_start)
    ly_received = bill_sum(Bill.received, Bill.bill_date >= ly_start, Bill.bill_date < ly_end)

    arrears_total = bill_sum(Bill.arrears, Bill.status.in_(open_status))
    # 已逾期口径以账龄桶为准：PARTIAL（部分收款但已过到期日）同样属于逾期，
    # 只看 status == "OVERDUE" 会漏掉一半以上（2536 万 vs 4101 万）。
    arrears_overdue = bill_sum(Bill.arrears, Bill.status.in_(open_status),
                               Bill.age_bucket != "NORMAL")

    # 「已到期账单」口径：已过到期日、应收非空、且账期不晚于下月
    due_conds = (Bill.due_date <= today, Bill.receivable > 0, Bill.bill_date <= m_next)
    due_receivable = bill_sum(Bill.receivable, *due_conds)
    due_received = bill_sum(Bill.received, *due_conds)
    collection_rate = round(due_received / due_receivable * 100, 2) if due_receivable else 0.0

    ytd_income = bill_sum(Bill.received, Bill.bill_date >= y_start, Bill.bill_date <= today)

    # ---------- 工单 ----------
    w_q = select(WorkOrder).where(WorkOrder.park_id.in_(park_ids)) if park_ids else select(WorkOrder).where(WorkOrder.id == -1)
    if building_id:
        w_q = w_q.where(WorkOrder.building_id == building_id)
    orders = list(db.scalars(w_q).all())
    closed_orders = [o for o in orders if o.status in ("CLOSED", "RATED")]
    wo_rate = round(len(closed_orders) / len(orders) * 100, 2) if orders else 0.0
    timeout_orders = [o for o in orders if o.is_timeout and o.status not in ("CLOSED", "RATED")]

    # ---------- 设备 ----------
    d_q = select(Device).where(Device.park_id.in_(park_ids)) if park_ids else select(Device).where(Device.id == -1)
    if building_id:
        d_q = d_q.where(Device.building_id == building_id)
    devices = list(db.scalars(d_q).all())
    online = [d for d in devices if d.is_online and d.status != "SCRAPPED"]
    device_online_rate = round(len(online) / len([d for d in devices if d.status != "SCRAPPED"]) * 100, 2) if devices else 0.0
    fault_devices = [d for d in devices if d.status == "FAULT"]
    maintain_due = [d for d in devices if d.next_maintain_date and d.next_maintain_date <= today + dt.timedelta(days=15)]

    # ---------- 能耗 ----------
    e_q = select(EnergyRecord.__table__)
    e_q = e_q.where(EnergyRecord.park_id.in_(park_ids)) if park_ids else e_q.where(EnergyRecord.id == -1)
    if building_id:
        e_q = e_q.where(EnergyRecord.building_id == building_id)
    energies = db.execute(e_q).all()
    cur_energy = [e for e in energies if e.record_date and m_start <= e.record_date < m_next]
    lm_energy = [e for e in energies if e.record_date and lm_start <= e.record_date < m_start]
    ly_energy = [e for e in energies if e.record_date and ly_start <= e.record_date < ly_end]

    def _energy_kwh(items):
        return round(sum(e.consumption or 0 for e in items if e.energy_type == "ELECTRICITY"), 2)

    cur_kwh = _energy_kwh(cur_energy)
    lm_kwh = _energy_kwh(lm_energy)
    ly_kwh = _energy_kwh(ly_energy)
    carbon = round(sum(e.carbon_kg or 0 for e in cur_energy), 2)
    energy_anomalies = [e for e in energies if e.is_anomaly and e.record_date and e.record_date >= today - dt.timedelta(days=30)]
    unit_energy = round(cur_kwh / total_rentable_area, 3) if total_rentable_area else None

    # ---------- 安全 ----------
    s_q = select(SafetyIncident).where(SafetyIncident.park_id.in_(park_ids)) if park_ids else select(SafetyIncident).where(SafetyIncident.id == -1)
    if building_id:
        s_q = s_q.where(SafetyIncident.building_id == building_id)
    incidents = list(db.scalars(s_q).all())
    open_incidents = [i for i in incidents if i.status not in ("CLOSED",)]
    critical_incidents = [i for i in incidents if i.risk_level in ("CRITICAL", "URGENT") and i.status != "CLOSED"]
    closed_incidents = [i for i in incidents if i.status == "CLOSED"]
    # 安全指数：走单一数据源（与安全页面、安全AI 同口径）
    safety = safety_engine.summary(incidents)
    safety_score = safety["safety_score"]
    safety_status = safety["safety_status"]

    # ---------- 项目 ----------
    p_q = select(Project).where(Project.park_id.in_(park_ids)) if park_ids else select(Project).where(Project.id == -1)
    proj_vis = auth.visible_project_ids()
    projects = list(db.scalars(p_q).all())
    if proj_vis is not None:
        projects = [p for p in projects if p.id in proj_vis]
    proj_in_progress = [p for p in projects if p.status == "IN_PROGRESS"]
    proj_delayed = [p for p in projects if p.status == "DELAYED" or (
        p.planned_end_date and p.planned_end_date < today and p.status not in ("COMPLETED", "CLOSED"))]
    proj_high_risk = [p for p in projects if p.risk_level in ("HIGH", "CRITICAL")]
    proj_completed = [p for p in projects if p.status in ("COMPLETED", "CLOSED")]
    total_budget = round(sum(p.approved_budget or p.budget or 0 for p in projects), 2)
    total_actual = round(sum(p.actual_cost or 0 for p in projects), 2)
    budget_exec_rate = round(total_actual / total_budget * 100, 2) if total_budget else 0.0
    avg_progress = round(sum(p.progress or 0 for p in projects) / len(projects), 2) if projects else 0.0
    # 里程碑以 milestones 表实时聚合：projects.milestone_total / milestone_done
    # 两个冗余列从未被写入（恒为 0），用它会让达成率永远显示 0%。
    ms_map = project_engine.milestone_stats(db, [p.id for p in projects])
    ms_total = sum(t for t, _ in ms_map.values())
    ms_done = sum(d for _, d in ms_map.values())
    ms_rate = round(ms_done / ms_total * 100, 2) if ms_total else 0.0
    waterfall_cnt = len([p for p in projects if p.management_method == "WATERFALL"])
    agile_cnt = len([p for p in projects if p.management_method == "AGILE"])
    hybrid_cnt = len([p for p in projects if p.management_method == "HYBRID"])

    sprints = list(db.scalars(select(Sprint).where(Sprint.project_id.in_([p.id for p in projects or []]))).all()) if projects else []
    sprint_rate = round(sum(s.completed_rate or 0 for s in sprints) / len(sprints), 2) if sprints else 0.0

    # ---------- 园区数量 ----------
    park_count = len(park_ids)

    # ================= KPI 列表 =================
    kpis: list[dict[str, Any]] = [
        _kpi("park_count", "园区数量", park_count, unit="个",
             basis="授权范围内的园区总数", link="/space"),
        _kpi("enterprise_count", "企业数量", len(enterpriss), unit="家",
             basis=f"园区档案中全部企业（含潜在/意向/入驻/退出）；其中入驻 {len(settled)} 家，退出 {len(exited)} 家",
             link="/enterprise"),
        _kpi("settle_rate", "企业入驻率", settle_rate, unit="%", target=85,
             basis=f"已入驻企业 {len(settled)} 家 ÷ 可容纳企业数 {capacity} 家（按可租面积 {total_rentable_area:,.0f} ㎡ ÷ 户均 1000 ㎡ 估算）",
             data_status="正常" if capacity else "数据不足：缺少可租面积数据", link="/space"),
        _kpi("occupancy_rate", "空间出租率", occupancy_rate, unit="%", target=90,
             basis=f"已出租面积 {rented_area:,.0f} ㎡ ÷ 可租面积 {total_rentable_area:,.0f} ㎡", link="/space"),
        _kpi("available_area", "可招商面积", round(available_area, 2), unit="㎡",
             basis=f"{len(available)} 个状态为「可租」的空间面积合计", link="/space"),
        _kpi("lead_count", "招商线索数量", len(active_leads), unit="条",
             basis=f"招商漏斗中处于「潜在线索~合同审批」阶段的线索 {len(active_leads)} 条（累计线索 {len(leads)} 条）",
             link="/leasing"),
        _kpi("conversion_rate", "招商转化率", conv_rate, unit="%", target=30,
             basis=f"已签约线索 {len(signed_leads)} 条 ÷ 已进入有效商机及以后的线索 {len(matured)} 条"
                   + (f"；流失 {len(lost_leads)} 条" if lost_leads else ""), link="/leasing"),
        _kpi("contract_expiring", "90天内合同到期", len(expiring_90), unit="份",
             basis=f"生效中合同 {len(active_contracts)} 份中，到期日在 90 天内（其中 30 天内 {len(expiring_30)} 份）"
                   if len(expiring_30) else f"生效中合同 {len(active_contracts)} 份中，到期日在 90 天内",
             data_status="提醒" if expiring_30 else "正常", link="/contract"),
        _kpi("collection_rate", "租金收缴率", collection_rate, unit="%", target=95,
             basis=f"已到期账单应收 {due_receivable:,.0f} 元中实收 "
                   f"{due_received:,.0f} 元", link="/finance"),
        _kpi("arrears_amount", "欠费金额", arrears_total, unit="元",
             basis=f"全部未结清账单欠费合计；其中已逾期欠费 {arrears_overdue:,.0f} 元",
             data_status="风险" if arrears_overdue else "正常", link="/finance"),
        _kpi("work_order_rate", "工单完成率", wo_rate, unit="%", target=95,
             basis=f"已关闭/已评价工单 {len(closed_orders)} 张 ÷ 工单总数 {len(orders)} 张"
                   + (f"；超时未完成 {len(timeout_orders)} 张" if timeout_orders else ""), link="/property"),
        _kpi("device_online_rate", "设备在线率", device_online_rate, unit="%", target=98,
             basis=f"在线且未报废设备 {len(online)} 台 ÷ 设备总数 {len([d for d in devices if d.status != 'SCRAPPED'])} 台"
                   + (f"；故障 {len(fault_devices)} 台" if fault_devices else ""),
             data_status="风险" if fault_devices else "正常", link="/device"),
        _kpi("energy_total", "本月园区总能耗", cur_kwh, unit="kWh",
             yoy=_pct(cur_kwh, ly_kwh), mom=_pct(cur_kwh, lm_kwh),
             basis=f"本月电耗合计；用电记录 "
                   f"{len([e for e in cur_energy if e.energy_type == 'ELECTRICITY'])} 条"
                   + (f"；单位面积能耗 {unit_energy} kWh/㎡" if unit_energy else ""),
             link="/energy"),
        _kpi("safety_risk", "安全风险数量", len(open_incidents), unit="项",
             basis=f"未闭环安全事件 {len(open_incidents)} 项（其中重大/紧急 {len(critical_incidents)} 项）；"
                   f"安全指数 {safety_score} 分（{safety_status}）",
             data_status="重大" if critical_incidents else ("风险" if open_incidents else "正常"), link="/safety"),
        _kpi("project_active", "在建项目数量", len(proj_in_progress), unit="个",
             basis=f"状态为「进行中」的项目 {len(proj_in_progress)} 个；项目总数 {len(projects)} 个", link="/project"),
        _kpi("project_delayed", "延期项目数量", len(proj_delayed), unit="个",
             basis=f"已过计划结束日期但未完成的项目 {len(proj_delayed)} 个"
                   + (f"；其中高风险 {len(proj_high_risk)} 个" if proj_high_risk else ""),
             data_status="风险" if proj_delayed else "正常", link="/project"),
        _kpi("budget_execution", "项目预算执行率", budget_exec_rate, unit="%", target=95,
             basis=f"项目实际成本 {total_actual:,.0f} 元 ÷ 批准预算 {total_budget:,.0f} 元"
                   + ("；尚无预算数据" if not total_budget else ""),
             data_status="数据不足：项目未登记预算" if not total_budget else "正常", link="/project"),
        _kpi("monthly_income", "本月经营收入", cur_received, unit="元",
             yoy=_pct(cur_received, ly_received), mom=_pct(cur_received, lm_received),
             basis=f"本月账单实收合计（应收 {cur_receivable:,.0f} 元）；年度累计 {ytd_income:,.0f} 元", link="/finance"),
    ]

    # ================= 图表数据 =================
    # 招商趋势（近 12 个月新增线索 / 签约）
    trend_months = [_shift_month(m_start, -i) for i in range(11, -1, -1)]
    lead_trend = []
    for ms in trend_months:
        me = _shift_month(ms, 1)
        new_leads = len([x for x in leads if x.created_at and ms <= x.created_at.date() < me])
        new_sign = len([x for x in leads if x.stage in ("SIGNED", "SETTLED") and x.updated_at and ms <= x.updated_at.date() < me])
        lead_trend.append({"month": f"{ms.year}-{ms.month:02d}", "leads": new_leads,
                           "signs": new_sign,
                           "conversion": round(new_sign / new_leads * 100, 1) if new_leads else 0.0})

    # 企业结构（按行业 + 按状态）
    industry_map: dict[str, int] = {}
    for e in enterpriss:
        k = e.industry or "未填写"
        industry_map[k] = industry_map.get(k, 0) + 1
    industry_dist = [{"name": k, "value": v} for k, v in
                     sorted(industry_map.items(), key=lambda x: -x[1])][:12]
    status_names = {"POTENTIAL": "潜在企业", "INTENT": "意向企业", "SIGNED": "签约企业",
                    "SETTLED": "入驻企业", "GROWING": "成长企业", "RISK": "风险企业", "EXITED": "退园企业"}
    status_dist = []
    for k, name in status_names.items():
        cnt = len([e for e in enterpriss if e.status == k])
        if cnt:
            status_dist.append({"name": name, "value": cnt, "key": k})

    # 空间出租（按楼栋）
    buildings = list(db.scalars(
        select(Building).where(Building.park_id.in_(park_ids)).order_by(Building.id)
    ).all()) if park_ids else []
    space_by_building = []
    for b in buildings:
        bs = [s for s in rentable if s.building_id == b.id]
        b_area = sum(s.rentable_area or s.area or 0 for s in bs)
        b_rented = sum(s.rentable_area or s.area or 0 for s in bs if s.status == "RENTED")
        b_vacant = sum(s.rentable_area or s.area or 0 for s in bs if s.status == "AVAILABLE")
        space_by_building.append({
            "building_id": b.id, "building_name": b.building_name,
            "space_count": len(bs),
            "rentable_area": round(b_area, 2),
            "rented_area": round(b_rented, 2),
            "vacant_area": round(b_vacant, 2),
            "occupancy_rate": round(b_rented / b_area * 100, 2) if b_area else 0.0,
            "enterprise_count": len(set(s.enterprise_id for s in bs if s.enterprise_id)),
            "build_area": b.build_area,
            "map_x": b.map_x, "map_y": b.map_y, "map_w": b.map_w, "map_d": b.map_d, "map_h": b.map_h,
            "status": b.status,
        })

    # 项目风险分布
    risk_names = {"LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "重大"}
    proj_risk_dist = [{"name": risk_names[k], "key": k,
                       "value": len([p for p in projects if p.risk_level == k])}
                      for k in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
                      if len([p for p in projects if p.risk_level == k])]
    proj_status_names = {"PLANNED": "计划中", "IN_PROGRESS": "进行中", "ON_HOLD": "暂停",
                         "DELAYED": "延期", "COMPLETED": "已完成", "CLOSED": "已关闭"}
    proj_status_dist = [{"name": proj_status_names[k], "key": k,
                         "value": len([p for p in projects if p.status == k])}
                        for k in proj_status_names if len([p for p in projects if p.status == k])]

    # 能源趋势（近 12 个月，按能源类型）
    energy_trend = []
    for ms in trend_months:
        me = _shift_month(ms, 1)
        row = {"month": f"{ms.year}-{ms.month:02d}"}
        for et, lab in [("ELECTRICITY", "电"), ("WATER", "水"), ("GAS", "气"), ("PV", "光伏")]:
            row[et] = round(sum(e.consumption or 0 for e in energies
                                if e.energy_type == et and e.record_date and ms <= e.record_date < me), 2)
        row["carbon"] = round(sum(e.carbon_kg or 0 for e in energies
                                  if e.record_date and ms <= e.record_date < me), 2)
        energy_trend.append(row)

    # 财务趋势（近 12 个月 应收/实收/欠费）—— 按月下推 SQL 聚合
    finance_trend = []
    for ms in trend_months:
        me = _shift_month(ms, 1)
        in_month = (Bill.bill_date >= ms, Bill.bill_date < me)
        finance_trend.append({
            "month": f"{ms.year}-{ms.month:02d}",
            "receivable": bill_sum(Bill.receivable, *in_month),
            "received": bill_sum(Bill.received, *in_month),
            "arrears": bill_sum(Bill.arrears, *in_month),
            "overdue": bill_sum(Bill.arrears, *in_month, Bill.status == "OVERDUE"),
        })

    # 工单趋势（近 12 个月）
    wo_trend = []
    for ms in trend_months:
        me = _shift_month(ms, 1)
        mo = [o for o in orders if o.submit_at and ms <= o.submit_at.date() < me]
        wo_trend.append({
            "month": f"{ms.year}-{ms.month:02d}",
            "total": len(mo),
            "closed": len([o for o in mo if o.status in ("CLOSED", "RATED")]),
            "timeout": len([o for o in mo if o.is_timeout]),
        })

    # 安全事件分布
    inc_type_names = {"安全生产": "安全生产", "消防": "消防", "隐患": "隐患", "危险源": "危险源",
                      "应急": "应急", "门禁": "门禁", "访客": "访客", "车辆": "车辆", "视频事件": "视频事件"}
    safety_dist = []
    for k, name in inc_type_names.items():
        cnt = len([i for i in incidents if i.incident_type == k])
        if cnt:
            safety_dist.append({"name": name, "value": cnt})
    safety_status_dist = [{"name": "已闭环", "key": "CLOSED", "value": len(closed_incidents)},
                          {"name": "处理中", "key": "OTHER", "value": len(open_incidents)}]

    # 欠费账龄
    # 欠费账龄：直接用 bills.age_bucket 的真实取值分桶（见 core/enums.AGE_BUCKETS）。
    # 旧代码硬编码 '0-30'/'31-60'/'61-90'/'90+' 四个键，与库内取值完全不交集，
    # 导致账龄分布图四项恒为 0（约 4100 万欠费凭空消失）。
    arrears_age = [
        {"name": AGE_BUCKET_LABELS[k], "key": k,
         "value": bill_sum(Bill.arrears, Bill.status.in_(open_status), Bill.age_bucket == k)}
        for k in AGE_BUCKETS
    ]

    # ---------- 数据状态说明 ----------
    data_status_notes: list[str] = []
    if not total_budget:
        data_status_notes.append("项目管理：尚未登记预算，预算执行率不可计算。")
    if not energies:
        data_status_notes.append("能源管理：能耗设备尚未接入，能耗数据缺失。")
    if not any(e.annual_revenue for e in enterpriss):
        data_status_notes.append("企业档案：缺少企业经营数据，无法判断企业经营风险。")
    if not devices:
        data_status_notes.append("设备管理：未登记设备台账。")

    return {
        "scope": {
            "level": "BUILDING" if building_id else ("PARK" if park_id else ("GROUP" if auth.is_group_admin else "AUTHORIZED")),
            "label": scope_label,
            "park_id": park_id,
            "building_id": building_id,
            "park_ids": park_ids,
        },
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_label": "演示数据",
        "kpis": kpis,
        "charts": {
            "funnel": funnel,
            "lead_trend": lead_trend,
            "industry_dist": industry_dist,
            "status_dist": status_dist,
            "space_by_building": space_by_building,
            "project_risk_dist": proj_risk_dist,
            "project_status_dist": proj_status_dist,
            "energy_trend": energy_trend,
            "finance_trend": finance_trend,
            "work_order_trend": wo_trend,
            "safety_dist": safety_dist,
            "safety_status_dist": safety_status_dist,
            "arrears_age": arrears_age,
        },
        "summary": {
            "park_count": park_count,
            "building_count": len(buildings),
            "total_rentable_area": round(total_rentable_area, 2),
            "rented_area": round(rented_area, 2),
            "vacant_area": round(available_area, 2),
            "enterprise_settled": len(settled),
            "enterprise_risk": len(risk_ent),
            "active_contracts": len(active_contracts),
            "collection_rate": collection_rate,
            "project_total": len(projects),
            "waterfall_count": waterfall_cnt,
            "agile_count": agile_cnt,
            "hybrid_count": hybrid_cnt,
            "avg_project_progress": avg_progress,
            "milestone_completion_rate": ms_rate,
            "sprint_completion_rate": sprint_rate,
            "safety_score": safety_score,
            "safety_status": safety_status,
            "energy_anomaly_count": len(energy_anomalies),
            "device_maintain_due": len(maintain_due),
            "unit_energy": unit_energy,
        },
        "data_status_notes": data_status_notes,
    }


def get_building_detail(db: Session, auth: AuthContext, building_id: int) -> dict[str, Any] | None:
    """一楼一档。"""
    b = db.get(Building, building_id)
    if not b or not auth.can_access_park(b.park_id):
        return None
    today = dt.date.today()
    spaces = list(db.scalars(select(Space).where(Space.building_id == building_id)).all())
    rentable = [s for s in spaces if s.space_type != "PARKING"]
    rented = [s for s in rentable if s.status == "RENTED"]
    total_area = sum(s.rentable_area or s.area or 0 for s in rentable)
    rented_area = sum(s.rentable_area or s.area or 0 for s in rented)

    floors = list(db.scalars(
        select(Floor).where(Floor.building_id == building_id).order_by(Floor.floor_number)
    ).all())
    floor_data = []
    for f in floors:
        fs = [s for s in rentable if s.floor_id == f.id]
        fa = sum(s.rentable_area or s.area or 0 for s in fs)
        fr = sum(s.rentable_area or s.area or 0 for s in fs if s.status == "RENTED")
        ent_ids = {s.enterprise_id for s in fs if s.enterprise_id}
        fc = len([c for c in db.scalars(select(Contract).where(Contract.building_id == building_id,
                                                               Contract.status.in_(["ACTIVE", "EXPIRING"]))).all()])
        wo = list(db.scalars(select(WorkOrder).where(WorkOrder.building_id == building_id)).all())
        f_wo = [o for o in wo if o.space_id in {s.id for s in fs}]
        e_consumption = sum(e.consumption or 0 for e in db.scalars(
            select(EnergyRecord).where(EnergyRecord.building_id == building_id,
                                       EnergyRecord.energy_type == "ELECTRICITY")).all())
        floor_data.append({
            "floor_id": f.id, "floor_name": f.floor_name, "floor_number": f.floor_number,
            "build_area": f.build_area, "rentable_area": round(fa, 2),
            "space_count": len(fs), "rented_count": len([s for s in fs if s.status == "RENTED"]),
            "enterprise_count": len(ent_ids),
            "occupancy_rate": round(fr / fa * 100, 2) if fa else 0.0,
            "work_order_count": len(f_wo),
            "status": f.status, "usage": f.usage,
        })

    contracts = list(db.scalars(select(Contract).where(Contract.building_id == building_id).order_by(Contract.end_date)).all())
    work_orders = list(db.scalars(select(WorkOrder).where(WorkOrder.building_id == building_id).order_by(WorkOrder.submit_at.desc())).all())
    devices = list(db.scalars(select(Device).where(Device.building_id == building_id)).all())
    projects = list(db.scalars(select(Project).where(Project.park_id == b.park_id)).all())
    b_projects = [p for p in projects if b.building_name.split("#")[0].strip()[:2] and
                  (b.building_name.split("#")[0].strip() in (p.project_name or ""))]

    energy_month = round(sum(e.consumption or 0 for e in db.scalars(
        select(EnergyRecord).where(EnergyRecord.building_id == building_id,
                                   EnergyRecord.energy_type == "ELECTRICITY",
                                   EnergyRecord.record_date >= today - dt.timedelta(days=30))).all()), 2)

    incidents = [i for i in db.scalars(select(SafetyIncident).where(SafetyIncident.building_id == building_id)).all()
                 if i.status != "CLOSED"]

    ent_ids = {s.enterprise_id for s in rentable if s.enterprise_id}
    enterprises = list(db.scalars(select(Enterprise).where(Enterprise.id.in_(ent_ids))).all()) if ent_ids else []

    return {
        "building": {
            "id": b.id, "building_code": b.building_code, "building_name": b.building_name,
            "building_type": b.building_type, "park_id": b.park_id,
            "floor_count": b.floor_count, "underground_floors": b.underground_floors,
            "build_area": b.build_area, "rentable_area": b.rentable_area,
            "completion_date": b.completion_date.isoformat() if b.completion_date else None,
            "property_manager": b.property_manager, "status": b.status,
            "map_x": b.map_x, "map_y": b.map_y, "map_w": b.map_w, "map_d": b.map_d, "map_h": b.map_h,
        },
        "kpi": {
            "space_count": len(rentable),
            "rented_count": len(rented),
            "rentable_area": round(total_area, 2),
            "rented_area": round(rented_area, 2),
            "vacant_area": round(total_area - rented_area, 2),
            "occupancy_rate": round(rented_area / total_area * 100, 2) if total_area else 0.0,
            "enterprise_count": len(enterprises),
            "contract_count": len([c for c in contracts if c.status in ("ACTIVE", "EXPIRING")]),
            "contract_expiring": len([c for c in contracts if c.end_date and today <= c.end_date <= today + dt.timedelta(days=90)]),
            "work_order_open": len([o for o in work_orders if o.status not in ("CLOSED", "RATED")]),
            "device_count": len(devices),
            "device_fault": len([d for d in devices if d.status == "FAULT"]),
            "energy_month": energy_month,
            "risk_count": len(incidents),
            "project_count": len(b_projects),
        },
        "floors": floor_data,
        "spaces": [{
            "id": s.id, "space_code": s.space_code, "space_name": s.space_name,
            "space_type": s.space_type, "status": s.status, "area": s.area,
            "rentable_area": s.rentable_area, "rent_price": s.rent_price,
            "enterprise_id": s.enterprise_id,
            "enterprise_name": next((e.enterprise_name for e in enterprises if e.id == s.enterprise_id), None),
            "lease_start": s.lease_start.isoformat() if s.lease_start else None,
            "lease_end": s.lease_end.isoformat() if s.lease_end else None,
            "vacant_days": (today - s.vacant_since).days if s.vacant_since else None,
        } for s in rentable],
        "contracts": [{"id": c.id, "contract_code": c.contract_code, "contract_name": c.contract_name,
                       "enterprise_name": c.enterprise_name, "end_date": c.end_date.isoformat() if c.end_date else None,
                       "monthly_rent": c.monthly_rent, "status": c.status,
                       "space_name": c.space_name} for c in contracts],
        "work_orders": [{"id": o.id, "order_code": o.order_code, "title": o.title,
                         "order_type": o.order_type, "status": o.status, "priority": o.priority,
                         "submit_at": o.submit_at.isoformat() if o.submit_at else None,
                         "is_timeout": o.is_timeout} for o in work_orders[:20]],
        "devices": [{"id": d.id, "device_code": d.device_code, "device_name": d.device_name,
                     "device_type": d.device_type, "status": d.status, "health_score": d.health_score,
                     "next_maintain_date": d.next_maintain_date.isoformat() if d.next_maintain_date else None}
                    for d in devices],
        "enterprises": [{"id": e.id, "enterprise_name": e.enterprise_name, "industry": e.industry,
                         "status": e.status, "employee_count": e.employee_count,
                         "leased_area": e.leased_area} for e in enterprises],
        "risks": [{"id": i.id, "title": i.title, "risk_level": i.risk_level, "status": i.status,
                   "incident_type": i.incident_type} for i in incidents],
        "data_label": "演示数据",
    }

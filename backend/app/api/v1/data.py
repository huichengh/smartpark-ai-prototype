"""数据中心路由。

覆盖：数据资产目录、数据上传与质量校验、数据质量报告、数据血缘与口径说明。
所有统计均由数据库实时聚合（GROUP BY / COUNT），不在前端硬编码。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.core.audit import write_audit
from app.core.security import CurrentAuth, DbSession
from app.schemas.common import paginate
from app.models import (
    Bill,
    Building,
    Contract,
    DataQualityIssue,
    DataQualityReport,
    DataUpload,
    Device,
    EnergyRecord,
    Enterprise,
    LeasingLead,
    Park,
    Payment,
    Project,
    SafetyHazard,
    SafetyIncident,
    ServiceRequest,
    Space,
    SprintTask,
    User,
    WbsItem,
    WorkOrder,
)

router = APIRouter(prefix="/data", tags=["数据中心"])

# 数据资产目录：模型 → (中文名, 归属于哪个「主题域」, 主表业务口径说明)
ASSET_CATALOG: list[tuple[Any, str, str, str]] = [
    (Park, "园区主数据", "空间资产", "园区基础档案，含面积、楼宇数、运营模式"),
    (Building, "楼宇档案", "空间资产", "楼宇层数、可租面积、数字孪生坐标"),
    (Space, "空间单元", "空间资产", "房间/铺位级单元，含可租面积、租金单价、实时状态"),
    (Enterprise, "企业档案", "企业服务", "入驻企业工商信息、行业、人数、联系人"),
    (Contract, "租赁合同", "合同财务", "合同期限、面积、月租金、免租期、付款日"),
    (Bill, "应收账单", "合同财务", "按合同月费月化生成的应收账单，含逾期账龄"),
    (Payment, "收款流水", "合同财务", "实际到账记录，用于核销账单与计算收缴率"),
    (LeasingLead, "招商线索", "招商运营", "线索来源渠道、意向面积、阶段、赢单概率"),
    (Project, "项目主档", "项目管理", "项目基线、预算、进度、健康度"),
    (WbsItem, "WBS 任务", "项目管理", "WBS 分解项，含关键路径标识与浮动时间"),
    (SprintTask, "敏捷任务", "项目管理", "看板任务，含所在列、故事点、经办人"),
    (WorkOrder, "服务工单", "物业运维", "报修工单，含优先级、响应时长、SLA 判定"),
    (Device, "设备台账", "物业运维", "设备健康度、下次保养日期"),
    (EnergyRecord, "能耗记录", "能源管理", "水电气分项计量，支持同环比"),
    (SafetyIncident, "安全事件", "安全管理", "事件等级、处理状态、损失"),
    (SafetyHazard, "安全隐患", "安全管理", "隐患等级、整改期限、闭环状态"),
    (ServiceRequest, "企业服务申请", "企业服务", "政策申报、场地、融资等服务请求"),
    (User, "系统用户", "系统管理", "账号、角色、组织归属"),
]


@router.get("/catalog")
def catalog(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """数据资产目录：逐表实时统计行数与更新时间（真实 COUNT 查询）。"""
    auth.require("data", "VIEW")
    vis = auth.visible_park_ids()

    items: list[dict[str, Any]] = []
    for model, cn_name, domain, desc in ASSET_CATALOG:
        try:
            total = db.scalar(select(func.count()).select_from(model)) or 0
        except Exception:
            total = 0

        park_scoped = hasattr(model, "park_id") and vis is not None
        scoped = total
        if park_scoped:
            q = select(func.count()).select_from(model)
            q = q.where(model.park_id.in_(vis)) if vis else q.where(model.id == -1)
            scoped = db.scalar(q) or 0

        updated = None
        if hasattr(model, "updated_at"):
            updated = db.scalar(select(func.max(model.updated_at)))

        items.append({
            "table": model.__tablename__,
            "model": model.__name__,
            "name": cn_name,
            "domain": domain,
            "description": desc,
            "row_count": int(total),
            "visible_row_count": int(scoped),
            "park_scoped": bool(hasattr(model, "park_id")),
            "updated_at": updated.isoformat() if updated else None,
            "is_demo": True,
        })

    domains: dict[str, dict[str, Any]] = {}
    for it in items:
        d = domains.setdefault(it["domain"], {"domain": it["domain"], "tables": 0,
                                              "rows": 0, "table_list": []})
        d["tables"] += 1
        d["rows"] += it["visible_row_count"]
        d["table_list"].append(it["name"])

    return {
        "items": sorted(items, key=lambda x: -x["visible_row_count"]),
        "domains": sorted(domains.values(), key=lambda x: -x["rows"]),
        "summary": {
            "table_total": len(items),
            "domain_total": len(domains),
            "row_total": sum(i["row_count"] for i in items),
            "visible_row_total": sum(i["visible_row_count"] for i in items),
        },
        "data_label": "演示数据",
        "note": ("行数为数据库实时 COUNT 结果；「可见行数」为按当前账号数据权限范围"
                 "过滤后的行数。全部数据为演示数据。"),
    }


@router.get("/uploads")
def uploads(db: DbSession, auth: CurrentAuth,
            data_type: str | None = None, status: str | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """数据上传批次列表。"""
    auth.require("data", "VIEW")
    vis = auth.visible_park_ids()
    q = select(DataUpload)
    if vis is not None:
        q = q.where(DataUpload.park_id.in_(vis)) if vis else q.where(DataUpload.id == -1)
    if data_type:
        q = q.where(DataUpload.data_type == data_type)
    if status:
        q = q.where(DataUpload.status == status)
    rows = list(db.scalars(q.order_by(DataUpload.upload_at.desc(),
                                      DataUpload.id.desc())).all())
    items = [{
        "id": u.id, "upload_code": u.upload_code, "file_name": u.file_name,
        "file_size": u.file_size, "file_type": u.file_type,
        "data_type": u.data_type, "park_id": u.park_id,
        "uploader_name": u.uploader_name,
        "upload_at": u.upload_at.isoformat() if u.upload_at else None,
        "row_count": u.row_count, "valid_count": u.valid_count,
        "error_count": u.error_count, "warning_count": u.warning_count,
        "quality_score": u.quality_score, "status": u.status,
        "columns": u.columns, "is_demo": u.is_demo,
    } for u in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "rows": sum(i["row_count"] or 0 for i in items),
        "errors": sum(i["error_count"] or 0 for i in items),
        "warnings": sum(i["warning_count"] or 0 for i in items),
        "avg_quality": (round(sum(i["quality_score"] or 0 for i in items) / len(items), 1)
                        if items else None),
        "by_type": {k: len([i for i in items if i["data_type"] == k])
                    for k in {i["data_type"] for i in items}},
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in {i["status"] for i in items}},
    }
    return result


@router.get("/uploads/{upload_id}")
def upload_detail(upload_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """上传批次详情 + 该批次的数据质量问题清单。"""
    auth.require("data", "VIEW")
    u = db.get(DataUpload, upload_id)
    if not u:
        raise HTTPException(404, "上传批次不存在")
    vis = auth.visible_park_ids()
    if vis is not None and u.park_id not in vis:
        raise HTTPException(403, "无权查看该园区数据")

    issues = list(db.scalars(
        select(DataQualityIssue).where(DataQualityIssue.upload_id == upload_id)
        .order_by(DataQualityIssue.severity.desc(), DataQualityIssue.row_no)
    ).all())
    reports = list(db.scalars(
        select(DataQualityReport).where(DataQualityReport.upload_id == upload_id)
    ).all())

    by_type: dict[str, int] = {}
    for i in issues:
        by_type[i.issue_type] = by_type.get(i.issue_type, 0) + 1

    return {
        "id": u.id, "upload_code": u.upload_code, "file_name": u.file_name,
        "file_size": u.file_size, "data_type": u.data_type, "park_id": u.park_id,
        "uploader_name": u.uploader_name,
        "upload_at": u.upload_at.isoformat() if u.upload_at else None,
        "row_count": u.row_count, "valid_count": u.valid_count,
        "error_count": u.error_count, "warning_count": u.warning_count,
        "quality_score": u.quality_score, "status": u.status,
        "columns": u.columns, "preview": u.preview, "mapping": u.mapping,
        "issues": [{
            "id": i.id, "row_no": i.row_no, "column_name": i.column_name,
            "field_key": i.field_key, "raw_value": i.raw_value,
            "issue_type": i.issue_type, "severity": i.severity,
            "description": i.description, "suggestion": i.suggestion,
            "suggested_value": i.suggested_value,
            "handle_mode": i.handle_mode, "handled": i.handled,
            "handled_at": i.handled_at.isoformat() if i.handled_at else None,
        } for i in issues],
        "issue_stats": {
            "total": len(issues),
            "by_type": by_type,
            "by_severity": {k: len([i for i in issues if i.severity == k])
                            for k in {i.severity for i in issues}},
            "unhandled": len([i for i in issues if not i.handled]),
        },
        "quality_reports": [{
            "report_code": r.report_code, "data_type": r.data_type,
            "total_rows": r.total_rows, "completeness": r.completeness,
            "uniqueness": r.uniqueness, "validity": r.validity,
            "consistency": r.consistency, "timeliness": r.timeliness,
            "overall_score": r.overall_score, "issue_summary": r.issue_summary,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        } for r in reports],
        "data_label": "演示数据",
    }


@router.get("/quality")
def quality(db: DbSession, auth: CurrentAuth,
            park_id: int | None = None) -> dict[str, Any]:
    """数据质量总览：按数据类型的六维评分 + 问题分布。"""
    auth.require("data", "VIEW")
    vis = auth.visible_park_ids()
    q = select(DataQualityReport)
    if park_id:
        q = q.where(DataQualityReport.park_id == park_id)
    elif vis is not None:
        q = q.where(DataQualityReport.park_id.in_(vis)) if vis else q.where(DataQualityReport.id == -1)
    reports = list(db.scalars(q.order_by(DataQualityReport.generated_at.desc())).all())

    # 每类数据取最新一份报告
    latest: dict[str, DataQualityReport] = {}
    for r in reports:
        key = r.data_type or "UNKNOWN"
        if key not in latest:
            latest[key] = r

    rows = []
    for k, r in latest.items():
        rows.append({
            "data_type": k, "report_code": r.report_code,
            "total_rows": r.total_rows,
            "completeness": r.completeness, "uniqueness": r.uniqueness,
            "validity": r.validity, "consistency": r.consistency,
            "timeliness": r.timeliness, "overall_score": r.overall_score,
            "issue_summary": r.issue_summary,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "level": ("优" if (r.overall_score or 0) >= 90 else
                      "良" if (r.overall_score or 0) >= 75 else
                      "需改进" if (r.overall_score or 0) >= 60 else "不合格"),
        })
    rows.sort(key=lambda x: x["overall_score"] or 0)

    iq = select(DataQualityIssue)
    issues = list(db.scalars(iq).all())
    issue_by_type: dict[str, int] = {}
    issue_by_sev: dict[str, int] = {}
    for i in issues:
        issue_by_type[i.issue_type] = issue_by_type.get(i.issue_type, 0) + 1
        issue_by_sev[i.severity] = issue_by_sev.get(i.severity, 0) + 1

    def avg(field: str) -> float | None:
        vals = [getattr(r, field) for r in latest.values() if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "items": rows,
        "summary": {
            "data_type_total": len(rows),
            "overall_score": avg("overall_score"),
            "completeness": avg("completeness"),
            "uniqueness": avg("uniqueness"),
            "validity": avg("validity"),
            "consistency": avg("consistency"),
            "timeliness": avg("timeliness"),
            "issue_total": len(issues),
            "issue_unhandled": len([i for i in issues if not i.handled]),
        },
        "issue_by_type": issue_by_type,
        "issue_by_severity": issue_by_sev,
        "data_label": "演示数据",
        "note": ("六维评分口径：完整性=非空字段占比；唯一性=去重后占比；"
                 "有效性=通过格式/枚举校验占比；一致性=跨表勾稽一致占比；"
                 "时效性=在更新周期内占比；总分=五项等权平均。"),
    }


@router.get("/lineage")
def lineage(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """数据血缘与口径说明：从源业务表到指标的计算链路（静态声明 + 实时行数）。"""
    auth.require("data", "VIEW")

    def cnt(model: Any) -> int:
        try:
            return int(db.scalar(select(func.count()).select_from(model)) or 0)
        except Exception:
            return 0

    chains = [
        {
            "metric": "出租率",
            "formula": "已出租空间面积 ÷ 可租空间面积 × 100%",
            "sources": [
                {"table": Space.__tablename__, "name": "空间单元", "field": "status / rentable_area",
                 "rows": cnt(Space)},
            ],
            "business_rule": "状态为 RENTED 的空间计入分子；全部可租状态空间计入分母。",
            "refresh": "写入空间状态时实时生效",
        },
        {
            "metric": "租金收缴率",
            "formula": "已核销收款金额 ÷ 应收账单金额 × 100%",
            "sources": [
                {"table": Bill.__tablename__, "name": "应收账单", "field": "amount / paid_amount", "rows": cnt(Bill)},
                {"table": Payment.__tablename__, "name": "收款流水", "field": "amount", "rows": cnt(Payment)},
            ],
            "business_rule": "账单状态 PAID/PARTIAL 的实收金额计入分子；账期内全部账单应收金额为分母。",
            "refresh": "收款登记后实时重算",
        },
        {
            "metric": "企业入驻数",
            "formula": "企业在租合同数（去重企业）",
            "sources": [
                {"table": Enterprise.__tablename__, "name": "企业档案", "field": "id", "rows": cnt(Enterprise)},
                {"table": Contract.__tablename__, "name": "租赁合同", "field": "enterprise_id / status", "rows": cnt(Contract)},
            ],
            "business_rule": "合同状态为 ACTIVE 且指向有效企业，按企业去重计数。",
            "refresh": "合同签约/退租后实时生效",
        },
        {
            "metric": "项目进度偏差",
            "formula": "实际进度 − 计划进度（按 WBS 权重加权）",
            "sources": [
                {"table": WbsItem.__tablename__, "name": "WBS 任务", "field": "progress / weight / is_critical", "rows": cnt(WbsItem)},
                {"table": Project.__tablename__, "name": "项目主档", "field": "progress / planned_progress", "rows": cnt(Project)},
            ],
            "business_rule": "任务进度按权重加权汇总为项目进度；关键路径任务的拖延直接传导为项目延期天数。",
            "refresh": "任务进度更新后重算关键路径",
        },
        {
            "metric": "招商漏斗转化率",
            "formula": "各阶段线索数 ÷ 首次接触线索数 × 100%",
            "sources": [
                {"table": LeasingLead.__tablename__, "name": "招商线索", "field": "stage / channel_id", "rows": cnt(LeasingLead)},
            ],
            "business_rule": "按渠道分组统计线索从初访到签约的逐级转化，渠道成本 ÷ 签约数 = 单签约成本。",
            "refresh": "线索阶段变更后实时生效",
        },
        {
            "metric": "工单平均响应时长",
            "formula": "Σ(受理时间 − 上报时间) ÷ 已受理工单数",
            "sources": [
                {"table": WorkOrder.__tablename__, "name": "服务工单", "field": "response_minutes / priority", "rows": cnt(WorkOrder)},
            ],
            "business_rule": "按优先级分档考核 SLA；未受理工单不计入均值，单列为超时风险。",
            "refresh": "工单状态流转时实时写入",
        },
        {
            "metric": "设备健康度",
            "formula": "100 − Σ(各项劣化扣分)，下限 0",
            "sources": [
                {"table": Device.__tablename__, "name": "设备台账", "field": "health_score / next_maintain_date", "rows": cnt(Device)},
            ],
            "business_rule": "健康度 < 55 触发预警并建议纳入更换计划；逾期未保养按天扣分。",
            "refresh": "巡检结果录入后重算",
        },
        {
            "metric": "能耗强度",
            "formula": "当期能耗总量 ÷ 建筑面积（可对比同比/环比）",
            "sources": [
                {"table": EnergyRecord.__tablename__, "name": "能耗记录", "field": "energy_type / value / record_date", "rows": cnt(EnergyRecord)},
                {"table": Building.__tablename__, "name": "楼宇档案", "field": "build_area", "rows": cnt(Building)},
            ],
            "business_rule": "按楼宇 + 能源类型 + 月份聚合；季节系数用于消除气温差异后再做同环比。",
            "refresh": "抄表数据录入后 T+0 生效",
        },
        {
            "metric": "安全指数",
            "formula": "100 − Σ(隐患扣分 + 事件扣分)",
            "sources": [
                {"table": SafetyIncident.__tablename__, "name": "安全事件", "field": "level / status", "rows": cnt(SafetyIncident)},
                {"table": SafetyHazard.__tablename__, "name": "安全隐患", "field": "level / status / deadline", "rows": cnt(SafetyHazard)},
            ],
            "business_rule": "逐项列明扣分构成，可追溯到具体事件/隐患记录，不做黑箱评分。",
            "refresh": "隐患上报/整改后实时生效",
        },
        {
            "metric": "企业服务响应率",
            "formula": "已响应服务申请数 ÷ 服务申请总数 × 100%",
            "sources": [
                {"table": ServiceRequest.__tablename__, "name": "企业服务申请", "field": "status", "rows": cnt(ServiceRequest)},
            ],
            "business_rule": "已受理及之后状态计入已响应；超期未响应单列督办。",
            "refresh": "服务申请状态变更后实时生效",
        },
    ]
    return {
        "chains": chains,
        "summary": {"metric_total": len(chains)},
        "data_label": "演示数据",
        "note": "血缘关系为系统实际计算链路声明，行数为数据库实时统计，可用于指标口径穿透追溯。",
    }


@router.get("/overview")
def data_overview(db: DbSession, auth: CurrentAuth,
                  park_id: int | None = None) -> dict[str, Any]:
    """数据中心首屏：资产规模、质量分、上传趋势、领域分布。"""
    auth.require("data", "VIEW")
    vis = auth.visible_park_ids()

    def scoped_count(model: Any) -> int:
        q = select(func.count()).select_from(model)
        if hasattr(model, "park_id"):
            if park_id:
                q = q.where(model.park_id == park_id)
            elif vis is not None:
                q = q.where(model.park_id.in_(vis)) if vis else q.where(model.id == -1)
        return int(db.scalar(q) or 0)

    return {
        "assets": {
            "parks": scoped_count(Park), "buildings": scoped_count(Building),
            "spaces": scoped_count(Space), "enterprises": scoped_count(Enterprise),
            "contracts": scoped_count(Contract), "bills": scoped_count(Bill),
            "payments": scoped_count(Payment), "leads": scoped_count(LeasingLead),
            "projects": scoped_count(Project), "wbs": scoped_count(WbsItem),
            "work_orders": scoped_count(WorkOrder), "devices": scoped_count(Device),
            "energy_records": scoped_count(EnergyRecord),
            "safety_incidents": scoped_count(SafetyIncident),
            "safety_hazards": scoped_count(SafetyHazard),
        },
        "uploads": {
            "total": scoped_count(DataUpload),
            "rows": int(db.scalar(select(func.sum(DataUpload.row_count))) or 0),
        },
        "data_label": "演示数据",
    }

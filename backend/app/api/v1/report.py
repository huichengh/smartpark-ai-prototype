"""报表中心路由。

需求书第 40 节：
  - 园区经营月报（十段式：经营总览 → …→ 项目管理）
  - 项目周报 / 项目月报
  - 报表归档记录（ReportRecord）与导出

报表正文由 report_service 基于真实数据库聚合生成，本模块负责：
权限校验、参数解析、落库归档、导出。
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select

from app.core.audit import write_audit
from app.core.security import CurrentAuth, DbSession
from app.models import Park, Project, ReportRecord
from app.schemas.common import paginate
from app.services import report_service

router = APIRouter(prefix="/report", tags=["报表中心"])

REPORT_TYPES: list[dict[str, str]] = [
    {"key": "PARK_MONTHLY", "label": "园区经营月报", "frequency": "月",
     "description": "覆盖经营总览、财务、招商、空间、合同、物业、设备、能源、安全、项目共十段"},
    {"key": "PROJECT_WEEKLY", "label": "项目周报", "frequency": "周",
     "description": "项目进度、里程碑、成本、风险、敏捷迭代的周度快照"},
    {"key": "PROJECT_MONTHLY", "label": "项目月报", "frequency": "月",
     "description": "项目月度体检报告，含健康度结论与建议措施"},
]


@router.get("/types")
def report_types(auth: CurrentAuth) -> dict[str, Any]:
    """可用报表类型字典。"""
    auth.require("report", "VIEW")
    return {"items": REPORT_TYPES}


@router.get("/park-monthly")
def park_monthly(db: DbSession, auth: CurrentAuth,
                 park_id: int | None = None, period: str | None = None) -> dict[str, Any]:
    """生成园区经营月报（实时聚合，不落库）。"""
    auth.require("report", "VIEW")
    _check_park(auth, park_id)
    data = report_service.build_operating_report(db, auth, park_id=park_id, period=period)
    return {**data, "template": "PARK_MONTHLY"}


@router.get("/project/{project_id}")
def project_report(project_id: int, db: DbSession, auth: CurrentAuth,
                   report_type: str = Query("WEEKLY", pattern="^(WEEKLY|MONTHLY)$")) -> dict[str, Any]:
    """生成项目周报/月报。"""
    auth.require("report", "VIEW")
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if not auth.can_access_project(project_id) and not auth.can_access_park(p.park_id):
        raise HTTPException(403, "无权查看该项目报表")
    data = report_service.build_project_report(
        db, p, "WEEKLY" if report_type == "WEEKLY" else "MONTHLY")
    return {**data, "template": f"PROJECT_{report_type}"}


@router.get("/archive")
def archive(db: DbSession, auth: CurrentAuth,
            report_type: str | None = None, park_id: int | None = None,
            project_id: int | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """报表归档记录列表。"""
    auth.require("report", "VIEW")
    vis = auth.visible_park_ids()
    q = select(ReportRecord)
    if vis is not None:
        q = q.where(ReportRecord.park_id.in_(vis)) if vis else q.where(ReportRecord.id == -1)
    if report_type:
        q = q.where(ReportRecord.report_type == report_type)
    if park_id:
        q = q.where(ReportRecord.park_id == park_id)
    if project_id:
        q = q.where(ReportRecord.project_id == project_id)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(
        q.order_by(ReportRecord.created_at.desc(), ReportRecord.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all())
    items = [_out(r) for r in rows]
    return {
        "items": items, "total": int(total), "page": page, "page_size": page_size,
        "pages": (int(total) + page_size - 1) // page_size,
        "data_label": "演示数据",
    }


@router.get("/archive/{rec_id}")
def archive_detail(rec_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("report", "VIEW")
    r = db.get(ReportRecord, rec_id)
    if not r:
        raise HTTPException(404, "报表记录不存在")
    vis = auth.visible_park_ids()
    if vis is not None and r.park_id not in vis:
        raise HTTPException(403, "无权查看该园区报表")
    return {**_out(r), "content": r.content, "data_label": "演示数据"}


@router.post("/generate")
def generate(db: DbSession, auth: CurrentAuth,
             report_type: str = Query(..., description="PARK_MONTHLY / PROJECT_WEEKLY / PROJECT_MONTHLY"),
             park_id: int | None = None, project_id: int | None = None,
             period: str | None = None, fmt: str = Query("JSON", pattern="^(JSON|MARKDOWN)$")) -> dict[str, Any]:
    """生成报表并落库归档（真实写 ReportRecord + 审计）。"""
    auth.require("report", "ADD")
    _check_park(auth, park_id)

    if report_type == "PARK_MONTHLY":
        data = report_service.build_operating_report(db, auth, park_id=park_id, period=period)
    elif report_type in ("PROJECT_WEEKLY", "PROJECT_MONTHLY"):
        if not project_id:
            raise HTTPException(400, "生成项目报表必须提供 project_id")
        p = db.get(Project, project_id)
        if not p:
            raise HTTPException(404, "项目不存在")
        if not auth.can_access_project(project_id) and not auth.can_access_park(p.park_id):
            raise HTTPException(403, "无权生成该项目报表")
        data = report_service.build_project_report(
            db, p, "WEEKLY" if report_type == "PROJECT_WEEKLY" else "MONTHLY")
        park_id = park_id or p.park_id
    else:
        raise HTTPException(400, f"不支持的报表类型：{report_type}")

    now = dt.datetime.now()
    seq = (db.scalar(select(func.count(ReportRecord.id))) or 0) + 1
    fmt_up = fmt.upper()
    content = _to_markdown(data) if fmt_up == "MARKDOWN" else None
    rec = ReportRecord(
        report_code=f"RP{now:%Y%m%d}{seq:05d}",
        report_name=data.get("report_name") or "未命名报表",
        report_type=report_type, park_id=park_id, project_id=project_id,
        period=data.get("period"), format=fmt_up,
        generated_by=auth.user.real_name,
        content=content or _json_str(data),
        status="GENERATED",
    )
    db.add(rec)
    db.flush()

    write_audit(db, module="report", action="ADD", auth=auth, object_type="ReportRecord",
                object_id=rec.id, object_name=rec.report_code,
                after_value={"report_type": report_type, "period": data.get("period"),
                             "format": fmt_up},
                change_summary=f"生成报表「{rec.report_name}」并归档（{fmt_up}）")
    db.commit()

    return {
        "success": True, "report_code": rec.report_code, "report_name": rec.report_name,
        "report_type": report_type, "format": fmt_up, "id": rec.id,
        "message": "报表已生成并归档",
        "report": data, "markdown": content,
        "data_label": "演示数据",
    }


@router.get("/archive/{rec_id}/export", response_class=PlainTextResponse)
def export_markdown(rec_id: int, db: DbSession, auth: CurrentAuth) -> PlainTextResponse:
    """导出报表为 Markdown 文本（真实导出 + 审计）。"""
    auth.require("report", "EXPORT")
    r = db.get(ReportRecord, rec_id)
    if not r:
        raise HTTPException(404, "报表记录不存在")
    vis = auth.visible_park_ids()
    if vis is not None and r.park_id not in vis:
        raise HTTPException(403, "无权导出该园区报表")

    body = r.content or ""
    if not body.lstrip().startswith("#"):
        try:
            import json
            body = _to_markdown(json.loads(body))
        except Exception:
            pass

    write_audit(db, module="report", action="EXPORT", auth=auth, object_type="ReportRecord",
                object_id=r.id, object_name=r.report_code,
                change_summary=f"导出报表「{r.report_name}」为 Markdown",
                after_value={"format": "MARKDOWN"})
    db.commit()

    # HTTP 头只能承载 latin-1；中文文件名按 RFC 5987 用 filename* 传 UTF-8
    filename = f"{r.report_code}.md"
    filename_cn = f"{r.report_code}_{r.report_name}.md"
    disposition = ("attachment; filename=\"" + filename + "\"; "
                   + "filename*=UTF-8''" + urllib.parse.quote(filename_cn))
    return PlainTextResponse(
        body, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": disposition})


@router.get("/summary")
def report_summary(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """报表中心首屏统计。"""
    auth.require("report", "VIEW")
    vis = auth.visible_park_ids()
    q = select(ReportRecord)
    if vis is not None:
        q = q.where(ReportRecord.park_id.in_(vis)) if vis else q.where(ReportRecord.id == -1)
    rows = list(db.scalars(q).all())
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in rows:
        by_type[r.report_type] = by_type.get(r.report_type, 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
    return {
        "total": len(rows),
        "by_type": by_type, "by_status": by_status,
        "available_types": REPORT_TYPES,
        "latest": sorted(
            [{"id": r.id, "report_code": r.report_code, "report_name": r.report_name,
              "report_type": r.report_type, "period": r.period,
              "generated_by": r.generated_by,
              "created_at": r.created_at.isoformat() if r.created_at else None}
             for r in rows],
            key=lambda x: x["created_at"] or "", reverse=True)[:5],
        "data_label": "演示数据",
    }


# ---------------------------------------------------------------- helpers

def _check_park(auth: Any, park_id: int | None) -> None:
    if park_id and not auth.can_access_park(park_id):
        raise HTTPException(403, "无权访问该园区")


def _out(r: ReportRecord) -> dict[str, Any]:
    return {
        "id": r.id, "report_code": r.report_code, "report_name": r.report_name,
        "report_type": r.report_type, "park_id": r.park_id,
        "project_id": r.project_id, "period": r.period, "format": r.format,
        "generated_by": r.generated_by, "status": r.status,
        "file_path": r.file_path,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "is_demo": True,
    }


def _json_str(data: dict[str, Any]) -> str:
    import json
    return json.dumps(data, ensure_ascii=False, default=str)


def _to_markdown(data: dict[str, Any]) -> str:
    """把报表结构渲染为 Markdown（供导出与归档）。"""
    lines: list[str] = []
    lines.append(f"# {data.get('report_name', '报表')}")
    lines.append("")
    meta = []
    if data.get("period"):
        meta.append(f"**报告期**：{data['period']}")
    if data.get("generated_at"):
        meta.append(f"**生成时间**：{data['generated_at']}")
    if data.get("generated_by"):
        meta.append(f"**生成人**：{data['generated_by']}")
    meta.append("**数据说明**：演示数据")
    lines.append(" ｜ ".join(meta))
    lines.append("")

    es = data.get("executive_summary") or {}
    if es:
        lines.append("## 摘要")
        lines.append("")
        if es.get("conclusion"):
            lines.append(f"**结论**：{es['conclusion']}")
            lines.append("")
        if es.get("health"):
            lines.append(f"**健康度**：{es['health']}")
            lines.append("")
        for h in _as_list(es.get("highlights")):
            lines.append(f"- {h}")
        for w in _as_list(es.get("warnings")):
            lines.append(f"- ⚠ {w}")
        for s in _as_list(es.get("signals")):
            lines.append(f"- 信号：{_fmt_signal(s)}")
        for s in _as_list(es.get("suggestions")):
            lines.append(f"- 建议：{s}")
        lines.append("")

    for sec in data.get("sections") or []:
        lines.append(f"## {sec.get('title', '')}")
        lines.append("")
        if not sec.get("data_sufficient", True):
            miss = "、".join(str(x) for x in _as_list(sec.get("missing_data"))) or "相关数据"
            lines.append(f"> 数据不足：缺少 {miss}，本节不做结论。")
            lines.append("")
        mets = sec.get("metrics") or []
        if mets and isinstance(mets[0], dict):
            lines.append("| 指标 | 数值 | 单位 | 口径 | 同比 | 环比 |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for m in mets:
                if not isinstance(m, dict) or "label" not in m:
                    continue
                lines.append(
                    f"| {m.get('label', '')} | {m.get('value', '-')} | {m.get('unit', '')} "
                    f"| {m.get('basis', '-')} | {_pct(m.get('yoy'))} | {_pct(m.get('mom'))} |")
            lines.append("")
        for n in _as_list(sec.get("notes")):
            lines.append(f"- {n}")
        lines.append("")

    ev = data.get("evidence") or {}
    if ev:
        lines.append("---")
        lines.append("")
        lines.append("### 数据来源与口径")
        lines.append("")
        lines.append(f"- 数据来源：{ev.get('data_source', '平台业务数据库')}")
        lines.append(f"- 涉及数据表：{', '.join(ev.get('tables') or [])}")
        lines.append(f"- 记录数：{ev.get('record_count', '-')}")
        lines.append(f"- 过滤条件：{ev.get('filters', {})}")
        lines.append("- 说明：本报表全部数据为演示数据，由平台数据库实时聚合生成。")
        lines.append("")
    return "\n".join(lines)


def _pct(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _as_list(v: Any) -> list[Any]:
    """把可能是 None / 标量 / 字典 / 列表的值统一规整为可迭代列表。

    报表服务在「数据不足」分支会把 notes 传为标量（含 bool），
    此处做防御性归一，避免渲染层因类型不一致而中断。
    """
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    if isinstance(v, dict):
        return [v]
    if isinstance(v, bool):
        return []
    return [v]


def _fmt_signal(s: Any) -> str:
    """信号项可能是 dict（type/level/text）或纯文本。"""
    if isinstance(s, dict):
        parts = [str(s.get("type") or ""), f"[{s.get('level')}]" if s.get("level") else "",
                 str(s.get("text") or s.get("conclusion") or "")]
        return " ".join(p for p in parts if p).strip()
    return str(s)

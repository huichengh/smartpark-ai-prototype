"""日志审计路由。

需求书要求：所有关键操作可追踪、可回溯。本模块直接读取 AuditLog，
不做任何二次加工，保证审计证据的原始性；并提供按模块/动作/用户/时间
的聚合，用于合规自查。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.enums import ACTION_LABELS, MODULE_LABELS
from app.core.security import CurrentAuth, DbSession
from app.models import AuditLog
from app.schemas.common import paginate

router = APIRouter(prefix="/audit", tags=["日志审计"])

# 模块 / 动作中文名统一由 app.core.enums 提供（此前此处单独维护一份，
# 缺 auth 与 agent 两项，导致审计列表里这两个模块显示为英文键名）。


def _out(r: AuditLog) -> dict[str, Any]:
    return {
        "id": r.id, "log_code": r.log_code,
        "user_id": r.user_id, "username": r.username, "real_name": r.real_name,
        "park_id": r.park_id,
        "module": r.module,
        "module_label": MODULE_LABELS.get(r.module or "", r.module),
        "action": r.action,
        "action_label": ACTION_LABELS.get(r.action or "", r.action),
        "object_type": r.object_type, "object_id": r.object_id,
        "object_name": r.object_name,
        "before_value": r.before_value, "after_value": r.after_value,
        "change_summary": r.change_summary, "approval_info": r.approval_info,
        "source": r.source, "ip_address": r.ip_address, "user_agent": r.user_agent,
        "result": r.result,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "is_demo": True,
    }


@router.get("")
def list_logs(db: DbSession, auth: CurrentAuth,
              module: str | None = None, action: str | None = None,
              user_id: int | None = None, object_type: str | None = None,
              keyword: str | None = None, source: str | None = None,
              result: str | None = None, date_from: str | None = None,
              date_to: str | None = None,
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """审计日志查询（仅审计模块 VIEW 权限可见）。"""
    auth.require("audit", "VIEW")
    vis = auth.visible_park_ids()

    q = select(AuditLog)
    if vis is not None:
        # 全局操作（park_id 为空，如登录）对超管以外的园区账号也可见，
        # 但仅限当前用户自身产生的记录，避免跨园区信息泄漏。
        if vis:
            q = q.where(or_(AuditLog.park_id.in_(vis),
                            (AuditLog.park_id.is_(None) & (AuditLog.user_id == auth.user.id))))
        else:
            q = q.where(AuditLog.user_id == auth.user.id)
    if module:
        q = q.where(AuditLog.module == module)
    if action:
        q = q.where(AuditLog.action == action)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if object_type:
        q = q.where(AuditLog.object_type == object_type)
    if source:
        q = q.where(AuditLog.source == source)
    if result:
        q = q.where(AuditLog.result == result)
    if keyword:
        like = f"%{keyword}%"
        q = q.where(or_(AuditLog.change_summary.like(like),
                        AuditLog.object_name.like(like),
                        AuditLog.real_name.like(like),
                        AuditLog.log_code.like(like)))
    if date_from:
        q = q.where(AuditLog.created_at >= _parse_dt(date_from))
    if date_to:
        q = q.where(AuditLog.created_at <= _parse_dt(date_to, end=True))

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(
        q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all())

    items = [_out(r) for r in rows]
    result_payload = {
        "items": items, "total": int(total),
        "page": page, "page_size": page_size,
        "pages": (int(total) + page_size - 1) // page_size,
        "data_label": "演示数据",
    }
    if page == 1:
        result_payload["stats"] = _stats(db, auth, vis)
    return result_payload


def _parse_dt(s: str, end: bool = False) -> dt.datetime:
    try:
        if len(s) == 10:
            d = dt.date.fromisoformat(s)
            return dt.datetime.combine(d, dt.time.max if end else dt.time.min)
        v = dt.datetime.fromisoformat(s)
        return v + (dt.timedelta(days=1) if end and v.time() == dt.time.min else dt.timedelta())
    except ValueError:
        raise HTTPException(400, f"时间格式不合法：{s}，应为 YYYY-MM-DD 或 ISO 日期时间")


def _stats(db: DbSession, auth: CurrentAuth, vis: list[int] | None) -> dict[str, Any]:
    base = select(AuditLog)
    if vis is not None:
        base = (base.where(AuditLog.park_id.in_(vis)) if vis
                else base.where(AuditLog.user_id == auth.user.id))

    sub = base.subquery()

    def agg(col_name: str, limit: int = 12) -> list[dict[str, Any]]:
        # 必须取子查询自身的列 sub.c[col_name]。
        # 若直接传 AuditLog.module 这类原始表列，SQLAlchemy 会生成
        #   SELECT audit_log.module, count(*) FROM (subquery), audit_log GROUP BY ...
        # 两个 FROM 之间没有连接条件 → 笛卡尔积，count 被放大到 全表行数 倍。
        col = sub.c[col_name]
        rows = db.execute(
            select(col, func.count()).select_from(sub)
            .group_by(col).order_by(func.count().desc()).limit(limit)
        ).all()
        return [{"key": k, "count": int(c)} for k, c in rows]

    total = db.scalar(select(func.count()).select_from(sub)) or 0

    by_module = agg("module")
    for m in by_module:
        m["label"] = MODULE_LABELS.get(m["key"] or "", m["key"])
    by_action = agg("action")
    for a in by_action:
        a["label"] = ACTION_LABELS.get(a["key"] or "", a["key"])

    sources = agg("source")
    results = agg("result")

    # 近 7 天趋势
    since = dt.datetime.now() - dt.timedelta(days=7)
    sub7 = base.where(AuditLog.created_at >= since).subquery()
    trend_rows = db.execute(
        select(func.date(sub7.c.created_at), func.count())
        .group_by(func.date(sub7.c.created_at))
        .order_by(func.date(sub7.c.created_at))
    ).all()
    trend_map = {str(d): int(c) for d, c in trend_rows}
    trend = []
    for i in range(6, -1, -1):
        day = (dt.date.today() - dt.timedelta(days=i))
        trend.append({"date": day.isoformat(),
                      "count": trend_map.get(day.isoformat(), 0)})

    # 风险操作 = 删除类动作 ∪ 执行失败。
    # 注意：AuditLog.result 的枚举值是 SUCCESS / FAILED（见 core/enums.py），
    # 早期写成 "FAIL" 与数据不交集，导致 risk_operations 恒为 0。
    risk_sub = base.where(or_(AuditLog.action.in_(("DELETE", "REJECT", "TERMINATE")),
                              AuditLog.result == "FAILED")).subquery()
    risks = db.scalar(select(func.count()).select_from(risk_sub)) or 0

    return {
        "total": int(total),
        "by_module": by_module, "by_action": by_action,
        "by_source": sources, "by_result": results,
        "trend_7d": trend,
        "risk_operations": int(risks),
        # AI 调用量口徑是「来源为 AI 的日志」，不是「module == ai」
        #（审计模块名里根本没有 ai，真实模块名是 agent）——旧写法恒为 0。
        "ai_calls": sum(s["count"] for s in sources if (s["key"] or "").upper() == "AI"),
    }


@router.get("/stats")
def audit_stats(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """审计统计概览。"""
    auth.require("audit", "VIEW")
    return {**_stats(db, auth, auth.visible_park_ids()), "data_label": "演示数据"}


@router.get("/resource/{object_type}/{object_id}")
def resource_trail(object_type: str, object_id: int, db: DbSession, auth: CurrentAuth,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """单个业务对象的完整操作轨迹（回溯用）。"""
    auth.require("audit", "VIEW")
    vis = auth.visible_park_ids()
    q = select(AuditLog).where(AuditLog.object_type == object_type,
                               AuditLog.object_id == object_id)
    if vis is not None:
        q = q.where(or_(AuditLog.park_id.in_(vis), AuditLog.park_id.is_(None))) if vis \
            else q.where(AuditLog.user_id == auth.user.id)
    rows = list(db.scalars(q.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())).all())
    items = [_out(r) for r in rows]
    result = paginate(items, page, page_size)
    result["timeline"] = [
        {"at": i["created_at"], "user": i["real_name"] or i["username"],
         "action": i["action_label"], "module": i["module_label"],
         "summary": i["change_summary"], "before": i["before_value"],
         "after": i["after_value"], "approval": i["approval_info"]}
        for i in items
    ]
    result["data_label"] = "演示数据"
    return result


@router.get("/{log_id}")
def log_detail(log_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("audit", "VIEW")
    r = db.get(AuditLog, log_id)
    if not r:
        raise HTTPException(404, "日志不存在")
    vis = auth.visible_park_ids()
    if vis is not None and r.park_id is not None and r.park_id not in vis:
        raise HTTPException(403, "无权查看该园区日志")
    d = _out(r)
    d["data_label"] = "演示数据"
    return d


@router.get("/meta/dict")
def audit_dict(auth: CurrentAuth) -> dict[str, Any]:
    """审计模块字典（供前端筛选器使用）。"""
    auth.require("audit", "VIEW")
    return {
        "modules": [{"key": k, "label": v} for k, v in MODULE_LABELS.items()],
        "actions": [{"key": k, "label": v} for k, v in ACTION_LABELS.items()],
        "sources": [
            {"key": "WEB", "label": "页面操作"},
            {"key": "API", "label": "接口调用"},
            {"key": "AI", "label": "AI Agent"},
            {"key": "SYSTEM", "label": "系统任务"},
            {"key": "IMPORT", "label": "数据导入"},
        ],
        "results": [{"key": "SUCCESS", "label": "成功"}, {"key": "FAIL", "label": "失败"}],
    }

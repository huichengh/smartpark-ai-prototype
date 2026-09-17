"""消息通知路由。

通知分两类：
  1. 系统触发（阈值越限、到期提醒、SLA 超时）— 由定时任务/业务写入
  2. AI 主动洞察 — build_daily_insights 生成的建议

所有通知都在 Notification 表中，带 trigger_value / threshold / suggestion，
可解释「为什么推给我」，不做黑箱推送。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.audit import write_audit
from app.core.enums import ENUM_LABELS
from app.core.security import CurrentAuth, DbSession
from app.models import Notification
from app.schemas.common import paginate

router = APIRouter(prefix="/notification", tags=["消息通知"])

# 标签统一取自 app.core.enums。
# 此前本文件单独维护两份表，均与 NotificationType / Severity 枚举脱节：
# SEVERITY_LABELS 缺 WARNING（库中实际值），NOTICE_TYPE_LABELS 的键
# 与库中 13 种 notice_type 完全不交集，导致前端显示 "WARNING"、"SPACE_VACANT"。
SEVERITY_LABELS = ENUM_LABELS["Severity"]
NOTICE_TYPE_LABELS = ENUM_LABELS["NotificationType"]

# 关联模块的中文标签。注意：通知里 related_module 存的是「复数路由段」
# （spaces / work-orders / approvals …），与 RBAC 的单数模块键不同，
# 因此这里单独维护一份，不能直接复用 core 的 MODULE_LABELS。
RELATED_MODULE_LABELS = {
    "spaces": "空间管理", "leasing": "招商管理", "enterprises": "企业管理",
    "contracts": "合同管理", "bills": "财务账单", "payments": "收款流水",
    "projects": "项目管理", "work-orders": "物业工单", "devices": "设备管理",
    "energy": "能源管理", "safety": "安全管理", "parking": "停车通行",
    "approvals": "审批中心", "policies": "政策服务", "notifications": "消息通知",
    "agent": "AI 智能体", "system": "系统管理",
}


def _out(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id, "notice_code": n.notice_code,
        "notice_type": n.notice_type,
        "notice_type_label": NOTICE_TYPE_LABELS.get(n.notice_type or "", n.notice_type),
        "title": n.title, "content": n.content, "park_id": n.park_id,
        "severity": n.severity,
        "severity_label": SEVERITY_LABELS.get(n.severity or "", n.severity),
        "related_module": n.related_module,
        "related_object_type": n.related_object_type,
        "related_object_id": n.related_object_id,
        "related_object_name": n.related_object_name,
        "trigger_value": n.trigger_value, "threshold": n.threshold,
        "suggestion": n.suggestion,
        "action_label": n.action_label, "action_route": n.action_route,
        "target_roles": n.target_roles, "target_user_id": n.target_user_id,
        "is_read": n.is_read, "is_handled": n.is_handled,
        "occurred_at": n.occurred_at.isoformat() if n.occurred_at else None,
        "deadline": n.deadline.isoformat() if n.deadline else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "is_demo": True,
    }


def _visible(auth: CurrentAuth) -> Any:
    """通知可见性：园区范围 + 角色定向 + 指定用户。"""
    vis = auth.visible_park_ids()
    clauses = []
    if vis is not None:
        clauses.append(Notification.park_id.in_(vis) if vis
                       else Notification.id == -1)
    role_codes = list(auth.role_codes)
    target = or_(Notification.target_user_id == auth.user.id,
                 Notification.target_user_id.is_(None))
    if role_codes:
        tgt = or_(*[Notification.target_roles.like(f"%{r}%") for r in role_codes])
        target = or_(target, tgt)
    clauses.append(or_(Notification.target_roles.is_(None), target))
    return clauses


@router.get("")
def list_notifications(db: DbSession, auth: CurrentAuth,
                       notice_type: str | None = None, severity: str | None = None,
                       is_read: bool | None = None, is_handled: bool | None = None,
                       related_module: str | None = None,
                       page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """我的通知列表。"""
    auth.require("notification", "VIEW")
    q = select(Notification).where(*_visible(auth))
    if notice_type:
        q = q.where(Notification.notice_type == notice_type)
    if severity:
        q = q.where(Notification.severity == severity)
    if is_read is not None:
        q = q.where(Notification.is_read == is_read)
    if is_handled is not None:
        q = q.where(Notification.is_handled == is_handled)
    if related_module:
        q = q.where(Notification.related_module == related_module)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(
        q.order_by(Notification.occurred_at.desc().nullslast(),
                   Notification.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all())
    items = [_out(n) for n in rows]
    result = {
        "items": items, "total": int(total), "page": page, "page_size": page_size,
        "pages": (int(total) + page_size - 1) // page_size,
        "data_label": "演示数据",
    }
    if page == 1:
        result["stats"] = _stats(db, auth)
    return result


def _stats(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    base = select(Notification).where(*_visible(auth)).subquery()

    def cnt(cond: Any = None) -> int:
        # 条件必须作用在子查询列 base.c.* 上。
        # 若传入 Notification.is_read 这类原始表列，会生成
        #   FROM (subquery), notification WHERE notification.is_read = 0
        # 无连接条件 → 笛卡尔积，得到的是 base行数 × notification全表行数，
        # 出现「未读数 17589 > 总数 41」这类自相矛盾的指标。
        stmt = select(func.count()).select_from(base)
        if cond is not None:
            stmt = stmt.where(cond)
        return int(db.scalar(stmt) or 0)

    sev_rows = db.execute(
        select(base.c.severity, func.count()).group_by(base.c.severity)
    ).all()
    type_rows = db.execute(
        select(base.c.notice_type, func.count()).group_by(base.c.notice_type)
    ).all()
    mod_rows = db.execute(
        select(base.c.related_module, func.count())
        .group_by(base.c.related_module).order_by(func.count().desc()).limit(10)
    ).all()

    now = dt.datetime.now()
    # 待办 = 未处理；紧急 = CRITICAL 未读
    return {
        "total": cnt(),
        "unread": cnt(base.c.is_read.is_(False)),
        "unhandled": cnt(base.c.is_handled.is_(False)),
        "critical_unread": cnt((base.c.severity == "CRITICAL") & (base.c.is_read.is_(False))),
        "overdue": cnt((base.c.deadline.isnot(None)) &
                       (base.c.deadline < now) &
                       (base.c.is_handled.is_(False))),
        "by_severity": {k or "UNKNOWN": int(c) for k, c in sev_rows},
        "by_type": {k or "UNKNOWN": int(c) for k, c in type_rows},
        "by_module": {k or "UNKNOWN": int(c) for k, c in mod_rows},
    }


@router.get("/unread-count")
def unread_count(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """角标：未读数与紧急未读数。"""
    auth.require("notification", "VIEW")
    s = _stats(db, auth)
    return {"unread": s["unread"], "critical_unread": s["critical_unread"],
            "unhandled": s["unhandled"], "overdue": s["overdue"]}


@router.get("/stats")
def stats(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("notification", "VIEW")
    return {**_stats(db, auth), "data_label": "演示数据"}


@router.get("/meta/dict")
def notice_dict(auth: CurrentAuth) -> dict[str, Any]:
    auth.require("notification", "VIEW")
    return {
        "types": [{"key": k, "label": v} for k, v in NOTICE_TYPE_LABELS.items()],
        "severities": [{"key": k, "label": v} for k, v in SEVERITY_LABELS.items()],
        # 统计口径 by_module 用的是复数路由段（spaces / work-orders …），
        # 一并下发标签，避免前端再维护一份字典
        "modules": [{"key": k, "label": v} for k, v in RELATED_MODULE_LABELS.items()],
    }


@router.get("/{notice_id}")
def notice_detail(notice_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("notification", "VIEW")
    n = db.get(Notification, notice_id)
    if not n:
        raise HTTPException(404, "通知不存在")
    vis = auth.visible_park_ids()
    if vis is not None and n.park_id is not None and n.park_id not in vis:
        raise HTTPException(403, "无权查看该通知")
    return {**_out(n), "data_label": "演示数据"}


@router.post("/{notice_id}/read")
def mark_read(notice_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """标记已读（幂等）。"""
    auth.require("notification", "VIEW")
    n = db.get(Notification, notice_id)
    if not n:
        raise HTTPException(404, "通知不存在")
    if not n.is_read:
        n.is_read = True
        write_audit(db, module="notification", action="EDIT", auth=auth,
                    object_type="Notification", object_id=n.id, object_name=n.notice_code,
                    after_value={"is_read": True}, change_summary=f"标记通知「{n.title}」为已读")
        db.commit()
    return {"success": True, "id": n.id, "is_read": n.is_read}


@router.post("/read-all")
def mark_all_read(db: DbSession, auth: CurrentAuth,
                  notice_type: str | None = None) -> dict[str, Any]:
    """全部标记已读（可按类型）。"""
    auth.require("notification", "VIEW")
    q = select(Notification).where(*_visible(auth), Notification.is_read.is_(False))
    if notice_type:
        q = q.where(Notification.notice_type == notice_type)
    rows = list(db.scalars(q).all())
    for n in rows:
        n.is_read = True
    if rows:
        write_audit(db, module="notification", action="EDIT", auth=auth,
                    object_type="Notification", object_id=None,
                    after_value={"count": len(rows), "notice_type": notice_type},
                    change_summary=f"批量标记 {len(rows)} 条通知为已读")
    db.commit()
    return {"success": True, "count": len(rows)}


@router.post("/{notice_id}/handle")
def handle(notice_id: int, db: DbSession, auth: CurrentAuth,
           note: str | None = None) -> dict[str, Any]:
    """标记已处理（业务动作已完成的确认）。"""
    auth.require("notification", "EDIT")
    n = db.get(Notification, notice_id)
    if not n:
        raise HTTPException(404, "通知不存在")
    n.is_read = True
    n.is_handled = True
    if note:
        n.suggestion = (n.suggestion or "") + f"\n[处理说明] {note}"
    write_audit(db, module="notification", action="EDIT", auth=auth,
                object_type="Notification", object_id=n.id, object_name=n.notice_code,
                after_value={"is_handled": True},
                change_summary=f"处理通知「{n.title}」" + (f"：{note}" if note else ""))
    db.commit()
    return {"success": True, "id": n.id, "is_handled": n.is_handled}


@router.get("/timeline/recent")
def recent_timeline(db: DbSession, auth: CurrentAuth, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """最近动态时间轴（供驾驶舱侧栏使用）。"""
    auth.require("notification", "VIEW")
    rows = list(db.scalars(
        select(Notification).where(*_visible(auth))
        .order_by(Notification.occurred_at.desc().nullslast(), Notification.id.desc())
        .limit(limit)).all())
    return {
        "items": [{
            "at": n.occurred_at.isoformat() if n.occurred_at else None,
            "title": n.title, "severity": n.severity,
            "type": NOTICE_TYPE_LABELS.get(n.notice_type or "", n.notice_type),
            "module": RELATED_MODULE_LABELS.get(n.related_module or "", n.related_module),
            "object": {"type": n.related_object_type, "id": n.related_object_id},
            "is_read": n.is_read,
        } for n in rows],
        "data_label": "演示数据",
    }

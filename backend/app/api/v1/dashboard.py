"""经营驾驶舱路由。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.models import Building, Notification, Park, Space
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["经营驾驶舱"])


@router.get("/summary")
def summary(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
            building_id: int | None = None) -> dict[str, Any]:
    auth.require("dashboard", "VIEW")
    park_id = resolve_park(auth, park_id)
    if building_id:
        b = db.get(Building, building_id)
        if not b:
            raise HTTPException(404, "楼宇不存在")
        if not auth.can_access_park(b.park_id):
            raise HTTPException(403, "无权访问该楼宇数据")
        park_id = b.park_id
    return dashboard_service.get_dashboard_summary(db, auth, park_id, building_id)


@router.get("/alerts")
def alerts(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
           limit: int = 20) -> dict[str, Any]:
    """今日洞察与预警（来自通知表，按严重度排序）。"""
    auth.require("dashboard", "VIEW")
    park_id = resolve_park(auth, park_id)
    from sqlalchemy import select

    q = select(Notification).where(Notification.target_user_id == auth.user.id,
                                   Notification.is_read.is_(False))
    unread = list(db.scalars(q).all())
    vis = auth.visible_park_ids()
    q2 = select(Notification)
    if park_id:
        q2 = q2.where(Notification.park_id == park_id)
    elif vis is not None:
        q2 = q2.where(Notification.park_id.in_(vis)) if vis else q2.where(Notification.id == -1)
    alln = list(db.scalars(q2).all())

    sev_rank = {"CRITICAL": 0, "RISK": 1, "WARNING": 2, "INFO": 3}
    alln.sort(key=lambda n: (sev_rank.get(n.severity, 9),
                             -(n.occurred_at.timestamp() if n.occurred_at else 0)))

    # 同一条规则在每个园区各生成一条通知，原样平铺会出现"账单逾期提醒"连刷好几行。
    # 按 notice_type 合并成一行并带上条数，标题只出现一次，读起来才是"几件事"而不是"几条记录"。
    merged: dict[str, dict[str, Any]] = {}
    for n in alln:
        key = n.notice_type or n.title or f"#{n.id}"
        cur = merged.get(key)
        if cur is None:
            merged[key] = {
                "id": n.id, "notice_code": n.notice_code, "notice_type": n.notice_type,
                "title": n.title, "content": n.content, "severity": n.severity,
                "trigger_value": n.trigger_value, "threshold": n.threshold,
                "suggestion": n.suggestion, "action_route": n.action_route,
                "park_id": n.park_id, "related_object_type": n.related_object_type,
                "related_object_id": n.related_object_id,
                "related_object_name": n.related_object_name,
                "related_module": n.related_module, "action_label": n.action_label,
                "occurred_at": n.occurred_at.isoformat() if n.occurred_at else None,
                "deadline": n.deadline.isoformat() if n.deadline else None,
                "is_read": n.is_read, "is_handled": n.is_handled,
                "count": 1,
            }
        else:
            cur["count"] += 1
            # 保留最严重的那条作为代表
            if sev_rank.get(n.severity, 9) < sev_rank.get(cur["severity"], 9):
                cur.update({
                    "severity": n.severity, "content": n.content,
                    "trigger_value": n.trigger_value, "threshold": n.threshold,
                    "suggestion": n.suggestion,
                    "occurred_at": n.occurred_at.isoformat() if n.occurred_at else cur["occurred_at"],
                })

    items = list(merged.values())
    items.sort(key=lambda x: sev_rank.get(x["severity"], 9))
    return {
        "my_unread": len(unread),
        "total": len(items),
        "raw_count": len(alln),
        "items": [
            {**x, "occurred_at": x.get("occurred_at")}
            for x in items[:limit]
        ],
        "severity_count": {k: len([x for x in items if x["severity"] == k])
                           for k in ["CRITICAL", "RISK", "WARNING", "INFO"]},
        "basis": "预警来源：系统规则引擎按业务阈值自动生成，触发值与阈值均随记录一并展示",
        "data_label": "演示数据",
    }


@router.get("/quick-stats")
def quick_stats(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """顶部快捷统计（轻量，供全局框架使用）。"""
    from sqlalchemy import func, select

    vis = auth.visible_park_ids()
    pq = select(func.count(Park.id))
    sq = select(func.count(Space.id)).where(Space.status == "AVAILABLE",
                                            Space.space_type != "PARKING")
    if vis is not None:
        pq = pq.where(Park.id.in_(vis)) if vis else pq.where(Park.id == -1)
        sq = sq.where(Space.park_id.in_(vis)) if vis else sq.where(Space.id == -1)
    return {
        "park_count": db.scalar(pq) or 0,
        "vacant_space_count": db.scalar(sq) or 0,
        "data_label": "演示数据",
    }

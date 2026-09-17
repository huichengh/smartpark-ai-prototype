"""物业服务：工单全流程 + 设备台账 + 巡检 + 能耗 + 安全 + 停车通行。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.audit import write_audit
from app.core.enums import ENERGY_TYPE_ORDER, ENERGY_UNITS, ENUM_LABELS, enum_label
from app.core.permissions import resolve_park_filter as resolve_park
from app.core.security import CurrentAuth, DbSession
from app.services import property_engine, safety_engine
from app.models import (
    AccessRecord,
    Bill,
    Building,
    Device,
    DeviceInspection,
    EnergyRecord,
    Enterprise,
    MeetingRoomBooking,
    Park,
    ParkingSpace,
    SafetyHazard,
    SafetyIncident,
    Space,
    Vehicle,
    Visitor,
    WorkOrder,
)
from app.schemas.common import WorkOrderCreate, paginate

router = APIRouter(prefix="/operation", tags=["运营服务"])

WO_STATUS = {
    "SUBMITTED": "已提交", "CLASSIFIED": "已分类", "DISPATCHED": "已派单",
    "ACCEPTED": "已接单", "PROCESSING": "处理中", "VERIFYING": "待验收",
    "RATED": "已评价", "CLOSED": "已关闭",
}
WO_FLOW = ["SUBMITTED", "CLASSIFIED", "DISPATCHED", "ACCEPTED", "PROCESSING",
           "VERIFYING", "RATED", "CLOSED"]

DEFAULT_SLA_HOURS = {"URGENT": 2, "HIGH": 4, "MEDIUM": 8, "LOW": 24}


# ================================================================ 工单
@router.get("/work-orders")
def list_work_orders(db: DbSession, auth: CurrentAuth,
                     park_id: int | None = None, building_id: int | None = None,
                     status: str | None = None, order_type: str | None = None,
                     priority: str | None = None, timeout_only: bool = False,
                     keyword: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("property", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(WorkOrder)
    if park_id:
        q = q.where(WorkOrder.park_id == park_id)
    elif vis is not None:
        q = q.where(WorkOrder.park_id.in_(vis)) if vis else q.where(WorkOrder.id == -1)
    if building_id:
        q = q.where(WorkOrder.building_id == building_id)
    if status:
        q = q.where(WorkOrder.status == status)
    if order_type:
        q = q.where(WorkOrder.order_type == order_type)
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if keyword:
        q = q.where(or_(WorkOrder.title.contains(keyword),
                        WorkOrder.order_code.contains(keyword)))
    orders = list(db.scalars(q.order_by(WorkOrder.submit_at.desc()).limit(5000)).all())
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    items = []
    for o in orders:
        if timeout_only and not (o.is_timeout and o.status not in ("CLOSED", "RATED")):
            continue
        resp_min = ((o.dispatch_at - o.submit_at).total_seconds() / 60
                    if o.dispatch_at and o.submit_at else None)
        items.append({
            "id": o.id, "order_code": o.order_code, "title": o.title,
            "order_type": o.order_type, "priority": o.priority,
            "status": o.status, "status_name": WO_STATUS.get(o.status, o.status),
            "park_id": o.park_id, "building_id": o.building_id,
            "building_name": buildings.get(o.building_id),
            "space_id": o.space_id, "enterprise_id": o.enterprise_id,
            "reporter_name": o.reporter_name, "reporter_phone": o.reporter_phone,
            "assignee_name": o.assignee_name, "assignee_team": o.assignee_team,
            "description": o.description, "location": o.location,
            "submit_at": o.submit_at.isoformat() if o.submit_at else None,
            "dispatch_at": o.dispatch_at.isoformat() if o.dispatch_at else None,
            "accept_at": o.accept_at.isoformat() if o.accept_at else None,
            "finish_at": o.finish_at.isoformat() if o.finish_at else None,
            "close_at": o.close_at.isoformat() if o.close_at else None,
            "handle_hours": o.handle_hours,
            "response_minutes": round(resp_min, 1) if resp_min is not None else None,
            "sla_hours": o.sla_hours,
            "is_timeout": o.is_timeout,
            "is_open": o.status not in ("CLOSED", "RATED"),
            "rating": o.rating, "rating_comment": o.rating_comment,
            "cost": o.cost,
            "ai_category": o.ai_category,
            "ai_confidence": o.ai_confidence,
            "ai_dispatch_suggestion": o.ai_dispatch_suggestion,
        })
    result = paginate(items, page, page_size)
    closed = [i for i in items if not i["is_open"]]
    handled = [i for i in items if i["handle_hours"]]
    ratings = [i["rating"] for i in items if i["rating"]]
    result["stats"] = {
        "total": len(items),
        "open": len([i for i in items if i["is_open"]]),
        "closed": len(closed),
        "completion_rate": round(len(closed) / len(items) * 100, 2) if items else 0.0,
        "timeout_count": len([i for i in items if i["is_timeout"]]),
        "timeout_rate": round(len([i for i in items if i["is_timeout"]]) / len(items) * 100, 2)
        if items else 0.0,
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in WO_STATUS if len([i for i in items if i["status"] == k])},
        "by_type": {k: {"total": len([i for i in items if i["order_type"] == k]),
                        "timeout": len([i for i in items if i["order_type"] == k
                                        and i["is_timeout"]])}
                    for k in {i["order_type"] for i in items}},
        "by_priority": {k: len([i for i in items if i["priority"] == k])
                        for k in {"URGENT", "HIGH", "MEDIUM", "LOW"}
                        if len([i for i in items if i["priority"] == k])},
        "avg_handle_hours": round(sum(i["handle_hours"] for i in handled) / len(handled), 2)
        if handled else None,
        "avg_response_minutes": round(sum(i["response_minutes"] for i in items
                                          if i["response_minutes"] is not None)
                                      / max(len([i for i in items
                                                 if i["response_minutes"] is not None]), 1), 2),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "rated_count": len(ratings),
    }
    return result


@router.get("/work-orders/{order_id}")
def work_order_detail(order_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("property", "VIEW")
    o = db.get(WorkOrder, order_id)
    if not o or not auth.can_access_park(o.park_id):
        raise HTTPException(404, "工单不存在或无权访问")
    b = db.get(Building, o.building_id) if o.building_id else None
    ent = db.get(Enterprise, o.enterprise_id) if o.enterprise_id else None
    next_idx = WO_FLOW.index(o.status) + 1 if o.status in WO_FLOW else None
    return {
        "order": {
            "id": o.id, "order_code": o.order_code, "title": o.title,
            "order_type": o.order_type, "priority": o.priority,
            "status": o.status, "status_name": WO_STATUS.get(o.status, o.status),
            "description": o.description, "location": o.location,
            "reporter_name": o.reporter_name, "reporter_phone": o.reporter_phone,
            "assignee_name": o.assignee_name, "assignee_team": o.assignee_team,
            "submit_at": o.submit_at.isoformat() if o.submit_at else None,
            "dispatch_at": o.dispatch_at.isoformat() if o.dispatch_at else None,
            "accept_at": o.accept_at.isoformat() if o.accept_at else None,
            "finish_at": o.finish_at.isoformat() if o.finish_at else None,
            "close_at": o.close_at.isoformat() if o.close_at else None,
            "handle_hours": o.handle_hours, "sla_hours": o.sla_hours,
            "is_timeout": o.is_timeout, "rating": o.rating,
            "rating_comment": o.rating_comment, "cost": o.cost,
            "images": o.images, "enterprise_name": o.enterprise_name,
            "ai_category": o.ai_category, "ai_confidence": o.ai_confidence,
            "ai_dispatch_suggestion": o.ai_dispatch_suggestion,
        },
        "building": {"id": b.id, "building_name": b.building_name} if b else None,
        "enterprise": {"id": ent.id, "enterprise_name": ent.enterprise_name} if ent else None,
        "flow": WO_FLOW,
        "flow_names": WO_STATUS,
        "current_index": WO_FLOW.index(o.status) if o.status in WO_FLOW else -1,
        "next_status": WO_FLOW[next_idx] if next_idx is not None and next_idx < len(WO_FLOW) else None,
        "data_label": "演示数据",
    }


@router.post("/work-orders")
def create_work_order(payload: WorkOrderCreate, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """创建工单（真实写库 + SLA 计算 + 审计）。"""
    auth.require("property", "ADD")
    park_id = payload.park_id or auth.user.park_id
    if not park_id:
        raise HTTPException(400, "必须指定园区（park_id）")
    if not auth.can_access_park(park_id):
        raise HTTPException(403, "无权在该园区创建工单")
    now = dt.datetime.now()
    seq = (db.scalar(select(func.count(WorkOrder.id))) or 0) + 1
    sla = DEFAULT_SLA_HOURS.get(payload.priority, 8)
    o = WorkOrder(
        order_code=f"WO{now:%Y%m%d}{seq:05d}",
        title=payload.title, order_type=payload.order_type,
        priority=payload.priority, status="SUBMITTED",
        park_id=park_id, building_id=payload.building_id,
        space_id=payload.space_id, enterprise_id=payload.enterprise_id,
        description=payload.description, reporter_name=auth.user.real_name,
        reporter_phone=auth.user.phone, submit_at=now, sla_hours=sla,
    )
    db.add(o)
    db.flush()
    write_audit(db, module="property", action="ADD", auth=auth, object_type="WorkOrder",
                object_id=o.id, object_name=o.order_code,
                after_value={"title": o.title, "type": o.order_type, "priority": o.priority,
                             "sla_hours": sla},
                change_summary=f"创建工单：{o.title}（优先级 {o.priority}，SLA {sla} 小时）",
                source="USER")
    db.commit()
    return {
        "success": True, "message": f"工单 {o.order_code} 已创建，SLA {sla} 小时",
        "order_id": o.id, "order_code": o.order_code, "status": o.status,
    }


@router.post("/work-orders/{order_id}/action")
def work_order_action(order_id: int, action: str, db: DbSession, auth: CurrentAuth,
                      handler_name: str | None = None, rating: int | None = None,
                      comment: str | None = None) -> dict[str, Any]:
    """工单流转：派单 / 接单 / 开始 / 完工 / 验收 / 关闭 / 评价。

    所有流转都会真实更新状态、时间戳、处理时长、超时标记并写审计。
    """
    auth.require("property", "EDIT")
    action = action.upper()
    if action not in ("DISPATCH", "ACCEPT", "START", "FINISH", "VERIFY", "CLOSE", "RATE"):
        raise HTTPException(400, f"非法动作：{action}")
    o = db.get(WorkOrder, order_id)
    if not o or not auth.can_access_park(o.park_id):
        raise HTTPException(404, "工单不存在或无权访问")

    now = dt.datetime.now()
    before = o.status
    msgs: list[str] = []
    target_map = {"DISPATCH": "DISPATCHED", "ACCEPT": "ACCEPTED", "START": "PROCESSING",
                  "FINISH": "VERIFYING", "VERIFY": "RATED", "CLOSE": "CLOSED", "RATE": "RATED"}
    expected_current = {"DISPATCH": ("SUBMITTED", "CLASSIFIED"), "ACCEPT": ("DISPATCHED",),
                        "START": ("ACCEPTED",), "FINISH": ("PROCESSING",),
                        "VERIFY": ("VERIFYING",), "CLOSE": ("VERIFYING", "RATED"),
                        "RATE": ("VERIFYING", "RATED", "CLOSED")}
    if o.status not in expected_current[action]:
        raise HTTPException(
            400, f"当前状态为「{WO_STATUS.get(o.status, o.status)}」，"
                 f"不允许执行 {action} 动作（需要 "
                 f"{'/'.join(WO_STATUS.get(s, s) for s in expected_current[action])} 状态）")

    if action == "DISPATCH":
        o.dispatch_at = now
        o.assignee_name = handler_name or o.assignee_name or "物业维修班组"
        o.assignee_team = o.assignee_team or "物业工程部"
        msgs.append(f"已派单至：{o.assignee_name}（{o.assignee_team}）")
    elif action == "ACCEPT":
        o.accept_at = now
        msgs.append("维护人员已接单")
    elif action == "START":
        msgs.append("开始处理")
    elif action == "FINISH":
        o.finish_at = now
        o.handle_hours = round((now - o.submit_at).total_seconds() / 3600, 2) if o.submit_at else None
        if o.submit_at and o.dispatch_at:
            o.response_minutes = round((o.dispatch_at - o.submit_at).total_seconds() / 60, 1)
        msgs.append(f"处理完成，累计耗时 {o.handle_hours} 小时")
    elif action in ("VERIFY", "RATE"):
        if rating is not None:
            if not 1 <= rating <= 5:
                raise HTTPException(400, "评分必须在 1~5 之间")
            o.rating = rating
            o.rating_comment = comment
            msgs.append(f"用户评价 {rating} 星")
        else:
            o.status = "VERIFYING"
            msgs.append("验收中")
        if o.status != "VERIFYING":
            o.close_at = now
            if o.submit_at and not o.handle_hours:
                o.handle_hours = round((now - o.submit_at).total_seconds() / 3600, 2)
    elif action == "CLOSE":
        o.close_at = now
        msgs.append("工单已关闭")

    if action != "VERIFY" or rating is not None:
        o.status = target_map[action]

    # 超时判定：处理时长超 SLA，或未完成且已超 SLA 仍未关闭
    if o.status in ("CLOSED", "RATED") and o.handle_hours and o.sla_hours:
        o.is_timeout = o.handle_hours > o.sla_hours
    elif o.status not in ("CLOSED", "RATED") and o.sla_hours and o.submit_at:
        o.is_timeout = (now - o.submit_at).total_seconds() / 3600 > o.sla_hours

    if comment and action != "RATE":
        o.description = (o.description or "") + f"\n[{action}] {comment}"

    write_audit(db, module="property", action="EDIT", auth=auth, object_type="WorkOrder",
                object_id=o.id, object_name=o.order_code,
                before_value={"status": before}, after_value={"status": o.status},
                change_summary=f"工单流转 {before} → {o.status}：" + "；".join(msgs),
                source="USER")
    db.commit()
    return {
        "success": True,
        "message": f"工单 {o.order_code}：" + "；".join(msgs),
        "status": o.status, "status_name": WO_STATUS.get(o.status, o.status),
        "handle_hours": o.handle_hours, "is_timeout": o.is_timeout, "rating": o.rating,
    }


@router.get("/work-orders/stats/by-type")
def work_order_stats(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    """工单统计：聚合指标 + 按类型 / 优先级 / 月度分布。

    聚合指标（open / closed / completion_rate / timeout_* / avg_*）与 AI 工具
    共用 app/services/property_engine.py，页面与 AI 的数字必然一致。
    """
    auth.require("property", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(WorkOrder)
    if park_id:
        q = q.where(WorkOrder.park_id == park_id)
    elif vis is not None:
        q = q.where(WorkOrder.park_id.in_(vis)) if vis else q.where(WorkOrder.id == -1)
    orders = list(db.scalars(q).all())

    stats = property_engine.work_order_stats(orders)
    stats["data_label"] = "演示数据"
    return stats


# ================================================================ 设备
@router.get("/devices")
def list_devices(db: DbSession, auth: CurrentAuth,
                 park_id: int | None = None, building_id: int | None = None,
                 device_type: str | None = None, status: str | None = None,
                 maintain_due: bool = False, fault_only: bool = False,
                 keyword: str | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("device", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Device)
    if park_id:
        q = q.where(Device.park_id == park_id)
    elif vis is not None:
        q = q.where(Device.park_id.in_(vis)) if vis else q.where(Device.id == -1)
    if building_id:
        q = q.where(Device.building_id == building_id)
    if device_type:
        q = q.where(Device.device_type == device_type)
    if status:
        q = q.where(Device.status == status)
    if fault_only:
        q = q.where(Device.status == "FAULT")
    if keyword:
        q = q.where(or_(Device.device_name.contains(keyword),
                        Device.device_code.contains(keyword),
                        Device.serial_no.contains(keyword)))
    devices = list(db.scalars(q).all())
    today = dt.date.today()
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    items = []
    for d in devices:
        due = d.next_maintain_date and d.next_maintain_date <= today + dt.timedelta(days=15)
        if maintain_due and not due:
            continue
        items.append({
            "id": d.id, "device_code": d.device_code, "device_name": d.device_name,
            "device_type": d.device_type, "brand": d.brand, "model": d.model,
            "serial_no": d.serial_no, "park_id": d.park_id,
            "building_id": d.building_id, "building_name": buildings.get(d.building_id),
            "location": d.location, "status": d.status,
            "health_score": d.health_score, "is_online": d.is_online,
            "is_iot_connected": d.is_iot_connected, "install_date": d.install_date.isoformat() if d.install_date else None,
            "warranty_end": d.warranty_end.isoformat() if d.warranty_end else None,
            "service_life_years": d.service_life_years,
            "last_inspect_date": d.last_inspect_date.isoformat() if d.last_inspect_date else None,
            "next_maintain_date": d.next_maintain_date.isoformat() if d.next_maintain_date else None,
            "maintain_due": bool(due),
            "maintain_overdue": bool(d.next_maintain_date and d.next_maintain_date < today),
            "owner_name": d.owner_name, "supplier": d.supplier,
            "purchase_price": d.purchase_price,
        })
    result = paginate(items, page, page_size)
    notscrap = [d for d in devices if d.status != "SCRAPPED"]
    hs = [d.health_score for d in devices if d.health_score is not None]
    result["stats"] = {
        "total": len(items),
        "online": len([d for d in items if d["is_online"]]),
        "online_rate": round(len([d for d in items if d["is_online"]]) / len(notscrap) * 100, 2)
        if notscrap else 0.0,
        "fault_count": len([d for d in items if d["status"] == "FAULT"]),
        "scrapped": len([d for d in items if d["status"] == "SCRAPPED"]),
        "maintain_due": len([d for d in items if d["maintain_due"]]),
        "maintain_overdue": len([d for d in items if d["maintain_overdue"]]),
        "iot_connected": len([d for d in items if d["is_iot_connected"]]),
        "avg_health_score": round(sum(hs) / len(hs), 2) if hs else None,
        "low_health_count": len([d for d in items
                                 if (d["health_score"] or 100) < 55]),
        "by_type": {k: {"total": len([d for d in items if d["device_type"] == k]),
                        "fault": len([d for d in items if d["device_type"] == k
                                      and d["status"] == "FAULT"])}
                    for k in {d["device_type"] for d in items}},
        "by_status": {k: len([d for d in items if d["status"] == k])
                      for k in {d["status"] for d in items}},
    }
    return result


@router.get("/devices/{device_id}")
def device_detail(device_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("device", "VIEW")
    d = db.get(Device, device_id)
    if not d or not auth.can_access_park(d.park_id):
        raise HTTPException(404, "设备不存在或无权访问")
    inspects = list(db.scalars(select(DeviceInspection).where(DeviceInspection.device_id == device_id)
                               .order_by(DeviceInspection.plan_date.desc())).all())
    # WorkOrder 无 device_id 外键，按「同楼宇 + 工单类型含设备名关键字」关联作为可解释的近似口径
    orders = list(db.scalars(select(WorkOrder).where(
        WorkOrder.park_id == d.park_id,
        WorkOrder.building_id == d.building_id,
        WorkOrder.order_type.in_(["设备维修", "维修", "保养"]),
    ).order_by(WorkOrder.submit_at.desc()).limit(30)).all())
    today = dt.date.today()
    return {
        "device": {
            "id": d.id, "device_code": d.device_code, "device_name": d.device_name,
            "device_type": d.device_type, "brand": d.brand, "model": d.model,
            "serial_no": d.serial_no, "location": d.location, "status": d.status,
            "health_score": d.health_score, "is_online": d.is_online,
            "is_iot_connected": d.is_iot_connected,
            "install_date": d.install_date.isoformat() if d.install_date else None,
            "warranty_end": d.warranty_end.isoformat() if d.warranty_end else None,
            "service_life_years": d.service_life_years,
            "last_inspect_date": d.last_inspect_date.isoformat() if d.last_inspect_date else None,
            "next_maintain_date": d.next_maintain_date.isoformat() if d.next_maintain_date else None,
            "owner_name": d.owner_name, "supplier": d.supplier,
            "purchase_price": d.purchase_price, "remark": d.remark,
            "maintain_overdue": bool(d.next_maintain_date and d.next_maintain_date < today),
            "maintain_due_15d": bool(d.next_maintain_date
                                     and d.next_maintain_date <= today + dt.timedelta(days=15)),
        },
        "inspections": [{
            "id": i.id, "inspect_code": i.inspect_code, "inspect_type": i.inspect_type,
            "plan_date": i.plan_date.isoformat() if i.plan_date else None,
            "actual_date": i.actual_date.isoformat() if i.actual_date else None,
            "inspector": i.inspector, "result": i.result,
            "fault_desc": i.fault_desc, "solution": i.solution,
            "cost": i.cost, "status": i.status,
            "is_abnormal": (i.result or "").upper() in ("ABNORMAL", "FAULT", "NG"),
            "next_plan_date": i.next_plan_date.isoformat() if i.next_plan_date else None,
        } for i in inspects],
        "work_orders": [{
            "id": o.id, "order_code": o.order_code, "title": o.title,
            "status": o.status, "priority": o.priority,
            "submit_at": o.submit_at.isoformat() if o.submit_at else None,
            "is_timeout": o.is_timeout,
        } for o in orders],
        "data_label": "演示数据",
    }


# ================================================================ 能源
@router.get("/energy/summary")
def energy_summary(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                   building_id: int | None = None, days: int = 30) -> dict[str, Any]:
    """能源总览：消耗 / 碳排放 / 单位面积 / 异常 / 楼栋排名 / 趋势。"""
    auth.require("energy", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(EnergyRecord)
    if park_id:
        q = q.where(EnergyRecord.park_id == park_id)
    elif vis is not None:
        q = q.where(EnergyRecord.park_id.in_(vis)) if vis else q.where(EnergyRecord.id == -1)
    if building_id:
        q = q.where(EnergyRecord.building_id == building_id)
    recs = list(db.scalars(q).all())
    today = dt.date.today()
    win_start = today - dt.timedelta(days=days)
    cur = [r for r in recs if r.record_date and r.record_date >= win_start]
    prev = [r for r in recs if r.record_date and win_start - dt.timedelta(days=days)
            <= r.record_date < win_start]

    # 标签与单位统一从 core/enums.py 取，避免各处自维护一份中英映射
    labels = ENUM_LABELS["EnergyType"]

    def s(items, et):
        return round(sum(r.consumption or 0 for r in items if r.energy_type == et), 2)

    cur_month = [r for r in recs if r.record_date and r.record_date >= today.replace(day=1)]

    by_type = []
    for et in ENERGY_TYPE_ORDER:
        c = s(cur, et)
        if c == 0 and s(recs, et) == 0:
            continue
        p = s(prev, et)
        by_type.append({
            "key": et, "label": labels.get(et, et), "unit": ENERGY_UNITS.get(et, ""),
            "consumption": c,
            "mom": round((c - p) / p * 100, 2) if p else None,
        })

    areas = {b.id: (b.rentable_area or b.build_area or 0)
             for b in db.scalars(select(Building)).all()}
    building_rows = {}
    for r in cur:
        if r.energy_type != "ELECTRICITY" or not r.building_id:
            continue
        building_rows.setdefault(r.building_id, 0.0)
        building_rows[r.building_id] += r.consumption or 0
    by_building = [{
        "building_id": bid, "building_name": next(
            (b.building_name for b in db.scalars(select(Building).where(Building.id == bid)).all()), None),
        "consumption": round(v, 2),
        "unit_consumption": round(v / areas[bid], 3) if areas.get(bid) else None,
    } for bid, v in building_rows.items()]
    by_building.sort(key=lambda x: -(x["unit_consumption"] or 0))

    # 12 个月趋势
    def shift(d, n):
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return dt.date(y, m, 1)

    m_start = today.replace(day=1)
    trend = []
    for ms in [shift(m_start, -i) for i in range(11, -1, -1)]:
        me = shift(ms, 1)
        mr = [r for r in recs if r.record_date and ms <= r.record_date < me]
        trend.append({
            "month": f"{ms.year}-{ms.month:02d}",
            "ELECTRICITY": s(mr, "ELECTRICITY"), "WATER": s(mr, "WATER"),
            "GAS": s(mr, "GAS"), "PV": s(mr, "PV"),
            "carbon": round(sum(r.carbon_kg or 0 for r in mr), 2),
            "cost": round(sum(r.cost or 0 for r in mr), 2),
        })

    e_area = sum(areas.get(bid, 0) for bid in {r.building_id for r in cur if r.building_id})
    # 时段/峰谷分析依赖 record_hour。演示数据为月度台账（record_hour 为空），
    # 此时必须返回 None 而不是 0：0% 会被读成"夜间用电占比为零"，
    # 而事实是"没有小时级数据"。前端据此显示"—"并提示数据口径。
    has_hourly = any(r.record_hour is not None for r in recs)
    night = [r for r in cur if r.record_hour is not None
             and (r.record_hour >= 22 or r.record_hour < 6)]
    cur_kwh = s(cur, "ELECTRICITY")

    return {
        "window_days": days,
        "by_type": by_type,
        "by_building": by_building[:20],
        "trend": trend,
        "totals": {
            "electricity_month": s(cur_month, "ELECTRICITY"),
            "water_month": s(cur_month, "WATER"),
            "carbon_kg": round(sum(r.carbon_kg or 0 for r in cur), 2),
            "carbon_ton": round(sum(r.carbon_kg or 0 for r in cur) / 1000, 3),
            "cost": round(sum(r.cost or 0 for r in cur), 2),
            "unit_area_consumption": round(s(cur, "ELECTRICITY") / e_area, 3) if e_area else None,
            "night_consumption_ratio": round(s(night, "ELECTRICITY") / cur_kwh * 100, 2)
            if has_hourly and cur_kwh else None,
            "has_hourly_detail": has_hourly,
            "anomaly_count": len([r for r in cur if r.is_anomaly]),
            "pv_generation": s(cur, "PV"),
        },
        "basis": {
            "carbon": "按各能源类型记录的 carbon_kg 字段合计（电网排放因子口径）",
            "unit_area_consumption": "统计窗口内电耗 ÷ 参与统计楼栋的可租面积合计",
            "night_consumption_ratio": "夜间（22:00–06:00）电耗 ÷ 窗口内电耗；"
                                       "需记录含 record_hour，否则返回 null",
            "mom": f"当前 {days} 天窗口 vs 上一个 {days} 天窗口",
        },
        "data_label": "演示数据",
    }


@router.get("/energy/records")
def energy_records(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                   building_id: int | None = None, energy_type: str | None = None,
                   period: str | None = None, anomaly_only: bool = False,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """能耗记录明细。

    period（日间/夜间）按 record_hour 实时推导——原先前端会传这个参数，
    但后端没有接收，导致"选了时段等于没选"，属于静默失效的筛选条件。
    """
    auth.require("energy", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(EnergyRecord)
    if park_id:
        q = q.where(EnergyRecord.park_id == park_id)
    elif vis is not None:
        q = q.where(EnergyRecord.park_id.in_(vis)) if vis else q.where(EnergyRecord.id == -1)
    if period == "夜间":
        q = q.where(or_(EnergyRecord.record_hour >= 22, EnergyRecord.record_hour < 6))
    elif period == "日间":
        q = q.where(EnergyRecord.record_hour >= 6, EnergyRecord.record_hour < 22)
    if building_id:
        q = q.where(EnergyRecord.building_id == building_id)
    if energy_type:
        q = q.where(EnergyRecord.energy_type == energy_type)
    if anomaly_only:
        q = q.where(EnergyRecord.is_anomaly.is_(True))
    recs = list(db.scalars(q.order_by(EnergyRecord.record_date.desc())).all())
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    items = [{
        "id": r.id, "energy_type": r.energy_type,
        "energy_type_name": labels_of(r.energy_type),
        "building_id": r.building_id, "building_name": buildings.get(r.building_id),
        "record_date": r.record_date.isoformat() if r.record_date else None,
        "record_hour": r.record_hour,
        # 无 record_hour（月度台账）时不得默认成"日间"，否则会被读成"这些用电都发生在白天"
        "period": (("夜间" if (r.record_hour >= 22 or r.record_hour < 6) else "日间")
                   if r.record_hour is not None else None),
        "consumption": r.consumption, "unit": r.unit,
        "cost": r.cost, "carbon_kg": r.carbon_kg, "baseline": r.baseline,
        "is_anomaly": r.is_anomaly, "anomaly_ratio": r.anomaly_ratio,
        "anomaly_note": r.anomaly_note,
        "peak_type": _peak_label(r.record_hour),
    } for r in recs]
    return paginate(items, page, page_size)


def _peak_label(hour: int | None) -> str | None:
    """按记录小时推导电价时段（模型未存峰谷字段，由数据实时判定）。"""
    if hour is None:
        return None
    if 8 <= hour < 11 or 18 <= hour < 21:
        return "尖峰"
    if 11 <= hour < 18 or 21 <= hour < 22:
        return "平段"
    return "谷段"


def labels_of(et: str) -> str:
    """能源类型中文名。统一走单一数据源，不要在此再维护一份字典。"""
    return enum_label(et, "EnergyType")


# ================================================================ 安全
@router.get("/safety/summary")
def safety_summary(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    auth.require("safety", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(SafetyIncident)
    if park_id:
        q = q.where(SafetyIncident.park_id == park_id)
    elif vis is not None:
        q = q.where(SafetyIncident.park_id.in_(vis)) if vis else q.where(SafetyIncident.id == -1)
    incs = list(db.scalars(q).all())
    hq = select(SafetyHazard)
    if park_id:
        hq = hq.where(SafetyHazard.park_id == park_id)
    elif vis is not None:
        hq = hq.where(SafetyHazard.park_id.in_(vis)) if vis else hq.where(SafetyHazard.id == -1)
    hazards = list(db.scalars(hq).all())

    open_incs = [i for i in incs if i.status != "CLOSED"]
    critical = [i for i in open_incs if i.risk_level in ("CRITICAL", "URGENT")]
    major = [i for i in open_incs if i.risk_level == "MAJOR"]
    overdue = [i for i in incs if i.is_overdue]
    open_hz = [h for h in hazards if h.status != "CLOSED"]

    # 安全指数走单一数据源（与驾驶舱、安全AI 完全同口径）
    score, status, score_model_detail = safety_engine.score_model(incs)

    by_type = {}
    for i in incs:
        k = i.incident_type or "未分类"
        d = by_type.setdefault(k, {"total": 0, "open": 0, "critical": 0})
        d["total"] += 1
        if i.status != "CLOSED":
            d["open"] += 1
        if i.risk_level in ("CRITICAL", "URGENT"):
            d["critical"] += 1

    hz_by_type = {}
    for h in hazards:
        k = h.hazard_type or "未分类"
        d = hz_by_type.setdefault(k, {"total": 0, "open": 0, "overdue": 0})
        d["total"] += 1
        if h.status != "CLOSED":
            d["open"] += 1
            if h.rectify_deadline and h.rectify_deadline < dt.date.today():
                d["overdue"] += 1

    return {
        "safety_score": score,
        "safety_status": status,
        "score_model": score_model_detail,
        "totals": {
            "total_incidents": len(incs), "open_incidents": len(open_incs),
            "critical_open": len(critical), "overdue_rectify": len(overdue),
            "closure_rate": round((len(incs) - len(open_incs)) / len(incs) * 100, 2) if incs else 0.0,
            "hazard_total": len(hazards), "hazard_open": len(open_hz),
            "hazard_overdue": len([h for h in open_hz if h.rectify_deadline
                                   and h.rectify_deadline < dt.date.today()]),
        },
        "by_type": by_type,
        "hazard_by_type": hz_by_type,
        "data_label": "演示数据",
    }


@router.get("/safety/incidents")
def list_incidents(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                   status: str | None = None, risk_level: str | None = None,
                   incident_type: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("safety", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(SafetyIncident)
    if park_id:
        q = q.where(SafetyIncident.park_id == park_id)
    elif vis is not None:
        q = q.where(SafetyIncident.park_id.in_(vis)) if vis else q.where(SafetyIncident.id == -1)
    if status:
        q = q.where(SafetyIncident.status == status)
    if risk_level:
        q = q.where(SafetyIncident.risk_level == risk_level)
    if incident_type:
        q = q.where(SafetyIncident.incident_type == incident_type)
    rows = list(db.scalars(q.order_by(SafetyIncident.found_at.desc())).all())
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    items = [{
        "id": i.id, "incident_code": i.incident_code, "title": i.title,
        "incident_type": i.incident_type, "risk_level": i.risk_level,
        "status": i.status, "park_id": i.park_id,
        "building_id": i.building_id, "building_name": buildings.get(i.building_id),
        "location": i.location, "description": i.description,
        "found_at": i.found_at.isoformat() if i.found_at else None,
        "found_by": i.found_by, "responsible_person": i.responsible_person,
        "rectify_measure": i.rectify_measure,
        "rectify_deadline": i.rectify_deadline.isoformat() if i.rectify_deadline else None,
        "closed_at": i.closed_at.isoformat() if i.closed_at else None,
        "review_result": i.review_result,
        "handle_hours": i.handle_hours,
        "is_overdue": i.is_overdue,
    } for i in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "open": len([i for i in items if i["status"] != "CLOSED"]),
        "critical_open": len([i for i in items if i["status"] != "CLOSED"
                              and i["risk_level"] in ("CRITICAL", "URGENT")]),
        "overdue": len([i for i in items if i["is_overdue"]]),
        "by_risk": {k: len([i for i in items if i["risk_level"] == k])
                    for k in {i["risk_level"] for i in items}},
        "by_type": {k: len([i for i in items if i["incident_type"] == k])
                    for k in {i["incident_type"] for i in items}},
    }
    return result


@router.get("/safety/hazards")
def list_hazards(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                 status: str | None = None, hazard_level: str | None = None,
                 overdue_only: bool = False,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("safety", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(SafetyHazard)
    if park_id:
        q = q.where(SafetyHazard.park_id == park_id)
    elif vis is not None:
        q = q.where(SafetyHazard.park_id.in_(vis)) if vis else q.where(SafetyHazard.id == -1)
    if status:
        q = q.where(SafetyHazard.status == status)
    if hazard_level:
        q = q.where(SafetyHazard.hazard_level == hazard_level)
    rows = list(db.scalars(q.order_by(SafetyHazard.rectify_deadline)).all())
    today = dt.date.today()
    buildings = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    items = []
    for h in rows:
        od = bool(h.status != "CLOSED" and h.rectify_deadline and h.rectify_deadline < today)
        if overdue_only and not od:
            continue
        items.append({
            "id": h.id, "hazard_code": h.hazard_code, "hazard_type": h.hazard_type,
            "hazard_level": h.hazard_level, "status": h.status, "park_id": h.park_id,
            "location": h.location, "description": h.description,
            "source": h.source, "risk_source_type": h.risk_source_type,
            "responsible_dept": h.responsible_dept,
            "found_date": h.found_date.isoformat() if h.found_date else None,
            "rectify_deadline": h.rectify_deadline.isoformat() if h.rectify_deadline else None,
            "close_date": h.rectify_deadline.isoformat()
            if h.status in ("CLOSED", "RECTIFIED") and h.rectify_deadline else None,
            "days_left": (h.rectify_deadline - today).days if h.rectify_deadline else None,
            "is_overdue": od,
        })
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "open": len([i for i in items if i["status"] != "CLOSED"]),
        "overdue": len([i for i in items if i["is_overdue"]]),
        "by_level": {k: len([i for i in items if i["hazard_level"] == k])
                     for k in {i["hazard_level"] for i in items}},
        "by_type": {k: len([i for i in items if i["hazard_type"] == k])
                    for k in {i["hazard_type"] for i in items}},
    }
    return result


# ================================================================ 停车通行
@router.get("/parking/overview")
def parking_overview(db: DbSession, auth: CurrentAuth, park_id: int | None = None) -> dict[str, Any]:
    auth.require("parking", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(ParkingSpace)
    if park_id:
        q = q.where(ParkingSpace.park_id == park_id)
    elif vis is not None:
        q = q.where(ParkingSpace.park_id.in_(vis)) if vis else q.where(ParkingSpace.id == -1)
    spaces = list(db.scalars(q).all())

    vq = select(Vehicle)
    if park_id:
        vq = vq.where(Vehicle.park_id == park_id)
    elif vis is not None:
        vq = vq.where(Vehicle.park_id.in_(vis)) if vis else vq.where(Vehicle.id == -1)
    vehicles = list(db.scalars(vq).all())

    aq = select(AccessRecord)
    if park_id:
        aq = aq.where(AccessRecord.park_id == park_id)
    elif vis is not None:
        aq = aq.where(AccessRecord.park_id.in_(vis)) if vis else aq.where(AccessRecord.id == -1)
    records = list(db.scalars(aq.order_by(AccessRecord.access_time.desc()).limit(2000)).all())

    visq = select(Visitor)
    if park_id:
        visq = visq.where(Visitor.park_id == park_id)
    elif vis is not None:
        visq = visq.where(Visitor.park_id.in_(vis)) if vis else visq.where(Visitor.id == -1)
    visitors = list(db.scalars(visq).all())

    total = len(spaces)
    occupied = len([s for s in spaces if s.status in ("OCCUPIED", "USED")])
    return {
        "spaces": {
            "total": total,
            "occupied": occupied,
            "available": len([s for s in spaces if s.status in ("AVAILABLE", "FREE")]),
            "reserved": len([s for s in spaces if s.status == "RESERVED"]),
            "occupancy_rate": round(occupied / total * 100, 2) if total else 0.0,
            "by_type": {k: len([s for s in spaces if s.parking_type == k])
                        for k in {s.parking_type for s in spaces}},
        },
        "vehicles": {
            "total": len(vehicles),
            "by_type": {k: len([v for v in vehicles if v.vehicle_type == k])
                        for k in {v.vehicle_type for v in vehicles}},
            "month_card": len([v for v in vehicles if (v.card_type == "MONTH")]),
            "new_energy": len([v for v in vehicles
                                if (v.vehicle_type or "").upper() in ("NEV", "ELECTRIC", "新能源")]),
        },
        "access": {
            "total_records": len(records),
            "today": len([r for r in records if r.access_time
                          and r.access_time.date() == dt.date.today()]),
            "by_gate": {k: len([r for r in records if r.gate_name == k])
                        for k in {r.gate_name for r in records if r.gate_name}},
        },
        "visitors": {
            "total": len(visitors),
            "pending": len([v for v in visitors if v.status == "PENDING"]),
            "in_park": len([v for v in visitors if v.status == "IN_PARK"]),
            "today": len([v for v in visitors if v.visit_time
                          and v.visit_time.date() == dt.date.today()]),
            "approved": len([v for v in visitors if v.status == "APPROVED"]),
        },
        "data_label": "演示数据",
    }


# ================================================================ 会议室 / 活动
@router.get("/meeting-rooms/bookings")
def meeting_bookings(db: DbSession, auth: CurrentAuth, park_id: int | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("service", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(MeetingRoomBooking)
    if park_id:
        q = q.where(MeetingRoomBooking.park_id == park_id)
    elif vis is not None:
        q = q.where(MeetingRoomBooking.park_id.in_(vis)) if vis else q.where(MeetingRoomBooking.id == -1)
    rows = list(db.scalars(q.order_by(MeetingRoomBooking.book_date.desc())).all())
    ents = {e.id: e.enterprise_name for e in db.scalars(select(Enterprise)).all()}
    items = [{
        "id": b.id, "booking_code": b.booking_code,
        "space_id": b.space_id, "space_name": b.space_name,
        "book_date": b.book_date.isoformat() if b.book_date else None,
        "start_time": b.start_time, "end_time": b.end_time,
        "enterprise_id": b.enterprise_id,
        "enterprise_name": b.enterprise_name or ents.get(b.enterprise_id),
        "booker": b.booker, "attendees": b.attendees,
        "status": b.status, "fee": b.fee,
    } for b in rows]
    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "total_fee": round(sum(i["fee"] or 0 for i in items), 2),
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in {i["status"] for i in items}},
    }
    return result

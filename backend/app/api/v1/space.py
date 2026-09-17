"""园区、楼宇、空间资产路由（含 2.5D 数字孪生）。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.core.security import CurrentAuth, DbSession, perm_guard
from app.models import (
    Building,
    Contract,
    Device,
    EnergyRecord,
    Enterprise,
    Floor,
    Park,
    SafetyIncident,
    Space,
    WorkOrder,
)
from app.core.permissions import resolve_park_filter as resolve_park
from app.schemas.common import paginate
from app.services import dashboard_service

router = APIRouter(prefix="/space", tags=["空间资产"])


# ---------------------------------------------------------------- 园区
@router.get("/parks")
def list_parks(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("park", "VIEW")
    vis = auth.visible_park_ids()
    q = select(Park).order_by(Park.park_code, Park.id)
    if vis is not None:
        q = q.where(Park.id.in_(vis)) if vis else q.where(Park.id == -1)
    parks = list(db.scalars(q).all())
    today = dt.date.today()
    items = []
    for p in parks:
        buildings = list(db.scalars(select(Building).where(Building.park_id == p.id)).all())
        spaces = list(db.scalars(select(Space).where(Space.park_id == p.id,
                                                     Space.space_type != "PARKING")).all())
        total_area = sum(s.rentable_area or s.area or 0 for s in spaces)
        rented_area = sum(s.rentable_area or s.area or 0 for s in spaces if s.status == "RENTED")
        ents = db.scalar(select(func.count(Enterprise.id)).where(
            Enterprise.park_id == p.id, Enterprise.status.in_(["SETTLED", "GROWING", "RISK"]))) or 0
        items.append({
            "id": p.id, "park_code": p.park_code, "park_name": p.park_name,
            "park_type": p.park_type, "city": p.city, "address": p.address,
            "total_area": p.total_area, "build_area": p.build_area,
            "rentable_area": p.rentable_area, "green_area": p.green_area,
            "manager_name": p.manager_name, "contact_phone": p.contact_phone,
            "status": p.status, "template_id": p.template_id,
            "building_count": len(buildings),
            "space_count": len(spaces),
            "rented_area_calc": round(rented_area, 2),
            "occupancy_rate": round(rented_area / total_area * 100, 2) if total_area else 0.0,
            "enterprise_count": ents,
        })
    return {"items": items, "total": len(items), "data_label": "演示数据"}


@router.get("/parks/{park_id}/twin")
def park_twin(park_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """2.5D 数字孪生数据：楼栋坐标 + 实时状态。"""
    auth.require("park", "VIEW")
    park = db.get(Park, park_id)
    if not park:
        raise HTTPException(404, "园区不存在")
    if not auth.can_access_park(park_id):
        raise HTTPException(403, "无权访问该园区数据")

    today = dt.date.today()
    buildings = list(db.scalars(
        select(Building).where(Building.park_id == park_id).order_by(Building.building_code, Building.id)
    ).all())
    spaces = list(db.scalars(select(Space).where(Space.park_id == park_id,
                                                 Space.space_type != "PARKING")).all())
    devices = list(db.scalars(select(Device).where(Device.park_id == park_id)).all())
    ents = {e.id: e for e in db.scalars(select(Enterprise).where(Enterprise.park_id == park_id)).all()}
    orders = list(db.scalars(select(WorkOrder).where(WorkOrder.park_id == park_id)).all())
    incidents = list(db.scalars(select(SafetyIncident).where(SafetyIncident.park_id == park_id)).all())
    month_start = today.replace(day=1)
    energy = list(db.scalars(select(EnergyRecord).where(
        EnergyRecord.park_id == park_id, EnergyRecord.record_date >= month_start)).all())

    nodes = []
    for b in buildings:
        bs = [s for s in spaces if s.building_id == b.id]
        area = sum(s.rentable_area or s.area or 0 for s in bs)
        rented = sum(s.rentable_area or s.area or 0 for s in bs if s.status == "RENTED")
        vacant = [s for s in bs if s.status == "AVAILABLE"]
        b_dev = [d for d in devices if d.building_id == b.id]
        b_ord = [o for o in orders if o.building_id == b.id and o.status not in ("CLOSED", "RATED")]
        b_inc = [i for i in incidents if i.building_id == b.id and i.status != "CLOSED"]
        b_kwh = sum(e.consumption or 0 for e in energy
                    if e.building_id == b.id and e.energy_type == "ELECTRICITY")
        occ = round(rented / area * 100, 2) if area else 0.0
        # 颜色分级：出租率 + 风险
        if b_inc:
            level = "RISK"
        elif occ >= 90:
            level = "GOOD"
        elif occ >= 70:
            level = "NORMAL"
        else:
            level = "VACANT"
        nodes.append({
            "id": b.id, "building_code": b.building_code, "building_name": b.building_name,
            "building_type": b.building_type, "floor_count": b.floor_count,
            "build_area": b.build_area, "rentable_area": round(area, 2),
            "rented_area": round(rented, 2),
            "occupancy_rate": occ,
            "space_count": len(bs), "rented_count": len([s for s in bs if s.status == "RENTED"]),
            "vacant_count": len(vacant), "vacant_area": round(sum(s.rentable_area or s.area or 0 for s in vacant), 2),
            "enterprise_count": len({s.enterprise_id for s in bs if s.enterprise_id}),
            "device_count": len(b_dev), "device_fault": len([d for d in b_dev if d.status == "FAULT"]),
            "open_work_order": len(b_ord), "open_incident": len(b_inc),
            "energy_month_kwh": round(b_kwh, 2),
            "level": level,
            "map_x": b.map_x, "map_y": b.map_y, "map_w": b.map_w, "map_d": b.map_d, "map_h": b.map_h,
            "status": b.status,
        })

    # 园区道路 / 绿化 / 出入口（演示用的语义化占位，坐标来自园区模板）
    import json as _json

    layout: dict[str, Any] = {}
    if park.template_id:
        row = db.execute(select(func.count()).select_from(Park)).scalar()
        _ = row
    try:
        layout = _json.loads(park.layout_json) if getattr(park, "layout_json", None) else {}
    except Exception:
        layout = {}

    return {
        "park": {
            "id": park.id, "park_code": park.park_code, "park_name": park.park_name,
            "park_type": park.park_type, "city": park.city, "address": park.address,
            "total_area": park.total_area, "build_area": park.build_area,
        },
        "nodes": nodes,
        "layout": layout,
        "stats": {
            "building_count": len(buildings),
            "space_count": len(spaces),
            "occupancy_rate": round(
                sum(s.rentable_area or s.area or 0 for s in spaces if s.status == "RENTED")
                / (sum(s.rentable_area or s.area or 0 for s in spaces) or 1) * 100, 2),
            "enterprise_count": len(ents),
            "risk_building_count": len([n for n in nodes if n["level"] == "RISK"]),
            "vacant_building_count": len([n for n in nodes if n["level"] == "VACANT"]),
        },
        "legend": [
            {"key": "GOOD", "name": "运营良好（出租率≥90%）", "color": "#1FB6A6"},
            {"key": "NORMAL", "name": "正常（出租率70%-90%）", "color": "#2F80ED"},
            {"key": "VACANT", "name": "招商压力（出租率<70%）", "color": "#F2994A"},
            {"key": "RISK", "name": "存在风险（有未闭环安全事件）", "color": "#EB5757"},
        ],
        "data_label": "演示数据",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- 楼宇
@router.get("/buildings")
def list_buildings(db: DbSession, auth: CurrentAuth,
                   park_id: int | None = None, keyword: str | None = None,
                   building_type: str | None = None, level: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    # 楼宇属于「空间资产管理」范畴。RBAC 的 22 个模块里只有 space，
    # 没有 building；早期写成 "building" 会让所有非集团管理员直接 403。
    auth.require("space", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Building)
    if park_id:
        q = q.where(Building.park_id == park_id)
    elif vis is not None:
        q = q.where(Building.park_id.in_(vis)) if vis else q.where(Building.id == -1)
    if keyword:
        q = q.where(or_(Building.building_name.contains(keyword),
                        Building.building_code.contains(keyword)))
    if building_type:
        q = q.where(Building.building_type == building_type)
    buildings = list(db.scalars(q.order_by(Building.building_code, Building.id)).all())

    spaces = list(db.scalars(select(Space).where(Space.space_type != "PARKING")).all())
    items = []
    for b in buildings:
        bs = [s for s in spaces if s.building_id == b.id]
        area = sum(s.rentable_area or s.area or 0 for s in bs)
        rented = sum(s.rentable_area or s.area or 0 for s in bs if s.status == "RENTED")
        occ = round(rented / area * 100, 2) if area else 0.0
        row = {
            "id": b.id, "building_code": b.building_code, "building_name": b.building_name,
            "building_type": b.building_type, "park_id": b.park_id,
            "floor_count": b.floor_count, "underground_floors": b.underground_floors,
            "build_area": b.build_area, "rentable_area": round(area, 2),
            "rented_area": round(rented, 2), "occupancy_rate": occ,
            "space_count": len(bs), "enterprise_count": len({s.enterprise_id for s in bs if s.enterprise_id}),
            "completion_date": b.completion_date.isoformat() if b.completion_date else None,
            "property_manager": b.property_manager, "status": b.status,
            "map_x": b.map_x, "map_y": b.map_y, "map_w": b.map_w, "map_d": b.map_d, "map_h": b.map_h,
        }
        if level == "RISK" and not (occ < 70):
            continue
        items.append(row)
    if level == "VACANT":
        items = [i for i in items if i["occupancy_rate"] < 70]
    return paginate(items, page, page_size)


@router.get("/buildings/{building_id}")
def building_detail(building_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """一楼一档。"""
    auth.require("space", "VIEW")
    data = dashboard_service.get_building_detail(db, auth, building_id)
    if not data:
        raise HTTPException(404, "楼宇不存在或无权访问")
    return data


# ---------------------------------------------------------------- 空间
@router.get("/spaces")
def list_spaces(db: DbSession, auth: CurrentAuth,
                park_id: int | None = None, building_id: int | None = None,
                floor_id: int | None = None,
                space_type: str | None = None, status: str | None = None,
                keyword: str | None = None,
                min_area: float | None = None, max_area: float | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("space", "VIEW")
    park_id = resolve_park(auth, park_id)
    vis = auth.visible_park_ids()
    q = select(Space)
    if park_id:
        q = q.where(Space.park_id == park_id)
    elif vis is not None:
        q = q.where(Space.park_id.in_(vis)) if vis else q.where(Space.id == -1)
    if building_id:
        q = q.where(Space.building_id == building_id)
    if floor_id:
        q = q.where(Space.floor_id == floor_id)
    if space_type:
        q = q.where(Space.space_type == space_type)
    if status:
        q = q.where(Space.status == status)
    if keyword:
        q = q.where(or_(Space.space_name.contains(keyword), Space.space_code.contains(keyword)))
    if min_area is not None:
        q = q.where(Space.area >= min_area)
    if max_area is not None:
        q = q.where(Space.area <= max_area)
    spaces = list(db.scalars(q.order_by(Space.building_id, Space.floor_id, Space.space_code)).all())

    bmap = {b.id: b.building_name for b in db.scalars(select(Building)).all()}
    fmap = {f.id: f.floor_name for f in db.scalars(select(Floor)).all()}
    emap = {e.id: e.enterprise_name for e in db.scalars(select(Enterprise)).all()}
    today = dt.date.today()
    items = []
    for s in spaces:
        items.append({
            "id": s.id, "space_code": s.space_code, "space_name": s.space_name,
            "space_type": s.space_type, "status": s.status,
            "park_id": s.park_id, "building_id": s.building_id,
            "building_name": bmap.get(s.building_id), "floor_id": s.floor_id,
            "floor_name": fmap.get(s.floor_id),
            "area": s.area, "rentable_area": s.rentable_area,
            "rent_price": s.rent_price, "property_price": s.property_price,
            "enterprise_id": s.enterprise_id,
            "enterprise_name": emap.get(s.enterprise_id),
            "lease_start": s.lease_start.isoformat() if s.lease_start else None,
            "lease_end": s.lease_end.isoformat() if s.lease_end else None,
            "vacant_days": (today - s.vacant_since).days if s.vacant_since else None,
            "monthly_rent": round((s.rentable_area or s.area or 0) * (s.rent_price or 0), 2),
        })
    result = paginate(items, page, page_size)
    # 统计（按筛选后的全集，非当前页）
    result["stats"] = {
        "total": len(items),
        "by_status": {k: len([i for i in items if i["status"] == k])
                      for k in {i["status"] for i in items}},
        "total_area": round(sum(i["rentable_area"] or i["area"] or 0 for i in items), 2),
        "rented_area": round(sum(i["rentable_area"] or i["area"] or 0 for i in items
                                 if i["status"] == "RENTED"), 2),
        "vacant_area": round(sum(i["rentable_area"] or i["area"] or 0 for i in items
                                 if i["status"] == "AVAILABLE"), 2),
        "occupancy_rate": round(
            sum(i["rentable_area"] or i["area"] or 0 for i in items if i["status"] == "RENTED")
            / (sum(i["rentable_area"] or i["area"] or 0 for i in items) or 1) * 100, 2),
    }
    return result


@router.get("/spaces/{space_id}")
def space_detail(space_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    auth.require("space", "VIEW")
    s = db.get(Space, space_id)
    if not s or not auth.can_access_park(s.park_id):
        raise HTTPException(404, "空间不存在或无权访问")
    b = db.get(Building, s.building_id) if s.building_id else None
    f = db.get(Floor, s.floor_id) if s.floor_id else None
    ent = db.get(Enterprise, s.enterprise_id) if s.enterprise_id else None
    contracts = list(db.scalars(select(Contract).where(Contract.space_id == space_id)).all())
    orders = list(db.scalars(select(WorkOrder).where(WorkOrder.space_id == space_id)
                             .order_by(WorkOrder.submit_at.desc())).all())
    return {
        "space": {
            "id": s.id, "space_code": s.space_code, "space_name": s.space_name,
            "space_type": s.space_type, "status": s.status, "area": s.area,
            "rentable_area": s.rentable_area, "rent_price": s.rent_price,
            "property_price": s.property_price, "orientation": s.orientation,
            "floor_height": s.floor_height, "load_bearing": s.load_bearing,
            "has_air_condition": s.has_air_condition, "has_network": s.has_network,
            "has_power_capacity": s.has_power_capacity, "remark": s.remark,
            "lease_start": s.lease_start.isoformat() if s.lease_start else None,
            "lease_end": s.lease_end.isoformat() if s.lease_end else None,
            "vacant_since": s.vacant_since.isoformat() if s.vacant_since else None,
        },
        "building": {"id": b.id, "building_name": b.building_name,
                     "building_type": b.building_type} if b else None,
        "floor": {"id": f.id, "floor_name": f.floor_name,
                  "floor_number": f.floor_number} if f else None,
        "enterprise": {"id": ent.id, "enterprise_name": ent.enterprise_name,
                       "industry": ent.industry, "status": ent.status} if ent else None,
        "contracts": [{"id": c.id, "contract_code": c.contract_code,
                       "contract_name": c.contract_name, "monthly_rent": c.monthly_rent,
                       "status": c.status,
                       "start_date": c.start_date.isoformat() if c.start_date else None,
                       "end_date": c.end_date.isoformat() if c.end_date else None}
                      for c in contracts],
        "work_orders": [{"id": o.id, "order_code": o.order_code, "title": o.title,
                         "status": o.status, "priority": o.priority,
                         "submit_at": o.submit_at.isoformat() if o.submit_at else None}
                        for o in orders[:20]],
        "data_label": "演示数据",
    }


@router.get("/spaces/board/{building_id}")
def space_board(building_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """一房一状态：楼栋楼层-空间矩阵视图。"""
    auth.require("space", "VIEW")
    b = db.get(Building, building_id)
    if not b or not auth.can_access_park(b.park_id):
        raise HTTPException(404, "楼宇不存在或无权访问")
    floors = list(db.scalars(select(Floor).where(Floor.building_id == building_id)
                             .order_by(Floor.floor_number.desc())).all())
    spaces = list(db.scalars(select(Space).where(Space.building_id == building_id)).all())
    emap = {e.id: e.enterprise_name for e in db.scalars(select(Enterprise)).all()}
    rows = []
    for f in floors:
        fs = [s for s in spaces if s.floor_id == f.id]
        fs.sort(key=lambda x: x.space_code or "")
        rows.append({
            "floor_id": f.id, "floor_name": f.floor_name,
            "floor_number": f.floor_number,
            "build_area": f.build_area, "rentable_area": f.rentable_area,
            "usage": f.usage,
            "spaces": [{
                "id": s.id, "space_code": s.space_code, "space_name": s.space_name,
                "space_type": s.space_type, "status": s.status,
                "area": s.area, "rent_price": s.rent_price,
                "enterprise_name": emap.get(s.enterprise_id),
                "lease_end": s.lease_end.isoformat() if s.lease_end else None,
            } for s in fs],
        })
    return {
        "building": {"id": b.id, "building_code": b.building_code,
                     "building_name": b.building_name, "building_type": b.building_type,
                     "floor_count": b.floor_count, "build_area": b.build_area},
        "rows": rows,
        "status_legend": [
            {"key": "RENTED", "name": "已出租", "color": "#2F80ED"},
            {"key": "AVAILABLE", "name": "可租", "color": "#1FB6A6"},
            {"key": "RESERVED", "name": "已预留", "color": "#F2C94C"},
            {"key": "SELF_USE", "name": "自用", "color": "#7B61FF"},
            {"key": "RENOVATING", "name": "装修中", "color": "#F2994A"},
            {"key": "MAINTENANCE", "name": "维护中", "color": "#9B9B9B"},
            {"key": "FROZEN", "name": "冻结", "color": "#EB5757"},
        ],
        "data_label": "演示数据",
    }

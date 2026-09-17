"""系统管理路由：组织、园区模板、用户、角色、权限、数据权限范围。

权限体系说明（需求书第 15-16 节）：
  RBAC（角色 × 模块 × 动作）+ 数据权限（组织层级可见范围）双模型。
  本模块是权限的唯一配置入口，所有变更均写审计日志。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.audit import write_audit
from app.core.enums import (
    ACTION_LABELS,
    MODULE_LABELS,
    AIPermissionLevel,
    ContractStatus,
    EnterpriseStatus,
    LeadStage,
    ManagementMethod,
    NotificationType,
    ParkType,
    ProjectStatus,
    ProjectType,
    RiskLevel,
    Severity,
    SpaceStatus,
    SpaceType,
    WorkOrderStatus,
    enum_label,
)
from app.core.security import (
    CurrentAuth,
    DbSession,
    hash_password,
    load_auth_context,
)
from app.models import (
    Organization,
    Park,
    ParkTemplate,
    Permission,
    Project,
    Role,
    RolePermission,
    User,
    UserParkScope,
    UserProjectScope,
    UserRole,
)
from app.schemas.common import UserCreate, UserUpdate, paginate

router = APIRouter(prefix="/system", tags=["系统管理"])

DATA_SCOPE_LABELS = {
    "GROUP": "集团全域", "PARK": "本园区", "DEPARTMENT": "本部门",
    "PROJECT": "参与项目", "ENTERPRISE": "本企业", "SELF": "仅本人",
}
# ACTION_LABELS / MODULE_LABELS 统一由 app.core.enums 提供，此处不再重复定义。


# ================================================================ 字典

@router.get("/dict")
def dicts(auth: CurrentAuth) -> dict[str, Any]:
    """全局枚举字典（前端下拉统一来源，避免前端硬编码）。"""
    auth.require("system", "VIEW")

    def opts(enum_cls: Any) -> list[dict[str, str]]:
        # 传枚举类名，精确命中重名枚举值（如 RISK / OFFICE / SIGNED）
        group = enum_cls.__name__
        return [{"key": m.value, "label": enum_label(m.value, group)} for m in enum_cls]

    return {
        "management_method": opts(ManagementMethod),
        "project_status": opts(ProjectStatus),
        "project_type": opts(ProjectType),
        "risk_level": opts(RiskLevel),
        "space_status": opts(SpaceStatus),
        "space_type": opts(SpaceType),
        "enterprise_status": opts(EnterpriseStatus),
        "lead_stage": opts(LeadStage),
        "contract_status": opts(ContractStatus),
        "work_order_status": opts(WorkOrderStatus),
        "park_type": opts(ParkType),
        "notification_type": opts(NotificationType),
        "severity": opts(Severity),
        "ai_permission_level": opts(AIPermissionLevel),
        "data_scope": [{"key": k, "label": v} for k, v in DATA_SCOPE_LABELS.items()],
        "module": [{"key": k, "label": v} for k, v in MODULE_LABELS.items()],
        "action": [{"key": k, "label": v} for k, v in ACTION_LABELS.items()],
    }


# 枚举中文标签统一由 app.core.enums 提供（ENUM_LABELS / enum_label），
# 本模块不再维护第二份，避免与枚举定义漂移。


# ================================================================ 组织

@router.get("/organizations")
def organizations(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """组织树（集团 → 区域公司 → 园区）。"""
    auth.require("system", "VIEW")
    orgs = list(db.scalars(select(Organization).order_by(Organization.id)).all())
    parks = list(db.scalars(select(Park).order_by(Park.park_code, Park.id)).all())

    vis = auth.visible_park_ids()
    if vis is not None:
        parks = [p for p in parks if p.id in vis]

    park_by_org: dict[int, list[dict[str, Any]]] = {}
    for p in parks:
        park_by_org.setdefault(p.organization_id or 0, []).append({
            "id": p.id, "park_code": p.park_code, "park_name": p.park_name,
            "short_name": p.short_name, "park_type": p.park_type,
            "park_type_label": enum_label(p.park_type, "ParkType"),
            "status": p.status, "operation_mode": p.operation_mode,
            "building_count": p.building_count, "build_area": p.build_area,
            "rentable_area": p.rentable_area,
            "manager_name": p.manager_name, "contact_phone": p.contact_phone,
        })

    items = []
    for o in orgs:
        items.append({
            "id": o.id, "org_code": o.org_code, "org_name": o.org_name,
            "short_name": o.short_name, "tenant_key": o.tenant_key,
            "contact_person": o.contact_person, "contact_phone": o.contact_phone,
            "address": o.address, "status": o.status, "remark": o.remark,
            "parks": park_by_org.get(o.id, []),
            "park_count": len(park_by_org.get(o.id, [])),
        })
    return {
        "items": items,
        "summary": {"org_total": len(items),
                    "park_total": len(parks),
                    "org_types": _org_levels(items)},
        "data_label": "演示数据",
    }


def _org_levels(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """组织层级统计：有下辖园区的视为区域公司，其余为集团/直属。"""
    regional = [i for i in items if i["park_count"] > 0]
    return [
        {"level": 1, "name": "集团/直属", "count": len(items) - len(regional)},
        {"level": 2, "name": "区域公司", "count": len(regional)},
    ]


@router.get("/parks")
def parks(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """园区列表（含模板与启用模块）。"""
    auth.require("system", "VIEW")
    vis = auth.visible_park_ids()
    q = select(Park)
    if vis is not None:
        q = q.where(Park.id.in_(vis)) if vis else q.where(Park.id == -1)
    rows = list(db.scalars(q.order_by(Park.park_code, Park.id)).all())

    tpl_map = {t.id: t for t in db.scalars(select(ParkTemplate)).all()}
    counts = dict(db.execute(
        select(Organization.id, func.count(Park.id))
        .join(Park, Park.organization_id == Organization.id)
        .group_by(Organization.id)).all()) if rows else {}

    items = [{
        "id": p.id, "park_code": p.park_code, "park_name": p.park_name,
        "short_name": p.short_name, "organization_id": p.organization_id,
        "template_id": p.template_id,
        "template_name": (tpl_map[p.template_id].template_name
                          if p.template_id in tpl_map else None),
        "park_type": p.park_type, "park_type_label": enum_label(p.park_type, "ParkType"),
        "province": p.province, "city": p.city, "district": p.district,
        "address": p.address, "longitude": p.longitude, "latitude": p.latitude,
        "total_area": p.total_area, "build_area": p.build_area,
        "rentable_area": p.rentable_area, "green_area": p.green_area,
        "building_count": p.building_count,
        "established_date": p.established_date.isoformat() if p.established_date else None,
        "manager_name": p.manager_name, "contact_phone": p.contact_phone,
        "operation_mode": p.operation_mode,
        "enabled_modules": p.enabled_modules,
        "status": p.status, "remark": p.remark,
    } for p in rows]
    return {"items": items, "total": len(items), "data_label": "演示数据"}


# ================================================================ 园区模板

@router.get("/templates")
def templates(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """可配置园区模板（决定该园区启用哪些模块与看板 KPI）。"""
    auth.require("system", "VIEW")
    rows = list(db.scalars(select(ParkTemplate).order_by(ParkTemplate.sort_order,
                                                         ParkTemplate.id)).all())
    park_cnt = dict(db.execute(
        select(Park.template_id, func.count(Park.id))
        .where(Park.template_id.isnot(None))
        .group_by(Park.template_id)).all())
    items = [{
        "id": t.id, "template_code": t.template_code, "template_name": t.template_name,
        "park_type": t.park_type, "park_type_label": enum_label(t.park_type, "ParkType"),
        "description": t.description,
        "enabled_modules": t.enabled_modules,
        "module_count": len(t.enabled_modules or []),
        "focus_areas": t.focus_areas, "dashboard_kpis": t.dashboard_kpis,
        "default_space_types": t.default_space_types,
        "is_system": t.is_system, "sort_order": t.sort_order,
        "park_count": int(park_cnt.get(t.id, 0)),
    } for t in rows]
    return {"items": items, "total": len(items), "data_label": "演示数据"}


@router.post("/templates/{tpl_id}/toggle-module")
def toggle_template_module(tpl_id: int, db: DbSession, auth: CurrentAuth,
                           module: str = Query(...), enabled: bool = Query(...)) -> dict[str, Any]:
    """启用/停用模板模块（真实写库 + 审计）——园区模块可配置能力。"""
    auth.require("system", "CONFIG")
    t = db.get(ParkTemplate, tpl_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    modules = list(t.enabled_modules or [])
    before = list(modules)
    if enabled and module not in modules:
        modules.append(module)
    elif not enabled and module in modules:
        modules.remove(module)
    else:
        return {"success": True, "message": "状态未变化", "enabled_modules": modules}
    t.enabled_modules = modules
    write_audit(db, module="system", action="CONFIG", auth=auth,
                object_type="ParkTemplate", object_id=t.id, object_name=t.template_code,
                before_value={"enabled_modules": before},
                after_value={"enabled_modules": modules},
                change_summary=(f"模板「{t.template_name}」"
                                f"{'启用' if enabled else '停用'}模块 {module}"))
    db.commit()
    return {"success": True, "enabled_modules": modules,
            "message": f"已{'启用' if enabled else '停用'}模块 {module}"}


# ================================================================ 用户

@router.get("/users")
def users(db: DbSession, auth: CurrentAuth,
          keyword: str | None = None, role_code: str | None = None,
          park_id: int | None = None, status: str | None = None,
          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    auth.require("system", "VIEW")
    vis = auth.visible_park_ids()

    q = select(User)
    if vis is not None:
        q = q.where(or_(User.park_id.in_(vis), User.park_id.is_(None))) if vis \
            else q.where(User.id == auth.user.id)
    if keyword:
        like = f"%{keyword}%"
        q = q.where(or_(User.username.like(like), User.real_name.like(like),
                        User.phone.like(like), User.email.like(like)))
    if park_id:
        q = q.where(User.park_id == park_id)
    if status:
        q = q.where(User.status == status)

    rows = list(db.scalars(q.order_by(User.id)).all())

    role_map = _user_role_map(db, [u.id for u in rows])
    if role_code:
        rows = [u for u in rows
                if role_code in {r["role_code"] for r in role_map.get(u.id, [])}]

    scope_map = _user_park_map(db, [u.id for u in rows])
    park_names = {p.id: p.park_name for p in db.scalars(select(Park)).all()}

    items = []
    for u in rows:
        roles = role_map.get(u.id, [])
        items.append({
            "id": u.id, "username": u.username, "real_name": u.real_name,
            "phone": u.phone, "email": u.email, "avatar": u.avatar,
            "organization_id": u.organization_id,
            "park_id": u.park_id,
            "park_name": park_names.get(u.park_id),
            "enterprise_id": u.enterprise_id,
            "department": u.department, "position": u.position,
            "status": u.status,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "is_demo": u.is_demo,
            "roles": roles,
            "role_label": "、".join(r["role_name"] for r in roles) or "未分配角色",
            "data_scope": roles[0]["data_scope"] if roles else "SELF",
            "extra_park_ids": scope_map.get(u.id, []),
            "extra_parks": [park_names.get(i) for i in scope_map.get(u.id, [])],
        })

    result = paginate(items, page, page_size)
    result["stats"] = {
        "total": len(items),
        "active": len([i for i in items if i["status"] == "ACTIVE"]),
        "disabled": len([i for i in items if i["status"] != "ACTIVE"]),
        "by_role": _count_by(items, lambda i: i["role_label"]),
        "by_park": _count_by(items, lambda i: i["park_name"] or "集团/未绑定"),
    }
    result["data_label"] = "演示数据"
    return result


def _count_by(items: list[dict[str, Any]], fn: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        k = fn(i)
        out[k] = out.get(k, 0) + 1
    return out


def _user_role_map(db: DbSession, uids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not uids:
        return {}
    rows = db.execute(
        select(UserRole.user_id, Role.role_code, Role.role_name, Role.data_scope)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(uids))
    ).all()
    out: dict[int, list[dict[str, Any]]] = {}
    for uid, code, name, scope in rows:
        out.setdefault(uid, []).append(
            {"role_code": code, "role_name": name, "data_scope": scope})
    return out


def _user_park_map(db: DbSession, uids: list[int]) -> dict[int, list[int]]:
    if not uids:
        return {}
    rows = db.execute(
        select(UserParkScope.user_id, UserParkScope.park_id)
        .where(UserParkScope.user_id.in_(uids))
    ).all()
    out: dict[int, list[int]] = {}
    for uid, pid in rows:
        out.setdefault(uid, []).append(pid)
    return out


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """一账号一档：角色、数据范围、参与项目、登录情况。"""
    auth.require("system", "VIEW")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    vis = auth.visible_park_ids()
    if vis is not None and u.park_id is not None and u.park_id not in vis and u.id != auth.user.id:
        raise HTTPException(403, "无权查看该用户")

    roles = _user_role_map(db, [u.id]).get(u.id, [])
    park_ids = _user_park_map(db, [u.id]).get(u.id, [])
    proj_rows = db.execute(
        select(UserProjectScope.project_id, UserProjectScope.scope_role,
               Project.project_name, Project.project_code)
        .join(Project, Project.id == UserProjectScope.project_id)
        .where(UserProjectScope.user_id == u.id)
    ).all()
    park_names = {p.id: p.park_name for p in db.scalars(select(Park)).all()}

    # 权限清单：把角色权限展开为 module:action
    perm_rows = db.execute(
        select(Permission.module, Permission.action, Permission.perm_name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == u.id)
        .distinct()
    ).all()
    perms = sorted({f"{m}:{a}" for m, a, _ in perm_rows})
    modules: dict[str, dict[str, Any]] = {}
    for m, a, _ in perm_rows:
        d = modules.setdefault(m, {"module": m, "label": MODULE_LABELS.get(m, m),
                                   "actions": []})
        d["actions"].append({"action": a, "label": ACTION_LABELS.get(a, a)})

    return {
        "id": u.id, "username": u.username, "real_name": u.real_name,
        "phone": u.phone, "email": u.email, "avatar": u.avatar,
        "organization_id": u.organization_id,
        "park_id": u.park_id, "park_name": park_names.get(u.park_id),
        "enterprise_id": u.enterprise_id,
        "department": u.department, "position": u.position,
        "status": u.status, "remark": u.remark,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "roles": roles,
        "role_label": "、".join(r["role_name"] for r in roles) or "未分配角色",
        "data_scope": roles[0]["data_scope"] if roles else "SELF",
        "data_scope_label": DATA_SCOPE_LABELS.get(
            roles[0]["data_scope"] if roles else "SELF", "仅本人"),
        "extra_park_scopes": [{"id": i, "name": park_names.get(i)} for i in park_ids],
        "project_scopes": [{"id": pid, "code": code, "name": name, "role": sr}
                           for pid, sr, name, code in proj_rows],
        "permission_count": len(perms),
        "permissions": perms,
        "module_permissions": sorted(modules.values(), key=lambda x: x["module"]),
        "is_demo": u.is_demo,
        "data_label": "演示数据",
    }


@router.post("/users")
def create_user(db: DbSession, auth: CurrentAuth, payload: UserCreate) -> dict[str, Any]:
    """新增用户（真实写库 + 角色绑定 + 审计）。"""
    auth.require("system", "ADD")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(400, f"登录账号 {payload.username} 已存在")

    u = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name, phone=payload.phone, email=payload.email,
        organization_id=payload.organization_id, park_id=payload.park_id,
        enterprise_id=payload.enterprise_id, department=payload.department,
        position=payload.position, status="ACTIVE", is_demo=True, remark="演示数据",
    )
    db.add(u)
    db.flush()

    for code in payload.role_codes or []:
        r = db.scalar(select(Role).where(Role.role_code == code))
        if r:
            db.add(UserRole(user_id=u.id, role_id=r.id))
    for pid in payload.park_scopes or []:
        db.add(UserParkScope(user_id=u.id, park_id=pid))
    for pid in payload.project_scopes or []:
        db.add(UserProjectScope(user_id=u.id, project_id=pid))

    write_audit(db, module="system", action="ADD", auth=auth, object_type="User",
                object_id=u.id, object_name=u.username,
                after_value={"real_name": u.real_name, "roles": payload.role_codes,
                             "park_id": u.park_id},
                change_summary=f"新增用户「{u.real_name}（{u.username}）」"
                               f"，角色：{'、'.join(payload.role_codes or []) or '未分配'}")
    db.commit()
    return {"success": True, "id": u.id, "message": "用户已创建"}


@router.patch("/users/{user_id}")
def update_user(user_id: int, db: DbSession, auth: CurrentAuth,
                payload: UserUpdate) -> dict[str, Any]:
    """修改用户信息、角色、数据范围。"""
    auth.require("system", "EDIT")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")

    before = {"real_name": u.real_name, "phone": u.phone, "email": u.email,
              "department": u.department, "position": u.position,
              "park_id": u.park_id, "status": u.status}
    for f in ("real_name", "phone", "email", "department", "position",
              "organization_id", "park_id", "enterprise_id", "status", "remark"):
        v = getattr(payload, f, None)
        if v is not None:
            setattr(u, f, v)
    if payload.password:
        u.password_hash = hash_password(payload.password)

    if payload.role_codes is not None:
        db.query(UserRole).filter(UserRole.user_id == u.id).delete(synchronize_session=False)
        for code in payload.role_codes:
            r = db.scalar(select(Role).where(Role.role_code == code))
            if r:
                db.add(UserRole(user_id=u.id, role_id=r.id))
    if payload.park_scopes is not None:
        db.query(UserParkScope).filter(UserParkScope.user_id == u.id).delete(synchronize_session=False)
        for pid in payload.park_scopes:
            db.add(UserParkScope(user_id=u.id, park_id=pid))
    if payload.project_scopes is not None:
        db.query(UserProjectScope).filter(UserProjectScope.user_id == u.id).delete(synchronize_session=False)
        for pid in payload.project_scopes:
            db.add(UserProjectScope(user_id=u.id, project_id=pid))

    after = {"real_name": u.real_name, "phone": u.phone, "email": u.email,
             "department": u.department, "position": u.position,
             "park_id": u.park_id, "status": u.status}
    if payload.role_codes is not None:
        after["roles"] = payload.role_codes
    write_audit(db, module="system", action="EDIT", auth=auth, object_type="User",
                object_id=u.id, object_name=u.username,
                before_value=before, after_value=after,
                change_summary=f"修改用户「{u.real_name}（{u.username}）」信息与授权")
    db.commit()
    return {"success": True, "id": u.id, "message": "用户已更新"}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, db: DbSession, auth: CurrentAuth,
                   new_password: str = Query(..., min_length=6)) -> dict[str, Any]:
    """重置密码（管理员操作，写审计但不记录密码明文）。"""
    auth.require("system", "CONFIG")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    u.password_hash = hash_password(new_password)
    write_audit(db, module="system", action="CONFIG", auth=auth, object_type="User",
                object_id=u.id, object_name=u.username,
                change_summary=f"重置用户「{u.real_name}（{u.username}）」的登录密码")
    db.commit()
    return {"success": True, "message": "密码已重置"}


# ================================================================ 角色与权限

@router.get("/roles")
def roles(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """角色列表（含权限数量与用户数量）。"""
    auth.require("system", "VIEW")
    rows = list(db.scalars(select(Role).order_by(Role.sort_order, Role.id)).all())

    perm_cnt = dict(db.execute(
        select(RolePermission.role_id, func.count(RolePermission.id))
        .group_by(RolePermission.role_id)).all())
    user_cnt = dict(db.execute(
        select(UserRole.role_id, func.count(UserRole.user_id))
        .group_by(UserRole.role_id)).all())

    items = [{
        "id": r.id, "role_code": r.role_code, "role_name": r.role_name,
        "role_category": r.role_category, "description": r.description,
        "data_scope": r.data_scope,
        "data_scope_label": DATA_SCOPE_LABELS.get(r.data_scope or "", r.data_scope),
        "is_system": r.is_system, "sort_order": r.sort_order,
        "permission_count": int(perm_cnt.get(r.id, 0)),
        "user_count": int(user_cnt.get(r.id, 0)),
    } for r in rows]

    by_cat: dict[str, int] = {}
    for i in items:
        by_cat[i["role_category"] or "其他"] = by_cat.get(i["role_category"] or "其他", 0) + 1

    return {
        "items": items, "total": len(items),
        "summary": {
            "role_total": len(items),
            "by_category": by_cat,
            "by_scope": _count_by(items, lambda i: i["data_scope_label"]),
            "permission_total": len(list(db.scalars(select(Permission)).all())),
            "binding_total": sum(int(v) for v in user_cnt.values()),
        },
        "data_label": "演示数据",
    }


@router.get("/roles/{role_id}")
def role_detail(role_id: int, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """角色详情：按模块分组的权限矩阵。"""
    auth.require("system", "VIEW")
    r = db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "角色不存在")

    perm_ids = set(db.scalars(
        select(RolePermission.permission_id).where(RolePermission.role_id == role_id)).all())
    all_perms = list(db.scalars(select(Permission).order_by(Permission.module,
                                                            Permission.action)).all())

    modules: dict[str, dict[str, Any]] = {}
    for p in all_perms:
        d = modules.setdefault(p.module, {
            "module": p.module, "label": MODULE_LABELS.get(p.module, p.module),
            "actions": [], "granted": []})
        d["actions"].append({"action": p.action, "label": ACTION_LABELS.get(p.action, p.action),
                             "perm_code": p.perm_code})
        if p.id in perm_ids:
            d["granted"].append(p.action)

    users = db.execute(
        select(User.id, User.real_name, User.username, User.department)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == role_id)).all()

    return {
        "id": r.id, "role_code": r.role_code, "role_name": r.role_name,
        "role_category": r.role_category, "description": r.description,
        "data_scope": r.data_scope,
        "data_scope_label": DATA_SCOPE_LABELS.get(r.data_scope or "", r.data_scope),
        "is_system": r.is_system,
        "permission_count": len(perm_ids),
        "permission_total": len(all_perms),
        "permissions": sorted(f"{p.module}:{p.action}" for p in all_perms if p.id in perm_ids),
        "modules": sorted(modules.values(), key=lambda x: x["module"]),
        "users": [{"id": i, "real_name": n, "username": un, "department": d}
                  for i, n, un, d in users],
        "user_count": len(users),
        "data_label": "演示数据",
    }


@router.post("/roles/{role_id}/permissions")
def set_role_permissions(role_id: int, db: DbSession, auth: CurrentAuth,
                         permissions: list[str] = Query(..., description="形如 space:VIEW")) -> dict[str, Any]:
    """整体设置角色权限（真实覆盖写 + 审计前后对比）。"""
    auth.require("system", "CONFIG")
    r = db.get(Role, role_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    if r.is_system and not auth.is_group_admin:
        raise HTTPException(403, "系统内置角色仅集团管理员可调整")

    targets = []
    for code in permissions:
        if ":" not in code:
            continue
        m, a = code.split(":", 1)
        p = db.scalar(select(Permission).where(Permission.module == m,
                                               Permission.action == a))
        if not p:
            raise HTTPException(400, f"权限项不存在：{code}")
        targets.append(p)

    before_rows = db.execute(
        select(Permission.module, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)).all()
    before = sorted(f"{m}:{a}" for m, a in before_rows)

    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete(synchronize_session=False)
    for p in targets:
        db.add(RolePermission(role_id=role_id, permission_id=p.id))

    after = sorted(f"{p.module}:{p.action}" for p in targets)
    write_audit(db, module="system", action="CONFIG", auth=auth, object_type="Role",
                object_id=r.id, object_name=r.role_code,
                before_value={"permissions": before, "count": len(before)},
                after_value={"permissions": after, "count": len(after)},
                change_summary=(f"调整角色「{r.role_name}」权限：{len(before)} → {len(after)} 项"))
    db.commit()
    return {"success": True, "role_code": r.role_code,
            "permission_count": len(after), "message": "角色权限已更新"}


@router.get("/permissions")
def permissions(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """全部权限项（模块 × 动作矩阵）。"""
    auth.require("system", "VIEW")
    rows = list(db.scalars(select(Permission).order_by(Permission.module,
                                                       Permission.action)).all())
    modules: dict[str, dict[str, Any]] = {}
    for p in rows:
        d = modules.setdefault(p.module, {
            "module": p.module, "label": MODULE_LABELS.get(p.module, p.module),
            "actions": []})
        d["actions"].append({"action": p.action, "label": ACTION_LABELS.get(p.action, p.action),
                             "perm_code": p.perm_code, "perm_name": p.perm_name})
    return {
        "items": [{"id": p.id, "perm_code": p.perm_code, "perm_name": p.perm_name,
                   "module": p.module, "module_label": MODULE_LABELS.get(p.module, p.module),
                   "action": p.action, "action_label": ACTION_LABELS.get(p.action, p.action)}
                  for p in rows],
        "modules": sorted(modules.values(), key=lambda x: x["module"]),
        "summary": {"total": len(rows), "module_total": len(modules),
                    "actions": len(ACTION_LABELS)},
        "data_label": "演示数据",
    }


@router.get("/me/permissions")
def my_permissions(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """当前登录用户的完整权限快照（前端据此渲染按钮级权限）。"""
    ctx = load_auth_context(db, auth.user)
    perms = sorted(ctx.permissions)
    modules: dict[str, list[str]] = {}
    for p in perms:
        if ":" in p:
            m, a = p.split(":", 1)
            modules.setdefault(m, []).append(a)
    return {
        **ctx.to_dict(),
        "module_permissions": {k: sorted(v) for k, v in modules.items()},
        "module_labels": MODULE_LABELS,
        "action_labels": ACTION_LABELS,
        "data_scope_label": DATA_SCOPE_LABELS.get(ctx.data_scope, ctx.data_scope),
    }

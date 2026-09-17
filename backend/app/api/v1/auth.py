"""认证与授权路由：登录、当前用户、菜单权限、可切换园区。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.config import settings
from app.core.security import (
    CurrentAuth,
    DbSession,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import Organization, Park, Role, User, UserRole
from app.schemas.common import ChangePasswordRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["认证授权"])

# ---------------------------------------------------------------- 登录节流
# 说明：User 表未设计锁定字段（保持账号模型简洁），故登录失败次数在进程内维护，
# 仅用于防暴力破解的轻量级节流，不改变账号状态。
_MAX_FAILURES = 5
_LOCK_SECONDS = 300
_failures: dict[str, list[Any]] = {}


def _prune(username: str) -> list[dt.datetime]:
    now = dt.datetime.now()
    times = [t for t in _failures.get(username, [])
             if (now - t).total_seconds() < _LOCK_SECONDS]
    if times:
        _failures[username] = times
    else:
        _failures.pop(username, None)
    return times


def _register_failure(username: str) -> None:
    _prune(username)
    _failures.setdefault(username, []).append(dt.datetime.now())


def _register_success(username: str) -> None:
    _failures.pop(username, None)


def _lock_remaining(username: str) -> int:
    times = _prune(username)
    if len(times) < _MAX_FAILURES:
        return 0
    elapsed = (dt.datetime.now() - times[-1]).total_seconds()
    return max(0, int(_LOCK_SECONDS - elapsed))


def _org_name(db, org_id) -> str | None:
    if not org_id:
        return None
    o = db.get(Organization, org_id)
    return o.org_name if o else None


def _menu_tree(auth) -> list[dict[str, Any]]:
    """按权限返回可访问的一级菜单。"""
    from app.seed.reference import MODULES_FOR_PERM

    mod_label = dict(MODULES_FOR_PERM) if isinstance(MODULES_FOR_PERM, list) else {}
    groups: list[tuple[str, str, list[tuple[str, str, str]]]] = [
        ("dashboard", "经营驾驶舱", [("dashboard", "经营驾驶舱", "/")]),
        ("space", "空间资产", [
            ("park", "园区数字孪生", "/park"),
            ("space", "空间资产", "/space"),
            ("building", "楼宇档案", "/building"),
        ]),
        ("leasing", "招商租赁", [
            ("leasing", "招商 CRM", "/leasing"),
            ("contract", "合同管理", "/contract"),
            ("enterprise", "企业全生命周期", "/enterprise"),
        ]),
        ("project", "项目管理", [
            ("project", "项目管理中心", "/project"),
            ("project", "项目组合", "/portfolio"),
        ]),
        ("operation", "运营服务", [
            ("property", "物业服务", "/property"),
            ("device", "设备设施", "/device"),
            ("energy", "能源低碳", "/energy"),
            ("safety", "安全管理", "/safety"),
            ("service", "企业服务", "/service"),
            ("parking", "停车通行", "/parking"),
        ]),
        ("finance", "财务收费", [("finance", "财务收费", "/finance")]),
        ("ai", "AI 智能", [
            ("ai", "AI 助手", "/ai"),
            ("ai", "AI 项目经理", "/ai-pm"),
            ("agent", "智能体管理", "/agents"),
        ]),
        ("governance", "治理中心", [
            ("approval", "审批中心", "/approval"),
            ("data", "数据中心", "/data"),
            ("report", "报表中心", "/report"),
            ("policy", "政策 AI", "/policy"),
            ("audit_log", "日志审计", "/audit-log"),
            ("system", "系统管理", "/system"),
        ]),
    ]
    out: list[dict[str, Any]] = []
    for key, name, children in groups:
        vis = [{"key": ck, "name": cn, "path": cp}
               for ck, cn, cp in children if auth.has_perm(ck, "VIEW")]
        if vis:
            out.append({"key": key, "name": name, "children": vis})
    return out


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == payload.username))

    # 安全：不区分「用户不存在」与「密码错误」，避免账号枚举
    if not user or not verify_password(payload.password, user.password_hash or ""):
        if user:
            _register_failure(user.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")

    # 连续失败锁定（User 表无锁定字段，故在进程内做轻量级节流）
    remain = _lock_remaining(user.username)
    if remain > 0:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"账号因连续登录失败已被临时锁定，请 {remain} 秒后重试")

    token = create_access_token({"sub": str(user.id), "username": user.username})

    from app.core.security import load_auth_context

    auth = load_auth_context(db, user)
    _register_success(user.username)
    user.last_login_at = dt.datetime.now()
    write_audit(db, module="auth", action="LOGIN", auth=auth, request=request,
                object_type="User", object_id=user.id, object_name=user.real_name,
                change_summary="用户登录", source="USER")
    db.commit()

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": auth.to_dict(),
    }


@router.post("/logout")
def logout(request: Request, db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    write_audit(db, module="auth", action="LOGOUT", auth=auth, request=request,
                object_type="User", object_id=auth.user.id, object_name=auth.user.real_name,
                change_summary="用户登出", source="USER")
    db.commit()
    return {"success": True, "message": "已安全登出"}


@router.get("/me")
def me(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    data = auth.to_dict()
    data["organization_name"] = _org_name(db, auth.user.organization_id)
    pk = db.get(Park, auth.user.park_id) if auth.user.park_id else None
    data["park_name"] = pk.park_name if pk else None
    data["menus"] = _menu_tree(auth)
    return data


@router.get("/parks")
def my_parks(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """当前用户可切换的园区列表（数据权限范围内）。"""
    vis = auth.visible_park_ids()
    q = select(Park).order_by(Park.park_code, Park.id)
    if vis is not None:
        q = q.where(Park.id.in_(vis)) if vis else q.where(Park.id == -1)
    parks = list(db.scalars(q).all())
    return {
        "items": [{
            "id": p.id, "park_code": p.park_code, "park_name": p.park_name,
            "park_type": p.park_type, "city": p.city, "status": p.status,
        } for p in parks],
        "can_switch": vis is None or len(vis) > 1,
        "data_scope": auth.data_scope,
        "data_label": "演示数据",
    }


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, db: DbSession,
                    auth: CurrentAuth) -> dict[str, Any]:
    user = auth.user
    if not verify_password(payload.old_password, user.password_hash or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码长度不得少于 6 位")
    user.password_hash = hash_password(payload.new_password)
    write_audit(db, module="auth", action="EDIT", auth=auth, request=request,
                object_type="User", object_id=user.id, object_name=user.real_name,
                change_summary="用户修改密码", before_value={"password": "***"},
                after_value={"password": "***"}, source="USER")
    db.commit()
    return {"success": True, "message": "密码修改成功，请重新登录"}


@router.get("/roles")
def list_roles(db: DbSession, auth: CurrentAuth) -> dict[str, Any]:
    """当前用户拥有的角色及权限明细。"""
    rows = db.execute(
        select(Role, UserRole).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == auth.user.id)
    ).all()
    return {
        "items": [{
            "role_code": r.role_code, "role_name": r.role_name,
            "data_scope": r.data_scope, "description": r.description,
            "is_system": r.is_system,
        } for r, _ in rows],
        "permission_count": len(auth.permissions),
        "permissions": sorted(auth.permissions),
        "data_scope": auth.data_scope,
        "visible_park_ids": auth.visible_park_ids(),
        "data_label": "演示数据",
    }

"""认证与授权核心：密码哈希、JWT、当前用户、数据权限过滤。"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import Role, RolePermission, Permission, User, UserParkScope, UserProjectScope

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False)

# --------------------------------------------------------------------------
# 密码哈希：优先 bcrypt（passlib），不可用时退化为 PBKDF2-SHA256（纯标准库）
# --------------------------------------------------------------------------
try:  # pragma: no cover - 环境相关
    from passlib.context import CryptContext

    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _HAS_BCRYPT = True
except Exception:  # pragma: no cover
    _pwd_context = None
    _HAS_BCRYPT = False


def hash_password(password: str) -> str:
    if _HAS_BCRYPT and _pwd_context is not None:
        try:
            return _pwd_context.hash(password)
        except Exception:
            pass
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    if hashed.startswith("pbkdf2_sha256$"):
        try:
            _, salt_hex, dk_hex = hashed.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
            return hmac.compare_digest(dk.hex(), dk_hex)
        except Exception:
            return False
    if _HAS_BCRYPT and _pwd_context is not None:
        try:
            return _pwd_context.verify(password, hashed)
        except Exception:
            return False
    return False


# --------------------------------------------------------------------------
# JWT：优先 python-jose，不可用时退化为 HMAC 签名的紧凑令牌
# --------------------------------------------------------------------------
try:  # pragma: no cover
    from jose import JWTError, jwt

    _HAS_JOSE = True
except Exception:  # pragma: no cover
    _HAS_JOSE = False


def _fallback_encode(payload: dict) -> str:
    import base64
    import json

    body = base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode().rstrip("=")
    sig = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _fallback_decode(token: str) -> dict:
    import base64
    import json

    body, sig = token.rsplit(".", 1)
    expect = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        raise ValueError("invalid token signature")
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode())


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    # JWT 的 exp/iat/nbf 必须是 NumericDate（整数秒），传 float 会导致解码端校验失败
    now_ts = int(dt.datetime.now(dt.UTC).timestamp())
    payload = {**data, "exp": int(expire.timestamp()), "iat": now_ts}
    if _HAS_JOSE:
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return _fallback_encode(payload)


def decode_token(token: str) -> dict:
    if _HAS_JOSE:
        try:
            return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as exc:
            raise ValueError(str(exc)) from exc
    return _fallback_decode(token)


# --------------------------------------------------------------------------
# 当前用户与权限上下文
# --------------------------------------------------------------------------


class AuthContext:
    """一次请求的完整授权上下文（用户 + 角色 + 权限 + 数据范围）。"""

    def __init__(self, user: User, roles: list[Role], permissions: set[str],
                 park_ids: list[int], project_ids: list[int]):
        self.user = user
        self.roles = roles
        self.permissions = permissions
        self.park_ids = park_ids
        self.project_ids = project_ids

    # ---- 角色判定 ----
    @property
    def role_codes(self) -> set[str]:
        return {r.role_code for r in self.roles}

    @property
    def data_scope(self) -> str:
        """取最宽的数据范围。"""
        order = ["GROUP", "PARK", "DEPARTMENT", "PROJECT", "ENTERPRISE", "SELF"]
        scopes = [r.data_scope for r in self.roles] or ["SELF"]
        for s in order:
            if s in scopes:
                return s
        return "SELF"

    @property
    def is_group_admin(self) -> bool:
        return bool({"GROUP_ADMIN", "SUPER_ADMIN"} & self.role_codes)

    @property
    def is_park_manager(self) -> bool:
        return "PARK_MANAGER" in self.role_codes

    @property
    def enterprise_id(self) -> int | None:
        return self.user.enterprise_id

    # ---- 数据权限 ----
    def visible_park_ids(self) -> list[int] | None:
        """None 表示全部园区可见（集团级）。"""
        if self.is_group_admin:
            return None
        if self.park_ids:
            return self.park_ids
        if self.user.park_id:
            return [self.user.park_id]
        return None if self.data_scope == "GROUP" else []

    def can_access_park(self, park_id: int | None) -> bool:
        vis = self.visible_park_ids()
        if vis is None:
            return True
        if park_id is None:
            return False
        return park_id in vis

    def visible_project_ids(self) -> list[int] | None:
        """None 表示不受项目级限制。"""
        if self.data_scope in ("GROUP", "PARK", "DEPARTMENT"):
            return None
        return self.project_ids

    def can_access_project(self, project_id: int) -> bool:
        vis = self.visible_project_ids()
        return vis is None or project_id in vis

    # ---- 功能权限 ----
    def has_perm(self, module: str, action: str = "VIEW") -> bool:
        if self.is_group_admin or "SUPER_ADMIN" in self.role_codes:
            return True
        return f"{module}:{action}" in self.permissions or "*:*" in self.permissions

    def require(self, module: str, action: str = "VIEW") -> None:
        if not self.has_perm(module, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足：需要 {module} 模块的 {action} 权限。当前角色：{self.role_label}",
            )

    @property
    def role_label(self) -> str:
        return "、".join(r.role_name for r in self.roles) or "未分配角色"

    def to_dict(self) -> dict:
        return {
            "id": self.user.id,
            "username": self.user.username,
            "real_name": self.user.real_name,
            "phone": self.user.phone,
            "email": self.user.email,
            "avatar": self.user.avatar,
            "department": self.user.department,
            "position": self.user.position,
            "organization_id": self.user.organization_id,
            "park_id": self.user.park_id,
            "enterprise_id": self.user.enterprise_id,
            "roles": [{"code": r.role_code, "name": r.role_name, "data_scope": r.data_scope} for r in self.roles],
            "role_label": self.role_label,
            "data_scope": self.data_scope,
            "permissions": sorted(self.permissions),
            "visible_park_ids": self.visible_park_ids(),
            "visible_project_ids": self.visible_project_ids(),
            "is_group_admin": self.is_group_admin,
        }


def load_auth_context(db: Session, user: User) -> AuthContext:
    role_ids = db.scalars(select(Role.id).join(Role.__table__.metadata.tables["user_roles"], Role.id ==
                                             Role.__table__.metadata.tables["user_roles"].c.role_id).where(
        Role.__table__.metadata.tables["user_roles"].c.user_id == user.id)).all()
    if not role_ids:
        from app.models import UserRole
        role_ids = db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id)).all()
    roles = list(db.scalars(select(Role).where(Role.id.in_(role_ids))).all()) if role_ids else []

    perms: set[str] = set()
    if role_ids:
        rows = db.execute(
            select(Permission.module, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        ).all()
        perms = {f"{m}:{a}" for m, a in rows}

    park_ids = list(db.scalars(select(UserParkScope.park_id).where(UserParkScope.user_id == user.id)).all())
    project_ids = list(db.scalars(select(UserProjectScope.project_id).where(UserProjectScope.user_id == user.id)).all())
    return AuthContext(user, roles, perms, park_ids, project_ids)


def get_current_auth(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    db: Session = Depends(get_db),
) -> AuthContext:
    if not token:
        token = request.headers.get("X-Token") or request.cookies.get("smartpark_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效，请重新登录")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证缺少用户标识")
    user = db.get(User, int(user_id))
    if not user or user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")
    return load_auth_context(db, user)


CurrentAuth = Annotated[AuthContext, Depends(get_current_auth)]
DbSession = Annotated[Session, Depends(get_db)]


def perm_guard(module: str, action: str = "VIEW"):
    """路由级权限依赖工厂。"""

    def _guard(auth: CurrentAuth) -> AuthContext:
        auth.require(module, action)
        return auth

    return _guard

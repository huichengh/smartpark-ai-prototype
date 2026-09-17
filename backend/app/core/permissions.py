"""数据权限过滤器：所有业务查询统一经过这里，实现多租户 / 园区 / 项目 / 企业隔离。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select

from app.core.security import AuthContext


def scope_by_park(stmt: Select, auth: AuthContext, model: Any, column: str = "park_id") -> Select:
    """按园区数据权限过滤查询。"""
    col = getattr(model, column, None)
    if col is None:
        return stmt
    vis = auth.visible_park_ids()
    if vis is None:
        return stmt
    if not vis:
        return stmt.where(col == -1)   # 无任何可见园区 → 空结果
    return stmt.where(col.in_(vis))


def scope_by_project(stmt: Select, auth: AuthContext, model: Any, column: str = "project_id") -> Select:
    """按项目数据权限过滤查询。"""
    col = getattr(model, column, None)
    if col is None:
        return stmt
    vis = auth.visible_project_ids()
    if vis is None:
        return stmt
    if not vis:
        return stmt.where(col == -1)
    return stmt.where(col.in_(vis))


def scope_by_enterprise(stmt: Select, auth: AuthContext, model: Any, column: str = "enterprise_id") -> Select:
    """企业级用户只能看到本企业数据。"""
    if auth.data_scope == "ENTERPRISE" or auth.enterprise_id:
        if auth.is_group_admin:
            return stmt
        col = getattr(model, column, None)
        if col is not None and auth.enterprise_id:
            return stmt.where(col == auth.enterprise_id)
    return stmt


def apply_scope(stmt: Select, auth: AuthContext, model: Any,
                park_column: str | None = "park_id",
                project_column: str | None = None,
                enterprise_column: str | None = None) -> Select:
    """组合应用数据权限。"""
    if park_column and hasattr(model, park_column):
        stmt = scope_by_park(stmt, auth, model, park_column)
    if project_column and hasattr(model, project_column):
        stmt = scope_by_project(stmt, auth, model, project_column)
    if enterprise_column and hasattr(model, enterprise_column):
        stmt = scope_by_enterprise(stmt, auth, model, enterprise_column)
    return stmt


def resolve_park_filter(auth: AuthContext, requested_park_id: int | None) -> int | None:
    """校验前端请求的园区是否在授权范围内。"""
    if requested_park_id is None:
        return None
    if not auth.can_access_park(requested_park_id):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权访问园区 ID={requested_park_id} 的数据（数据权限：{auth.data_scope}）",
        )
    return requested_park_id

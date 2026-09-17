"""API v1 路由聚合。

挂载顺序即前端信息架构顺序（需求书第 12 节 20 个一级菜单）。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    approval,
    audit,
    auth,
    contract,
    dashboard,
    data,
    enterprise,
    finance,
    leasing,
    notification,
    operation,
    project,
    report,
    space,
    system,
)

api_router = APIRouter()

# ---- 认证（无 /api/v1 业务前缀，独立挂载）----
api_router.include_router(auth.router)

# ---- 业务模块 ----
api_router.include_router(dashboard.router)
api_router.include_router(space.router)
api_router.include_router(enterprise.router)
api_router.include_router(leasing.router)
api_router.include_router(contract.router)
api_router.include_router(finance.router)
api_router.include_router(project.router)
api_router.include_router(operation.router)
api_router.include_router(approval.router)
api_router.include_router(agent.router)
api_router.include_router(data.router)
api_router.include_router(report.router)
api_router.include_router(notification.router)
api_router.include_router(audit.router)
api_router.include_router(system.router)

__all__ = ["api_router"]

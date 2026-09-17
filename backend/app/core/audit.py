"""操作日志审计：AI建议、审批、数据导入、算法结果、项目变更全部可追溯。"""
from __future__ import annotations

import datetime as dt
import itertools

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

_counter = itertools.count(1)


def _log_code() -> str:
    return f"LOG{dt.datetime.now():%Y%m%d%H%M%S}{next(_counter):04d}"


def write_audit(
    db: Session,
    *,
    module: str,
    action: str,
    auth=None,
    request: Request | None = None,
    object_type: str | None = None,
    object_id: int | None = None,
    object_name: str | None = None,
    before_value: dict | None = None,
    after_value: dict | None = None,
    change_summary: str | None = None,
    approval_info: str | None = None,
    source: str = "USER",
    result: str = "SUCCESS",
) -> AuditLog:
    user = getattr(auth, "user", None) if auth else None
    log = AuditLog(
        log_code=_log_code(),
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        real_name=getattr(user, "real_name", None) or "系统",
        park_id=getattr(user, "park_id", None),
        module=module,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_name=object_name,
        before_value=before_value,
        after_value=after_value,
        change_summary=change_summary,
        approval_info=approval_info,
        source=source,
        ip_address=(request.client.host if request and request.client else None),
        user_agent=(request.headers.get("user-agent") if request else None),
        result=result,
        created_at=dt.datetime.now(),
    )
    db.add(log)
    return log

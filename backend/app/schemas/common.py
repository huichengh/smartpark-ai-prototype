"""通用请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)
    keyword: str | None = None
    park_id: int | None = None
    sort_by: str | None = None
    order: str = "desc"


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
    data_label: str = "演示数据"


def paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    start = max(0, (page - 1) * page_size)
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "data_label": "演示数据",
    }


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(APPROVE|REJECT)$")
    comment: str | None = None


class WorkOrderCreate(BaseModel):
    title: str
    order_type: str = "维修"
    priority: str = "MEDIUM"
    park_id: int | None = None
    building_id: int | None = None
    space_id: int | None = None
    enterprise_id: int | None = None
    description: str | None = None


class WorkOrderAction(BaseModel):
    action: str = Field(..., pattern="^(DISPATCH|ACCEPT|START|FINISH|VERIFY|CLOSE|RATE)$")
    handler_name: str | None = None
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = None


class TaskProgressUpdate(BaseModel):
    progress: float = Field(..., ge=0, le=100)
    actual_start: str | None = None
    actual_end: str | None = None
    note: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    agent_key: str | None = None
    park_id: int | None = None
    project_id: int | None = None
    enterprise_id: int | None = None
    conversation_id: int | None = None


class BillPayRequest(BaseModel):
    amount: float = Field(..., gt=0)
    pay_method: str = "银行转账"
    pay_date: str | None = None
    remark: str | None = None


class UserCreate(BaseModel):
    """新增用户请求。"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=64)
    real_name: str = Field(..., min_length=1, max_length=50)
    phone: str | None = None
    email: str | None = None
    organization_id: int | None = None
    park_id: int | None = None
    enterprise_id: int | None = None
    department: str | None = None
    position: str | None = None
    role_codes: list[str] = Field(default_factory=list)
    park_scopes: list[int] = Field(default_factory=list)
    project_scopes: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    """修改用户请求（None 表示不修改；列表字段传空列表表示清空）。"""
    real_name: str | None = None
    password: str | None = Field(None, min_length=6, max_length=64)
    phone: str | None = None
    email: str | None = None
    organization_id: int | None = None
    park_id: int | None = None
    enterprise_id: int | None = None
    department: str | None = None
    position: str | None = None
    status: str | None = None
    remark: str | None = None
    role_codes: list[str] | None = None
    park_scopes: list[int] | None = None
    project_scopes: list[int] | None = None

"""园智汇 —— 全量 ORM 模型定义（对应需求书第 43 节数据表清单）。

组织与租户
  organizations / parks / park_templates / buildings / floors / spaces
企业
  enterprises / enterprise_contacts / enterprise_tags / enterprise_policy_records
身份与权限
  users / roles / permissions / user_roles / role_permissions
招商
  leasing_leads / leasing_followups / leasing_activities / channels
合同与收费
  contracts / contract_payments / bills / payments
项目（瀑布 / 敏捷 / 混合）
  projects / project_phases / wbs_items / project_tasks / task_dependencies
  milestones / project_costs / project_risks / project_issues / project_changes
  epics / features / user_stories / sprints / sprint_tasks
物业 / 设备 / 能耗 / 安全
  work_orders / devices / device_inspections / energy_records / safety_incidents
  safety_hazards
企业服务与政策
  service_requests / policies / policy_matches
停车与通行
  parking_spaces / vehicles / visitors / access_records
AI / 审批 / 数据 / 系统
  ai_recommendations / ai_conversations / ai_messages / approval_requests / approval_steps
  data_uploads / data_quality_reports / notifications / audit_logs
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def now() -> dt.datetime:
    return dt.datetime.now()


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ==========================================================================
# 一、组织 / 租户 / 园区
# ==========================================================================


class Organization(Base, TimestampMixin):
    """集团级租户。"""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    org_name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(100))
    tenant_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    contact_person: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    remark: Mapped[str | None] = mapped_column(Text)

    parks: Mapped[list["Park"]] = relationship(back_populates="organization")


class ParkTemplate(Base, TimestampMixin):
    """可配置园区模板：不同类型园区开启不同模块。"""

    __tablename__ = "park_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    template_name: Mapped[str] = mapped_column(String(100))
    park_type: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # 启用的功能模块 key 列表
    enabled_modules: Mapped[list | None] = mapped_column(JSON, default=list)
    # 关注的核心业务关键词
    focus_areas: Mapped[list | None] = mapped_column(JSON, default=list)
    # 驾驶舱 KPI 卡片配置
    dashboard_kpis: Mapped[list | None] = mapped_column(JSON, default=list)
    # 默认空间类型集合
    default_space_types: Mapped[list | None] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Park(Base, TimestampMixin):
    """园区（多租户核心隔离维度）。"""

    __tablename__ = "parks"

    id: Mapped[int] = mapped_column(primary_key=True)
    park_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(100))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("park_templates.id"))
    park_type: Mapped[str] = mapped_column(String(40), index=True)
    province: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(50))
    district: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    total_area: Mapped[float] = mapped_column(Float, default=0.0)          # 占地 m²
    build_area: Mapped[float] = mapped_column(Float, default=0.0)          # 建筑面积 m²
    rentable_area: Mapped[float] = mapped_column(Float, default=0.0)       # 可租面积 m²
    green_area: Mapped[float] = mapped_column(Float, default=0.0)
    building_count: Mapped[int] = mapped_column(Integer, default=0)
    established_date: Mapped[dt.date | None] = mapped_column(Date)
    manager_name: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    operation_mode: Mapped[str | None] = mapped_column(String(50))          # 运营模式
    enabled_modules: Mapped[list | None] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    remark: Mapped[str | None] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="parks")
    buildings: Mapped[list["Building"]] = relationship(back_populates="park")


class Building(Base, TimestampMixin):
    """楼栋。"""

    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_code: Mapped[str] = mapped_column(String(50), index=True)
    building_name: Mapped[str] = mapped_column(String(120))
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_type: Mapped[str] = mapped_column(String(40), default="OFFICE")
    floor_count: Mapped[int] = mapped_column(Integer, default=1)
    underground_floors: Mapped[int] = mapped_column(Integer, default=0)
    build_area: Mapped[float] = mapped_column(Float, default=0.0)
    rentable_area: Mapped[float] = mapped_column(Float, default=0.0)
    # 2.5D 数字孪生示意图上的相对坐标（百分比）
    map_x: Mapped[float] = mapped_column(Float, default=50.0)
    map_y: Mapped[float] = mapped_column(Float, default=50.0)
    map_w: Mapped[float] = mapped_column(Float, default=8.0)
    map_d: Mapped[float] = mapped_column(Float, default=6.0)
    map_h: Mapped[float] = mapped_column(Float, default=10.0)
    completion_date: Mapped[dt.date | None] = mapped_column(Date)
    property_manager: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="NORMAL")
    remark: Mapped[str | None] = mapped_column(Text)

    park: Mapped["Park"] = relationship(back_populates="buildings")
    floors: Mapped[list["Floor"]] = relationship(back_populates="building")


class Floor(Base, TimestampMixin):
    """楼层。"""

    __tablename__ = "floors"

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_code: Mapped[str] = mapped_column(String(50), index=True)
    floor_name: Mapped[str] = mapped_column(String(80))
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    floor_number: Mapped[int] = mapped_column(Integer, default=1)
    build_area: Mapped[float] = mapped_column(Float, default=0.0)
    rentable_area: Mapped[float] = mapped_column(Float, default=0.0)
    usage: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="NORMAL")

    building: Mapped["Building"] = relationship(back_populates="floors")
    spaces: Mapped[list["Space"]] = relationship(back_populates="floor")


class Space(Base, TimestampMixin):
    """空间单元：房间 / 工位 / 停车位（一房一状态）。"""

    __tablename__ = "spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    space_name: Mapped[str] = mapped_column(String(120))
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), index=True)
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"), index=True)
    parent_space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id"))
    space_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE", index=True)
    area: Mapped[float] = mapped_column(Float, default=0.0)
    rentable_area: Mapped[float] = mapped_column(Float, default=0.0)
    rent_price: Mapped[float] = mapped_column(Float, default=0.0)        # 元/m²/月
    property_price: Mapped[float] = mapped_column(Float, default=0.0)    # 元/m²/月
    orientation: Mapped[str | None] = mapped_column(String(30))
    decoration: Mapped[str | None] = mapped_column(String(50))
    has_air_conditioner: Mapped[bool] = mapped_column(Boolean, default=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    lease_start: Mapped[dt.date | None] = mapped_column(Date)
    lease_end: Mapped[dt.date | None] = mapped_column(Date)
    vacant_since: Mapped[dt.date | None] = mapped_column(Date)     # 空置起始：用于空置时长统计
    leasing_status: Mapped[str | None] = mapped_column(String(40))
    remark: Mapped[str | None] = mapped_column(Text)

    floor: Mapped["Floor"] = relationship(back_populates="spaces")


# ==========================================================================
# 二、企业全生命周期
# ==========================================================================


class Enterprise(Base, TimestampMixin):
    """企业档案（一企一档）。"""

    __tablename__ = "enterprises"

    id: Mapped[int] = mapped_column(primary_key=True)
    enterprise_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    enterprise_name: Mapped[str] = mapped_column(String(200), index=True)
    short_name: Mapped[str | None] = mapped_column(String(100))
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(30), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    industry: Mapped[str | None] = mapped_column(String(60), index=True)
    sub_industry: Mapped[str | None] = mapped_column(String(60))
    enterprise_type: Mapped[str | None] = mapped_column(String(50))   # 有限责任/股份/外资…
    enterprise_nature: Mapped[str | None] = mapped_column(String(50))  # 民企/国企/外资
    status: Mapped[str] = mapped_column(String(30), default="POTENTIAL", index=True)
    register_capital: Mapped[float] = mapped_column(Float, default=0.0)   # 万元
    paid_in_capital: Mapped[float] = mapped_column(Float, default=0.0)
    established_date: Mapped[dt.date | None] = mapped_column(Date)
    legal_person: Mapped[str | None] = mapped_column(String(50))
    contact_person: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    contact_email: Mapped[str | None] = mapped_column(String(100))
    employee_count: Mapped[int] = mapped_column(Integer, default=0)
    rnd_employee_count: Mapped[int] = mapped_column(Integer, default=0)
    annual_revenue: Mapped[float] = mapped_column(Float, default=0.0)      # 万元
    annual_tax: Mapped[float] = mapped_column(Float, default=0.0)          # 万元
    financing_stage: Mapped[str | None] = mapped_column(String(40))
    financing_amount: Mapped[float] = mapped_column(Float, default=0.0)    # 万元
    ip_count: Mapped[int] = mapped_column(Integer, default=0)              # 知识产权
    invention_patent_count: Mapped[int] = mapped_column(Integer, default=0)
    software_copyright_count: Mapped[int] = mapped_column(Integer, default=0)
    is_high_tech: Mapped[bool] = mapped_column(Boolean, default=False)     # 高新技术企业
    is_specialized: Mapped[bool] = mapped_column(Boolean, default=False)   # 专精特新
    is_little_giant: Mapped[bool] = mapped_column(Boolean, default=False)  # 小巨人
    is_tech_sme: Mapped[bool] = mapped_column(Boolean, default=False)      # 科技型中小企业
    settle_date: Mapped[dt.date | None] = mapped_column(Date)
    exit_date: Mapped[dt.date | None] = mapped_column(Date)
    leased_area: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    risk_note: Mapped[str | None] = mapped_column(Text)
    credit_rating: Mapped[str | None] = mapped_column(String(10))
    tags: Mapped[list | None] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)

    contacts: Mapped[list["EnterpriseContact"]] = relationship(back_populates="enterprise")
    tags_rel: Mapped[list["EnterpriseTag"]] = relationship(back_populates="enterprise")


class EnterpriseContact(Base, TimestampMixin):
    __tablename__ = "enterprise_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    position: Mapped[str | None] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    remark: Mapped[str | None] = mapped_column(Text)

    enterprise: Mapped["Enterprise"] = relationship(back_populates="contacts")


class EnterpriseTag(Base, TimestampMixin):
    __tablename__ = "enterprise_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id"), index=True)
    tag_name: Mapped[str] = mapped_column(String(60))
    tag_type: Mapped[str | None] = mapped_column(String(40))
    tag_value: Mapped[str | None] = mapped_column(String(120))

    enterprise: Mapped["Enterprise"] = relationship(back_populates="tags_rel")


# ==========================================================================
# 三、用户 / 角色 / 权限
# ==========================================================================


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    perm_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    perm_name: Mapped[str] = mapped_column(String(80))
    module: Mapped[str] = mapped_column(String(60), index=True)
    action: Mapped[str] = mapped_column(String(30))   # VIEW/ADD/EDIT/DELETE/IMPORT/EXPORT/APPROVE/AI/CONFIG
    description: Mapped[str | None] = mapped_column(String(200))


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    role_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    role_name: Mapped[str] = mapped_column(String(80))
    role_category: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(String(300))
    # 数据权限范围：GROUP / PARK / DEPARTMENT / PROJECT / ENTERPRISE / SELF
    data_scope: Mapped[str] = mapped_column(String(30), default="SELF")
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), index=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    real_name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(100))
    avatar: Mapped[str | None] = mapped_column(String(200))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    department: Mapped[str | None] = mapped_column(String(80))
    position: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)


class UserParkScope(Base):
    """用户授权的园区范围（数据权限）。"""

    __tablename__ = "user_park_scopes"
    __table_args__ = (UniqueConstraint("user_id", "park_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)


class UserProjectScope(Base):
    """用户授权的项目范围（项目数据权限）。"""

    __tablename__ = "user_project_scopes"
    __table_args__ = (UniqueConstraint("user_id", "project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    scope_role: Mapped[str | None] = mapped_column(String(40))  # 项目经理 / 成员 / 观察者


# ==========================================================================
# 四、招商 CRM
# ==========================================================================


class Channel(Base, TimestampMixin):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(100))
    channel_type: Mapped[str | None] = mapped_column(String(40))  # 政府推荐/中介/线上/活动/自主
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    remark: Mapped[str | None] = mapped_column(Text)


class LeasingActivity(Base, TimestampMixin):
    """招商活动。"""

    __tablename__ = "leasing_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    activity_name: Mapped[str] = mapped_column(String(200))
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    activity_type: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(200))
    budget: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    lead_count: Mapped[int] = mapped_column(Integer, default=0)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")


class LeasingLead(Base, TimestampMixin):
    """招商线索（招商漏斗主表）。"""

    __tablename__ = "leasing_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    contact_person: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    contact_position: Mapped[str | None] = mapped_column(String(60))
    industry: Mapped[str | None] = mapped_column(String(60), index=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"))
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("leasing_activities.id"))
    stage: Mapped[str] = mapped_column(String(30), default="LEAD", index=True)
    stage_entered_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    owner_name: Mapped[str | None] = mapped_column(String(50))
    # 选址需求
    demand_area: Mapped[float] = mapped_column(Float, default=0.0)         # 意向面积 m²
    demand_budget: Mapped[float] = mapped_column(Float, default=0.0)       # 预算 元/m²/月
    demand_space_type: Mapped[str | None] = mapped_column(String(40))
    demand_floor: Mapped[str | None] = mapped_column(String(40))
    investment_amount: Mapped[float] = mapped_column(Float, default=0.0)   # 投资规模 万元
    expected_employees: Mapped[int] = mapped_column(Integer, default=0)
    expected_settle_date: Mapped[dt.date | None] = mapped_column(Date)
    qualification: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float, default=0.0)               # AI 商机评分
    win_probability: Mapped[float] = mapped_column(Float, default=0.0)     # 成交可能性
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(60))
    last_followup_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    next_followup_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    lost_reason: Mapped[str | None] = mapped_column(String(200))
    converted_enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    remark: Mapped[str | None] = mapped_column(Text)

    followups: Mapped[list["LeasingFollowup"]] = relationship(back_populates="lead")


class LeasingFollowup(Base, TimestampMixin):
    __tablename__ = "leasing_followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leasing_leads.id"), index=True)
    followup_type: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(String(200))
    followup_by: Mapped[str | None] = mapped_column(String(50))
    followup_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    next_action: Mapped[str | None] = mapped_column(String(200))
    next_action_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    lead: Mapped["LeasingLead"] = relationship(back_populates="followups")


# ==========================================================================
# 五、合同
# ==========================================================================


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    contract_name: Mapped[str] = mapped_column(String(200))
    contract_type: Mapped[str] = mapped_column(String(40), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), index=True)
    space_name: Mapped[str | None] = mapped_column(String(120))
    leased_area: Mapped[float] = mapped_column(Float, default=0.0)
    party_a: Mapped[str | None] = mapped_column(String(200))
    party_b: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    sign_date: Mapped[dt.date | None] = mapped_column(Date)
    rent_price: Mapped[float] = mapped_column(Float, default=0.0)          # 元/m²/月
    monthly_rent: Mapped[float] = mapped_column(Float, default=0.0)
    property_price: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_property_fee: Mapped[float] = mapped_column(Float, default=0.0)
    deposit: Mapped[float] = mapped_column(Float, default=0.0)
    free_rent_months: Mapped[int] = mapped_column(Integer, default=0)
    rent_increase_rule: Mapped[str | None] = mapped_column(String(200))
    payment_cycle: Mapped[str | None] = mapped_column(String(30))          # 月付/季付/半年付/年付
    payment_day: Mapped[int] = mapped_column(Integer, default=5)
    contract_amount: Mapped[float] = mapped_column(Float, default=0.0)     # 合同总额
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    owner_name: Mapped[str | None] = mapped_column(String(50))
    signed_by: Mapped[str | None] = mapped_column(String(50))
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    renewed_from_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    terminate_date: Mapped[dt.date | None] = mapped_column(Date)
    terminate_reason: Mapped[str | None] = mapped_column(String(200))
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    remark: Mapped[str | None] = mapped_column(Text)


class ContractPayment(Base, TimestampMixin):
    """合同收款计划 / 账期。"""

    __tablename__ = "contract_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    period_name: Mapped[str] = mapped_column(String(60))
    due_date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/PARTIAL/PAID/OVERDUE
    paid_date: Mapped[dt.date | None] = mapped_column(Date)


# ==========================================================================
# 六、项目（瀑布 / 敏捷 / 混合）
# ==========================================================================


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    project_name: Mapped[str] = mapped_column(String(200), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    parent_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    project_type: Mapped[str] = mapped_column(String(50), index=True)
    management_method: Mapped[str] = mapped_column(String(20), default="WATERFALL", index=True)
    project_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    project_manager_name: Mapped[str | None] = mapped_column(String(50))
    department: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    charter: Mapped[dict | None] = mapped_column(JSON)     # 项目章程
    objective: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    planned_end_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    actual_end_date: Mapped[dt.date | None] = mapped_column(Date)
    baseline_end_date: Mapped[dt.date | None] = mapped_column(Date)
    budget: Mapped[float] = mapped_column(Float, default=0.0)
    approved_budget: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    committed_cost: Mapped[float] = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    planned_progress: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    health: Mapped[str | None] = mapped_column(String(20))     # GREEN / YELLOW / RED
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    team_size: Mapped[int] = mapped_column(Integer, default=0)
    milestone_done: Mapped[int] = mapped_column(Integer, default=0)
    milestone_total: Mapped[int] = mapped_column(Integer, default=0)
    ai_summary: Mapped[dict | None] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text)

    children: Mapped[list["Project"]] = relationship(
        back_populates="parent", remote_side="Project.id"
    )
    parent: Mapped["Project | None"] = relationship(
        back_populates="children", remote_side="Project.parent_project_id"
    )


class ProjectPhase(Base, TimestampMixin):
    """瀑布阶段 / 敏捷迭代容器。"""

    __tablename__ = "project_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    phase_code: Mapped[str] = mapped_column(String(30))
    phase_name: Mapped[str] = mapped_column(String(100))
    phase_order: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    owner: Mapped[str | None] = mapped_column(String(50))
    deliverable: Mapped[str | None] = mapped_column(String(200))


class WbsItem(Base, TimestampMixin):
    """WBS：项目 → 阶段 → 工作包 → 任务 → 子任务。"""

    __tablename__ = "wbs_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id"), index=True)
    phase_id: Mapped[int | None] = mapped_column(ForeignKey("project_phases.id"))
    wbs_code: Mapped[str] = mapped_column(String(40), index=True)
    item_name: Mapped[str] = mapped_column(String(200))
    item_level: Mapped[int] = mapped_column(Integer, default=1)   # 1阶段 2工作包 3任务 4子任务
    item_type: Mapped[str | None] = mapped_column(String(30))
    owner_name: Mapped[str | None] = mapped_column(String(50))
    responsible_role: Mapped[str | None] = mapped_column(String(50))
    plan_start: Mapped[dt.date | None] = mapped_column(Date)
    plan_end: Mapped[dt.date | None] = mapped_column(Date)
    actual_start: Mapped[dt.date | None] = mapped_column(Date)
    actual_end: Mapped[dt.date | None] = mapped_column(Date)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    budget: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    risk_level: Mapped[str | None] = mapped_column(String(20))
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)   # 关键路径
    slack_days: Mapped[int] = mapped_column(Integer, default=0)          # 总时差
    es: Mapped[dt.date | None] = mapped_column(Date)   # 最早开始
    ef: Mapped[dt.date | None] = mapped_column(Date)   # 最早完成
    ls: Mapped[dt.date | None] = mapped_column(Date)   # 最晚开始
    lf: Mapped[dt.date | None] = mapped_column(Date)   # 最晚完成
    predecessors: Mapped[list | None] = mapped_column(JSON, default=list)
    successors: Mapped[list | None] = mapped_column(JSON, default=list)
    deliverable: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TaskDependency(Base):
    """任务依赖关系（用于关键路径计算）。"""

    __tablename__ = "task_dependencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    predecessor_id: Mapped[int] = mapped_column(ForeignKey("wbs_items.id"), index=True)
    successor_id: Mapped[int] = mapped_column(ForeignKey("wbs_items.id"), index=True)
    dep_type: Mapped[str] = mapped_column(String(10), default="FS")   # FS/SS/FF/SF
    lag_days: Mapped[int] = mapped_column(Integer, default=0)


class ProjectTask(Base, TimestampMixin):
    """通用任务（含敏捷 Task）。"""

    __tablename__ = "project_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    wbs_item_id: Mapped[int | None] = mapped_column(ForeignKey("wbs_items.id"))
    user_story_id: Mapped[int | None] = mapped_column(ForeignKey("user_stories.id"))
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), index=True)
    task_code: Mapped[str | None] = mapped_column(String(40))
    task_name: Mapped[str] = mapped_column(String(200))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    assignee_name: Mapped[str | None] = mapped_column(String(50))
    story_point: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(30), default="BACKLOG", index=True)
    board_column: Mapped[str] = mapped_column(String(30), default="BACKLOG", index=True)
    labels: Mapped[list | None] = mapped_column(JSON, default=list)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    estimate_hours: Mapped[float] = mapped_column(Float, default=0.0)
    actual_hours: Mapped[float] = mapped_column(Float, default=0.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)


class Milestone(Base, TimestampMixin):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_code: Mapped[str | None] = mapped_column(String(40))
    milestone_name: Mapped[str] = mapped_column(String(120))
    plan_date: Mapped[dt.date | None] = mapped_column(Date)
    actual_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String(50))
    deliverable: Mapped[str | None] = mapped_column(String(200))
    is_key: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProjectCost(Base, TimestampMixin):
    __tablename__ = "project_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    cost_code: Mapped[str | None] = mapped_column(String(40))
    cost_subject: Mapped[str] = mapped_column(String(80))       # 预算科目
    cost_type: Mapped[str] = mapped_column(String(40))          # 预算/合同/采购/实际/支付
    budget_amount: Mapped[float] = mapped_column(Float, default=0.0)
    contract_amount: Mapped[float] = mapped_column(Float, default=0.0)
    purchase_amount: Mapped[float] = mapped_column(Float, default=0.0)
    planned_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_amount: Mapped[float] = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    occur_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    supplier: Mapped[str | None] = mapped_column(String(120))
    remark: Mapped[str | None] = mapped_column(Text)


class ProjectRisk(Base, TimestampMixin):
    """风险登记册。"""

    __tablename__ = "project_risks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    risk_code: Mapped[str] = mapped_column(String(40), index=True)
    risk_title: Mapped[str] = mapped_column(String(200))
    risk_description: Mapped[str | None] = mapped_column(Text)
    risk_category: Mapped[str] = mapped_column(String(50))
    probability: Mapped[int] = mapped_column(Integer, default=3)   # 1-5
    impact: Mapped[int] = mapped_column(Integer, default=3)        # 1-5
    risk_score: Mapped[int] = mapped_column(Integer, default=9)
    risk_level: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    risk_owner: Mapped[str | None] = mapped_column(String(50))
    strategy: Mapped[str | None] = mapped_column(String(40))       # 规避/减轻/转移/接受
    response_plan: Mapped[str | None] = mapped_column(Text)
    trigger_condition: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    identified_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    closed_date: Mapped[dt.date | None] = mapped_column(Date)
    ai_identified: Mapped[bool] = mapped_column(Boolean, default=False)
    related_wbs_code: Mapped[str | None] = mapped_column(String(40))


class ProjectIssue(Base, TimestampMixin):
    __tablename__ = "project_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    issue_code: Mapped[str] = mapped_column(String(40))
    issue_title: Mapped[str] = mapped_column(String(200))
    issue_description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    owner: Mapped[str | None] = mapped_column(String(50))
    raised_by: Mapped[str | None] = mapped_column(String(50))
    raised_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    solution: Mapped[str | None] = mapped_column(Text)
    closed_date: Mapped[dt.date | None] = mapped_column(Date)


class ProjectChange(Base, TimestampMixin):
    """变更管理：保存变更前 / 变更后 / 原因 / 申请人 / 审批人。"""

    __tablename__ = "project_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    change_code: Mapped[str] = mapped_column(String(40), index=True)
    change_title: Mapped[str] = mapped_column(String(200))
    change_type: Mapped[str] = mapped_column(String(40))     # 范围/进度/成本/设计/技术/供应商
    change_reason: Mapped[str | None] = mapped_column(Text)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON)
    impact_scope: Mapped[str | None] = mapped_column(Text)
    impact_schedule_days: Mapped[int] = mapped_column(Integer, default=0)
    impact_cost: Mapped[float] = mapped_column(Float, default=0.0)
    impact_risk: Mapped[str | None] = mapped_column(String(200))
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    applicant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applicant_name: Mapped[str | None] = mapped_column(String(50))
    apply_date: Mapped[dt.date | None] = mapped_column(Date)
    approver_name: Mapped[str | None] = mapped_column(String(50))
    approve_date: Mapped[dt.datetime | None] = mapped_column(DateTime)
    approve_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    is_baseline_change: Mapped[bool] = mapped_column(Boolean, default=False)
    new_baseline_version: Mapped[str | None] = mapped_column(String(20))


class Epic(Base, TimestampMixin):
    __tablename__ = "epics"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    epic_code: Mapped[str] = mapped_column(String(40))
    epic_title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    story_points: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    target_date: Mapped[dt.date | None] = mapped_column(Date)


class Feature(Base, TimestampMixin):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    epic_id: Mapped[int | None] = mapped_column(ForeignKey("epics.id"), index=True)
    feature_code: Mapped[str] = mapped_column(String(40))
    feature_title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    story_points: Mapped[int] = mapped_column(Integer, default=0)


class UserStory(Base, TimestampMixin):
    __tablename__ = "user_stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    feature_id: Mapped[int | None] = mapped_column(ForeignKey("features.id"), index=True)
    story_code: Mapped[str] = mapped_column(String(40))
    story_title: Mapped[str] = mapped_column(String(200))
    as_a: Mapped[str | None] = mapped_column(String(100))
    i_want: Mapped[str | None] = mapped_column(Text)
    so_that: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text)
    story_point: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(30), default="BACKLOG", index=True)
    assignee_name: Mapped[str | None] = mapped_column(String(50))
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), index=True)
    labels: Mapped[list | None] = mapped_column(JSON, default=list)
    backlog_order: Mapped[int] = mapped_column(Integer, default=0)


class Sprint(Base, TimestampMixin):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    sprint_code: Mapped[str] = mapped_column(String(40))
    sprint_name: Mapped[str] = mapped_column(String(120))
    sprint_goal: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(String(50))
    story_count: Mapped[int] = mapped_column(Integer, default=0)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    done_points: Mapped[int] = mapped_column(Integer, default=0)
    completed_rate: Mapped[float] = mapped_column(Float, default=0.0)
    velocity: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    review_summary: Mapped[str | None] = mapped_column(Text)
    retro_summary: Mapped[str | None] = mapped_column(Text)
    # 燃尽图数据点：[{date, remaining, ideal}]
    burndown: Mapped[list | None] = mapped_column(JSON, default=list)


class SprintTask(Base, TimestampMixin):
    """Sprint 任务（敏捷看板卡片）。"""

    __tablename__ = "sprint_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    story_id: Mapped[int | None] = mapped_column(ForeignKey("user_stories.id"))
    task_code: Mapped[str] = mapped_column(String(40))
    task_title: Mapped[str] = mapped_column(String(200))
    task_desc: Mapped[str | None] = mapped_column(Text)
    assignee_name: Mapped[str | None] = mapped_column(String(50))
    story_point: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    board_column: Mapped[str] = mapped_column(String(30), default="BACKLOG", index=True)
    labels: Mapped[list | None] = mapped_column(JSON, default=list)
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    column_order: Mapped[int] = mapped_column(Integer, default=0)
    estimate_hours: Mapped[float] = mapped_column(Float, default=0.0)
    actual_hours: Mapped[float] = mapped_column(Float, default=0.0)


# ==========================================================================
# 七、物业 / 设备 / 能耗 / 安全
# ==========================================================================


class WorkOrder(Base, TimestampMixin):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    order_type: Mapped[str] = mapped_column(String(40), index=True)  # 报修/投诉/保洁/巡检/设施维护/企业服务
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"))
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id"))
    location: Mapped[str | None] = mapped_column(String(200))
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    ai_category: Mapped[str | None] = mapped_column(String(50))       # AI 分类
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ai_dispatch_suggestion: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")  # NORMAL/URGENT/MAJOR
    sla_hours: Mapped[float] = mapped_column(Float, default=24.0)
    status: Mapped[str] = mapped_column(String(30), default="SUBMITTED", index=True)
    reporter_name: Mapped[str | None] = mapped_column(String(50))
    reporter_phone: Mapped[str | None] = mapped_column(String(30))
    assignee_name: Mapped[str | None] = mapped_column(String(50))
    assignee_team: Mapped[str | None] = mapped_column(String(60))
    submit_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    dispatch_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    accept_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    close_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    response_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    handle_hours: Mapped[float] = mapped_column(Float, default=0.0)
    is_timeout: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[float | None] = mapped_column(Float)
    rating_comment: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    images: Mapped[list | None] = mapped_column(JSON, default=list)


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    device_name: Mapped[str] = mapped_column(String(120))
    device_type: Mapped[str] = mapped_column(String(50), index=True)  # 电梯/空调/消防/水泵/配电柜/变压器/监控/门禁/充电桩/照明
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"))
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"))
    location: Mapped[str | None] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    serial_no: Mapped[str | None] = mapped_column(String(80))
    owner_name: Mapped[str | None] = mapped_column(String(50))
    supplier: Mapped[str | None] = mapped_column(String(120))
    install_date: Mapped[dt.date | None] = mapped_column(Date)
    warranty_end: Mapped[dt.date | None] = mapped_column(Date)
    service_life_years: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", index=True)  # RUNNING/STANDBY/FAULT/MAINTENANCE/SCRAPPED
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    health_score: Mapped[float] = mapped_column(Float, default=95.0)
    inspect_cycle_days: Mapped[int] = mapped_column(Integer, default=30)
    last_inspect_date: Mapped[dt.date | None] = mapped_column(Date)
    next_maintain_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    runtime_hours: Mapped[float] = mapped_column(Float, default=0.0)
    energy_consumption: Mapped[float] = mapped_column(Float, default=0.0)
    fault_count: Mapped[int] = mapped_column(Integer, default=0)
    is_iot_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    iot_protocol: Mapped[str | None] = mapped_column(String(40))
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0)
    remark: Mapped[str | None] = mapped_column(Text)


class DeviceInspection(Base, TimestampMixin):
    __tablename__ = "device_inspections"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    inspect_code: Mapped[str | None] = mapped_column(String(50))
    inspect_type: Mapped[str] = mapped_column(String(30))   # 巡检/保养/维修/故障
    plan_date: Mapped[dt.date | None] = mapped_column(Date)
    actual_date: Mapped[dt.date | None] = mapped_column(Date)
    inspector: Mapped[str | None] = mapped_column(String(50))
    result: Mapped[str | None] = mapped_column(String(30))  # NORMAL/ABNORMAL/FIXED
    description: Mapped[str | None] = mapped_column(Text)
    fault_desc: Mapped[str | None] = mapped_column(Text)
    solution: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    next_plan_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")


class EnergyRecord(Base, TimestampMixin):
    __tablename__ = "energy_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    energy_type: Mapped[str] = mapped_column(String(20), index=True)   # ELECTRICITY/WATER/GAS/PV/CHARGING
    record_date: Mapped[dt.date] = mapped_column(Date, index=True)
    record_hour: Mapped[int | None] = mapped_column(Integer)
    consumption: Mapped[float] = mapped_column(Float, default=0.0)     # 用量
    unit: Mapped[str] = mapped_column(String(20), default="kWh")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    carbon_kg: Mapped[float] = mapped_column(Float, default=0.0)
    baseline: Mapped[float] = mapped_column(Float, default=0.0)        # 基线值
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    anomaly_ratio: Mapped[float] = mapped_column(Float, default=0.0)   # 偏离基线比例
    anomaly_note: Mapped[str | None] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class SafetyIncident(Base, TimestampMixin):
    __tablename__ = "safety_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"))
    incident_type: Mapped[str] = mapped_column(String(40), index=True)  # 安全生产/消防/隐患/危险源/应急/门禁/访客/车辆/视频事件
    risk_level: Mapped[str] = mapped_column(String(20), default="GENERAL", index=True)  # GENERAL/MAJOR/CRITICAL/URGENT
    severity: Mapped[str] = mapped_column(String(20), default="WARNING")
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(60))       # 巡检/AI识别/IoT/人工上报/视频AI
    found_by: Mapped[str | None] = mapped_column(String(50))
    found_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    responsible_person: Mapped[str | None] = mapped_column(String(50))
    responsible_dept: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="FOUND", index=True)
    # 闭环时间戳
    reported_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    assigned_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    rectified_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    rectify_deadline: Mapped[dt.date | None] = mapped_column(Date)
    rectify_measure: Mapped[str | None] = mapped_column(Text)
    review_result: Mapped[str | None] = mapped_column(String(200))
    handle_hours: Mapped[float] = mapped_column(Float, default=0.0)
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)


class SafetyHazard(Base, TimestampMixin):
    """隐患台账（与事件区分：隐患是常态排查项）。"""

    __tablename__ = "safety_hazards"

    id: Mapped[int] = mapped_column(primary_key=True)
    hazard_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    hazard_type: Mapped[str] = mapped_column(String(50))
    hazard_level: Mapped[str] = mapped_column(String(20), default="GENERAL")
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    found_date: Mapped[dt.date | None] = mapped_column(Date)
    responsible_dept: Mapped[str | None] = mapped_column(String(80))
    rectify_deadline: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="FOUND")
    risk_source_type: Mapped[str | None] = mapped_column(String(50))  # 危险源类型


# ==========================================================================
# 八、企业服务 / 政策
# ==========================================================================


class Policy(Base, TimestampMixin):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    policy_name: Mapped[str] = mapped_column(String(200))
    policy_level: Mapped[str] = mapped_column(String(30))   # 国家级/省级/市级/区级/园区级
    issuing_authority: Mapped[str | None] = mapped_column(String(120))
    policy_category: Mapped[str] = mapped_column(String(60), index=True)  # 高企/专精特新/人才/研发/融资/知识产权/租金补贴
    applicable_industry: Mapped[list | None] = mapped_column(JSON, default=list)
    applicable_scale: Mapped[str | None] = mapped_column(String(100))
    # 匹配条件：结构化
    conditions: Mapped[dict | None] = mapped_column(JSON)
    # 最高补贴金额，单位「元」。前端把它当数值渲染（fmt(sub , 0)），
    # 因此必须是数值列；历史实现声明为 String 且写入 float 字符串，
    # 导致 AI 文本出现「补贴：300000.0」这类未格式化输出。
    subsidy_amount: Mapped[float | None] = mapped_column(Float, default=0.0)
    requirement: Mapped[str | None] = mapped_column(Text)
    material_list: Mapped[list | None] = mapped_column(JSON, default=list)
    publish_date: Mapped[dt.date | None] = mapped_column(Date)
    deadline: Mapped[dt.date | None] = mapped_column(Date, index=True)
    source_url: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class PolicyMatch(Base, TimestampMixin):
    __tablename__ = "policy_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), index=True)
    enterprise_id: Mapped[int] = mapped_column(ForeignKey("enterprises.id"), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_level: Mapped[str] = mapped_column(String(20), default="可能符合")  # 可能符合/建议核验/数据不足
    match_reason: Mapped[str | None] = mapped_column(Text)
    missing_data: Mapped[list | None] = mapped_column(JSON, default=list)
    risk_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="SUGGESTED")
    matched_by: Mapped[str | None] = mapped_column(String(40), default="AI")


class ServiceRequest(Base, TimestampMixin):
    """企业服务诉求（政策申报/人才/金融/法律/培训/会议室/活动）。"""

    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    service_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    requirement: Mapped[str | None] = mapped_column(Text)
    contact_person: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    status: Mapped[str] = mapped_column(String(30), default="SUBMITTED", index=True)
    handler: Mapped[str | None] = mapped_column(String(50))
    handle_note: Mapped[str | None] = mapped_column(Text)
    submit_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    satisfaction: Mapped[float | None] = mapped_column(Float)


class Activity(Base, TimestampMixin):
    """园区活动 / 公告。"""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    activity_type: Mapped[str] = mapped_column(String(40))   # 培训/沙龙/政策宣讲/招聘/文体/公告
    content: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[dt.datetime | None] = mapped_column(DateTime)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime)
    location: Mapped[str | None] = mapped_column(String(200))
    organizer: Mapped[str | None] = mapped_column(String(100))
    max_participants: Mapped[int] = mapped_column(Integer, default=0)
    registered_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")


class MeetingRoomBooking(Base, TimestampMixin):
    __tablename__ = "meeting_room_bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id"))
    space_name: Mapped[str | None] = mapped_column(String(120))
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    booker: Mapped[str | None] = mapped_column(String(50))
    book_date: Mapped[dt.date | None] = mapped_column(Date)
    start_time: Mapped[str | None] = mapped_column(String(10))
    end_time: Mapped[str | None] = mapped_column(String(10))
    attendees: Mapped[int] = mapped_column(Integer, default=0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="BOOKED")


# ==========================================================================
# 九、收费 / 停车
# ==========================================================================


class Bill(Base, TimestampMixin):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), index=True)
    space_id: Mapped[int | None] = mapped_column(ForeignKey("spaces.id"))
    fee_type: Mapped[str] = mapped_column(String(40), index=True)  # 租金/物业费/水费/电费/停车费/服务费/会议室/其他
    period: Mapped[str | None] = mapped_column(String(30))
    # bill_date 是账单所有日期区间汇总（本月/上月/去年同月/近 12 个月趋势）
    # 的过滤列，必须建索引；否则每次汇总都要全表扫 3.5 万行。
    bill_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    reduction_amount: Mapped[float] = mapped_column(Float, default=0.0)
    receivable: Mapped[float] = mapped_column(Float, default=0.0)
    received: Mapped[float] = mapped_column(Float, default=0.0)
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0)
    arrears: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="UNPAID", index=True)  # UNPAID/PARTIAL/PAID/OVERDUE/REFUNDED
    overdue_days: Mapped[int] = mapped_column(Integer, default=0)
    age_bucket: Mapped[str | None] = mapped_column(String(20))    # 0-30 / 31-60 / 61-90 / 90+
    invoice_status: Mapped[str | None] = mapped_column(String(20))
    invoice_no: Mapped[str | None] = mapped_column(String(60))
    dunning_count: Mapped[int] = mapped_column(Integer, default=0)
    last_dunning_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    remark: Mapped[str | None] = mapped_column(Text)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"), index=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    pay_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    pay_method: Mapped[str | None] = mapped_column(String(30))
    pay_type: Mapped[str] = mapped_column(String(20), default="RECEIPT")   # RECEIPT收款 / REFUND退款
    operator: Mapped[str | None] = mapped_column(String(50))
    remark: Mapped[str | None] = mapped_column(Text)


class ParkingSpace(Base, TimestampMixin):
    __tablename__ = "parking_spaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    area_name: Mapped[str | None] = mapped_column(String(80))
    parking_type: Mapped[str] = mapped_column(String(30), default="NORMAL")  # NORMAL/CHARGING/ACCESSIBLE/VIP
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    space_no: Mapped[str | None] = mapped_column(String(20))
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    vehicle_plate: Mapped[str | None] = mapped_column(String(20))
    monthly_fee: Mapped[float] = mapped_column(Float, default=0.0)
    has_charger: Mapped[bool] = mapped_column(Boolean, default=False)
    charger_power: Mapped[float] = mapped_column(Float, default=0.0)


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    vehicle_type: Mapped[str] = mapped_column(String(30), default="FUEL")   # FUEL/NEW_ENERGY
    owner_type: Mapped[str] = mapped_column(String(30), default="ENTERPRISE")  # ENTERPRISE/VISITOR/STAFF
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    owner_name: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(30))
    card_type: Mapped[str | None] = mapped_column(String(30))   # 月卡/年卡/临时
    card_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
    parking_space_id: Mapped[int | None] = mapped_column(ForeignKey("parking_spaces.id"))


class Visitor(Base, TimestampMixin):
    __tablename__ = "visitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    visitor_name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(30))
    id_card_mask: Mapped[str | None] = mapped_column(String(30))
    company: Mapped[str | None] = mapped_column(String(120))
    visit_purpose: Mapped[str | None] = mapped_column(String(120))
    visit_enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    visit_enterprise_name: Mapped[str | None] = mapped_column(String(200))
    visit_person: Mapped[str | None] = mapped_column(String(50))
    visit_time: Mapped[dt.datetime | None] = mapped_column(DateTime)
    leave_time: Mapped[dt.datetime | None] = mapped_column(DateTime)
    plate_no: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="APPROVED")
    approver: Mapped[str | None] = mapped_column(String(50))


class AccessRecord(Base, TimestampMixin):
    __tablename__ = "access_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    park_id: Mapped[int] = mapped_column(ForeignKey("parks.id"), index=True)
    access_type: Mapped[str] = mapped_column(String(30))  # PERSON/VEHICLE
    gate_name: Mapped[str | None] = mapped_column(String(80))
    subject_name: Mapped[str | None] = mapped_column(String(80))
    plate_no: Mapped[str | None] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(10))  # IN/OUT
    access_time: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    device_code: Mapped[str | None] = mapped_column(String(60))
    result: Mapped[str] = mapped_column(String(20), default="PASS")


# ==========================================================================
# 十、AI / 审批 / 数据 / 系统
# ==========================================================================


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"))
    agent_key: Mapped[str | None] = mapped_column(String(40))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class AIMessage(Base, TimestampMixin):
    """AI 对话消息，结构化保存【结论】【关键数据】等分区与数据依据。"""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))     # user / assistant
    content: Mapped[str] = mapped_column(Text)
    agent_key: Mapped[str | None] = mapped_column(String(40))
    agent_name: Mapped[str | None] = mapped_column(String(60))
    intent: Mapped[str | None] = mapped_column(String(60))
    structured: Mapped[dict | None] = mapped_column(JSON)   # 统一输出格式分区
    evidence: Mapped[dict | None] = mapped_column(JSON)     # 数据来源 / 调用模块 / 算法
    permission_level: Mapped[str | None] = mapped_column(String(10))
    decision_status: Mapped[str | None] = mapped_column(String(20))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    data_sufficient: Mapped[bool] = mapped_column(Boolean, default=True)


class AIRecommendation(Base, TimestampMixin):
    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    rec_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    agent_key: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON)
    severity: Mapped[str] = mapped_column(String(20), default="INFO")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    related_module: Mapped[str | None] = mapped_column(String(50))
    related_object_type: Mapped[str | None] = mapped_column(String(50))
    related_object_id: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    suggestion: Mapped[str | None] = mapped_column(Text)
    action_label: Mapped[str | None] = mapped_column(String(50))
    action_route: Mapped[str | None] = mapped_column(String(200))
    permission_level: Mapped[str] = mapped_column(String(10), default="L1")
    decision_status: Mapped[str] = mapped_column(String(20), default="信息提示")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    generated_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    read_count: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    approval_type: Mapped[str] = mapped_column(String(50), index=True)
    # 合同/费用/采购/项目/预算/项目变更/企业准入/退租/风险处置
    title: Mapped[str] = mapped_column(String(200))
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    related_object_type: Mapped[str | None] = mapped_column(String(50))
    related_object_id: Mapped[int | None] = mapped_column(Integer)
    enterprise_id: Mapped[int | None] = mapped_column(ForeignKey("enterprises.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    content: Mapped[str | None] = mapped_column(Text)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    urgency: Mapped[str] = mapped_column(String(20), default="NORMAL")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, default=1)
    applicant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applicant_name: Mapped[str | None] = mapped_column(String(50))
    apply_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    finish_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(40))   # AI建议 / 人工提交
    remark: Mapped[str | None] = mapped_column(Text)


class ApprovalStep(Base, TimestampMixin):
    __tablename__ = "approval_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    step_no: Mapped[int] = mapped_column(Integer, default=1)
    step_name: Mapped[str] = mapped_column(String(80))
    approver_role: Mapped[str | None] = mapped_column(String(60))
    approver_name: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    comment: Mapped[str | None] = mapped_column(Text)
    approve_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    duration_hours: Mapped[float] = mapped_column(Float, default=0.0)


class DataUpload(Base, TimestampMixin):
    __tablename__ = "data_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    file_name: Mapped[str] = mapped_column(String(200))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_type: Mapped[str] = mapped_column(String(20), default="CSV")
    data_type: Mapped[str] = mapped_column(String(50), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    uploader_name: Mapped[str | None] = mapped_column(String(50))
    upload_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    columns: Mapped[list | None] = mapped_column(JSON, default=list)
    preview: Mapped[list | None] = mapped_column(JSON, default=list)
    mapping: Mapped[dict | None] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class DataQualityIssue(Base, TimestampMixin):
    """数据质量问题明细（禁止静默修改数据，逐条列出并给出处理方式）。"""

    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("data_uploads.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer, default=0)
    column_name: Mapped[str | None] = mapped_column(String(80))
    field_key: Mapped[str | None] = mapped_column(String(80))
    raw_value: Mapped[str | None] = mapped_column(String(300))
    issue_type: Mapped[str] = mapped_column(String(40), index=True)
    # FIELD_MAPPING/DATA_TYPE/MISSING/DUPLICATE/OUTLIER/DATE_FORMAT/PRIMARY_KEY/REFERENCE
    severity: Mapped[str] = mapped_column(String(20), default="WARNING")
    description: Mapped[str] = mapped_column(String(400))
    suggestion: Mapped[str | None] = mapped_column(String(400))
    suggested_value: Mapped[str | None] = mapped_column(String(300))
    handle_mode: Mapped[str | None] = mapped_column(String(30))  # AUTO_CLEAN/MANUAL_CONFIRM/KEEP_RAW
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class DataQualityReport(Base, TimestampMixin):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("data_uploads.id"), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"))
    data_type: Mapped[str] = mapped_column(String(50))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    completeness: Mapped[float] = mapped_column(Float, default=0.0)
    uniqueness: Mapped[float] = mapped_column(Float, default=0.0)
    validity: Mapped[float] = mapped_column(Float, default=0.0)
    consistency: Mapped[float] = mapped_column(Float, default=0.0)
    timeliness: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    issue_summary: Mapped[dict | None] = mapped_column(JSON)
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class ReportRecord(Base, TimestampMixin):
    """报表生成记录。"""

    __tablename__ = "report_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    report_name: Mapped[str] = mapped_column(String(200))
    report_type: Mapped[str] = mapped_column(String(50), index=True)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    period: Mapped[str | None] = mapped_column(String(40))
    format: Mapped[str] = mapped_column(String(10), default="JSON")
    generated_by: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[dict | None] = mapped_column(JSON)
    file_path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="DONE")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    notice_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    notice_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="INFO", index=True)
    related_module: Mapped[str | None] = mapped_column(String(50))
    related_object_type: Mapped[str | None] = mapped_column(String(50))
    related_object_id: Mapped[int | None] = mapped_column(Integer)
    related_object_name: Mapped[str | None] = mapped_column(String(200))
    trigger_value: Mapped[str | None] = mapped_column(String(120))
    threshold: Mapped[str | None] = mapped_column(String(120))
    suggestion: Mapped[str | None] = mapped_column(Text)
    action_label: Mapped[str | None] = mapped_column(String(50))
    action_route: Mapped[str | None] = mapped_column(String(200))
    target_roles: Mapped[list | None] = mapped_column(JSON, default=list)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_handled: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[dt.datetime | None] = mapped_column(DateTime, index=True)
    deadline: Mapped[dt.datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    log_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    username: Mapped[str | None] = mapped_column(String(60))
    real_name: Mapped[str | None] = mapped_column(String(50))
    park_id: Mapped[int | None] = mapped_column(ForeignKey("parks.id"), index=True)
    module: Mapped[str] = mapped_column(String(50), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    object_type: Mapped[str | None] = mapped_column(String(50))
    object_id: Mapped[int | None] = mapped_column(Integer)
    object_name: Mapped[str | None] = mapped_column(String(200))
    before_value: Mapped[dict | None] = mapped_column(JSON)
    after_value: Mapped[dict | None] = mapped_column(JSON)
    change_summary: Mapped[str | None] = mapped_column(Text)
    approval_info: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(30))   # USER / AI / SYSTEM
    ip_address: Mapped[str | None] = mapped_column(String(60))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    result: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)

"""多园区多租户模拟演示数据生成器。

覆盖 4 个不同类型园区：
  1. 星海科技产业园（TECH）—— 科技园区模板
  2. 云谷智能制造工业园（INDUSTRIAL）—— 工业园模板
  3. 枢纽智慧物流园（LOGISTICS）—— 物流园模板
  4. 创芯产业创新中心（INNOVATION）—— 孵化器模板

生成内容：组织/园区模板/园区/楼栋/楼层/空间/企业/联系人/用户/角色/权限/
招商线索/跟进/活动/渠道/合同/收款计划/账单/收款/项目（瀑布+敏捷+混合）/
阶段/WBS/依赖/里程碑/成本/风险/问题/变更/Epic/Feature/UserStory/Sprint/SprintTask/
工单/设备/巡检/能耗/安全事件/隐患/政策/政策匹配/服务请求/活动/会议室预约/
停车位/车辆/访客/通行记录/AI建议/审批/审批步骤/数据上传/数据质量问题/数据质量报告/
报表/通知/审计日志。

所有企业均为虚构名称，脚本中明确标注 demo_data_marker。
"""
from __future__ import annotations

import datetime as dt
import random
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import *  # noqa: F403
from app.models import (  # 显式导入以避免歧义
    AccessRecord, Activity, AIConversation, AIMessage, AIRecommendation,
    ApprovalRequest, ApprovalStep, AuditLog, Bill, Building, Channel, Contract,
    ContractPayment, DataQualityIssue, DataQualityReport, DataUpload, Device,
    DeviceInspection, EnergyRecord, Enterprise, EnterpriseContact, EnterpriseTag,
    Epic, Feature, Floor, LeasingActivity, LeasingFollowup, LeasingLead,
    MeetingRoomBooking, Milestone, Notification, Organization, Park, ParkingSpace,
    ParkTemplate, Payment, Permission, Policy, PolicyMatch, Project, ProjectChange,
    ProjectCost, ProjectIssue, ProjectPhase, ProjectRisk, ProjectTask, ReportRecord,
    Role, RolePermission, SafetyHazard, SafetyIncident, ServiceRequest, Space,
    Sprint, SprintTask, TaskDependency, User, UserParkScope, UserProjectScope,
    UserRole, UserStory, Vehicle, Visitor, WbsItem, WorkOrder,
)

random.seed(20260917)
TODAY = dt.date.today()
NOW = dt.datetime.now()
DEMO_MARKER = "演示数据"
GEN = f"DEMO-{TODAY.isoformat()}"


def d(offset_days: int) -> dt.date:
    return TODAY + dt.timedelta(days=offset_days)


def dtm(offset_days: int = 0, hour: int = 9, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(d(offset_days), dt.time(hour, minute))


def pick(seq, i: int):
    return seq[i % len(seq)]


# 中文取名字库
SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
GIVEN = ["伟", "芳", "娜", "敏", "静", "强", "磊", "洋", "艳", "勇", "军", "杰", "娟", "涛",
         "明", "超", "秀英", "霞", "平", "刚", "桂英", "文", "辉", "建国", "建华", "晨", "欣",
         "宇", "阳", "璇", "蕊", "婷", "亮", "鹏", "峰", "琳", "楠", "雪", "博", "菲", "睿"]


def cn_name(i: int) -> str:
    return f"{SURNAMES[i % len(SURNAMES)]}{GIVEN[(i * 7) % len(GIVEN)]}"


def phone(i: int) -> str:
    return f"13{8 + i % 2}{(10000000 + i * 137) % 100000000:08d}"


def credit_code(i: int) -> str:
    chars = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    body = "".join(chars[(i * 31 + k * 17) % len(chars)] for k in range(17))
    return f"91{body[:15]}{chars[(i * 7) % len(chars)]}"


INDUSTRIES = ["软件和信息技术服务业", "电子设备制造业", "智能制造装备", "生物医药",
              "新材料", "现代物流", "电子商务", "人工智能", "集成电路", "新能源",
              "工业设计", "检验检测服务", "供应链管理", "汽车零部件", "精密仪器"]

TECH_IND = ["软件和信息技术服务业", "人工智能", "集成电路", "电子商务", "工业设计",
            "检验检测服务", "电子设备制造业"]
MFG_IND = ["智能制造装备", "汽车零部件", "精密仪器", "新材料", "新能源", "电子设备制造业"]
LOG_IND = ["现代物流", "供应链管理", "电子商务", "汽车零部件"]
INNO_IND = ["软件和信息技术服务业", "人工智能", "生物医药", "新材料"]

MFG_PREFIX = ["精", "华", "恒", "泰", "鼎", "力", "正", "宏", "深", "拓", "联", "卓", "锐", "固"]
MFG_MID = ["创", "智", "信", "达", "鑫", "锐", "科", "捷", "芯", "航", "盛", "越"]
MFG_SUFFIX = ["精密制造有限公司", "智能装备有限公司", "电子科技有限公司",
              "新材料科技有限公司", "产业发展有限公司", "科技股份有限公司",
              "智能制造有限公司", "自动化设备有限公司"]

SOFT_PREFIX = ["智", "云", "数", "思", "极", "未", "星", "灵", "诺", "拓", "点", "凌"]
SOFT_MID = ["联", "智", "科", "元", "维", "策", "讯", "码", "云", "慧"]
SOFT_SUFFIX = ["科技有限公司", "软件技术有限公司", "信息技术有限公司",
               "智能科技有限公司", "网络科技有限公司", "数据科技有限公司"]

LOG_PREFIX = ["顺", "通", "捷", "安", "联", "汇", "运", "驰", "宝", "中"]
LOG_SUFFIX = ["供应链管理有限公司", "物流有限公司", "仓储服务有限公司",
              "国际物流有限公司", "供应链科技有限公司"]


def gen_company_name(i: int, kind: str) -> str:
    if kind == "mfG":
        return f"{pick(MFG_PREFIX, i)}{pick(MFG_MID, i * 3)}{pick(MFG_SUFFIX, i * 5)}"
    if kind == "log":
        return f"{pick(LOG_PREFIX, i)}{pick(LOG_PREFIX, i * 2)}{pick(LOG_SUFFIX, i * 3)}"
    return f"{pick(SOFT_PREFIX, i)}{pick(SOFT_MID, i * 3)}{pick(SOFT_SUFFIX, i * 5)}"


# ==========================================================================
# 平台功能模块与园区模板（需求书第 4 节）
# ==========================================================================

ALL_MODULES = [
    "dashboard", "leasing", "enterprise", "space", "project", "contract",
    "property", "device", "energy", "safety", "service", "finance",
    "parking", "ai", "data", "approval", "report", "notification", "system",
]

PARK_TEMPLATES = [
    {
        "template_code": "TPL_TECH", "template_name": "科技产业园模板", "park_type": "TECH",
        "description": "面向科技产业园、软件园，重点覆盖企业服务、人才服务、政策服务、办公租赁、招商管理。",
        "enabled_modules": ["dashboard", "leasing", "enterprise", "space", "project", "contract",
                            "property", "device", "energy", "safety", "service", "finance",
                            "parking", "ai", "data", "approval", "report", "notification", "system"],
        "focus_areas": ["企业服务", "人才服务", "政策服务", "办公租赁", "招商管理"],
        "dashboard_kpis": ["enterprise_count", "occupancy_rate", "conversion_rate", "monthly_income",
                           "collection_rate", "safety_risk", "energy_total", "project_active"],
        "default_space_types": ["OFFICE", "LAB", "MEETING", "WORKSTATION", "SHOP", "PARKING"],
        "sort_order": 1,
    },
    {
        "template_code": "TPL_INDUSTRIAL", "template_name": "工业园区模板", "park_type": "INDUSTRIAL",
        "description": "面向工业园、制造业园区，重点覆盖厂房、设备、工程、能源、安全生产。",
        "enabled_modules": ["dashboard", "leasing", "enterprise", "space", "project", "contract",
                            "property", "device", "energy", "safety", "finance", "parking",
                            "ai", "data", "approval", "report", "notification", "system"],
        "focus_areas": ["厂房", "设备", "工程", "能源", "安全生产"],
        "dashboard_kpis": ["enterprise_count", "occupancy_rate", "energy_total", "safety_risk",
                           "device_online_rate", "project_active", "project_delayed", "budget_execution"],
        "default_space_types": ["FACTORY", "WAREHOUSE", "OFFICE", "PARKING"],
        "sort_order": 2,
    },
    {
        "template_code": "TPL_LOGISTICS", "template_name": "物流园模板", "park_type": "LOGISTICS",
        "description": "面向物流园，重点覆盖仓储、车辆、停车、物流设施、仓库出租。",
        "enabled_modules": ["dashboard", "leasing", "enterprise", "space", "project", "contract",
                            "property", "device", "energy", "safety", "finance", "parking",
                            "ai", "data", "approval", "report", "notification", "system"],
        "focus_areas": ["仓储", "车辆", "停车", "物流设施", "仓库出租"],
        "dashboard_kpis": ["enterprise_count", "occupancy_rate", "available_area", "monthly_income",
                           "collection_rate", "work_order_rate", "energy_total", "safety_risk"],
        "default_space_types": ["WAREHOUSE", "FACTORY", "OFFICE", "PARKING"],
        "sort_order": 3,
    },
    {
        "template_code": "TPL_INCUBATOR", "template_name": "创业孵化器模板", "park_type": "INCUBATOR",
        "description": "面向孵化器与创新中心，重点覆盖创业企业、工位、会议室、融资、政策、成长管理。",
        "enabled_modules": ["dashboard", "leasing", "enterprise", "space", "project", "contract",
                            "property", "service", "finance", "ai", "data", "approval",
                            "report", "notification", "system"],
        "focus_areas": ["创业企业", "工位", "会议室", "融资", "政策", "成长管理"],
        "dashboard_kpis": ["enterprise_count", "space_occupancy", "conversion_rate",
                           "monthly_income", "project_active", "conversion_rate"],
        "default_space_types": ["OFFICE", "WORKSTATION", "MEETING", "LAB", "PARKING"],
        "sort_order": 4,
    },
    {
        "template_code": "TPL_CHEMICAL", "template_name": "化工园区模板", "park_type": "CHEMICAL",
        "description": "面向化工园区，重点覆盖安全生产、危险源、设备、环保、能耗、应急管理。",
        "enabled_modules": ["dashboard", "enterprise", "space", "project", "contract", "device",
                            "energy", "safety", "finance", "ai", "data", "approval", "report",
                            "notification", "system"],
        "focus_areas": ["安全生产", "危险源", "设备", "环保", "能耗", "应急管理"],
        "dashboard_kpis": ["enterprise_count", "safety_risk", "device_online_rate", "energy_total"],
        "default_space_types": ["FACTORY", "WAREHOUSE", "LAB", "PARKING"],
        "sort_order": 5,
    },
]

# ==========================================================================
# 角色与权限矩阵（需求书第 41-42 节）
# ==========================================================================

ROLES = [
    ("SUPER_ADMIN", "集团管理员", "集团", "GROUP", "查看所有园区全部数据与配置权限"),
    ("GROUP_ADMIN", "集团管理员", "集团", "GROUP", "查看所有园区全部数据与配置权限"),
    ("PARK_MANAGER", "园区负责人", "园区", "PARK", "仅管理自己园区的业务数据"),
    ("LEASING_MANAGER", "招商主管", "招商", "PARK", "招商线索、商机、签约管理"),
    ("LEASING_STAFF", "招商专员", "招商", "PARK", "线索跟进与客户维护"),
    ("OPERATION_STAFF", "运营人员", "运营", "PARK", "空间、合同、企业服务日常运营"),
    ("PROJECT_MANAGER", "项目经理", "项目", "PROJECT", "查看并管理授权项目"),
    ("PROJECT_MEMBER", "项目成员", "项目", "PROJECT", "查看参与的项目并更新任务"),
    ("PROPERTY_STAFF", "物业人员", "物业", "PARK", "物业工单、设备巡检处理"),
    ("FINANCE_STAFF", "财务人员", "财务", "PARK", "收费、账单、催缴管理"),
    ("SAFETY_STAFF", "安全人员", "安全", "PARK", "安全事件、隐患、巡检管理"),
    ("ENTERPRISE_ADMIN", "企业管理员", "企业", "ENTERPRISE", "仅查看本企业数据与服务"),
    ("ENTERPRISE_STAFF", "企业员工", "企业", "ENTERPRISE", "查看本人授权的服务"),
    ("SYS_ADMIN", "系统管理员", "系统", "GROUP", "用户、角色、权限、日志管理"),
    ("VIEWER", "普通查看人员", "只读", "SELF", "只读查看，无编辑权限"),
]

MODULES_FOR_PERM = [
    ("dashboard", "驾驶舱"), ("park", "园区管理"), ("enterprise", "企业全生命周期"),
    ("space", "空间与资产"), ("leasing", "招商管理"), ("contract", "租赁与合同"),
    ("project", "项目管理中心"), ("property", "物业服务中心"), ("device", "设备设施"),
    ("energy", "能源与低碳"), ("safety", "安全风险管理"), ("service", "企业服务中心"),
    ("policy", "政策服务"), ("finance", "财务收费"), ("parking", "停车与通行"),
    ("ai", "AI园区助手"), ("data", "数据中心"), ("approval", "审批中心"),
    ("report", "报表中心"), ("notification", "消息预警"), ("system", "系统管理"),
    ("audit", "日志审计"),
]

ACTIONS = [("VIEW", "查看"), ("ADD", "新增"), ("EDIT", "编辑"), ("DELETE", "删除"),
           ("IMPORT", "导入"), ("EXPORT", "导出"), ("APPROVE", "审批"),
           ("AI", "AI分析"), ("CONFIG", "配置")]

# 各角色的权限范围（模块 → 动作集）
ROLE_PERM_MATRIX = {
    "SUPER_ADMIN": {"*": ["VIEW", "ADD", "EDIT", "DELETE", "IMPORT", "EXPORT", "APPROVE", "AI", "CONFIG"]},
    "GROUP_ADMIN": {"*": ["VIEW", "ADD", "EDIT", "DELETE", "IMPORT", "EXPORT", "APPROVE", "AI", "CONFIG"]},
    "PARK_MANAGER": {
        "dashboard": ["VIEW", "EXPORT", "AI"], "park": ["VIEW", "EDIT"],
        "enterprise": ["VIEW", "ADD", "EDIT", "EXPORT", "AI"], "space": ["VIEW", "ADD", "EDIT", "EXPORT"],
        "leasing": ["VIEW", "ADD", "EDIT", "APPROVE", "AI"], "contract": ["VIEW", "ADD", "EDIT", "APPROVE"],
        "project": ["VIEW", "ADD", "EDIT", "APPROVE", "AI", "EXPORT"], "property": ["VIEW", "EDIT", "APPROVE"],
        "device": ["VIEW", "EDIT"], "energy": ["VIEW", "AI"], "safety": ["VIEW", "ADD", "EDIT", "APPROVE"],
        "service": ["VIEW", "ADD", "EDIT"], "policy": ["VIEW", "AI"], "finance": ["VIEW", "APPROVE", "EXPORT"],
        "parking": ["VIEW", "EDIT"], "ai": ["VIEW", "AI"], "data": ["VIEW", "IMPORT", "EXPORT"],
        "approval": ["VIEW", "APPROVE"], "report": ["VIEW", "EXPORT"], "notification": ["VIEW"],
        "audit": ["VIEW"],
    },
    "LEASING_MANAGER": {
        "dashboard": ["VIEW", "AI"], "enterprise": ["VIEW", "ADD", "EDIT", "AI"],
        "space": ["VIEW"], "leasing": ["VIEW", "ADD", "EDIT", "DELETE", "IMPORT", "EXPORT", "APPROVE", "AI"],
        "contract": ["VIEW", "ADD", "EDIT"], "ai": ["VIEW", "AI"], "report": ["VIEW", "EXPORT"],
        "notification": ["VIEW"], "data": ["VIEW", "IMPORT", "EXPORT"], "approval": ["VIEW"],
    },
    "LEASING_STAFF": {
        "dashboard": ["VIEW", "AI"], "enterprise": ["VIEW", "ADD", "EDIT"],
        "space": ["VIEW"], "leasing": ["VIEW", "ADD", "EDIT", "AI"], "contract": ["VIEW"],
        "ai": ["VIEW", "AI"], "notification": ["VIEW"],
    },
    "OPERATION_STAFF": {
        "dashboard": ["VIEW", "AI"], "enterprise": ["VIEW", "ADD", "EDIT", "AI"],
        "space": ["VIEW", "ADD", "EDIT"], "leasing": ["VIEW", "ADD", "EDIT"],
        "contract": ["VIEW", "ADD", "EDIT"], "project": ["VIEW"], "property": ["VIEW", "ADD", "EDIT"],
        "service": ["VIEW", "ADD", "EDIT"], "policy": ["VIEW", "AI"], "finance": ["VIEW"],
        "parking": ["VIEW", "EDIT"], "ai": ["VIEW", "AI"], "report": ["VIEW"],
        "notification": ["VIEW"], "approval": ["VIEW"],
    },
    "PROJECT_MANAGER": {
        "dashboard": ["VIEW", "AI"], "project": ["VIEW", "ADD", "EDIT", "APPROVE", "AI", "EXPORT"],
        "approval": ["VIEW"], "report": ["VIEW", "EXPORT"], "ai": ["VIEW", "AI"],
        "notification": ["VIEW"], "data": ["VIEW", "IMPORT"],
    },
    "PROJECT_MEMBER": {
        "dashboard": ["VIEW"], "project": ["VIEW", "EDIT"], "ai": ["VIEW", "AI"],
        "notification": ["VIEW"], "report": ["VIEW"],
    },
    "PROPERTY_STAFF": {
        "dashboard": ["VIEW"], "property": ["VIEW", "ADD", "EDIT"], "device": ["VIEW", "ADD", "EDIT"],
        "energy": ["VIEW", "ADD"], "safety": ["VIEW", "ADD", "EDIT"], "space": ["VIEW"],
        "ai": ["VIEW", "AI"], "notification": ["VIEW"],
    },
    "FINANCE_STAFF": {
        "dashboard": ["VIEW", "AI"], "finance": ["VIEW", "ADD", "EDIT", "IMPORT", "EXPORT", "AI"],
        "contract": ["VIEW"], "enterprise": ["VIEW"], "report": ["VIEW", "EXPORT"],
        "ai": ["VIEW", "AI"], "notification": ["VIEW"], "approval": ["VIEW"],
    },
    "SAFETY_STAFF": {
        "dashboard": ["VIEW"], "safety": ["VIEW", "ADD", "EDIT", "APPROVE", "AI"],
        "device": ["VIEW", "EDIT"], "property": ["VIEW", "ADD", "EDIT"],
        "ai": ["VIEW", "AI"], "notification": ["VIEW"], "report": ["VIEW"],
    },
    "ENTERPRISE_ADMIN": {
        "dashboard": ["VIEW"], "enterprise": ["VIEW", "EDIT"], "contract": ["VIEW"],
        "service": ["VIEW", "ADD"], "finance": ["VIEW"], "property": ["VIEW", "ADD"],
        "parking": ["VIEW", "ADD"], "ai": ["VIEW", "AI"], "notification": ["VIEW"],
    },
    "ENTERPRISE_STAFF": {
        "dashboard": ["VIEW"], "enterprise": ["VIEW"], "service": ["VIEW", "ADD"],
        "property": ["VIEW", "ADD"], "notification": ["VIEW"],
    },
    "SYS_ADMIN": {
        "system": ["VIEW", "ADD", "EDIT", "DELETE", "CONFIG"], "audit": ["VIEW", "EXPORT"],
        "dashboard": ["VIEW"], "data": ["VIEW", "IMPORT", "EXPORT", "CONFIG"],
        "notification": ["VIEW"], "ai": ["VIEW"],
    },
    "VIEWER": {"dashboard": ["VIEW"], "report": ["VIEW"], "notification": ["VIEW"], "ai": ["VIEW"]},
}

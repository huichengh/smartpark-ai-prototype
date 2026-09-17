"""平台统一枚举定义（业务口径唯一来源）。"""
from __future__ import annotations

from enum import StrEnum


class ManagementMethod(StrEnum):
    WATERFALL = "WATERFALL"      # 瀑布式
    AGILE = "AGILE"              # 敏捷式
    HYBRID = "HYBRID"            # 混合式


class ProjectStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    DELAYED = "DELAYED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class RiskLevel(StrEnum):
    LOW = "LOW"            # 低
    MEDIUM = "MEDIUM"      # 中
    HIGH = "HIGH"          # 高
    CRITICAL = "CRITICAL"  # 重大


class SpaceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"        # 可租
    RESERVED = "RESERVED"          # 已预订 / 预留
    RENTED = "RENTED"              # 已出租
    RENOVATING = "RENOVATING"      # 装修中
    MAINTENANCE = "MAINTENANCE"    # 维修中
    SELF_USE = "SELF_USE"          # 自用
    FROZEN = "FROZEN"              # 冻结
    DISABLED = "DISABLED"          # 停用


class SpaceType(StrEnum):
    OFFICE = "OFFICE"          # 办公楼
    FACTORY = "FACTORY"        # 厂房
    WAREHOUSE = "WAREHOUSE"    # 仓库
    SHOP = "SHOP"              # 商铺
    LAB = "LAB"                # 实验室
    MEETING = "MEETING"        # 会议室
    WORKSTATION = "WORKSTATION"  # 工位
    PARKING = "PARKING"        # 停车位
    PUBLIC = "PUBLIC"          # 公共空间


class EnterpriseStatus(StrEnum):
    POTENTIAL = "POTENTIAL"    # 潜在企业
    INTENT = "INTENT"          # 意向企业
    SIGNED = "SIGNED"          # 签约企业
    SETTLED = "SETTLED"        # 入驻企业
    GROWING = "GROWING"        # 成长企业
    RISK = "RISK"              # 风险企业
    EXITED = "EXITED"          # 退园企业


class LeadStage(StrEnum):
    LEAD = "LEAD"                    # 潜在线索
    CONTACTED = "CONTACTED"          # 已联系
    QUALIFIED = "QUALIFIED"          # 有效商机
    SITE_VISIT = "SITE_VISIT"        # 实地看房
    NEGOTIATION = "NEGOTIATION"      # 商务谈判
    CONTRACT_APPROVAL = "CONTRACT_APPROVAL"  # 合同审批
    SIGNED = "SIGNED"                # 签约
    SETTLED = "SETTLED"              # 入驻
    LOST = "LOST"                    # 流失


class ContractStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class WorkOrderStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CLASSIFIED = "CLASSIFIED"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    VERIFYING = "VERIFYING"
    RATED = "RATED"
    CLOSED = "CLOSED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"        # 待审批
    IN_REVIEW = "IN_REVIEW"    # 审批中
    APPROVED = "APPROVED"      # 已通过
    REJECTED = "REJECTED"      # 已拒绝
    WITHDRAWN = "WITHDRAWN"    # 已撤回


class DecisionStatus(StrEnum):
    """AI 输出的决策状态。"""
    INFO = "信息提示"
    AI_SUGGESTION = "AI建议"
    NEED_CONFIRM = "需人工确认"
    NEED_APPROVAL = "待审批"


class AIPermissionLevel(StrEnum):
    L1_QUERY = "L1"       # 信息查询
    L2_ADVISE = "L2"      # 分析与建议
    L3_ACTION = "L3"      # 高影响动作（必须人工审批）


class ParkType(StrEnum):
    TECH = "TECH"                     # 科技产业园
    SOFTWARE = "SOFTWARE"             # 软件园
    INDUSTRIAL = "INDUSTRIAL"         # 工业园
    MANUFACTURING = "MANUFACTURING"   # 制造业园区
    LOGISTICS = "LOGISTICS"           # 物流园
    ECOMMERCE = "ECOMMERCE"           # 电商产业园
    BIOMED = "BIOMED"                 # 生物医药园
    CULTURE = "CULTURE"               # 文创园
    INCUBATOR = "INCUBATOR"           # 创业孵化器
    HEADQUARTER = "HEADQUARTER"       # 总部经济园
    OFFICE = "OFFICE"                 # 写字楼型产业园
    CHEMICAL = "CHEMICAL"             # 化工园区
    INNOVATION = "INNOVATION"         # 产业创新中心


class ProjectType(StrEnum):
    PARK_CONSTRUCTION = "PARK_CONSTRUCTION"      # 园区建设
    FACTORY_RENOVATION = "FACTORY_RENOVATION"    # 厂房改造
    DECORATION = "DECORATION"                    # 装修改造
    INFRASTRUCTURE = "INFRASTRUCTURE"            # 基础设施
    FIRE_CONTROL = "FIRE_CONTROL"                # 消防改造
    EQUIPMENT_INSTALL = "EQUIPMENT_INSTALL"      # 设备安装
    ENERGY_SAVING = "ENERGY_SAVING"              # 节能项目
    DIGITAL = "DIGITAL"                          # 数字化建设
    SOFTWARE = "SOFTWARE"                        # 软件开发
    INVESTMENT = "INVESTMENT"                    # 招商专项
    ENTERPRISE_SERVICE = "ENTERPRISE_SERVICE"    # 企业服务
    EVENT_OPERATION = "EVENT_OPERATION"          # 活动运营
    PROCESS_OPTIMIZATION = "PROCESS_OPTIMIZATION"  # 流程优化


class NotificationType(StrEnum):
    CONTRACT_EXPIRY = "CONTRACT_EXPIRY"        # 合同到期
    RENT_ARREARS = "RENT_ARREARS"              # 租金欠费
    SPACE_VACANT = "SPACE_VACANT"              # 空间长期空置
    LEASING_STAGNANT = "LEASING_STAGNANT"      # 招商停滞
    PROJECT_DELAY = "PROJECT_DELAY"            # 项目延期
    BUDGET_OVERSPEND = "BUDGET_OVERSPEND"      # 预算超支
    DEVICE_FAULT = "DEVICE_FAULT"              # 设备故障
    INSPECTION_OVERDUE = "INSPECTION_OVERDUE"  # 巡检逾期
    ENERGY_ANOMALY = "ENERGY_ANOMALY"          # 能耗异常
    SAFETY_HAZARD = "SAFETY_HAZARD"            # 安全隐患
    POLICY_DEADLINE = "POLICY_DEADLINE"        # 政策申报截止
    WORK_ORDER_TIMEOUT = "WORK_ORDER_TIMEOUT"  # 工单超时
    APPROVAL_PENDING = "APPROVAL_PENDING"      # 待审批


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    RISK = "RISK"
    CRITICAL = "CRITICAL"


# ================================================================ 中文标签（全平台单一数据源）
#
# 为什么按「枚举类名 → {值: 中文}」分组而不是一张扁平表：
#   不同枚举类存在重名值，语义却不同。例如
#     RISK  : Severity=「风险」  / EnterpriseStatus=「风险企业」
#     OFFICE: SpaceType=「办公楼」/ ParkType=「办公园区」
#     SIGNED: LeadStage=「已签约」/ EnterpriseStatus=「签约企业」
#   扁平表只能二选一，必然有一处展示错误。因此按类分组，调用方传 group 精确取值。
#
# 之前的教训：标签表散落在 system.py / notification.py / audit.py 三处，
# 且长期未与枚举定义同步，导致前端看到 "EXPENSE"、"WARNING"、"PARK_CONSTRUCTION"
# 这类英文枚举（实测 36 项未映射）。现统一收敛到本文件，新增枚举只需在此登记。

ENUM_LABELS: dict[str, dict[str, str]] = {
    "ManagementMethod": {
        "WATERFALL": "瀑布式", "AGILE": "敏捷式", "HYBRID": "混合式",
    },
    "ProjectStatus": {
        "PLANNED": "未开始", "IN_PROGRESS": "进行中", "ON_HOLD": "已挂起",
        "DELAYED": "已延期", "COMPLETED": "已完成", "CLOSED": "已关闭",
    },
    "RiskLevel": {
        "LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "重大",
    },
    "SpaceStatus": {
        "AVAILABLE": "可租", "RESERVED": "已预订", "RENTED": "已出租",
        "RENOVATING": "装修中", "MAINTENANCE": "维修中", "SELF_USE": "自用",
        "FROZEN": "冻结", "DISABLED": "停用",
    },
    "SpaceType": {
        "OFFICE": "办公楼", "FACTORY": "厂房", "WAREHOUSE": "仓库", "SHOP": "商铺",
        "LAB": "实验室", "MEETING": "会议室", "WORKSTATION": "工位",
        "PARKING": "停车位", "PUBLIC": "公共空间",
    },
    "EnterpriseStatus": {
        "POTENTIAL": "潜在企业", "INTENT": "意向企业", "SIGNED": "签约企业",
        "SETTLED": "入驻企业", "GROWING": "成长企业", "RISK": "风险企业",
        "EXITED": "退园企业",
    },
    "LeadStage": {
        "LEAD": "潜在线索", "CONTACTED": "已联系", "QUALIFIED": "有效商机",
        "SITE_VISIT": "实地看房", "NEGOTIATION": "商务谈判",
        "CONTRACT_APPROVAL": "合同审批", "SIGNED": "已签约",
        "SETTLED": "已入驻", "LOST": "已流失",
    },
    "ContractStatus": {
        "DRAFT": "草稿", "PENDING": "待生效", "ACTIVE": "生效中",
        "EXPIRING": "即将到期", "EXPIRED": "已到期", "TERMINATED": "已终止",
    },
    "WorkOrderStatus": {
        "SUBMITTED": "已提交", "CLASSIFIED": "已分类", "DISPATCHED": "已派单",
        "ACCEPTED": "已受理", "PROCESSING": "处理中", "VERIFYING": "验收中",
        "RATED": "已评价", "CLOSED": "已关闭",
    },
    "ParkType": {
        "TECH": "科技园", "SOFTWARE": "软件园", "INDUSTRIAL": "工业园",
        "MANUFACTURING": "制造园", "LOGISTICS": "物流园", "ECOMMERCE": "电商园",
        "BIOMED": "生物医药园", "CULTURE": "文创园", "INCUBATOR": "孵化器",
        "HEADQUARTER": "总部基地", "OFFICE": "办公园区", "CHEMICAL": "化工园",
        "INNOVATION": "创新园",
    },
    "NotificationType": {
        "CONTRACT_EXPIRY": "合同到期预警", "RENT_ARREARS": "租金欠费预警",
        "SPACE_VACANT": "空间空置预警", "LEASING_STAGNANT": "招商线索停滞",
        "PROJECT_DELAY": "项目延期预警", "BUDGET_OVERSPEND": "预算超支预警",
        "DEVICE_FAULT": "设备故障预警", "INSPECTION_OVERDUE": "巡检逾期预警",
        "ENERGY_ANOMALY": "能耗异常预警", "SAFETY_HAZARD": "安全隐患预警",
        "POLICY_DEADLINE": "政策申报截止", "WORK_ORDER_TIMEOUT": "工单超时预警",
        "APPROVAL_PENDING": "待办审批提醒",
    },
    "Severity": {
        "INFO": "提示", "WARNING": "预警", "RISK": "风险", "CRITICAL": "紧急",
    },
    "AIPermissionLevel": {
        "L1": "L1 信息查询", "L2": "L2 分析与建议",
        "L3": "L3 高影响动作（需人工审批）",
    },
    "ProjectType": {
        "PARK_CONSTRUCTION": "园区建设工程", "FACTORY_RENOVATION": "厂房改造工程",
        "DECORATION": "装修工程", "INFRASTRUCTURE": "基础设施工程",
        "FIRE_CONTROL": "消防工程", "EQUIPMENT_INSTALL": "设备安装工程",
        "ENERGY_SAVING": "节能改造工程", "DIGITAL": "数字化项目",
        "SOFTWARE": "软件项目", "INVESTMENT": "投资项目",
        "ENTERPRISE_SERVICE": "企业服务项目", "EVENT_OPERATION": "活动运营项目",
        "PROCESS_OPTIMIZATION": "流程优化项目",
    },
    "ApprovalType": {
        "CONTRACT_RENEWAL": "合同续约申请", "PROJECT_CHANGE": "项目变更申请",
        "PURCHASE": "采购申请", "EXPENSE": "费用报销", "OVERTIME": "加班申请",
        "BUDGET_ADJUST": "预算调整申请", "AI_ACTION": "AI 建议执行确认",
        "SPACE_DISCOUNT": "空间租金优惠申请",
        # 历史/扩展类型
        "CONTRACT": "合同审批", "CHANGE": "项目变更", "PAYMENT": "付款申请",
        "SPACE": "空间调整", "ENTERPRISE": "企业准入",
        "POLICY": "政策申报", "DEVICE_SCRAP": "设备报废", "OTHER": "其他",
    },
    "BusinessStatus": {
        "PENDING": "待审批", "IN_REVIEW": "审批中", "APPROVED": "已批准",
        "REJECTED": "已驳回", "WITHDRAWN": "已撤回",
    },
    "EnergyType": {
        # 注意：energy_records.energy_type 存的就是这些英文枚举值。
        # 早期 seeder 误存中文「电」/「水」，导致所有按 ELECTRICITY 比较的
        # 统计恒为 0；标签只用于展示，绝不能写回数据库。
        "ELECTRICITY": "电力", "WATER": "用水", "GAS": "燃气",
        "PV": "光伏发电", "CHARGING": "充电桩",
    },
}

# 模块 / 动作中文标签（日志审计、权限矩阵、系统字典共用同一份）
MODULE_LABELS: dict[str, str] = {
    "dashboard": "数据驾驶舱", "space": "空间资产", "enterprise": "企业服务",
    "leasing": "招商运营", "contract": "合同管理", "finance": "财务管理",
    "project": "项目管理", "operation": "物业运维", "safety": "安全管理",
    "approval": "审批中心", "ai": "AI Agent", "data": "数据中心",
    "report": "报表中心", "notification": "消息通知", "system": "系统管理",
    "audit": "日志审计", "energy": "能源管理", "parking": "停车管理",
    "device": "设备管理", "service": "企业服务工单",
    "auth": "登录认证", "agent": "AI 智能体",
    # 审计日志里 property 与 operation 并存（历史写入路径不同），统一到「物业运维」
    "property": "物业运维",
}

ACTION_LABELS: dict[str, str] = {
    "VIEW": "查看", "ADD": "新增", "EDIT": "修改", "DELETE": "删除",
    "IMPORT": "导入", "EXPORT": "导出", "APPROVE": "审批",
    "AI": "AI 调用", "CONFIG": "配置",
    # 审计日志额外记录的动作（非 RBAC 权限点）
    "LOGIN": "登录", "LOGOUT": "登出",
    "GENERATE": "生成", "DOWNLOAD": "下载",
    "ADOPT": "采纳建议", "REJECT": "驳回", "TERMINATE": "终止",
}

# 能源类型的计量单位（energy_records.unit 的真实取值）。
# 与 ENUM_LABELS["EnergyType"] 配对使用：标签管展示，单位管计量，
# 二者必须与库里存的枚举值一致，避免再次出现「中英错配 → 统计归零」。
ENERGY_UNITS: dict[str, str] = {
    "ELECTRICITY": "kWh", "WATER": "m³", "GAS": "m³",
    "PV": "kWh", "CHARGING": "kWh",
}

ENERGY_TYPE_ORDER: tuple[str, ...] = ("ELECTRICITY", "WATER", "GAS", "PV", "CHARGING")

# 欠费账龄分桶。库里 bills.age_bucket 的实际取值是这 6 个，
# NORMAL 表示未逾期（不计入账龄分布）。顺序即展示顺序。
AGE_BUCKETS: tuple[str, ...] = (
    "D1_30", "D31_90", "D91_180", "D181_365", "OVER_365",
)

AGE_BUCKET_LABELS: dict[str, str] = {
    "NORMAL": "未逾期",
    "D1_30": "1-30 天",
    "D31_90": "31-90 天",
    "D91_180": "91-180 天",
    "D181_365": "181-365 天",
    "OVER_365": "365 天以上",
}


def _build_flat() -> dict[str, str]:
    """合成不分组的兜底表；同名值按 ENUM_LABELS 声明顺序先到先得。"""
    flat: dict[str, str] = {}
    for group in ENUM_LABELS.values():
        for k, v in group.items():
            flat.setdefault(k, v)
    return flat


# 不分组的兜底表。重名值在此统一取更通用的译法（精确展示请传 group）。
FLAT_LABELS: dict[str, str] = _build_flat()
FLAT_LABELS.update({
    "RISK": "风险",
    "OFFICE": "办公楼",
    "SIGNED": "已签约",
    "SETTLED": "已入驻",
    "PENDING": "待处理",
    "ACTIVE": "生效中",
    "CLOSED": "已关闭",
    "INFO": "提示",
})


def enum_label(value: str | None, group: str | None = None) -> str:
    """取枚举中文标签。传 group（枚举类名）可精确命中重名值。"""
    if not value:
        return ""
    if group:
        hit = ENUM_LABELS.get(group, {}).get(value)
        if hit:
            return hit
    return FLAT_LABELS.get(value, value)


def module_label(value: str | None) -> str:
    if not value:
        return ""
    return MODULE_LABELS.get(value, value)


def action_label(value: str | None) -> str:
    if not value:
        return ""
    return ACTION_LABELS.get(value, value)

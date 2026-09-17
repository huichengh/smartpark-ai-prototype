/**
 * 导航配置
 *
 * 20 个一级菜单，与需求文档的信息架构一致，并与后端各业务模块路由对齐。
 * `perm` 用于按权限点隐藏菜单（与后端 auth.require(module, action) 对应），
 * 但「隐藏」只是体验优化 —— 真正的边界始终由后端校验。
 */
import type { LucideIcon } from 'lucide-react'
import {
  LayoutDashboard,
  Boxes,
  Building2,
  Handshake,
  FileSignature,
  Wallet,
  FolderKanban,
  Wrench,
  Zap,
  ShieldAlert,
  Car,
  CalendarClock,
  ClipboardCheck,
  Bot,
  Database,
  FileBarChart2,
  Bell,
  ScrollText,
  Settings2,
  Network,
} from 'lucide-react'

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  group: string
  /** 需要的权限点：module + action，缺省表示登录即可见 */
  perm?: [string, string]
  desc?: string
}

export const NAV_GROUPS = [
  '总览',
  '资产与招商',
  '经营与项目',
  '运营与安全',
  '智能与治理',
] as const

export const NAV_ITEMS: NavItem[] = [
  {
    path: '/dashboard',
    label: '数据驾驶舱',
    icon: LayoutDashboard,
    group: '总览',
    desc: '园区核心指标总览与告警',
  },
  {
    path: '/twin',
    label: '园区数字孪生',
    icon: Boxes,
    group: '总览',
    desc: '2.5D 楼栋与空间可视化',
  },
  {
    path: '/space',
    label: '空间资产管理',
    icon: Building2,
    group: '资产与招商',
    perm: ['space', 'VIEW'],
    desc: '楼栋、楼层、空间单元与出租状态',
  },
  {
    path: '/leasing',
    label: '招商运营管理',
    icon: Handshake,
    group: '资产与招商',
    perm: ['leasing', 'VIEW'],
    desc: '线索漏斗、跟进记录与停滞预警',
  },
  {
    path: '/enterprise',
    label: '企业服务中心',
    icon: Network,
    group: '资产与招商',
    perm: ['enterprise', 'VIEW'],
    desc: '企业档案、政策匹配与服务诉求',
  },
  {
    path: '/contracts',
    label: '合同管理',
    icon: FileSignature,
    group: '经营与项目',
    perm: ['contract', 'VIEW'],
    desc: '租约全周期、到期预警与退租',
  },
  {
    path: '/finance',
    label: '财务与账单',
    icon: Wallet,
    group: '经营与项目',
    perm: ['finance', 'VIEW'],
    desc: '账单、收款、欠费账龄与收缴率',
  },
  {
    path: '/projects',
    label: '项目管理中心',
    icon: FolderKanban,
    group: '经营与项目',
    perm: ['project', 'VIEW'],
    desc: 'WBS/CPM/EVM、风险、里程碑与敏捷',
  },
  {
    path: '/operations',
    label: '物业运维',
    icon: Wrench,
    group: '运营与安全',
    // 与后端 operation.py 的 auth.require("property", ...) 对齐
    perm: ['property', 'VIEW'],
    desc: '工单派发、SLA 与设备巡检',
  },
  {
    path: '/energy',
    label: '能源管理',
    icon: Zap,
    group: '运营与安全',
    perm: ['energy', 'VIEW'],
    desc: '能耗趋势、分项计量与异常诊断',
  },
  {
    path: '/safety',
    label: '安全管理',
    icon: ShieldAlert,
    group: '运营与安全',
    perm: ['safety', 'VIEW'],
    desc: '隐患整改、事故复盘与整改闭环',
  },
  {
    path: '/parking',
    label: '停车与通行',
    icon: Car,
    group: '运营与安全',
    perm: ['parking', 'VIEW'],
    desc: '车位、车辆、访客与道闸记录',
  },
  {
    path: '/meeting',
    label: '会议室与活动',
    icon: CalendarClock,
    group: '运营与安全',
    perm: ['service', 'VIEW'],
    desc: '会议室预订与服务活动',
  },
  {
    path: '/approval',
    label: '审批中心',
    icon: ClipboardCheck,
    group: '智能与治理',
    perm: ['approval', 'VIEW'],
    desc: '待办审批、流程轨迹与风险提示',
  },
  {
    path: '/ai',
    label: 'AI 智能体',
    icon: Bot,
    group: '智能与治理',
    // 注意：RBAC 的模块键是 ai（见后端 core/enums.py 的 22 个模块与 agent.py 的
    // auth.require("ai", ...)）。曾经误写成 'agent'——那是审计日志的 module 名，
    // 不是权限模块，导致 can('agent','VIEW') 恒为 false，本菜单被永久隐藏。
    perm: ['ai', 'VIEW'],
    desc: '主 Agent 对话 + 11 个子 Agent',
  },
  {
    path: '/data',
    label: '数据中心',
    icon: Database,
    group: '智能与治理',
    perm: ['data', 'VIEW'],
    desc: '数据资产目录、质量评分与血缘',
  },
  {
    path: '/report',
    label: '报表中心',
    icon: FileBarChart2,
    group: '智能与治理',
    perm: ['report', 'VIEW'],
    desc: '园区月报、项目报告与归档导出',
  },
  {
    path: '/notification',
    label: '消息通知',
    icon: Bell,
    group: '智能与治理',
    desc: '待办、预警与 AI 洞察推送',
  },
  {
    path: '/audit',
    label: '日志审计',
    icon: ScrollText,
    group: '智能与治理',
    // 审计是独立模块 audit（后端 audit.py 用 audit:VIEW），不是 system
    perm: ['audit', 'VIEW'],
    desc: '操作留痕、对象轨迹与合规追溯',
  },
  {
    path: '/system',
    label: '系统管理',
    icon: Settings2,
    group: '智能与治理',
    perm: ['system', 'VIEW'],
    desc: '组织、园区、模板、用户与角色',
  },
]

export function findNav(pathname: string): NavItem | undefined {
  // 取最长前缀匹配，保证 /projects/14 仍高亮「项目管理中心」
  return [...NAV_ITEMS]
    .sort((a, b) => b.path.length - a.path.length)
    .find((n) => pathname === n.path || pathname.startsWith(`${n.path}/`))
}

/**
 * 各业务模块 API 封装
 *
 * 全部端点与后端 app/api/v1/*.py 的实际注册路径一一对应
 * （路径清单由 backend 导出的 openapi.json 校对，非凭记忆书写）。
 */
import { api, request, type ApiError } from './client'

// ================================================================ 通用类型
export interface PageResult<T> {
  items: T[]
  total: number
  page?: number
  page_size?: number
  pages?: number
  data_label?: string
  [k: string]: any
}

export interface SessionUser {
  id: number
  username: string
  real_name: string
  phone?: string | null
  email?: string | null
  avatar?: string | null
  department?: string | null
  position?: string | null
  organization_id?: number | null
  park_id?: number | null
  enterprise_id?: number | null
  roles?: { code: string; name: string; data_scope: string }[]
  role_label?: string
  data_scope?: string
  visible_park_ids?: number[] | null
  permissions?: string[]
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: SessionUser
}

// ================================================================ 认证
export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResult>({
      method: 'POST',
      url: '/auth/login',
      data: { username, password },
    }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get<SessionUser>('/auth/me'),
  parks: () => api.get<any[]>('/auth/parks'),
  roles: () => api.get<any[]>('/auth/roles'),
  changePassword: (old_password: string, new_password: string) =>
    api.post('/auth/change-password', { old_password, new_password }),
}

// ================================================================ 驾驶舱
export const dashboardApi = {
  summary: (park_id?: number | null) =>
    api.get<any>('/dashboard/summary', park_id ? { park_id } : undefined),
  alerts: (park_id?: number | null) =>
    api.get<any>('/dashboard/alerts', park_id ? { park_id } : undefined),
  quickStats: (park_id?: number | null) =>
    api.get<any>('/dashboard/quick-stats', park_id ? { park_id } : undefined),
}

// ================================================================ 空间资产 / 数字孪生
export const spaceApi = {
  parks: (park_id?: number | null) =>
    api.get<any>('/space/parks', park_id ? { park_id } : undefined),
  buildings: (park_id?: number | null, page_size = 50) =>
    api.get<any>('/space/buildings', { park_id, page_size }),
  building: (id: number) => api.get<any>(`/space/buildings/${id}`),
  twin: (park_id: number) => api.get<any>(`/space/parks/${park_id}/twin`),
  board: (building_id: number) =>
    api.get<any>(`/space/spaces/board/${building_id}`),
  spaces: (params: Record<string, any> = {}) => api.get<PageResult<any>>('/space/spaces', params),
  space: (id: number) => api.get<any>(`/space/spaces/${id}`),
}

// ================================================================ 企业与政策
export const enterpriseApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/enterprise/enterprises', params),
  detail: (id: number) => api.get<any>(`/enterprise/enterprises/${id}`),
  tag: (id: number, tag_name: string) =>
    api.post(`/enterprise/enterprises/${id}/tags`, undefined, { tag_name }),
  policies: (params: Record<string, any> = {}) =>
    api.get<any>('/enterprise/policies', params),
  policy: (id: number) => api.get<any>(`/enterprise/policies/${id}`),
  matches: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/enterprise/policy-matches', params),
  serviceRequests: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/enterprise/service-requests', params),
  industries: () => api.get<any>('/enterprise/enterprises/meta/industries'),
}

// ================================================================ 招商
export const leasingApi = {
  channels: () => api.get<any>('/leasing/channels'),
  funnel: (park_id?: number | null) =>
    api.get<any>('/leasing/funnel', park_id ? { park_id } : undefined),
  leads: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/leasing/leads', params),
  lead: (id: number) => api.get<any>(`/leasing/leads/${id}`),
  activities: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/leasing/activities', params),
  stagnant: (params: Record<string, any> = {}) =>
    api.get<any>('/leasing/stagnant', params),
  followup: (
    id: number,
    data: { content: string; followup_type?: string; result?: string; next_action?: string },
  ) =>
    api.post(`/leasing/leads/${id}/followup`, undefined, {
      content: data.content,
      followup_type: data.followup_type,
      result: data.result,
      next_action: data.next_action,
    }),
  moveStage: (id: number, stage: string, lost_reason?: string) =>
    api.post(`/leasing/leads/${id}/stage`, undefined, { stage, lost_reason }),
}

// ================================================================ 合同
export const contractApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/contracts', params),
  detail: (id: number) => api.get<any>(`/contracts/${id}`),
  expiring: (params: Record<string, any> = {}) =>
    api.get<any>('/contracts/expiring', params),
  renewIntent: (id: number, note?: string, intent = 'RENEW') =>
    api.post(`/contracts/${id}/renew-intent`, undefined, { intent, note }),
  terminate: (id: number, reason: string) =>
    api.post(`/contracts/${id}/terminate`, undefined, { reason }),
}

// ================================================================ 财务
export const financeApi = {
  bills: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/finance/bills', params),
  bill: (id: number) => api.get<any>(`/finance/bills/${id}`),
  pay: (id: number, data: { amount: number; pay_method?: string; remark?: string }) =>
    api.post(`/finance/bills/${id}/pay`, data),
  dunning: (id: number, note?: string) =>
    api.post(`/finance/bills/${id}/dunning`, undefined, { note }),
  payments: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/finance/payments', params),
  summary: (park_id?: number | null) =>
    api.get<any>('/finance/summary', park_id ? { park_id } : undefined),
  investProjects: () => api.get<any>('/finance/projects/investment'),
}

// ================================================================ 项目管理
export const projectApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/projects', params),
  portfolio: (park_id?: number | null) =>
    api.get<any>('/projects/portfolio', park_id ? { park_id } : undefined),
  detail: (id: number) => api.get<any>(`/projects/${id}`),
  gantt: (id: number) => api.get<any>(`/projects/${id}/gantt`),
  evm: (id: number) => api.get<any>(`/projects/${id}/evm`),
  risks: (id: number, params: Record<string, any> = {}) =>
    api.get<any>(`/projects/${id}/risks`, params),
  milestones: (id: number) => api.get<any>(`/projects/${id}/milestones`),
  agile: (id: number) => api.get<any>(`/projects/${id}/agile`),
  board: (sprint_id: number) => api.get<any>(`/projects/sprints/${sprint_id}/board`),
  moveTask: (task_id: number, board_column: string, column_order?: number) =>
    api.patch(`/projects/sprint-tasks/${task_id}/move`, undefined, { board_column, column_order }),
  updateTask: (
    project_id: number,
    task_id: number,
    data: { progress: number; actual_start?: string; actual_end?: string; note?: string },
  ) => api.patch(`/projects/${project_id}/tasks/${task_id}`, undefined, data),
  changeDecision: (
    project_id: number,
    change_id: number,
    data: { decision: 'APPROVE' | 'REJECT'; comment?: string },
  ) => api.post(`/projects/${project_id}/changes/${change_id}/decision`, undefined, data),
}

// ================================================================ 物业运维 / 能源 / 安全
export const operationApi = {
  workOrders: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/work-orders', params),
  workOrder: (id: number) => api.get<any>(`/operation/work-orders/${id}`),
  createWorkOrder: (data: Record<string, any>) =>
    api.post('/operation/work-orders', data),
  workOrderAction: (
    id: number,
    data: { action: string; assignee_name?: string; rating?: number; remark?: string },
  ) =>
    // 后端该端点的参数是 query，且名为 handler_name / comment
    api.post(`/operation/work-orders/${id}/action`, undefined, {
      action: data.action,
      handler_name: data.assignee_name,
      rating: data.rating,
      comment: data.remark,
    }),
  workOrderStats: (params: Record<string, any> = {}) =>
    api.get<any>('/operation/work-orders/stats/by-type', params),
  devices: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/devices', params),
  device: (id: number) => api.get<any>(`/operation/devices/${id}`),
  energyRecords: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/energy/records', params),
  energySummary: (params: Record<string, any> = {}) =>
    api.get<any>('/operation/energy/summary', params),
  safetySummary: (params: Record<string, any> = {}) =>
    api.get<any>('/operation/safety/summary', params),
  incidents: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/safety/incidents', params),
  hazards: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/safety/hazards', params),
  parkingOverview: (params: Record<string, any> = {}) =>
    api.get<any>('/operation/parking/overview', params),
  meetingBookings: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/operation/meeting-rooms/bookings', params),
}

// ================================================================ 审批中心
export const approvalApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/approvals', params),
  todo: (params: Record<string, any> = {}) =>
    api.get<any>('/approvals/todo', params),
  detail: (id: number) => api.get<any>(`/approvals/${id}`),
  decide: (
    id: number,
    data: { decision: 'APPROVE' | 'REJECT' | 'RETURN'; comment?: string },
  ) => api.post(`/approvals/${id}/decision`, undefined, data),
  withdraw: (id: number, reason?: string) =>
    api.post(`/approvals/${id}/withdraw`, undefined, { reason }),
}

// ================================================================ AI Agent
/** Agent 统一输出格式（需求文档第 36 节），后端按此结构返回 response */
export interface AgentStructured {
  '结论'?: string
  '关键数据'?: any
  '原因分析'?: any
  '建议措施'?: any
  '影响范围'?: any
  '风险'?: any
  '责任部门/角色'?: any
  '决策状态'?: string
  data_sufficient?: boolean
  missing_data?: string[]
  agent_key?: string
  agent_name?: string
  [k: string]: any
}

export interface AgentEvidence {
  data_source?: string
  tables?: string[]
  record_count?: number
  filters?: any
  modules_invoked?: string[]
  formula?: any
  generated_at?: string
  data_label?: string
  user_scope?: any
  [k: string]: any
}

export interface AgentExtraItem {
  priority?: number
  category?: string
  level?: string
  title?: string
  detail?: string
  suggestion?: string
  owner?: string
  evidence?: string
  [k: string]: any
}

export interface AgentChatReply {
  question?: string
  response: AgentStructured
  intent?: string
  intent_label?: string
  intents_all?: { key: string; name: string }[]
  evidence?: AgentEvidence
  /** L1 信息查询 / L2 分析与建议 / L3 高影响动作（需人工审批） */
  permission_level?: string
  data_sufficient?: boolean
  missing_data?: string[]
  latency_ms?: number
  extra?: AgentExtraItem[]
  conversation_id: number
  message_id?: number
  created_at?: string
  data_label?: string
}

export const agentApi = {
  agents: () => api.get<any>('/agent/agents'),
  tools: () => api.get<any>('/agent/tools'),
  /** 注意：后端字段为 question（非 message），见 app/schemas/common.py::ChatRequest */
  chat: (data: {
    question: string
    conversation_id?: number | null
    agent_key?: string
    park_id?: number | null
    project_id?: number | null
    enterprise_id?: number | null
  }) => api.post<AgentChatReply>('/agent/chat', data),
  conversations: (params: Record<string, any> = {}) =>
    api.get<any>('/agent/conversations', params),
  conversation: (id: number) =>
    api.get<any>(`/agent/conversations/${id}`),
  messages: (conversation_id: number) =>
    api.get<any>('/agent/messages', { conversation_id }),
  recommendations: (params: Record<string, any> = {}) =>
    api.get<any>('/agent/recommendations', params),
  adopt: (id: number, note?: string) =>
    api.post(`/agent/recommendations/${id}/adopt`, undefined, { note }),
  reject: (id: number, reason?: string) =>
    api.post(`/agent/recommendations/${id}/reject`, undefined, { reason }),
  dailyInsight: (park_id?: number | null) =>
    api.get<any>('/agent/daily-insight', park_id ? { park_id } : undefined),
  pm: (project_id: number) => api.get<any>(`/agent/pm/${project_id}`),
}

// ================================================================ 数据中心
export const dataApi = {
  catalog: () => api.get<any>('/data/catalog'),
  overview: () => api.get<any>('/data/overview'),
  quality: () => api.get<any>('/data/quality'),
  lineage: () => api.get<any>('/data/lineage'),
  uploads: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/data/uploads', params),
  upload: (id: number) => api.get<any>(`/data/uploads/${id}`),
}

// ================================================================ 报表中心
export const reportApi = {
  types: () => api.get<any>('/report/types'),
  parkMonthly: (params: Record<string, any> = {}) =>
    api.get<any>('/report/park-monthly', params),
  project: (project_id: number) => api.get<any>(`/report/project/${project_id}`),
  archive: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/report/archive', params),
  archiveDetail: (id: number) => api.get<any>(`/report/archive/${id}`),
  generate: (data: {
    report_type: string
    park_id?: number | null
    project_id?: number | null
    period?: string
    fmt?: string
  }) =>
    api.post('/report/generate', undefined, {
      report_type: data.report_type,
      park_id: data.park_id,
      project_id: data.project_id,
      period: data.period,
      fmt: data.fmt,
    }),
  exportArchive: (id: number) =>
    api.download(`/report/archive/${id}/export`),
  summary: () => api.get<any>('/report/summary'),
}

// ================================================================ 消息通知
export const notificationApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/notification', params),
  detail: (id: number) => api.get<any>(`/notification/${id}`),
  unreadCount: () => api.get<any>('/notification/unread-count'),
  stats: () => api.get<any>('/notification/stats'),
  markRead: (id: number) => api.post(`/notification/${id}/read`),
  markAllRead: (notice_type?: string) =>
    api.post('/notification/read-all', undefined, { notice_type }),
  handle: (id: number, note?: string) =>
    api.post(`/notification/${id}/handle`, undefined, { note }),
  timeline: (limit = 20) => api.get<any>('/notification/timeline/recent', { limit }),
  dict: () => api.get<any>('/notification/meta/dict'),
}

// ================================================================ 日志审计
export const auditApi = {
  list: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/audit', params),
  detail: (id: number) => api.get<any>(`/audit/${id}`),
  stats: (params: Record<string, any> = {}) =>
    api.get<any>('/audit/stats', params),
  byResource: (object_type: string, object_id: number | string) =>
    api.get<any>(`/audit/resource/${object_type}/${object_id}`),
  dict: () => api.get<any>('/audit/meta/dict'),
}

// ================================================================ 系统管理
export const systemApi = {
  dict: () => api.get<any>('/system/dict'),
  organizations: () => api.get<any>('/system/organizations'),
  parks: () => api.get<any>('/system/parks'),
  templates: () => api.get<any>('/system/templates'),
  toggleModule: (tpl_id: number, module_key: string, enabled: boolean) =>
    // 后端该端点的参数是 query，且名为 module
    api.post(`/system/templates/${tpl_id}/toggle-module`, undefined, {
      module: module_key,
      enabled,
    }),
  users: (params: Record<string, any> = {}) =>
    api.get<PageResult<any>>('/system/users', params),
  user: (id: number) => api.get<any>(`/system/users/${id}`),
  createUser: (data: Record<string, any>) => api.post('/system/users', data),
  updateUser: (id: number, data: Record<string, any>) =>
    api.patch(`/system/users/${id}`, data),
  resetPassword: (id: number, new_password: string) =>
    api.post(`/system/users/${id}/reset-password`, undefined, { new_password }),
  roles: () => api.get<any>('/system/roles'),
  role: (id: number) => api.get<any>(`/system/roles/${id}`),
  setRolePermissions: (id: number, permissions: string[]) =>
    api.post(`/system/roles/${id}/permissions`, undefined, { permissions }),
  permissions: () => api.get<any>('/system/permissions'),
  myPermissions: () => api.get<any>('/system/me/permissions'),
}

export { ApiException } from './client'
export type { ApiError }

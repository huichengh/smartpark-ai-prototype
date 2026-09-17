/**
 * 审批中心 —— 我的待办 / 全部审批 / 审批详情与决策
 *
 * 设计要点：
 *  - 「我的待办」由后端按「当前步骤审批角色 ∈ 本人角色」实时匹配（见 /approvals/todo 的 basis），
 *    前端不做权限推断，只渲染结果。
 *  - 决策动作走 can('approval','APPROVE') 门禁，与后端 auth.require 一一对应。
 *  - AI 生成的审批单（is_ai_generated）显式标注：AI 只能发起请求，决策必须由人做出。
 *  - 审批类型分布、待批金额等统计全部来自后端 stats，前端不自行汇总。
 */
import { useState } from 'react'
import { approvalApi } from '@/api/modules'
import { pushToast, useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Segmented, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption } from '@/components/Charts'
import {
  AlertTriangle, ArrowLeft, Bot, CheckCircle2, Clock, FileText,
  RefreshCw, RotateCcw, User, XCircle,
} from 'lucide-react'

type AnyRow = Record<string, any>

const RISK_TONE: Record<string, string> = {
  LOW: 'ok', MEDIUM: 'warn', HIGH: 'risk', CRITICAL: 'danger',
}
const RISK_LABEL: Record<string, string> = {
  LOW: '低', MEDIUM: '中', HIGH: '高', CRITICAL: '紧急',
}
const URGENCY_TONE: Record<string, string> = {
  LOW: 'muted', NORMAL: 'muted', URGENT: 'warn', CRITICAL: 'danger',
}
const URGENCY_LABEL: Record<string, string> = {
  LOW: '不紧急', NORMAL: '常规', URGENT: '紧急', CRITICAL: '特急',
}
const STATUS_TONE: Record<string, string> = {
  PENDING: 'warn', IN_REVIEW: 'info', APPROVED: 'ok',
  REJECTED: 'danger', WITHDRAWN: 'muted',
}
const STEP_TONE: Record<string, string> = {
  PENDING: 'warn', APPROVED: 'ok', REJECTED: 'danger', SKIPPED: 'muted',
}

const money = (v: any) => {
  const n = Number(v) || 0
  if (Math.abs(n) >= 10000) {
    return `${(n / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 万`
  }
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

const fmtTime = (s?: string | null) => (s ? String(s).replace('T', ' ').slice(0, 16) : '—')

/** 后端可能返回字符串或对象，统一渲染，避免出现 [object Object] */
const renderAny = (v: any): string => {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v, null, 1)
  } catch {
    return String(v)
  }
}

export default function Approval() {
  const { can } = useAuth()
  const [tab, setTab] = useState<'todo' | 'all'>('todo')
  const [selected, setSelected] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 20

  const todo = useAsync(() => approvalApi.todo(), [], { enabled: tab === 'todo' })
  const all = useAsync(
    () =>
      approvalApi.list({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      }),
    [page, statusFilter],
    { enabled: tab === 'all' },
  )
  const detail = useAsync(
    () => approvalApi.detail(selected as number),
    [selected],
    { enabled: selected != null },
  )

  const cur = tab === 'todo' ? todo : all
  const rows: AnyRow[] = cur.data?.items ?? []
  const stats: AnyRow = all.data?.stats ?? {}
  const ap: AnyRow = detail.data?.approval ?? {}
  const steps: AnyRow[] = detail.data?.steps ?? []
  const related = detail.data?.related_object

  const refreshAll = () => {
    todo.reload()
    all.reload()
    if (selected != null) detail.reload()
  }

  async function doDecide(decision: 'APPROVE' | 'REJECT') {
    if (selected == null) return
    setBusy(true)
    try {
      const res: any = await approvalApi.decide(selected, {
        decision,
        comment: comment.trim() || undefined,
      })
      pushToast('ok', res?.message ?? (decision === 'APPROVE' ? '已同意' : '已驳回'))
      setComment('')
      refreshAll()
    } catch (e: any) {
      pushToast('err', e?.message ?? '审批失败')
    } finally {
      setBusy(false)
    }
  }

  async function doWithdraw() {
    if (selected == null) return
    const reason = window.prompt('请输入撤回理由（将记入日志审计）', '申请人撤回')
    if (reason === null) return
    setBusy(true)
    try {
      const res: any = await approvalApi.withdraw(selected, reason || undefined)
      pushToast('ok', res?.message ?? '已撤回')
      refreshAll()
    } catch (e: any) {
      pushToast('err', e?.message ?? '撤回失败')
    } finally {
      setBusy(false)
    }
  }

  const byTypeOption = barOption({
    x: Object.keys(stats.by_type ?? {}),
    series: [{ name: '单据数', data: Object.values(stats.by_type ?? {}).map((v) => Number(v) || 0) }],
    horizontal: true,
    showLegend: false,
  })

  const pendingSteps = Number(ap.total_steps) || 0
  const doneSteps = steps.filter((s) => s.status === 'APPROVED').length

  return (
    <div className="space-y-5">
      <PageHeader
        title="审批中心"
        desc="多级审批流转：AI 可发起申请但不可代为决策，所有决策动作均记录审批人与意见。"
        demo
        extra={
          <Btn variant="ghost" onClick={refreshAll}>
            <RefreshCw size={13} /> 刷新
          </Btn>
        }
      />

      {/* 统计（来自 /approvals 的 stats） */}
      {Object.keys(stats).length > 0 && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
          <KpiCard label="审批单总数" value={stats.total ?? 0} unit="张" />
          <KpiCard label="待审批" value={stats.pending ?? 0} unit="张" tone="warn" />
          <KpiCard label="我的待办" value={stats.my_todo ?? 0} unit="张" tone="risk" />
          <KpiCard label="已批准" value={stats.approved ?? 0} unit="张" tone="ok" />
          <KpiCard label="已驳回" value={stats.rejected ?? 0} unit="张" />
          <KpiCard
            label="待批金额" value={money(stats.total_amount)} unit="元"
            tone="ai" hint={`AI 发起 ${stats.ai_generated ?? 0} 张`}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          value={tab}
          onChange={(v) => { setTab(v); setSelected(null) }}
          options={[
            { value: 'todo', label: `我的待办（${todo.data?.total ?? 0}）` },
            { value: 'all', label: '全部审批' },
          ]}
        />
        {tab === 'all' && (
          <select
            className={`${inputCls} max-w-[200px]`}
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部状态</option>
            <option value="PENDING">待审批</option>
            <option value="IN_REVIEW">审批中</option>
            <option value="APPROVED">已批准</option>
            <option value="REJECTED">已驳回</option>
            <option value="WITHDRAWN">已撤回</option>
          </select>
        )}
        {tab === 'todo' && todo.data?.basis && (
          <span className="text-[11px] text-slate-500">{todo.data.basis}</span>
        )}
      </div>

      {tab === 'todo' && todo.data?.overdue_3days > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-state-danger/28 bg-state-danger/[0.07] p-3">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-state-danger" />
          <div className="text-xs leading-relaxed text-slate-300">
            <b className="text-state-danger">有 {todo.data.overdue_3days} 张待办已滞留超过 3 天</b>
            ，建议优先处理高紧急度单据，避免影响业务流转。
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_440px]">
        {/* ------------------------------------------------ 列表 */}
        <div className="space-y-5">
          <Panel
            title={tab === 'todo' ? '待我审批' : '全部审批单'}
            subtitle={`共 ${cur.data?.total ?? 0} 张`}
            padded={false}
          >
            <DataTable<AnyRow>
              columns={[
                {
                  key: 'title', title: '审批单', width: 280,
                  render: (r) => (
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[13px] font-medium text-slate-100">{r.title}</span>
                        {r.is_ai_generated && (
                          <Tag tone="ai" className="shrink-0"><Bot size={9} /> AI</Tag>
                        )}
                      </div>
                      <div className="mt-0.5 font-num text-[11px] text-slate-500">{r.approval_code}</div>
                    </div>
                  ),
                },
                { key: 'approval_type_name', title: '类型', width: 130, render: (r) => r.approval_type_name ?? '—' },
                { key: 'applicant_name', title: '申请人', width: 130, render: (r) => r.applicant_name ?? '—' },
                {
                  key: 'amount', title: '金额', width: 110, align: 'right',
                  render: (r) => (Number(r.amount) > 0 ? `${money(r.amount)} 元` : '—'),
                },
                {
                  key: 'risk_level', title: '风险', width: 70,
                  render: (r) => (
                    <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>
                      {RISK_LABEL[r.risk_level] ?? r.risk_level ?? '—'}
                    </Tag>
                  ),
                },
                tab === 'todo'
                  ? {
                      key: 'pending_days', title: '滞留', width: 80, align: 'right',
                      render: (r) => (
                        <span className={Number(r.pending_days) > 3 ? 'text-state-danger' : ''}>
                          {r.pending_days != null ? `${r.pending_days} 天` : '—'}
                        </span>
                      ),
                    }
                  : {
                      key: 'status_name', title: '状态', width: 90,
                      render: (r) => (
                        <Tag tone={STATUS_TONE[r.status] ?? 'muted'}>{r.status_name ?? r.status}</Tag>
                      ),
                    },
                {
                  key: 'current_step_name', title: '当前环节', width: 140,
                  render: (r) => (
                    <span className="text-[12px] text-slate-300">
                      {r.current_step_name ?? '—'}
                      <span className="ml-1 font-num text-[10px] text-slate-500">
                        {r.current_step}/{r.total_steps}
                      </span>
                    </span>
                  ),
                },
              ]}
              rows={rows}
              loading={cur.loading}
              error={cur.error}
              onRetry={cur.reload}
              empty={tab === 'todo' ? '当前没有待你审批的单据' : '暂无审批单'}
              rowKey={(r) => r.id}
              onRowClick={(r) => { setSelected(r.id); setComment('') }}
              compact
            />
          </Panel>

          {tab === 'all' && Number(cur.data?.pages ?? cur.data?.total_pages) > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">
                第 {cur.data?.page ?? page} / {cur.data?.pages ?? cur.data?.total_pages} 页
              </span>
              <div className="flex gap-2">
                <Btn size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
                <Btn
                  size="sm"
                  disabled={page >= Number(cur.data?.pages ?? cur.data?.total_pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </Btn>
              </div>
            </div>
          )}

          {Object.keys(stats.by_type ?? {}).length > 0 && (
            <Panel title="审批类型分布" subtitle="按单据类型统计（来自后端 stats.by_type）">
              <Chart height={Math.max(180, Object.keys(stats.by_type).length * 42)} option={byTypeOption} />
            </Panel>
          )}
        </div>

        {/* ------------------------------------------------ 详情 */}
        <div className="space-y-4">
          {selected == null ? (
            <Panel title="审批详情">
              <EmptyState text="从左侧选择一张审批单查看详情" hint="可查看流转步骤、关联业务对象与 AI 分析意见" />
            </Panel>
          ) : detail.loading ? (
            <Panel title="审批详情"><Loading /></Panel>
          ) : detail.error ? (
            <Panel title="审批详情">
              <ErrorState error={detail.error} onRetry={detail.reload} />
            </Panel>
          ) : (
            <>
              <Panel
                title={ap.title}
                subtitle={`${ap.approval_code ?? ''}`}
                extra={
                  <Btn size="sm" variant="ghost" onClick={() => setSelected(null)}>
                    <ArrowLeft size={12} /> 收起
                  </Btn>
                }
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Tag tone={STATUS_TONE[ap.status] ?? 'muted'}>{ap.status_name ?? ap.status}</Tag>
                  <Tag tone={RISK_TONE[ap.risk_level] ?? 'muted'}>
                    风险 {RISK_LABEL[ap.risk_level] ?? ap.risk_level}
                  </Tag>
                  <Tag tone={URGENCY_TONE[ap.urgency] ?? 'muted'}>
                    {URGENCY_LABEL[ap.urgency] ?? ap.urgency}
                  </Tag>
                  {ap.is_ai_generated && <Tag tone="ai"><Bot size={9} /> AI 发起</Tag>}
                  {ap.source && <Tag tone="muted">{ap.source}</Tag>}
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 text-[12px]">
                  {([
                    ['审批类型', ap.approval_type_name],
                    ['申请人', ap.applicant_name],
                    ['申请时间', fmtTime(ap.apply_at)],
                    ['金额', Number(ap.amount) > 0 ? `${money(ap.amount)} 元` : '—'],
                    ['当前环节', `${ap.current_step_name ?? '—'}（第 ${ap.current_step}/${ap.total_steps} 步）`],
                    ['当前审批角色', ap.current_approver_role],
                    ['结束时间', ap.finish_at ? fmtTime(ap.finish_at) : '进行中'],
                    ['关联对象', ap.related_object_type ?? '—'],
                  ] as [string, any][]).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                      <dt className="text-[11px] text-slate-500">{k}</dt>
                      <dd className="mt-0.5 text-slate-200">{renderAny(v)}</dd>
                    </div>
                  ))}
                </dl>

                {ap.content && (
                  <div className="mt-3 rounded-lg border border-white/8 bg-white/[0.03] p-3">
                    <div className="text-[11px] text-slate-500">申请说明</div>
                    <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{ap.content}</p>
                  </div>
                )}
                {ap.remark && (
                  <div className="mt-2 rounded-lg border border-white/8 bg-white/[0.03] p-3">
                    <div className="text-[11px] text-slate-500">审批意见</div>
                    <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{ap.remark}</p>
                  </div>
                )}
              </Panel>

              {/* AI 分析 */}
              {ap.ai_analysis && (
                <Panel title="AI 预审意见" subtitle="AI 仅提供参考，不参与决策" >
                  <div className="flex gap-2 rounded-lg border border-ai/25 bg-ai/[0.07] p-3">
                    <Bot size={15} className="mt-0.5 shrink-0 text-ai-light" />
                    <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-slate-300">
                      {renderAny(ap.ai_analysis)}
                    </p>
                  </div>
                </Panel>
              )}

              {/* 关联业务对象 */}
              {related && (
                <Panel title="关联业务对象" subtitle={related.type ?? ''}>
                  <dl className="grid grid-cols-2 gap-3 text-[12px]">
                    {Object.entries(related)
                      .filter(([k]) => k !== 'type')
                      .map(([k, v]) => (
                        <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                          <dt className="font-num text-[11px] text-slate-500">{k}</dt>
                          <dd className="mt-0.5 text-slate-200">{renderAny(v)}</dd>
                        </div>
                      ))}
                  </dl>
                </Panel>
              )}

              {/* 流转步骤 */}
              <Panel title="审批流转" subtitle={`已通过 ${doneSteps} / ${pendingSteps} 步`}>
                {pendingSteps > 0 && (
                  <div className="mb-3">
                    <ProgressBar
                      value={(doneSteps / pendingSteps) * 100}
                      tone={ap.status === 'REJECTED' ? 'danger' : 'brand'}
                      height={8}
                    />
                  </div>
                )}
                <ol className="space-y-3">
                  {steps.map((s) => (
                    <li key={s.id} className="flex gap-3">
                      <div className="mt-0.5 shrink-0">
                        {s.status === 'APPROVED' ? (
                          <CheckCircle2 size={16} className="text-state-ok" />
                        ) : s.status === 'REJECTED' ? (
                          <XCircle size={16} className="text-state-danger" />
                        ) : (
                          <Clock size={16} className="text-slate-500" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[12px] font-medium text-slate-200">
                            第 {s.step_no} 步 · {s.step_name}
                          </span>
                          <Tag tone={STEP_TONE[s.status] ?? 'muted'}>{s.status}</Tag>
                          {s.approver_role && <Tag tone="muted">{s.approver_role}</Tag>}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
                          <span className="inline-flex items-center gap-1">
                            <User size={10} /> {s.approver_name ?? '待指派'}
                          </span>
                          {s.approve_at && <span>{fmtTime(s.approve_at)}</span>}
                          {s.duration_hours != null && <span className="font-num">耗时 {s.duration_hours} h</span>}
                        </div>
                        {s.comment && (
                          <p className="mt-1 rounded border border-white/8 bg-white/[0.03] px-2 py-1 text-[11px] text-slate-400">
                            {s.comment}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              </Panel>

              {/* 决策区 */}
              <Panel title="审批决策" subtitle="决策动作将写入日志审计">
                {!can('approval', 'APPROVE') ? (
                  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3 text-xs text-slate-400">
                    当前账号缺少 <b className="font-num">approval:APPROVE</b> 权限，可查看但不可决策。
                  </div>
                ) : !detail.data?.can_i_approve ? (
                  <div className="rounded-lg border border-state-warn/25 bg-state-warn/[0.07] p-3 text-xs text-slate-300">
                    该单据当前环节为「{ap.current_step_name ?? '—'}」，
                    您的角色不在该环节审批人范围内，无法决策。
                  </div>
                ) : (
                  <div className="space-y-3">
                    <textarea
                      className={`${inputCls} min-h-[76px] resize-y`}
                      placeholder="审批意见（可选，将随决策一并记录）"
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Btn variant="primary" loading={busy} onClick={() => void doDecide('APPROVE')}>
                        <CheckCircle2 size={13} /> 同意
                      </Btn>
                      <Btn variant="danger" loading={busy} onClick={() => void doDecide('REJECT')}>
                        <XCircle size={13} /> 驳回
                      </Btn>
                      {(ap.status === 'PENDING' || ap.status === 'IN_REVIEW') && (
                        <Btn variant="ghost" loading={busy} onClick={() => void doWithdraw()}>
                          <RotateCcw size={13} /> 撤回
                        </Btn>
                      )}
                    </div>
                    <p className="text-[11px] leading-relaxed text-slate-500">
                      审批通过后将自动推进至下一步骤；全部步骤通过后单据状态变为「已批准」，
                      变更摘要会写入日志审计（模块 audit）。
                    </p>
                  </div>
                )}
              </Panel>

              {detail.data?.data_label && (
                <div className="flex items-center gap-2 text-[11px] text-slate-500">
                  <FileText size={11} /> {detail.data.data_label}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

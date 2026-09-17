/**
 * 安全管理 —— 安全指数 / 事件 / 隐患
 *
 * safety_score 由后端按 score_model（base − deductions）计算，
 * 页面把评分模型原样展示，确保「分数怎么来的」可追溯。
 */
import { useMemo, useState } from 'react'
import { operationApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

type AnyRow = Record<string, any>

const INCIDENT_TYPE: Record<string, string> = {
  EQUIPMENT: '设备事故', WORK_AT_HEIGHT: '高处作业', CHEMICAL: '化学品',
  FIRE: '火灾', FLOOD: '水患', INJURY: '人员伤害', GAS: '燃气泄漏',
}
const HAZARD_TYPE: Record<string, string> = {
  CHEMICAL: '化学品', FIRE: '消防', PERSONAL: '人身安全', WORK_AT_HEIGHT: '高处作业',
  ELECTRIC: '电气', CONSTRUCTION: '施工', CONFINED_SPACE: '有限空间',
  EQUIPMENT: '设备', GAS: '燃气',
}
const LEVEL_TONE: Record<string, string> = {
  CRITICAL: 'danger', HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok',
}
const LEVEL_LABEL: Record<string, string> = {
  CRITICAL: '重大', HIGH: '高', MEDIUM: '中', LOW: '低',
}

export default function Safety() {
  const { activeParkId, can } = useAuth()
  const [tab, setTab] = useState<'incident' | 'hazard'>('incident')
  const [level, setLevel] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const summary = useAsync(
    () => operationApi.safetySummary({ park_id: activeParkId ?? undefined }),
    [activeParkId],
  )
  const incidents = useAsync(
    () => operationApi.incidents({
      park_id: activeParkId ?? undefined,
      level: level || undefined,
      status: status || undefined,
      page, page_size: pageSize,
    }),
    [activeParkId, level, status, page],
    { enabled: tab === 'incident' },
  )
  const hazards = useAsync(
    () => operationApi.hazards({
      park_id: activeParkId ?? undefined,
      level: level || undefined,
      status: status || undefined,
      page, page_size: pageSize,
    }),
    [activeParkId, level, status, page],
    { enabled: tab === 'hazard' },
  )

  const s = summary.data
  const totals = s?.totals ?? {}
  const model = s?.score_model ?? {}

  const incidentTypeOption = useMemo(
    () =>
      barOption({
        x: Object.keys(s?.by_type ?? {}).map((k) => INCIDENT_TYPE[k] ?? k),
        series: [{
          name: '事件数',
          data: Object.values(s?.by_type ?? {}).map((v) => Number(v) || 0),
          color: '#EF4444',
        }],
        showLegend: false,
      }),
    [s],
  )

  const hazardTypeOption = useMemo(
    () =>
      pieOption({
        data: Object.entries(s?.hazard_by_type ?? {}).map(([k, v]) => ({
          name: HAZARD_TYPE[k] ?? k,
          value: Number(v) || 0,
        })),
        centerLabel: { title: '隐患总数', value: totals.hazard_total ?? 0 },
      }),
    [s, totals],
  )

  const cur = tab === 'incident' ? incidents : hazards
  const rows: any[] = cur.data?.items ?? []
  const total = cur.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const scoreTone = Number(s?.safety_score) >= 90 ? 'ok' : Number(s?.safety_score) >= 75 ? 'warn' : 'risk'
  const deductTotal = useMemo(
    () => (model.deductions ?? []).reduce((sum: number, d: AnyRow) => sum + (Number(d.total) || 0), 0),
    [model],
  )

  return (
    <div className="space-y-5">
      <PageHeader
        title="安全管理"
        desc="安全指数、事件与隐患排查治理，评分由后端按扣分模型计算并公开口径。"
        demo
        extra={<Btn variant="ghost" onClick={() => summary.reload()}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {summary.loading ? (
        <Panel><Loading text="正在汇总安全指标…" /></Panel>
      ) : summary.error ? (
        <Panel><ErrorState error={summary.error} onRetry={summary.reload} /></Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
            <KpiCard
              label="安全指数" value={fmt(s?.safety_score, 1)} unit="分"
              tone={scoreTone} hint={s?.safety_status}
            />
            <KpiCard label="事件总数" value={totals.total_incidents ?? 0} unit="起" />
            <KpiCard
              label="未闭环事件" value={totals.open_incidents ?? 0} unit="起"
              tone={Number(totals.open_incidents) > 0 ? 'warn' : 'ok'}
            />
            <KpiCard
              label="重大未闭环" value={totals.critical_open ?? 0} unit="起"
              tone={Number(totals.critical_open) > 0 ? 'risk' : 'ok'}
            />
            <KpiCard
              label="闭环率" value={fmt(totals.closure_rate, 1)} unit="%"
              tone={Number(totals.closure_rate) >= 90 ? 'ok' : 'warn'}
            />
            <KpiCard label="隐患总数" value={totals.hazard_total ?? 0} unit="项" />
            <KpiCard
              label="整改超期" value={totals.overdue_rectify ?? totals.hazard_overdue ?? 0} unit="项"
              tone={Number(totals.overdue_rectify ?? totals.hazard_overdue) > 0 ? 'risk' : 'ok'}
            />
          </div>

          {/* 评分模型 */}
          {(model.final != null || model.deductions != null) && (
            <Panel title="安全指数模型" subtitle={model.note ?? '评分 = 基准分 − 累计扣分'}>
              <div className="flex flex-wrap items-center gap-6">
                <div className="flex items-baseline gap-2">
                  <span className="text-xs text-slate-500">基准分</span>
                  <span className="font-num text-2xl font-semibold text-slate-200">{fmt(model.base, 1)}</span>
                </div>
                <span className="text-xl text-slate-600">−</span>
                <div className="flex items-baseline gap-2">
                  <span className="text-xs text-slate-500">累计扣分</span>
                  {/* deductions 是「扣减项明细数组」，不是数字：直接 fmt(数组) 会渲染成 NaN */}
                  <span className="font-num text-2xl font-semibold text-state-danger">{fmt(deductTotal, 1)}</span>
                </div>
                <span className="text-xl text-slate-600">=</span>
                <div className="flex items-baseline gap-2">
                  <span className="text-xs text-slate-500">最终得分</span>
                  <span className={`font-num text-2xl font-semibold ${
                    scoreTone === 'ok' ? 'text-state-ok' : scoreTone === 'warn' ? 'text-state-warn' : 'text-state-danger'
                  }`}>
                    {fmt(model.final, 1)}
                  </span>
                </div>
                <div className="min-w-[220px] flex-1">
                  <ProgressBar
                    value={Number(model.final) || 0}
                    tone={scoreTone}
                    height={8}
                  />
                </div>
              </div>

              {/* 扣减项明细：口径可完整回溯，不只在标题里写一句公式 */}
              {(model.deductions ?? []).length > 0 && (
                <div className="mt-4 overflow-hidden rounded-lg border border-white/8">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-white/4 text-slate-400">
                      <tr>
                        <th className="px-3 py-2 font-medium">扣减项</th>
                        <th className="px-3 py-2 text-right font-medium">数量</th>
                        <th className="px-3 py-2 text-right font-medium">单项扣分</th>
                        <th className="px-3 py-2 text-right font-medium">小计</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/6">
                      {(model.deductions ?? []).map((d: AnyRow, i: number) => (
                        <tr key={i} className="text-slate-300">
                          <td className="px-3 py-2">{d.item}</td>
                          <td className="px-3 py-2 text-right font-num">{d.count}</td>
                          <td className="px-3 py-2 text-right font-num">{fmt(d.per, 1)}</td>
                          <td className={`px-3 py-2 text-right font-num ${Number(d.total) > 0 ? 'text-state-danger' : 'text-slate-500'}`}>
                            {Number(d.total) > 0 ? `−${fmt(d.total, 1)}` : '0.0'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------- 图表区 */}
      {s && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Panel title="事件类型分布" subtitle="按事件类型统计起数">
            <Chart height={280} option={incidentTypeOption} empty={Object.keys(s.by_type ?? {}).length === 0} />
          </Panel>
          <Panel title="隐患类型分布" subtitle="按隐患类型统计项数">
            <Chart height={280} option={hazardTypeOption} empty={Object.keys(s.hazard_by_type ?? {}).length === 0} />
          </Panel>
        </div>
      )}

      {/* ------------------------------------------------------ 台账列表 */}
      <Panel
        title={tab === 'incident' ? '安全事件台账' : '安全隐患台账'}
        subtitle={`共 ${total} 条`}
        extra={
          <div className="flex items-center gap-2">
            <Btn size="sm" variant={tab === 'incident' ? 'primary' : 'ghost'} onClick={() => { setTab('incident'); setPage(1) }}>
              安全事件
            </Btn>
            <Btn size="sm" variant={tab === 'hazard' ? 'primary' : 'ghost'} onClick={() => { setTab('hazard'); setPage(1) }}>
              安全隐患
            </Btn>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
            <span className="font-num text-xs text-slate-500">{page} / {pages}</span>
            <Btn variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>下一页</Btn>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="等级">
            <select className={inputCls} value={level}
              onChange={(e) => { setLevel(e.target.value); setPage(1) }}>
              <option value="">全部</option>
              {Object.entries(LEVEL_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="状态">
            <select className={inputCls} value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
              <option value="">全部</option>
              <option value="OPEN">未闭环</option>
              <option value="CLOSED">已闭环</option>
              <option value="RECTIFYING">整改中</option>
            </select>
          </Field>
          {(level || status) && (
            <Btn variant="ghost" onClick={() => { setLevel(''); setStatus(''); setPage(1) }}>清空筛选</Btn>
          )}
        </div>

        {tab === 'incident' ? (
          <DataTable<any>
            columns={[
              { key: 'incident_code', title: '编号', render: (r) => <span className="font-num text-xs">{r.incident_code}</span> },
              {
                key: 'incident_type', title: '事件',
                render: (r) => (
                  <div className="min-w-0">
                    <div className="font-medium text-slate-100">
                      {INCIDENT_TYPE[r.incident_type] ?? r.incident_type}
                    </div>
                    <div className="truncate text-[11px] text-slate-500">{r.description ?? r.title ?? '—'}</div>
                  </div>
                ),
              },
              {
                key: 'level', title: '等级',
                render: (r) => <Tag tone={LEVEL_TONE[r.level] ?? 'muted'}>{LEVEL_LABEL[r.level] ?? r.level}</Tag>,
              },
              { key: 'location', title: '位置', render: (r) => r.location ?? '—' },
              { key: 'occur_date', title: '发生日期', render: (r) => <span className="font-num">{r.occur_date ?? r.occurred_at ?? '—'}</span> },
              {
                key: 'status', title: '状态',
                render: (r) => (
                  <Tag tone={r.status === 'CLOSED' ? 'ok' : r.status === 'RECTIFYING' ? 'warn' : 'danger'}>
                    {{ CLOSED: '已闭环', OPEN: '未闭环', RECTIFYING: '整改中' }[r.status as string] ?? r.status}
                  </Tag>
                ),
              },
              {
                key: 'rectify_deadline', title: '整改期限',
                render: (r) => <span className="font-num">{r.rectify_deadline ?? '—'}</span>,
              },
              {
                key: 'handle_hours', title: '处理时长(h)', align: 'right',
                render: (r) => (r.handle_hours != null ? fmt(r.handle_hours, 1) : <span className="text-slate-600">—</span>),
              },
              {
                key: 'is_overdue', title: '超期',
                render: (r) => (r.is_overdue ? <Tag tone="danger">已超期</Tag> : <span className="text-slate-600">—</span>),
              },
              { key: 'review_result', title: '复查结论', render: (r) => r.review_result ?? '—' },
            ]}
            rows={rows}
            loading={incidents.loading}
            error={incidents.error}
            onRetry={incidents.reload}
            rowKey={(r) => r.id}
            compact
            empty="没有匹配的安全事件"
          />
        ) : (
          <DataTable<any>
            columns={[
              { key: 'hazard_code', title: '编号', render: (r) => <span className="font-num text-xs">{r.hazard_code}</span> },
              {
                key: 'hazard_type', title: '隐患',
                render: (r) => (
                  <div className="min-w-0">
                    <div className="font-medium text-slate-100">{HAZARD_TYPE[r.hazard_type] ?? r.hazard_type}</div>
                    <div className="truncate text-[11px] text-slate-500">{r.description ?? '—'}</div>
                  </div>
                ),
              },
              {
                key: 'hazard_level', title: '等级',
                render: (r) => <Tag tone={LEVEL_TONE[r.hazard_level] ?? 'muted'}>
                  {LEVEL_LABEL[r.hazard_level] ?? r.hazard_level}
                </Tag>,
              },
              { key: 'location', title: '位置', render: (r) => r.location ?? '—' },
              { key: 'source', title: '来源', render: (r) => r.source ?? '—' },
              { key: 'found_date', title: '发现日期', render: (r) => <span className="font-num">{r.found_date ?? '—'}</span> },
              { key: 'responsible_dept', title: '责任部门', render: (r) => r.responsible_dept ?? '—' },
              {
                key: 'rectify_deadline', title: '整改期限',
                render: (r) => {
                  const overdue = r.rectify_deadline
                    && new Date(r.rectify_deadline) < new Date()
                    && r.status !== 'CLOSED'
                  return <span className={`font-num ${overdue ? 'text-state-danger' : ''}`}>{r.rectify_deadline ?? '—'}</span>
                },
              },
              {
                key: 'status', title: '状态',
                render: (r) => (
                  <Tag tone={r.status === 'CLOSED' ? 'ok' : r.status === 'RECTIFYING' ? 'warn' : 'danger'}>
                    {{ CLOSED: '已闭环', OPEN: '待整改', RECTIFYING: '整改中' }[r.status as string] ?? r.status}
                  </Tag>
                ),
              },
              { key: 'risk_source_type', title: '风险源', render: (r) => r.risk_source_type ?? '—' },
            ]}
            rows={rows}
            loading={hazards.loading}
            error={hazards.error}
            onRetry={hazards.reload}
            rowKey={(r) => r.id}
            compact
            empty="没有匹配的安全隐患"
          />
        )}

        {!can('safety', 'VIEW') && (
          <div className="mt-3 text-xs text-slate-500">
            当前账号对安全管理为只读权限，如需处置请在审批中心发起流程。
          </div>
        )}
      </Panel>
    </div>
  )
}

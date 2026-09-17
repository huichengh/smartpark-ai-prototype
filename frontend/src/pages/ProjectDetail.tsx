/**
 * 项目详情 —— 项目管理中心的核心页面
 *
 * 覆盖：项目概况 / AI 诊断 / 甘特图（CPM 关键路径）/ WBS / 里程碑 /
 *       挣值分析（EVM）/ 风险矩阵 / 问题与变更 / 敏捷看板（仅敏捷或混合项目）
 *
 * 关键设计：
 *  - 瀑布式项目请求敏捷数据后端返回 400，这是**预期的业务行为**，页面需给出
 *    明确的产品化提示，而不是把它当作错误红屏。
 *  - 甘特图用纯 DOM + 百分比定位实现（不引入额外图表库），保证在等轴测/深色
 *    主题下的一致观感。
 */
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { projectApi } from '@/api/modules'
import { ApiException } from '@/api/client'
import { useAsync, pushToast } from '@/hooks/useAsync'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Segmented, Tag, cx,
} from '@/components/ui'
import { Chart, barOption, lineOption, pieOption } from '@/components/Charts'
import type { EChartsOption } from 'echarts'

const fmt = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const wan = (v: any) => {
  const n = Number(v) || 0
  return Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(2)} 万` : n.toFixed(2)
}

const RISK_TONE: Record<string, string> = { HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok' }
const METHOD_TONE: Record<string, string> = { WATERFALL: 'info', AGILE: 'ai', HYBRID: 'warn' }

type AnyRow = Record<string, any>
type Tab = 'overview' | 'gantt' | 'wbs' | 'evm' | 'risk' | 'issues' | 'agile'

export default function ProjectDetail() {
  const { id } = useParams()
  const projectId = Number(id)
  const [tab, setTab] = useState<Tab>('overview')

  const detail = useAsync(() => projectApi.detail(projectId), [projectId], { enabled: !!projectId })
  const gantt = useAsync(() => projectApi.gantt(projectId), [projectId], {
    enabled: !!projectId && (tab === 'gantt' || tab === 'overview'),
  })
  const evm = useAsync(() => projectApi.evm(projectId), [projectId], {
    enabled: !!projectId && (tab === 'evm' || tab === 'overview'),
  })
  /** 敏捷接口对瀑布式项目返回 400 —— 属预期业务行为 */
  const agile = useAsync(() => projectApi.agile(projectId), [projectId], {
    enabled: !!projectId && tab === 'agile',
  })

  const p = detail.data?.project
  const diag = detail.data?.diagnosis

  const tabs = useMemo(() => {
    const method = p?.management_method
    const base: { value: Tab; label: string }[] = [
      { value: 'overview', label: '项目概况' },
      { value: 'gantt', label: '甘特图' },
      { value: 'wbs', label: 'WBS 分解' },
      { value: 'evm', label: '挣值分析' },
      { value: 'risk', label: '风险矩阵' },
      { value: 'issues', label: '问题与变更' },
    ]
    if (method === 'AGILE' || method === 'HYBRID') {
      base.push({ value: 'agile', label: '敏捷看板' })
    }
    return base
  }, [p?.management_method])

  if (detail.loading) {
    return <Panel><Loading text="正在加载项目详情…" /></Panel>
  }
  if (detail.error) {
    return (
      <Panel title="项目详情">
        <ErrorState error={detail.error} onRetry={detail.reload} />
        <div className="mt-4 text-center">
          <Link to="/projects" className="text-xs text-brand-300 hover:underline">返回项目列表</Link>
        </div>
      </Panel>
    )
  }
  if (!p) return <Panel><EmptyState text="项目不存在" /></Panel>

  return (
    <div className="space-y-5">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {p.project_name}
            <Tag tone={METHOD_TONE[p.management_method] ?? 'muted'}>
              {p.management_method_name ?? p.management_method}
            </Tag>
          </span>
        }
        desc={
          <span className="font-num">
            {p.project_code} · {p.department ?? '—'} · 项目经理 {p.project_manager_name ?? '—'}
          </span>
        }
        demo
        extra={
          <div className="flex items-center gap-2">
            <Btn variant="ghost" onClick={() => { detail.reload(); gantt.reload(); evm.reload() }}>
              刷新
            </Btn>
            <Link to="/projects">
              <Btn variant="ghost">返回列表</Btn>
            </Link>
          </div>
        }
      />

      <Segmented value={tab} onChange={(v) => setTab(v as Tab)} options={tabs} />

      {tab === 'overview' && (
        <OverviewTab detail={detail.data} diag={diag} gantt={gantt.data} evm={evm.data?.evm} />
      )}
      {tab === 'gantt' && <GanttTab data={gantt.data} loading={gantt.loading} error={gantt.error} onRetry={gantt.reload} />}
      {tab === 'wbs' && <WbsTab rows={detail.data?.wbs ?? []} />}
      {tab === 'evm' && <EvmTab data={evm.data} loading={evm.loading} error={evm.error} onRetry={evm.reload} />}
      {tab === 'risk' && <RiskTab data={detail.data} />}
      {tab === 'issues' && <IssuesTab data={detail.data} projectId={projectId} onChanged={detail.reload} />}
      {tab === 'agile' && (
        <AgileTab data={agile.data} loading={agile.loading} error={agile.error} onRetry={agile.reload}
                  method={p.management_method} />
      )}
    </div>
  )
}

/* ------------------------------------------------------------ 概况 */

function OverviewTab({ detail, diag, gantt, evm }: any) {
  const p = detail?.project ?? {}
  const cp = detail?.critical_path ?? {}
  const ms = detail?.milestones ?? []
  const risks: AnyRow[] = detail?.risks ?? []

  const methodOption = useMemo(
    () =>
      pieOption({
        data: Object.entries(
          risks.reduce((acc: Record<string, number>, r) => {
            const k = r.risk_level ?? 'UNKNOWN'
            acc[k] = (acc[k] ?? 0) + 1
            return acc
          }, {}),
        ).map(([name, value]) => ({
          name: { HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' }[name] ?? name,
          value: value as number,
        })),
        centerLabel: { title: '风险总数', value: risks.length },
      }),
    [risks],
  )

  return (
    <div className="space-y-5">
      {/* 核心指标 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard label="总体进度" value={fmt(p.progress, 1)} unit="%" hint={`计划 ${fmt(p.planned_progress, 0)}%`} />
        <KpiCard
          label="进度偏差" value={fmt(p.progress_variance, 1)} unit="%"
          tone={Number(p.progress_variance) < -5 ? 'risk' : 'ok'}
          hint="实际 − 计划"
        />
        <KpiCard
          label="风险等级" value={p.risk_level_name ?? p.risk_level ?? '—'}
          tone={RISK_TONE[p.risk_level] === 'danger' ? 'risk' : RISK_TONE[p.risk_level] === 'warn' ? 'warn' : 'ok'}
        />
        <KpiCard label="批准预算" value={wan(p.approved_budget ?? p.budget)} unit="元" />
        <KpiCard label="已发生成本" value={wan(p.actual_cost)} unit="元" />
        <KpiCard
          label="预算执行率" value={fmt(p.execution_rate, 1)} unit="%"
          tone={Number(p.execution_rate) > 100 ? 'risk' : 'brand'}
        />
      </div>

      {/* AI 诊断 */}
      {diag && (
        <Panel
          title="项目健康诊断"
          subtitle={`健康度：${diag.health ?? '—'}${diag.data_sufficient === false ? '（数据不足）' : ''}`}
          icon={<span className="text-base">AI</span>}
        >
          {diag.conclusion && (
            <p className="mb-4 rounded-lg border border-white/8 bg-white/[0.04] px-4 py-3 text-sm leading-relaxed text-slate-200">
              {diag.conclusion}
            </p>
          )}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {[
              { key: 'schedule', label: '进度' },
              { key: 'cost', label: '成本' },
              { key: 'risk', label: '风险' },
              { key: 'milestone', label: '里程碑' },
            ].map(({ key, label }) => {
              const s = diag[key]
              if (!s) return null
              return (
                <div key={key} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-300">{label}</span>
                    {s.level && (
                      <Tag tone={RISK_TONE[s.level] ?? (s.level === 'GOOD' ? 'ok' : 'muted')}>
                        {s.level}
                      </Tag>
                    )}
                  </div>
                  <p className="text-[11px] leading-relaxed text-slate-400">
                    {s.text ?? s.conclusion ?? s.detail ?? '—'}
                  </p>
                  {s.basis && (
                    <p className="mt-1.5 border-t border-white/6 pt-1.5 text-[10px] text-slate-600">
                      口径：{s.basis}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
          {diag.data_sufficient === false && (
            <p className="mt-3 rounded-lg border border-state-warn/25 bg-state-warn/8 px-3 py-2 text-[11px] text-state-warn">
              部分诊断维度数据不足，结论仅供参考。
            </p>
          )}
        </Panel>
      )}

      {/* 关键路径摘要 */}
      {cp?.tasks && (
        <Panel
          title="关键路径（CPM）"
          subtitle={cp.basis ?? '基于任务依赖执行前推/后推计算'}
          extra={
            <div className="flex items-center gap-3 text-xs">
              <span className="text-slate-500">关键任务 <b className="font-num text-state-danger">{cp.critical_task_count ?? 0}</b></span>
              <span className="text-slate-500">项目工期 <b className="font-num text-slate-200">{cp.project_duration_days ?? '—'}</b> 天</span>
            </div>
          }
        >
          {cp.implicit_dependency_chain && (
            <p className="mb-3 rounded-lg border border-state-warn/25 bg-state-warn/8 px-3 py-2 text-[11px] text-state-warn">
              检测到未显式登记的隐含依赖链：{String(cp.implicit_dependency_chain)}
            </p>
          )}
          <div className="flex flex-wrap gap-1.5">
            {(cp.tasks as AnyRow[]).map((t) => (
              <span
                key={t.id ?? t.wbs_code}
                title={`${t.item_name}｜工期 ${t.duration_days ?? 0} 天｜浮时 ${t.slack_days ?? 0} 天`}
                className={cx(
                  'rounded-md border px-2 py-1 text-[11px]',
                  t.is_critical
                    ? 'border-state-danger/35 bg-state-danger/10 text-state-danger'
                    : 'border-white/10 bg-white/[0.04] text-slate-300',
                )}
              >
                {t.wbs_code} {t.item_name}
              </span>
            ))}
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        {/* 里程碑 */}
        <div className="xl:col-span-2">
          <Panel title="里程碑" subtitle={`共 ${ms.length} 个，关键里程碑以星标标示`}>
            {ms.length === 0 ? (
              <EmptyState text="暂无里程碑" />
            ) : (
              <ol className="relative space-y-3 border-l border-white/10 pl-5">
                {ms.map((m: AnyRow) => {
                  const done = m.status === 'ACHIEVED'
                  return (
                    <li key={m.id} className="relative">
                      <span
                        className={cx(
                          'absolute -left-[26px] top-1 h-3 w-3 rounded-full border-2',
                          done
                            ? 'border-state-ok bg-state-ok/30'
                            : m.is_overdue
                              ? 'border-state-danger bg-state-danger/30'
                              : 'border-white/25 bg-[#0D1B2A]',
                        )}
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-slate-200">
                          {m.milestone_name}
                        </span>
                        {m.is_key && <Tag tone="ai">关键</Tag>}
                        <Tag tone={done ? 'ok' : m.is_overdue ? 'danger' : 'muted'}>
                          {done ? '已达成' : m.is_overdue ? '已逾期' : '进行中'}
                        </Tag>
                        {Number(m.delay_days) > 0 && (
                          <span className="font-num text-[11px] text-state-danger">
                            延期 {m.delay_days} 天
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 font-num text-[11px] text-slate-500">
                        {m.milestone_code} · 计划 {m.plan_date ?? '—'}
                        {m.actual_date && ` · 实际 ${m.actual_date}`}
                        {m.deliverable && ` · 交付物 ${m.deliverable}`}
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}
          </Panel>
        </div>

        {/* 风险分布 */}
        <Panel title="风险等级分布" subtitle="基于项目风险台账统计">
          <Chart height={250} option={methodOption} empty={risks.length === 0} />
        </Panel>
      </div>

      {/* EVM 摘要 */}
      {evm && (
        <Panel title="挣值分析摘要" subtitle={evm.basis ? '' : 'EV / PV / AC 由后端基于 WBS 与成本台账计算'}>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
            <KpiCard label="CPI 成本绩效" value={fmt(evm.cpi, 3)}
              tone={Number(evm.cpi) >= 1 ? 'ok' : 'risk'} hint="EV ÷ AC，≥1 为成本节约" />
            <KpiCard label="SPI 进度绩效" value={fmt(evm.spi, 3)}
              tone={Number(evm.spi) >= 1 ? 'ok' : 'risk'} hint="EV ÷ PV，≥1 为进度超前" />
            <KpiCard label="EV 挣值" value={wan(evm.ev)} unit="元" />
            <KpiCard label="PV 计划值" value={wan(evm.pv)} unit="元" />
            <KpiCard label="AC 实际成本" value={wan(evm.ac)} unit="元" />
            <KpiCard label="EAC 完工估算" value={wan(evm.eac)} unit="元"
              tone={Number(evm.vac) < 0 ? 'risk' : 'ok'}
              hint={`VAC ${wan(evm.vac)}`} />
          </div>
          {evm.basis && (
            <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
              {typeof evm.basis === 'string' ? evm.basis : Object.entries(evm.basis).map(([k, v]) => `${k}：${v}`).join('；')}
            </p>
          )}
        </Panel>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ 甘特图 */

function GanttTab({ data, loading, error, onRetry }: any) {
  if (loading) return <Panel><Loading text="正在计算关键路径…" /></Panel>
  if (error) return <Panel><ErrorState error={error} onRetry={onRetry} /></Panel>
  if (!data) return <Panel><EmptyState text="暂无甘特数据" /></Panel>

  const tasks: AnyRow[] = data.tasks ?? []
  const total = Math.max(1, Number(data.project_duration_days) || 1)
  const todayOffset = tasks[0]?.offset_today ?? 0

  const criticalSet = new Set(data.critical_path ?? [])

  return (
    <div className="space-y-5">
      <Panel
        title="项目甘特图"
        subtitle={data.basis ?? ''}
        extra={
          <div className="flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1.5 text-slate-400">
              <i className="inline-block h-2.5 w-3 rounded-sm bg-state-danger" /> 关键路径
            </span>
            <span className="flex items-center gap-1.5 text-slate-400">
              <i className="inline-block h-2.5 w-3 rounded-sm bg-brand-500" /> 普通任务
            </span>
            <span className="font-num text-slate-500">工期 {total} 天</span>
          </div>
        }
      >
        {tasks.length === 0 ? (
          <EmptyState text="暂无 WBS 任务" hint="甘特图需要项目先完成 WBS 拆解。" />
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[860px]">
              {/* 表头 */}
              <div className="mb-2 flex items-center gap-3 border-b border-white/8 pb-2 text-[11px] text-slate-500">
                <div className="w-[300px] shrink-0">任务</div>
                <div className="relative flex-1">
                  <span>时间轴（相对项目开工）</span>
                  {todayOffset > 0 && (
                    <span
                      className="absolute -top-1 font-num text-state-warn"
                      style={{ left: `${Math.min(97, (todayOffset / total) * 100)}%` }}
                    >
                      今日
                    </span>
                  )}
                </div>
              </div>

              {/* 任务行 */}
              <div className="relative space-y-1">
                {/* 今日竖线 */}
                {todayOffset > 0 && (
                  <div
                    className="pointer-events-none absolute bottom-0 top-0 z-10 w-px bg-state-warn/55"
                    style={{ left: `calc(300px + 12px + (100% - 312px) * ${Math.min(1, todayOffset / total)})` }}
                  />
                )}

                {tasks.map((t) => {
                  const isCrit = t.is_critical || criticalSet.has(t.id)
                  const start = Number(t.offset_start) || 0
                  const end = Number(t.offset_end) || 0
                  const left = (start / total) * 100
                  const width = Math.max(0.6, ((end - start) / total) * 100)
                  const indent = (Number(t.item_level) || 1) - 1
                  const risky = t.risk_level && t.risk_level !== 'LOW'
                  return (
                    <div key={t.id} className="flex items-center gap-3 rounded-md py-0.5 hover:bg-white/[0.03]">
                      <div
                        className="w-[300px] shrink-0 truncate text-xs"
                        style={{ paddingLeft: indent * 12 }}
                        title={`${t.item_name}｜${t.plan_start ?? '—'} → ${t.plan_end ?? '—'}｜浮时 ${t.slack_days ?? 0} 天`}
                      >
                        <span className="font-num text-slate-500">{t.wbs_code}</span>{' '}
                        <span className={isCrit ? 'font-medium text-state-danger' : 'text-slate-200'}>
                          {t.item_name}
                        </span>
                        {t.overdue && <span className="ml-1.5 text-[10px] text-state-danger">逾期</span>}
                        {risky && <span className="ml-1.5 text-[10px] text-state-warn">⚠</span>}
                      </div>

                      <div className="relative h-5 flex-1">
                        <div className="absolute inset-y-0 w-full rounded bg-white/[0.03]" />
                        <div
                          className={cx(
                            'absolute top-1 h-3 rounded-sm transition-all',
                            isCrit
                              ? 'bg-state-danger/85'
                              : Number(t.progress) >= 100
                                ? 'bg-state-ok/70'
                                : 'bg-brand-500/70',
                          )}
                          style={{ left: `${left}%`, width: `${width}%` }}
                          title={`进度 ${fmt(t.progress, 0)}%｜计划 ${t.plan_start} → ${t.plan_end}`}
                        >
                          {width > 6 && (
                            <span className="absolute inset-0 flex items-center justify-center text-[9px] text-white/90">
                              {fmt(t.progress, 0)}%
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="w-[86px] shrink-0 font-num text-[10px] text-slate-500">
                        {t.duration_days ? `${t.duration_days}天` : '汇总'}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </Panel>

      {/* 依赖关系 */}
      {(data.dependencies ?? []).length > 0 && (
        <Panel title="任务依赖关系" subtitle={`共 ${data.dependencies.length} 条前置/后置约束`}>
          <DataTable<AnyRow>
            columns={[
              { key: 'id', title: '#', width: 60 },
              {
                key: 'predecessor_id', title: '前置任务',
                render: (r) => {
                  const t = tasks.find((x) => x.id === r.predecessor_id)
                  return t ? `${t.wbs_code} ${t.item_name}` : `#${r.predecessor_id}`
                },
              },
              {
                key: 'successor_id', title: '后置任务',
                render: (r) => {
                  const t = tasks.find((x) => x.id === r.successor_id)
                  return t ? `${t.wbs_code} ${t.item_name}` : `#${r.successor_id}`
                },
              },
              {
                key: 'dep_type', title: '类型',
                render: (r) => (
                  <Tag tone="muted">
                    {{ FS: '完成-开始', SS: '开始-开始', FF: '完成-完成', SF: '开始-完成' }[r.dep_type as string] ?? r.dep_type}
                  </Tag>
                ),
              },
              { key: 'lag_days', title: '滞后(天)', align: 'right', render: (r) => r.lag_days ?? 0 },
            ]}
            rows={data.dependencies}
            rowKey={(r) => r.id}
            compact
          />
        </Panel>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ WBS */

function WbsTab({ rows }: { rows: AnyRow[] }) {
  if (!rows?.length) return <Panel><EmptyState text="暂无 WBS 数据" /></Panel>

  return (
    <Panel
      title="WBS 工作分解结构"
      subtitle={`共 ${rows.length} 个节点；关键路径任务以红色标示，浮时为 0 即无机动时间`}
    >
      <DataTable<AnyRow>
        columns={[
          {
            key: 'wbs_code', title: 'WBS', width: 96,
            render: (r) => (
              <span className="font-num" style={{ paddingLeft: ((Number(r.item_level) || 1) - 1) * 10 }}>
                {r.wbs_code}
              </span>
            ),
          },
          {
            key: 'item_name', title: '任务名称',
            render: (r) => (
              <span className={r.is_critical ? 'font-medium text-state-danger' : 'text-slate-200'}>
                {r.item_name}
              </span>
            ),
          },
          { key: 'item_type', title: '类型', render: (r) => (r.item_type === 'SUMMARY' ? '汇总' : '作业') },
          { key: 'owner_name', title: '负责人', render: (r) => r.owner_name ?? '—' },
          { key: 'plan_start', title: '计划开始', render: (r) => r.plan_start ?? '—' },
          { key: 'plan_end', title: '计划完成', render: (r) => r.plan_end ?? '—' },
          {
            key: 'progress', title: '进度', width: 130,
            render: (r) => <ProgressBar value={Number(r.progress) || 0} showText />,
          },
          {
            key: 'slack_days', title: '浮时(天)', align: 'right',
            render: (r) => (
              <span className={Number(r.slack_days) === 0 && r.is_critical ? 'text-state-danger' : ''}>
                {r.slack_days ?? '—'}
              </span>
            ),
          },
          {
            key: 'budget', title: '预算(元)', align: 'right',
            render: (r) => fmt(r.budget),
          },
          {
            key: 'actual_cost', title: '实际(元)', align: 'right',
            render: (r) => (
              <span className={Number(r.actual_cost) > Number(r.budget) && Number(r.budget) > 0 ? 'text-state-danger' : ''}>
                {fmt(r.actual_cost)}
              </span>
            ),
          },
          {
            key: 'risk_level', title: '风险',
            render: (r) => (r.risk_level
              ? <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>{r.risk_level}</Tag>
              : <span className="text-slate-600">—</span>),
          },
        ]}
        rows={rows}
        rowKey={(r) => r.id}
        compact
      />
    </Panel>
  )
}

/* ------------------------------------------------------------ EVM */

function EvmTab({ data, loading, error, onRetry }: any) {
  if (loading) return <Panel><Loading text="正在计算挣值指标…" /></Panel>
  if (error) return <Panel><ErrorState error={error} onRetry={onRetry} /></Panel>
  if (!data) return <Panel><EmptyState text="暂无挣值数据" /></Panel>

  const e = data.evm ?? {}
  const trend: AnyRow[] = data.trend ?? []
  const subjects: AnyRow[] = e.subjects ?? []

  const trendOption = lineOption({
    x: trend.map((t) => t.month),
    series: [
      { name: 'PV 计划值', data: trend.map((t) => t.pv), color: '#2F80ED' },
      { name: 'EV 挣值', data: trend.map((t) => t.ev), color: '#00D4FF' },
      { name: 'AC 实际成本', data: trend.map((t) => t.ac), color: '#7B61FF' },
    ],
    yName: '元',
  })

  const indexOption = lineOption({
    x: trend.map((t) => t.month),
    series: [
      { name: 'CPI', data: trend.map((t) => t.cpi), color: '#22C55E' },
      { name: 'SPI', data: trend.map((t) => t.spi), color: '#FACC15' },
    ],
    smooth: false,
  })

  if (e.data_sufficient === false) {
    return (
      <Panel title="挣值分析">
        <EmptyState
          text="数据不足，无法计算挣值指标"
          hint={
            data.missing_data?.length
              ? `缺少：${data.missing_data.join('、')}`
              : '需要项目具备完整的 WBS 预算与实际成本记录。'
          }
        />
      </Panel>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-8">
        <KpiCard label="EV 挣值" value={wan(e.ev)} unit="元" hint="已完成工作的预算价值" />
        <KpiCard label="PV 计划值" value={wan(e.pv)} unit="元" hint="计划完成工作的预算" />
        <KpiCard label="AC 实际成本" value={wan(e.ac)} unit="元" hint="实际发生的成本" />
        <KpiCard label="CPI" value={fmt(e.cpi, 3)} tone={Number(e.cpi) >= 1 ? 'ok' : 'risk'} hint="EV ÷ AC" />
        <KpiCard label="SPI" value={fmt(e.spi, 3)} tone={Number(e.spi) >= 1 ? 'ok' : 'risk'} hint="EV ÷ PV" />
        <KpiCard label="CV 成本偏差" value={wan(e.cost_variance)} unit="元" hint="EV − AC" />
        <KpiCard label="EAC 完工估算" value={wan(e.eac)} unit="元" hint="按当前 CPI 推算" />
        <KpiCard label="VAC 完工偏差" value={wan(e.vac)} unit="元"
          tone={Number(e.vac) < 0 ? 'risk' : 'ok'} hint="批准预算 − EAC" />
      </div>

      {(e.overspend_risk || data.data_sufficient === true) && (
        <div
          className={cx(
            'rounded-lg border px-4 py-3 text-sm',
            e.overspend_risk
              ? 'border-state-danger/30 bg-state-danger/[0.08] text-state-danger'
              : 'border-state-ok/28 bg-state-ok/[0.08] text-state-ok',
          )}
        >
          <span className="font-medium">成本趋势判断：</span>
          {e.overspend_risk
            ? `存在超支风险（VAC ${wan(e.vac)} 元），建议复核工程量与签证变更。`
            : '当前成本处于预算控制范围内。'}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel title="挣值曲线" subtitle="PV / EV / AC 月度趋势">
          <Chart height={300} option={trendOption} empty={trend.length === 0} />
        </Panel>
        <Panel title="绩效指数趋势" subtitle="CPI 与 SPI，>1 表示优于基准">
          <Chart height={300} option={indexOption} empty={trend.length === 0} />
        </Panel>
      </div>

      {subjects.length > 0 && (
        <Panel title="成本科目明细" subtitle="按 cost_subject 归集的预算与执行">
          <DataTable<AnyRow>
            columns={[
              { key: 'cost_subject', title: '成本科目' },
              { key: 'budget_amount', title: '预算(元)', align: 'right', render: (r) => fmt(r.budget_amount, 2) },
              { key: 'planned_cost', title: '计划(元)', align: 'right', render: (r) => fmt(r.planned_cost, 2) },
              { key: 'actual_amount', title: '实际(元)', align: 'right', render: (r) => fmt(r.actual_amount, 2) },
              {
                key: 'diff', title: '偏差(元)', align: 'right',
                render: (r) => {
                  const d = Number(r.actual_amount) - Number(r.budget_amount)
                  return <span className={d > 0 ? 'text-state-danger' : 'text-state-ok'}>{fmt(d, 2)}</span>
                },
              },
            ]}
            rows={subjects}
            rowKey={(r, i) => r.id ?? r.cost_subject ?? i}
            compact
          />
        </Panel>
      )}

      {data.basis && (
        <Panel title="指标口径说明">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-xs md:grid-cols-2">
            {Object.entries(data.basis as Record<string, string>).map(([k, v]) => (
              <div key={k} className="flex gap-3 border-b border-white/5 py-1.5">
                <dt className="w-16 shrink-0 font-num font-medium text-brand-300">{k}</dt>
                <dd className="text-slate-400">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ 风险矩阵 */

function RiskTab({ data }: any) {
  const risks: AnyRow[] = data?.risks ?? []
  const matrix: AnyRow[] = data?.matrix ?? []
  const axis = data?.matrix_axis ?? { x: '影响', y: '概率' }
  const zones: AnyRow[] = data?.level_zones ?? []

  /** 5×5 概率-影响矩阵，用 HTML 网格渲染以便精确控制颜色与提示 */
  const cellOf = (prob: number, impact: number) => {
    const hit = matrix.find((m) => Number(m.probability) === prob && Number(m.impact) === impact)
    return hit
  }
  const zoneColor = (score: number) => {
    const z = zones.find((z) => score >= Number(z.score_min) && score <= Number(z.score_max))
    return z?.color ?? '#64748B'
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel
          title="风险矩阵"
          subtitle={`横轴 ${axis.x ?? '影响'} / 纵轴 ${axis.y ?? '概率'}；色块由后端 level_zones 下发`}
        >
          <div className="flex gap-3">
            {/* Y 轴标签 */}
            <div className="flex flex-col justify-between py-1 text-[10px] text-slate-500">
              {[5, 4, 3, 2, 1].map((p) => (
                <span key={p} className="h-11 leading-[44px]">{p}</span>
              ))}
            </div>

            <div className="flex-1">
              <div className="grid grid-cols-5 gap-1">
                {[5, 4, 3, 2, 1].flatMap((prob) =>
                  [1, 2, 3, 4, 5].map((impact) => {
                    const cell = cellOf(prob, impact)
                    const count = cell?.count ?? cell?.risk_count ?? 0
                    const score = prob * impact
                    const c = zoneColor(score)
                    return (
                      <div
                        key={`${prob}-${impact}`}
                        title={
                          `概率 ${prob} × 影响 ${impact} = ${score}` +
                          (count ? `｜风险 ${count} 项` : '｜无风险')
                        }
                        className="flex h-11 flex-col items-center justify-center rounded border text-[11px] transition-transform hover:scale-105"
                        style={{
                          background: count ? `${c}30` : 'rgba(255,255,255,0.03)',
                          borderColor: count ? `${c}88` : 'rgba(255,255,255,0.08)',
                        }}
                      >
                        {count > 0 ? (
                          <>
                            <span className="font-num font-semibold" style={{ color: c }}>{count}</span>
                            <span className="text-[9px] text-slate-500">{score}</span>
                          </>
                        ) : (
                          <span className="text-[9px] text-slate-700">{score}</span>
                        )}
                      </div>
                    )
                  }),
                )}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-slate-500">
                {[1, 2, 3, 4, 5].map((i) => <span key={i} className="w-11 text-center">{i}</span>)}
              </div>
              <p className="mt-1 text-center text-[10px] text-slate-500">{axis.x ?? '影响程度'} →</p>
            </div>
          </div>

          {zones.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-3 border-t border-white/6 pt-3">
              {zones.map((z) => (
                <span key={z.name} className="flex items-center gap-1.5 text-[11px] text-slate-400">
                  <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: z.color }} />
                  {z.name}（{z.score_min}–{z.score_max}）
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="风险等级分布" subtitle="按 risk_level 统计">
          <Chart
            height={300}
            option={pieOption({
              data: Object.entries(
                risks.reduce((a: Record<string, number>, r) => {
                  const k = { HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' }[r.risk_level as string] ?? r.risk_level ?? '未知'
                  a[k] = (a[k] ?? 0) + 1
                  return a
                }, {}),
              ).map(([name, value]) => ({ name, value: value as number })),
              centerLabel: { title: '风险项', value: risks.length },
            })}
            empty={risks.length === 0}
          />
        </Panel>
      </div>

      <Panel title="风险台账" subtitle={`共 ${risks.length} 条；AI 识别的风险以紫色标签标示`}>
        <DataTable<AnyRow>
          columns={[
            { key: 'risk_code', title: '编号', width: 92 },
            {
              key: 'risk_title', title: '风险',
              render: (r) => (
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-medium text-slate-100">{r.risk_title}</span>
                    {r.is_ai_identified && <Tag tone="ai">AI</Tag>}
                  </div>
                  <div className="truncate text-[11px] text-slate-500">{r.risk_description ?? '—'}</div>
                </div>
              ),
            },
            { key: 'risk_category', title: '类别', render: (r) => r.risk_category ?? '—' },
            {
              key: 'risk_level', title: '等级',
              render: (r) => <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>{r.risk_level ?? '—'}</Tag>,
            },
            {
              key: 'risk_score', title: '评分', align: 'right',
              render: (r) => (
                <span className="font-num">
                  {r.risk_score ?? ((Number(r.probability) * Number(r.impact)) || '—')}
                </span>
              ),
            },
            { key: 'strategy', title: '应对策略', render: (r) => r.strategy ?? '—' },
            {
              key: 'response_plan', title: '应对计划',
              render: (r) => (
                <span className="text-[11px] text-slate-400">{r.response_plan ?? '—'}</span>
              ),
            },
            { key: 'risk_owner', title: '责任人', render: (r) => r.risk_owner ?? '—' },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={r.status === 'CLOSED' ? 'ok' : r.status === 'OPEN' ? 'warn' : 'muted'}>
                  {{ OPEN: '开放', CLOSED: '已关闭', MITIGATING: '缓解中' }[r.status as string] ?? r.status}
                </Tag>
              ),
            },
            {
              key: 'due_date', title: '截止',
              render: (r) => {
                const overdue = r.due_date && new Date(r.due_date) < new Date() && r.status !== 'CLOSED'
                return (
                  <span className={cx('font-num text-xs', overdue && 'text-state-danger')}>
                    {r.due_date ?? '—'}
                  </span>
                )
              },
            },
          ]}
          rows={risks}
          rowKey={(r) => r.id}
          compact
          empty="该项目暂无风险记录"
        />
      </Panel>
    </div>
  )
}

/* ------------------------------------------------------------ 问题与变更 */

function IssuesTab({ data, projectId, onChanged }: any) {
  const issues: AnyRow[] = data?.issues ?? []
  const changes: AnyRow[] = data?.changes ?? []
  const costs: AnyRow[] = data?.costs ?? []
  const [busy, setBusy] = useState<number | null>(null)

  const decide = async (changeId: number, decision: 'APPROVE' | 'REJECT') => {
    setBusy(changeId)
    try {
      await projectApi.changeDecision(projectId, changeId, { decision })
      pushToast('ok', decision === 'APPROVE' ? '已批准该变更' : '已驳回该变更')
      onChanged?.()
    } catch (e: any) {
      pushToast('err', e?.message ?? '操作失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <Panel title="问题台账" subtitle={`共 ${issues.length} 条`}>
        <DataTable<AnyRow>
          columns={[
            { key: 'issue_code', title: '编号', width: 92 },
            {
              key: 'issue_title', title: '问题',
              render: (r) => (
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{r.issue_title}</div>
                  <div className="truncate text-[11px] text-slate-500">{r.issue_description ?? '—'}</div>
                </div>
              ),
            },
            {
              key: 'severity', title: '严重度',
              render: (r) => <Tag tone={RISK_TONE[r.severity] ?? 'muted'}>{r.severity ?? '—'}</Tag>,
            },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={r.status === 'CLOSED' || r.status === 'RESOLVED' ? 'ok' : 'warn'}>
                  {{ OPEN: '待处理', RESOLVED: '已解决', CLOSED: '已关闭', IN_PROGRESS: '处理中' }[r.status as string] ?? r.status}
                </Tag>
              ),
            },
            { key: 'owner', title: '责任人', render: (r) => r.owner ?? '—' },
            { key: 'raised_by', title: '提出方', render: (r) => r.raised_by ?? '—' },
            { key: 'raised_date', title: '提出日期', render: (r) => r.raised_date ?? '—' },
            {
              key: 'due_date', title: '截止日期',
              render: (r) => <span className="font-num">{r.due_date ?? '—'}</span>,
            },
            {
              key: 'solution', title: '解决方案',
              render: (r) => <span className="text-[11px] text-slate-400">{r.solution ?? '待补充'}</span>,
            },
          ]}
          rows={issues}
          rowKey={(r) => r.id}
          compact
          empty="该项目暂无问题记录"
        />
      </Panel>

      <Panel
        title="变更管理"
        subtitle={
          changes.length
            ? `共 ${changes.length} 条；基线变更会重新计算计划与成本基准`
            : '暂无变更'
        }
      >
        <div className="space-y-3">
          {changes.length === 0 ? (
            <EmptyState text="该项目暂无变更申请" />
          ) : (
            changes.map((c) => (
              <div key={c.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-num text-xs text-slate-500">{c.change_code}</span>
                      <span className="font-medium text-slate-100">{c.change_title}</span>
                      <Tag tone={c.status === 'APPROVED' ? 'ok' : c.status === 'REJECTED' ? 'danger' : 'warn'}>
                        {{ APPROVED: '已批准', REJECTED: '已驳回', PENDING: '待审批', DRAFT: '草稿' }[c.status as string] ?? c.status}
                      </Tag>
                      {c.is_baseline_change && <Tag tone="ai">基线变更</Tag>}
                      {c.impact_risk && (
                        <Tag tone={RISK_TONE[c.impact_risk] ?? 'muted'}>影响风险 {c.impact_risk}</Tag>
                      )}
                    </div>
                    <p className="mt-1.5 text-xs text-slate-400">{c.change_reason ?? '—'}</p>
                  </div>

                  <div className="flex items-center gap-2">
                    {c.status === 'PENDING' && (
                      <>
                        <Btn size="sm" variant="primary" loading={busy === c.id}
                             onClick={() => decide(c.id, 'APPROVE')}>
                          批准
                        </Btn>
                        <Btn size="sm" variant="danger" loading={busy === c.id}
                             onClick={() => decide(c.id, 'REJECT')}>
                          驳回
                        </Btn>
                      </>
                    )}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3 border-t border-white/6 pt-3 text-[11px] md:grid-cols-4">
                  <div>
                    <span className="text-slate-500">进度影响 </span>
                    <b className={cx('font-num', Number(c.impact_schedule_days) > 0 ? 'text-state-warn' : 'text-slate-200')}>
                      {c.impact_schedule_days ?? 0} 天
                    </b>
                  </div>
                  <div>
                    <span className="text-slate-500">成本影响 </span>
                    <b className="font-num text-slate-200">{wan(c.impact_cost)} 元</b>
                  </div>
                  <div>
                    <span className="text-slate-500">申请人 </span>
                    <span className="text-slate-300">{c.applicant_name ?? '—'}（{c.apply_date ?? '—'}）</span>
                  </div>
                  <div>
                    <span className="text-slate-500">审批人 </span>
                    <span className="text-slate-300">{c.approver_name ?? '待审批'}{c.approve_date ? `（${c.approve_date}）` : ''}</span>
                  </div>
                </div>

                {c.ai_analysis && (
                  <div className="mt-3 rounded-lg border border-ai/25 bg-ai/[0.07] px-3 py-2 text-[11px] text-ai-light">
                    <span className="font-medium">AI 影响分析：</span>
                    {typeof c.ai_analysis === 'string' ? c.ai_analysis : JSON.stringify(c.ai_analysis)}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Panel>

      <Panel title="成本台账" subtitle={`共 ${costs.length} 条记录`}>
        <DataTable<AnyRow>
          columns={[
            { key: 'cost_code', title: '编号', width: 96 },
            { key: 'cost_subject', title: '成本科目' },
            {
              key: 'cost_type', title: '类型',
              render: (r) => (
                <Tag tone="muted">
                  {{ ACTUAL: '实际', PLANNED: '计划', BUDGET: '预算' }[r.cost_type as string] ?? r.cost_type}
                </Tag>
              ),
            },
            { key: 'budget_amount', title: '预算(元)', align: 'right', render: (r) => fmt(r.budget_amount, 2) },
            { key: 'planned_cost', title: '计划(元)', align: 'right', render: (r) => fmt(r.planned_cost, 2) },
            { key: 'actual_amount', title: '实际(元)', align: 'right', render: (r) => fmt(r.actual_amount, 2) },
            { key: 'contract_amount', title: '合同(元)', align: 'right', render: (r) => fmt(r.contract_amount, 2) },
            { key: 'purchase_amount', title: '采购(元)', align: 'right', render: (r) => fmt(r.purchase_amount, 2) },
            { key: 'paid_amount', title: '已付(元)', align: 'right', render: (r) => fmt(r.paid_amount, 2) },
            { key: 'supplier', title: '供应商', render: (r) => r.supplier ?? '—' },
            { key: 'occur_date', title: '发生日期', render: (r) => <span className="font-num">{r.occur_date ?? '—'}</span> },
          ]}
          rows={costs}
          rowKey={(r) => r.id}
          compact
          empty="暂无成本记录"
        />
      </Panel>
    </div>
  )
}

/* ------------------------------------------------------------ 敏捷看板 */

function AgileTab({ data, loading, error, onRetry, method }: any) {
  const [sprintId, setSprintId] = useState<number | null>(null)

  const metrics = data?.metrics
  const sprints: AnyRow[] = data?.sprints ?? []
  const activeSprint = useMemo(() => {
    if (sprintId) return sprints.find((s) => s.id === sprintId)
    return sprints.find((s) => s.status === 'ACTIVE') ?? sprints[sprints.length - 1]
  }, [sprints, sprintId])

  const board = useAsync(
    () => projectApi.board(activeSprint!.id),
    [activeSprint?.id],
    { enabled: !!activeSprint?.id },
  )

  // 瀑布式项目：后端明确返回 400，这是预期业务行为
  if (error instanceof ApiException && error.code === 400) {
    return (
      <Panel title="敏捷视图不可用">
        <EmptyState
          text="当前项目采用瀑布式管理，未启用敏捷视图"
          hint={
            <>
              本项目管理方式为「{method ?? 'WATERFALL'}」。敏捷看板仅对 <b className="text-slate-300">敏捷式（AGILE）</b>
              {' '}或 <b className="text-slate-300">混合式（HYBRID）</b> 项目开放。
              如需启用，请在项目设置中调整管理方式。
            </>
          }
        />
      </Panel>
    )
  }

  if (loading) return <Panel><Loading text="正在加载敏捷数据…" /></Panel>
  if (error) return <Panel><ErrorState error={error} onRetry={onRetry} /></Panel>
  if (!data) return <Panel><EmptyState text="暂无敏捷数据" /></Panel>

  const burndown = activeSprint?.burndown ?? []
  const burndownOption = lineOption({
    x: burndown.map((b: AnyRow) => String(b.date).slice(5)),
    series: [
      { name: '理想剩余', data: burndown.map((b: AnyRow) => b.ideal), color: '#64748B', area: false },
      { name: '实际剩余', data: burndown.map((b: AnyRow) => b.remaining), color: '#7B61FF', area: true },
    ],
  })

  const velocityOption = barOption({
    x: (metrics?.velocity_trend ?? []).map((v: AnyRow) => v.sprint),
    series: [{ name: '完成点数', data: (metrics?.velocity_trend ?? []).map((v: AnyRow) => v.points) }],
    showLegend: false,
  })

  return (
    <div className="space-y-5">
      {metrics && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
          <KpiCard label="Epic" value={metrics.epics?.length ?? 0} unit="个" />
          <KpiCard label="Feature" value={metrics.features?.length ?? 0} unit="个" />
          <KpiCard label="User Story" value={metrics.stories?.length ?? 0} unit="条" />
          <KpiCard label="Sprint" value={metrics.sprints?.length ?? 0} unit="个" />
          <KpiCard label="故事点总量" value={metrics.total_story_points ?? 0} />
          <KpiCard label="已完成点数" value={metrics.done_story_points ?? 0} tone="ok" />
          <KpiCard
            label="平均速率" value={fmt(metrics.velocity, 1)} unit="点/Sprint"
            tone="ai" hint={`待办健康度：${metrics.backlog_health ?? '—'}`}
          />
        </div>
      )}

      {metrics?.basis && (
        <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] px-4 py-2.5 text-xs text-brand-200">
          {metrics.basis}
        </div>
      )}

      {/* Sprint 选择 */}
      <Panel
        title="迭代看板"
        subtitle={activeSprint
          ? `${activeSprint.sprint_name} · ${activeSprint.start_date} → ${activeSprint.end_date}｜目标：${activeSprint.sprint_goal ?? '—'}`
          : '请选择迭代'}
        extra={
          <select
            className="rounded-lg border border-white/12 bg-white/[0.05] px-3 py-1.5 text-xs text-slate-100 outline-none"
            value={activeSprint?.id ?? ''}
            onChange={(e) => setSprintId(Number(e.target.value))}
          >
            {sprints.map((s) => (
              <option key={s.id} value={s.id}>
                {s.sprint_name}（{s.status === 'ACTIVE' ? '进行中' : s.status === 'COMPLETED' ? '已完成' : '未开始'}）
              </option>
            ))}
          </select>
        }
      >
        {board.loading ? (
          <Loading text="正在加载看板…" />
        ) : board.error ? (
          <ErrorState error={board.error} onRetry={board.reload} />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {(board.data?.columns ?? []).map((col: AnyRow) => (
              <div key={col.column} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
                <div className="mb-2.5 flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-200">{col.column_name}</span>
                  <span className="font-num text-[11px] text-slate-500">
                    {col.count} 项 · {col.story_points ?? 0} 点
                  </span>
                </div>
                <div className="space-y-2">
                  {(col.tasks ?? []).length === 0 ? (
                    <p className="py-6 text-center text-[11px] text-slate-600">暂无任务</p>
                  ) : (
                    (col.tasks as AnyRow[]).map((t) => (
                      <div
                        key={t.id}
                        className="rounded-lg border border-white/8 bg-[#101D2F]/70 p-2.5 transition-colors hover:border-brand-400/40"
                        title={t.task_title}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-num text-[10px] text-slate-500">{t.task_code}</span>
                          {t.is_blocked && <Tag tone="danger">阻塞</Tag>}
                        </div>
                        <p className="mt-1 text-xs leading-snug text-slate-200">{t.task_title}</p>
                        <div className="mt-2 flex items-center justify-between text-[10px]">
                          <span className="text-slate-500">{t.assignee_name ?? '未分配'}</span>
                          <span className="flex items-center gap-1.5">
                            {t.priority && (
                              <Tag tone={{ HIGH: 'warn', URGENT: 'danger', MEDIUM: 'info', LOW: 'muted' }[t.priority as string] ?? 'muted'}>
                                {t.priority}
                              </Tag>
                            )}
                            <span className="font-num text-slate-400">{t.story_point ?? 0} pt</span>
                          </span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel
          title="燃尽图"
          subtitle={activeSprint ? `${activeSprint.sprint_name}｜完成率 ${fmt(activeSprint.completed_rate, 1)}%` : ''}
        >
          <Chart height={280} option={burndownOption} empty={burndown.length === 0} />
        </Panel>
        <Panel title="迭代速率趋势" subtitle="各 Sprint 完成故事点">
          <Chart height={280} option={velocityOption} empty={(metrics?.velocity_trend ?? []).length === 0} />
        </Panel>
      </div>

      {/* Epic → Feature 树 */}
      <Panel title="Epic / Feature 分解" subtitle="按 Epic 归集的 Feature 及其故事点数">
        <div className="space-y-3">
          {(data.epics ?? []).map((e: AnyRow) => {
            const feats = (data.features ?? []).filter((f: AnyRow) => f.epic_id === e.id)
            return (
              <div key={e.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-num text-xs text-slate-500">{e.epic_code}</span>
                  <span className="font-medium text-slate-100">{e.epic_title}</span>
                  <Tag tone={e.status === 'DONE' ? 'ok' : e.status === 'IN_PROGRESS' ? 'info' : 'muted'}>
                    {{ DONE: '已完成', IN_PROGRESS: '进行中', TODO: '待办' }[e.status as string] ?? e.status}
                  </Tag>
                  {e.priority && <Tag tone="ai">{e.priority}</Tag>}
                  <span className="font-num text-[11px] text-slate-500">
                    {e.story_points ?? 0} 点 · {e.feature_count ?? feats.length} 个 Feature
                  </span>
                </div>
                {feats.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {feats.map((f: AnyRow) => (
                      <span
                        key={f.id}
                        title={`${f.feature_title}｜${f.story_count ?? 0} 条故事｜负责人 ${f.owner ?? '—'}`}
                        className={cx(
                          'rounded-md border px-2 py-1 text-[11px]',
                          f.status === 'DONE'
                            ? 'border-state-ok/30 bg-state-ok/10 text-state-ok'
                            : 'border-white/10 bg-white/[0.04] text-slate-300',
                        )}
                      >
                        {f.feature_code} {f.feature_title}
                        <span className="ml-1.5 font-num text-slate-500">{f.story_points ?? 0}pt</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          {(data.epics ?? []).length === 0 && <EmptyState text="暂无 Epic" />}
        </div>
      </Panel>

      <Panel title="用户故事" subtitle={`共 ${(data.stories ?? []).length} 条`}>
        <DataTable<AnyRow>
          columns={[
            { key: 'story_code', title: '编号', width: 106 },
            {
              key: 'story_title', title: '故事',
              render: (r) => (
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{r.story_title}</div>
                  <div className="truncate text-[11px] text-slate-500">
                    作为 {r.as_a ?? '—'}，我希望 {r.i_want ?? '—'}，以便 {r.so_that ?? '—'}
                  </div>
                </div>
              ),
            },
            { key: 'feature_title', title: '所属 Feature', render: (r) => r.feature_title ?? '—' },
            {
              key: 'story_point', title: '点数', align: 'right',
              render: (r) => <span className="font-num">{r.story_point ?? 0}</span>,
            },
            {
              key: 'priority', title: '优先级',
              render: (r) => (
                <Tag tone={{ HIGH: 'warn', URGENT: 'danger', MEDIUM: 'info', LOW: 'muted' }[r.priority as string] ?? 'muted'}>
                  {r.priority ?? '—'}
                </Tag>
              ),
            },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={{ DONE: 'ok', IN_PROGRESS: 'info', TODO: 'muted' }[r.status as string] ?? 'muted'}>
                  {{ DONE: '已完成', IN_PROGRESS: '进行中', TODO: '待办' }[r.status as string] ?? r.status}
                </Tag>
              ),
            },
            { key: 'assignee_name', title: '负责人', render: (r) => r.assignee_name ?? r.assignee ?? '未分配' },
          ]}
          rows={data.stories ?? []}
          rowKey={(r) => r.id}
          compact
        />
      </Panel>
    </div>
  )
}

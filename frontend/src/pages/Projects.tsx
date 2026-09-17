/**
 * 项目管理中心 —— 项目组合视图
 *
 * 全部指标来自 /projects/portfolio（后端聚合），前端不做任何硬编码；
 * 每个 KPI 展示后端下发的计算口径（basis）。
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { projectApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'
import type { EChartsOption } from 'echarts'

const METHOD_TONE: Record<string, string> = {
  WATERFALL: 'info',
  AGILE: 'ai',
  HYBRID: 'warn',
}

const RISK_TONE: Record<string, string> = {
  HIGH: 'danger',
  MEDIUM: 'warn',
  LOW: 'ok',
}

const fmt = (v: any, digits = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

/** 万元缩写，用于图表轴标签与卡片 */
const wan = (v: any) => {
  const n = Number(v) || 0
  return n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n.toFixed(0)}`
}

export default function Projects() {
  const { activeParkId } = useAuth()
  const navigate = useNavigate()

  const [method, setMethod] = useState('')
  const [risk, setRisk] = useState('')
  const [keyword, setKeyword] = useState('')

  const portfolio = useAsync(
    () => projectApi.portfolio(activeParkId ?? undefined),
    [activeParkId],
  )

  const data = portfolio.data
  const all: any[] = data?.items ?? []
  const summary = data?.summary ?? {}

  /** 客户端筛选仅用于交互，指标仍以后端 summary 为准 */
  const rows = useMemo(
    () =>
      all.filter((p) => {
        if (method && p.management_method !== method) return false
        if (risk && p.risk_level !== risk) return false
        if (keyword.trim()) {
          const k = keyword.trim().toLowerCase()
          return (
            String(p.project_name ?? '').toLowerCase().includes(k) ||
            String(p.project_code ?? '').toLowerCase().includes(k)
          )
        }
        return true
      }),
    [all, method, risk, keyword],
  )

  const basis: string = data?.basis ?? ''

  /* ---------------------------------------------------------- 散点图（风险矩阵） */
  const scatterOption = useMemo<EChartsOption>(() => {
    const pts: any[] = data?.scatter ?? []
    const groups = new Map<string, any[]>()
    for (const p of pts) {
      const k = p.risk_level ?? 'UNKNOWN'
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k)!.push(p)
    }
    const color: Record<string, string> = { HIGH: '#EF4444', MEDIUM: '#FACC15', LOW: '#22C55E' }
    const name: Record<string, string> = { HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' }
    return {
      legend: { top: 0, right: 0 },
      grid: { left: 8, right: 18, top: 34, bottom: 24, containLabel: true },
      tooltip: {
        trigger: 'item',
        formatter: (p: any) =>
          `${p.data[3]}<br/>计划进度 ${p.data[0]}%<br/>实际进度 ${p.data[1]}%<br/>预算 ${wan(p.data[2])}`,
      },
      xAxis: {
        type: 'value',
        name: '计划进度(%)',
        max: 100,
        nameTextStyle: { color: '#64748B', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        name: '实际进度(%)',
        max: 100,
        nameTextStyle: { color: '#64748B', fontSize: 11 },
      },
      series: [...groups.entries()].map(([k, arr]) => ({
        name: name[k] ?? k,
        type: 'scatter' as const,
        symbolSize: (v: any) => Math.max(9, Math.min(34, Math.sqrt(Number(v[2]) || 0) / 62)),
        itemStyle: { color: color[k] ?? '#2F80ED', opacity: 0.78 },
        data: arr.map((p) => [p.x, p.y, p.size, `${p.project_name}（${p.project_code}）`]),
      })),
    }
  }, [data])

  const methodOption = useMemo(
    () =>
      pieOption({
        data: (data?.by_method ?? []).map((d: any) => ({ name: d.name, value: d.count })),
        centerLabel: { title: '项目总数', value: summary.project_count ?? 0 },
      }),
    [data, summary],
  )

  const parkOption = useMemo(
    () =>
      barOption({
        x: (data?.by_park ?? []).map((d: any) => d.name),
        series: [
          { name: '预算(元)', data: (data?.by_park ?? []).map((d: any) => d.budget) },
          { name: '实际(元)', data: (data?.by_park ?? []).map((d: any) => d.actual) },
        ],
      }),
    [data],
  )

  return (
    <div className="space-y-5">
      <PageHeader
        title="项目管理中心"
        desc="项目组合视图：进度偏差、成本执行、风险分布与关键路径，全部由后端聚合计算。"
        demo
        extra={
          <Btn variant="ghost" onClick={portfolio.reload}>刷新数据</Btn>
        }
      />

      {basis && (
        <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] px-4 py-2.5 text-xs text-brand-200">
          <span className="font-medium">指标口径：</span>
          {basis}
        </div>
      )}

      {/* ------------------------------------------------------------ KPI */}
      {portfolio.loading ? (
        <Panel><Loading text="正在聚合项目组合…" /></Panel>
      ) : portfolio.error ? (
        <Panel><ErrorState error={portfolio.error} onRetry={portfolio.reload} /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
          <KpiCard label="项目总数" value={summary.project_count ?? 0} unit="个" />
          <KpiCard label="进行中" value={summary.in_progress ?? 0} unit="个" tone="brand" />
          <KpiCard
            label="延期项目" value={summary.delayed ?? 0} unit="个"
            tone={Number(summary.delayed) > 0 ? 'warn' : 'ok'}
          />
          <KpiCard
            label="高风险项目" value={summary.high_risk ?? 0} unit="个"
            tone={Number(summary.high_risk) > 0 ? 'risk' : 'ok'}
          />
          <KpiCard label="总预算" value={wan(summary.total_budget)} unit="元" hint="跨园区汇总" />
          <KpiCard label="已发生成本" value={wan(summary.total_actual)} unit="元" />
          <KpiCard
            label="预算执行率" value={fmt(summary.budget_execution_rate, 1)} unit="%"
            tone="ai" hint="实际成本 ÷ 批准预算"
          />
        </div>
      )}

      {/* ------------------------------------------------------- 图表区 */}
      {data && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <Panel
              title="进度偏差矩阵"
              subtitle="横轴计划进度 / 纵轴实际进度 / 气泡大小代表预算；落在对角线下方即为进度滞后"
            >
              {(data.scatter ?? []).length === 0 ? (
                <EmptyState text="暂无可绘制的项目" hint="需要项目同时具备计划进度与实际进度。" />
              ) : (
                <Chart height={330} option={scatterOption} />
              )}
            </Panel>
          </div>
          <Panel title="管理方式分布" subtitle="瀑布式 / 敏捷 / 混合">
            <Chart
              height={330}
              option={methodOption}
              empty={(data.by_method ?? []).length === 0}
            />
          </Panel>
        </div>
      )}

      {data && (data.by_park ?? []).length > 0 && (
        <Panel title="各园区预算执行对比" subtitle="预算与已发生成本并列（单位：元）">
          <Chart height={260} option={parkOption} />
        </Panel>
      )}

      {/* ------------------------------------------------------- 项目列表 */}
      <Panel
        title="项目清单"
        subtitle={`当前显示 ${rows.length} / ${all.length} 个项目`}
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="搜索">
            <input
              className={inputCls}
              placeholder="项目名称或编号"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </Field>
          <Field label="管理方式">
            <select className={inputCls} value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="">全部</option>
              {(data?.by_method ?? []).map((m: any) => (
                <option key={m.key} value={m.key}>{m.name}</option>
              ))}
            </select>
          </Field>
          <Field label="风险等级">
            <select className={inputCls} value={risk} onChange={(e) => setRisk(e.target.value)}>
              <option value="">全部</option>
              {(data?.by_risk ?? []).map((m: any) => (
                <option key={m.key} value={m.key}>{m.name}</option>
              ))}
            </select>
          </Field>
          {(method || risk || keyword) && (
            <Btn variant="ghost" onClick={() => { setMethod(''); setRisk(''); setKeyword('') }}>
              清空筛选
            </Btn>
          )}
        </div>

        <DataTable
          columns={[
            {
              key: 'project_name', title: '项目',
              render: (r) => (
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{r.project_name}</div>
                  <div className="font-num text-[11px] text-slate-500">
                    {r.project_code} · {r.department ?? '—'}
                  </div>
                </div>
              ),
            },
            {
              key: 'management_method', title: '管理方式',
              render: (r) => (
                <Tag tone={METHOD_TONE[r.management_method] ?? 'muted'}>
                  {r.management_method_name ?? r.management_method}
                </Tag>
              ),
            },
            {
              key: 'status', title: '状态',
              render: (r) => <span className="text-xs">{r.status_name ?? r.status}</span>,
            },
            {
              key: 'progress', title: '进度', width: 168,
              render: (r) => (
                <div className="space-y-1">
                  <ProgressBar
                    value={Number(r.progress) || 0}
                    tone={Number(r.progress_variance) < -10 ? 'danger' : 'brand'}
                  />
                  <div className="flex justify-between font-num text-[10px] text-slate-500">
                    <span>实际 {fmt(r.progress, 1)}%</span>
                    <span>计划 {fmt(r.planned_progress, 0)}%</span>
                  </div>
                </div>
              ),
            },
            {
              key: 'progress_variance', title: '偏差', align: 'right',
              render: (r) => {
                const v = Number(r.progress_variance) || 0
                return (
                  <span className={v < -5 ? 'text-state-danger' : v < 0 ? 'text-state-warn' : 'text-state-ok'}>
                    {v > 0 ? '+' : ''}{v.toFixed(1)}%
                  </span>
                )
              },
            },
            {
              key: 'execution_rate', title: '预算执行', align: 'right',
              render: (r) => `${fmt(r.execution_rate, 1)}%`,
            },
            {
              key: 'risk_level', title: '风险',
              render: (r) => (
                <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>
                  {r.risk_level_name ?? r.risk_level ?? '—'}
                </Tag>
              ),
            },
            {
              key: 'milestone_rate', title: '里程碑', align: 'right',
              render: (r) => `${r.milestone_done ?? 0}/${r.milestone_total ?? 0}`,
            },
            {
              key: 'delay_days', title: '延期天数', align: 'right',
              render: (r) => {
                const d = Number(r.delay_days) || 0
                return d > 0
                  ? <span className="text-state-danger">{d} 天</span>
                  : <span className="text-slate-600">—</span>
              },
            },
            {
              key: 'ops', title: '操作',
              render: (r) => (
                <Link
                  to={`/projects/${r.id}`}
                  className="text-xs text-brand-300 hover:text-brand-200 hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  查看详情
                </Link>
              ),
            },
          ]}
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => navigate(`/projects/${r.id}`)}
          compact
          empty="没有匹配的项目"
        />
      </Panel>
    </div>
  )
}

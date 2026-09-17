/**
 * 日志审计 —— 全平台操作留痕
 *
 * 设计要点：
 *  - 每次写操作都记录 before_value / after_value，可还原「谁在何时把什么改成了什么」，
 *    本页提供变更前后对照视图。
 *  - 统计口径（模块/动作/来源/结果分布、近 7 天趋势）全部来自 /audit/stats，
 *    前端只做渲染。
 *  - 来源/结果的中文标签由 /audit/meta/dict 下发，前端不硬编码字典。
 */
import { useState } from 'react'
import { auditApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import {
  EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, Tag, Btn, inputCls,
} from '@/components/ui'
import { Chart, barOption, lineOption } from '@/components/Charts'
import {
  Activity, Bot, RefreshCw, ShieldAlert, X,
} from 'lucide-react'

type AnyRow = Record<string, any>

const SOURCE_TONE: Record<string, string> = {
  WEB: 'info', USER: 'brand', AI: 'ai', SYSTEM: 'muted', API: 'muted',
}

const fmtTime = (s?: string | null) => (s ? String(s).replace('T', ' ').slice(0, 19) : '—')

/** 变更值可能是对象/数组/字符串，统一以可读形式渲染 */
const pretty = (v: any): string => {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

export default function Audit() {
  const [moduleFilter, setModuleFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [resultFilter, setResultFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<AnyRow | null>(null)
  const pageSize = 20

  const dict = useAsync(() => auditApi.dict(), [])
  const stats = useAsync(() => auditApi.stats(), [])
  const list = useAsync(
    () =>
      auditApi.list({
        page,
        page_size: pageSize,
        module: moduleFilter || undefined,
        action: actionFilter || undefined,
        result: resultFilter || undefined,
        keyword: keyword || undefined,
      }),
    [page, moduleFilter, actionFilter, resultFilter, keyword],
  )

  const modules: AnyRow[] = dict.data?.modules ?? []
  const actions: AnyRow[] = dict.data?.actions ?? []
  const sources: AnyRow[] = dict.data?.sources ?? []
  const results: AnyRow[] = dict.data?.results ?? []
  const sourceLabel = (k?: string) => sources.find((x) => x.key === k)?.label ?? k ?? '—'
  const resultLabel = (k?: string) => results.find((x) => x.key === k)?.label ?? k ?? '—'

  const rows: AnyRow[] = list.data?.items ?? []
  const s: AnyRow = stats.data ?? {}

  const trendOption = lineOption({
    x: (s.trend_7d ?? []).map((d: AnyRow) => String(d.date).slice(5)),
    series: [{ name: '操作次数', data: (s.trend_7d ?? []).map((d: AnyRow) => Number(d.count) || 0) }],
    area: true,
    showLegend: false,
  })

  const moduleOption = barOption({
    x: (s.by_module ?? []).map((m: AnyRow) => m.label ?? m.key),
    series: [{ name: '操作次数', data: (s.by_module ?? []).map((m: AnyRow) => Number(m.count) || 0) }],
    horizontal: true,
    showLegend: false,
  })

  const actionOption = barOption({
    x: (s.by_action ?? []).map((a: AnyRow) => a.label ?? a.key),
    series: [{ name: '操作次数', data: (s.by_action ?? []).map((a: AnyRow) => Number(a.count) || 0) }],
    horizontal: true,
    showLegend: false,
  })

  const refresh = () => { list.reload(); stats.reload() }

  const resetFilter = () => {
    setModuleFilter(''); setActionFilter(''); setResultFilter(''); setKeyword(''); setPage(1)
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="日志审计"
        desc="记录每一次业务写操作：操作人、模块、动作、变更前后值、来源与结果，支持按资源追溯。"
        demo
        extra={<Btn variant="ghost" onClick={refresh}><RefreshCw size={13} /> 刷新</Btn>}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="日志总数" value={s.total ?? 0} unit="条" hint="当前权限范围内" />
        <KpiCard
          label="高风险操作" value={s.risk_operations ?? 0} unit="次" tone="risk"
          hint="DELETE 或执行失败的操作"
        />
        <KpiCard label="AI 调用" value={s.ai_calls ?? 0} unit="次" tone="ai" hint="模块 = ai" />
        <KpiCard
          label="近 7 天操作" value={(s.trend_7d ?? []).reduce((a: number, d: AnyRow) => a + (Number(d.count) || 0), 0)}
          unit="次" tone="brand"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Panel title="近 7 天操作趋势" subtitle="按日统计">
          <Chart height={250} option={trendOption} empty={!(s.trend_7d ?? []).length} />
        </Panel>
        <Panel title="模块分布" subtitle="按业务模块统计">
          <Chart
            height={Math.max(220, (s.by_module ?? []).length * 24)}
            option={moduleOption}
            empty={!(s.by_module ?? []).length}
          />
        </Panel>
        <Panel title="动作分布" subtitle="按操作类型统计">
          <Chart
            height={Math.max(220, (s.by_action ?? []).length * 26)}
            option={actionOption}
            empty={!(s.by_action ?? []).length}
          />
        </Panel>
      </div>

      {/* 筛选 */}
      <Panel title="日志检索" subtitle="模块 / 动作 / 结果 / 关键词">
        <div className="flex flex-wrap gap-3">
          <select
            className={`${inputCls} max-w-[190px]`}
            value={moduleFilter}
            onChange={(e) => { setModuleFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部模块</option>
            {modules.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
          <select
            className={`${inputCls} max-w-[160px]`}
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部动作</option>
            {actions.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
          </select>
          <select
            className={`${inputCls} max-w-[140px]`}
            value={resultFilter}
            onChange={(e) => { setResultFilter(e.target.value); setPage(1) }}
          >
            <option value="">全部结果</option>
            {results.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
          <input
            className={`${inputCls} max-w-[260px]`}
            placeholder="搜索日志编号 / 对象名称 / 变更摘要"
            value={keyword}
            onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
          />
          <Btn variant="ghost" onClick={resetFilter}>重置</Btn>
        </div>
      </Panel>

      {/* 列表 */}
      {list.loading ? (
        <Panel><Loading text="加载审计日志…" /></Panel>
      ) : list.error ? (
        <Panel><ErrorState error={list.error} onRetry={list.reload} /></Panel>
      ) : rows.length === 0 ? (
        <Panel><EmptyState text="没有符合条件的日志记录" hint="可放宽筛选条件后重试。" /></Panel>
      ) : (
        <Panel
          title="操作日志"
          subtitle={`共 ${list.data?.total ?? 0} 条 · 点击行查看变更前后对照`}
          padded={false}
        >
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-white/8">
                  {['日志编号', '时间', '操作人', '模块', '动作', '对象', '变更摘要', '来源', '结果'].map((h, i) => (
                    <th
                      key={h}
                      className={`whitespace-nowrap px-3.5 py-2.5 text-xs font-medium text-slate-400 ${
                        i === 0 ? 'text-left' : 'text-left'
                      }`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setSelected(r)}
                    className="cursor-pointer border-b border-white/5 transition-colors last:border-0 hover:bg-brand-500/[0.07]"
                  >
                    <td className="px-3.5 py-2 font-num text-[11px] text-slate-400">{r.log_code}</td>
                    <td className="whitespace-nowrap px-3.5 py-2 font-num text-[11px] text-slate-400">
                      {fmtTime(r.created_at)}
                    </td>
                    <td className="px-3.5 py-2 text-slate-200">
                      {r.real_name ?? r.username ?? '—'}
                    </td>
                    <td className="px-3.5 py-2 text-slate-300">{r.module_label ?? r.module ?? '—'}</td>
                    <td className="px-3.5 py-2">
                      <Tag tone="muted">{r.action_label ?? r.action ?? '—'}</Tag>
                    </td>
                    <td className="max-w-[200px] truncate px-3.5 py-2 text-slate-300" title={r.object_name ?? ''}>
                      {r.object_name ?? r.object_type ?? '—'}
                    </td>
                    <td className="max-w-[300px] truncate px-3.5 py-2 text-slate-400" title={r.change_summary ?? ''}>
                      {r.change_summary ?? '—'}
                    </td>
                    <td className="px-3.5 py-2">
                      <Tag tone={SOURCE_TONE[r.source] ?? 'muted'}>{sourceLabel(r.source)}</Tag>
                    </td>
                    <td className="px-3.5 py-2">
                      <Tag tone={r.result === 'SUCCESS' ? 'ok' : 'danger'}>
                        {resultLabel(r.result)}
                      </Tag>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {Number(list.data?.pages) > 1 && (
            <div className="flex items-center justify-between border-t border-white/8 px-5 py-3">
              <span className="text-xs text-slate-500">
                第 {list.data?.page ?? page} / {list.data?.pages} 页
              </span>
              <div className="flex gap-2">
                <Btn size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
                <Btn
                  size="sm" disabled={page >= Number(list.data?.pages ?? 1)}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </Btn>
              </div>
            </div>
          )}
        </Panel>
      )}

      {/* 详情 */}
      {selected && (
        <Panel
          title={`日志详情 · ${selected.log_code}`}
          subtitle={`${selected.real_name ?? selected.username ?? ''} · ${fmtTime(selected.created_at)}`}
          extra={
            <Btn size="sm" variant="ghost" onClick={() => setSelected(null)}>
              <X size={12} /> 关闭
            </Btn>
          }
        >
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {([
              ['操作人', selected.real_name ?? selected.username],
              ['模块', selected.module_label ?? selected.module],
              ['动作', selected.action_label ?? selected.action],
              ['来源', sourceLabel(selected.source)],
              ['结果', resultLabel(selected.result)],
              ['对象类型', selected.object_type],
              ['对象 ID', selected.object_id],
              ['IP 地址', selected.ip_address],
            ] as [string, any][]).map(([k, v]) => (
              <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                <div className="text-[11px] text-slate-500">{k}</div>
                <div className="mt-0.5 font-num text-[12px] text-slate-200">{v ?? '—'}</div>
              </div>
            ))}
          </div>

          {selected.change_summary && (
            <div className="mt-3 rounded-lg border border-white/8 bg-white/[0.03] p-3">
              <div className="text-[11px] text-slate-500">变更摘要</div>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{selected.change_summary}</p>
            </div>
          )}

          {selected.approval_info && (
            <div className="mt-2 rounded-lg border border-white/8 bg-white/[0.03] p-3">
              <div className="text-[11px] text-slate-500">审批信息</div>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{selected.approval_info}</p>
            </div>
          )}

          {(selected.before_value != null || selected.after_value != null) && (
            <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-state-danger/22 bg-state-danger/[0.05] p-3">
                <div className="mb-1 flex items-center gap-1.5 text-[11px] text-state-danger">
                  <ShieldAlert size={11} /> 变更前
                </div>
                <pre className="max-h-[240px] overflow-auto whitespace-pre-wrap break-all font-num text-[11px] leading-relaxed text-slate-300">
                  {pretty(selected.before_value)}
                </pre>
              </div>
              <div className="rounded-lg border border-state-ok/22 bg-state-ok/[0.05] p-3">
                <div className="mb-1 flex items-center gap-1.5 text-[11px] text-state-ok">
                  <Activity size={11} /> 变更后
                </div>
                <pre className="max-h-[240px] overflow-auto whitespace-pre-wrap break-all font-num text-[11px] leading-relaxed text-slate-300">
                  {pretty(selected.after_value)}
                </pre>
              </div>
            </div>
          )}

          <div className="mt-3 flex items-start gap-2 text-[11px] leading-relaxed text-slate-500">
            <Bot size={11} className="mt-0.5 shrink-0" />
            <span>
              来源为「AI」的记录表示该动作由 AI 建议触发，但仍由人工确认执行；
              审计日志本身不可修改与删除。
            </span>
          </div>
          {selected.user_agent && (
            <div className="mt-1 truncate text-[11px] text-slate-600">{selected.user_agent}</div>
          )}
        </Panel>
      )}
    </div>
  )
}

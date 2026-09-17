/**
 * 数据驾驶舱
 *
 * 所有指标与图表均由 /dashboard/summary 动态返回，前端不做任何指标硬编码。
 * 每个 KPI 都展示后端给出的 `basis`（计算口径）与 `data_status`，
 * 满足「可解释、可追踪、可回溯」的要求 —— 用户能看清数字是怎么算出来的。
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  Building2,
  CircleDollarSign,
  FileSignature,
  Handshake,
  Info,
  Layers,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
} from 'lucide-react'
import { dashboardApi, agentApi } from '@/api/modules'
import { useAuth } from '@/context/AuthContext'
import { useAsync, pushToast } from '@/hooks/useAsync'
import {
  Btn,
  DemoBadge,
  EmptyState,
  ErrorState,
  KpiCard,
  Loading,
  PageHeader,
  Panel,
  ProgressBar,
  StatLine,
  Tag,
  cx,
} from '@/components/ui'
import { Chart, barOption, lineOption, pieOption, funnelOption, rankBarOption, RISE, FALL } from '@/components/Charts'

/** KPI 图标按 key 映射（纯展示，不含业务数据） */
const KPI_ICON: Record<string, JSX.Element> = {
  park_count: <Building2 size={15} />,
  enterprise_count: <Users size={15} />,
  settle_rate: <TrendingUp size={15} />,
  occupancy_rate: <Layers size={15} />,
  available_area: <Building2 size={15} />,
  lead_count: <Handshake size={15} />,
  conversion_rate: <Activity size={15} />,
  contract_expiring: <FileSignature size={15} />,
  collection_rate: <CircleDollarSign size={15} />,
  project_total: <Layers size={15} />,
  safety_score: <ShieldCheck size={15} />,
}

/** data_status 到视觉色调的映射 */
function statusTone(s?: string) {
  if (!s) return 'muted'
  if (s.includes('异常') || s.includes('风险')) return 'danger'
  if (s.includes('提醒') || s.includes('预警')) return 'warn'
  if (s.includes('正常')) return 'ok'
  return 'muted'
}

export default function Dashboard() {
  const { activeParkId, user } = useAuth()
  const nav = useNavigate()
  const [detail, setDetail] = useState<string | null>(null)

  const { data, loading, error, reload } = useAsync(
    () => dashboardApi.summary(activeParkId),
    [activeParkId],
  )
  const alerts = useAsync(() => dashboardApi.alerts(activeParkId), [activeParkId])
  const insight = useAsync(() => agentApi.dailyInsight(activeParkId), [activeParkId])

  const kpis = useMemo(() => (data?.kpis ?? []) as any[], [data])
  const charts = (data?.charts ?? {}) as Record<string, any[]>
  const summary = (data?.summary ?? {}) as Record<string, any>

  if (loading && !data) return <Loading text="正在加载驾驶舱数据…" />
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (!data) return <EmptyState text="暂无驾驶舱数据" />

  const scope = data.scope ?? {}
  const notes = (data.data_status_notes ?? []) as any[]

  return (
    <div className="space-y-5">
      <PageHeader
        title="数据驾驶舱"
        demo
        desc={
          <>
            当前视图：
            <span className="text-slate-300">
              {scope.park_name ?? '全部园区'}
            </span>
            {scope.data_scope ? ` · 数据范围 ${scope.data_scope}` : ''}
            {data.updated_at ? ` · 数据时间 ${String(data.updated_at).replace('T', ' ')}` : ''}
          </>
        }
        extra={
          <Btn onClick={reload} loading={loading}>
            <RefreshCw size={13} /> 刷新数据
          </Btn>
        }
      />

      {/* 数据质量提示：后端明确告知哪些指标数据不完整 */}
      {notes.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-card border border-state-warn/28 bg-state-warn/[0.07] px-4 py-3">
          <Info size={15} className="mt-0.5 shrink-0 text-state-warn" />
          <div className="min-w-0 text-[12px] leading-relaxed text-slate-300">
            <span className="font-medium text-state-warn">数据完整性提示：</span>
            {notes.map((n, i) => (
              <span key={i}>
                {i > 0 && '；'}
                {n.label ?? n.key}
                {n.note ? ` —— ${n.note}` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* KPI 网格 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
        {kpis.map((k) => {
          const tone =
            k.key === 'safety_score'
              ? 'ok'
              : k.data_status && k.data_status !== '正常'
                ? 'warn'
                : 'brand'
          return (
            <button
              key={k.key}
              onClick={() => setDetail(k.key)}
              className="text-left"
              title="点击查看计算口径"
            >
              <KpiCard
                label={k.label}
                value={k.value ?? '—'}
                unit={k.unit}
                delta={k.mom}
                deltaLabel="环比"
                icon={KPI_ICON[k.key] ?? <Activity size={15} />}
                tone={tone}
                hint={
                  k.target
                    ? `目标 ${k.target}${k.unit ?? ''}`
                    : undefined
                }
              />
            </button>
          )
        })}
      </div>

      {/* 指标口径抽屉 */}
      {detail && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-20 backdrop-blur-sm"
          onClick={() => setDetail(null)}
        >
          <div
            className="w-full max-w-lg animate-fade-up rounded-panel border border-white/12 bg-nav-panel/97 p-5 shadow-glass backdrop-blur-xl"
            onClick={(e) => e.stopPropagation()}
          >
            {(() => {
              const k = kpis.find((x) => x.key === detail)
              if (!k) return null
              return (
                <>
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="text-base font-semibold text-slate-50">{k.label}</h3>
                      <div className="mt-1.5 flex items-baseline gap-1.5">
                        <span className="font-num text-kpi-sm font-semibold text-brand-400">
                          {k.value ?? '—'}
                        </span>
                        <span className="text-xs text-slate-400">{k.unit}</span>
                      </div>
                    </div>
                    <Tag tone={statusTone(k.data_status)}>{k.data_status ?? '正常'}</Tag>
                  </div>

                  <div className="mt-4 space-y-3 text-[13px]">
                    <div>
                      <p className="mb-1 text-xs font-medium text-slate-400">计算口径</p>
                      <p className="leading-relaxed text-slate-300">{k.basis ?? '未提供口径说明'}</p>
                    </div>
                    <StatLine
                      items={[
                        { label: '目标值', value: k.target != null ? `${k.target}${k.unit ?? ''}` : '未设定' },
                        { label: '趋势', value: k.trend ?? '—' },
                        { label: '环比', value: k.mom != null ? `${k.mom}%` : '—' },
                        { label: '同比', value: k.yoy != null ? `${k.yoy}%` : '—' },
                      ]}
                    />
                    {k.link && (
                      <Btn size="sm" onClick={() => { setDetail(null); nav(k.link) }}>
                        前往相关模块查看明细
                      </Btn>
                    )}
                  </div>
                </>
              )
            })()}
          </div>
        </div>
      )}

      {/* 图表区 */}
      <div className="grid gap-4 xl:grid-cols-3">
        {/* 招商漏斗 */}
        <Panel
          title="招商转化漏斗"
          subtitle="各阶段线索到达数量"
          icon={<Handshake size={15} />}
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/leasing')}>查看明细</Btn>}
        >
          <Chart
            height={272}
            empty={!charts.funnel?.length}
            option={funnelOption({
              data: (charts.funnel ?? []).map((f: any) => ({
                name: f.stage_name ?? f.stage,
                value: f.reached ?? f.count,
              })),
            })}
          />
        </Panel>

        {/* 线索与签约趋势 */}
        <Panel
          title="线索获取与签约趋势"
          subtitle="按月统计线索量、签约量与转化率"
          icon={<TrendingUp size={15} />}
        >
          <Chart
            height={272}
            empty={!charts.lead_trend?.length}
            option={lineOption({
              x: (charts.lead_trend ?? []).map((d: any) => d.month),
              series: [
                { name: '新增线索', data: (charts.lead_trend ?? []).map((d: any) => d.leads), color: '#2F80ED' },
                { name: '签约', data: (charts.lead_trend ?? []).map((d: any) => d.signs), color: '#22C55E' },
              ],
              area: true,
            })}
          />
        </Panel>

        {/* 企业经营状态 */}
        <Panel
          title="企业构成"
          subtitle="按经营状态分布"
          icon={<Users size={15} />}
        >
          <Chart
            height={272}
            empty={!charts.status_dist?.length}
            option={pieOption({
              data: (charts.status_dist ?? []).map((d: any) => ({ name: d.name, value: d.value })),
              centerLabel: {
                title: '企业总数',
                value: summary.enterprise_settled ?? (charts.status_dist ?? []).reduce((s: number, x: any) => s + (x.value ?? 0), 0),
              },
            })}
          />
        </Panel>

        {/* 楼栋出租率对比 */}
        <Panel
          title="楼栋出租率对比"
          subtitle="已租面积 / 可租面积"
          icon={<Building2 size={15} />}
          className="xl:col-span-2"
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/twin')}>数字孪生视图</Btn>}
        >
          <Chart
            height={260}
            empty={!charts.space_by_building?.length}
            option={barOption({
              x: (charts.space_by_building ?? []).map((b: any) => b.building_name),
              series: [
                {
                  name: '出租率(%)',
                  data: (charts.space_by_building ?? []).map((b: any) => b.occupancy_rate),
                  color: '#2F80ED',
                },
              ],
              showLegend: false,
            })}
          />
        </Panel>

        {/* 欠费账龄 */}
        <Panel
          title="欠费账龄结构"
          subtitle="逾期账龄分档金额"
          icon={<CircleDollarSign size={15} />}
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/finance')}>财务明细</Btn>}
        >
          <Chart
            height={260}
            empty={
              !charts.arrears_age?.length ||
              (charts.arrears_age ?? []).every((a: any) => !a.value)
            }
            option={barOption({
              x: (charts.arrears_age ?? []).map((a: any) => a.name),
              series: [
                {
                  name: '金额',
                  data: (charts.arrears_age ?? []).map((a: any) => a.value),
                  color: '#F97316',
                },
              ],
              showLegend: false,
            })}
          />
        </Panel>

        {/* 财务趋势 */}
        <Panel
          title="应收与实收趋势"
          subtitle="按月统计应收、实收与欠费"
          icon={<CircleDollarSign size={15} />}
          className="xl:col-span-2"
        >
          <Chart
            height={252}
            empty={!charts.finance_trend?.length}
            option={lineOption({
              x: (charts.finance_trend ?? []).map((d: any) => d.month),
              series: [
                { name: '应收', data: (charts.finance_trend ?? []).map((d: any) => d.receivable), color: '#2F80ED' },
                { name: '实收', data: (charts.finance_trend ?? []).map((d: any) => d.received), color: '#22C55E' },
                { name: '欠费', data: (charts.finance_trend ?? []).map((d: any) => d.arrears), color: '#EF4444' },
              ],
            })}
          />
        </Panel>

        {/* 项目风险分布 */}
        <Panel
          title="项目风险分布"
          subtitle="在建项目风险等级"
          icon={<AlertTriangle size={15} />}
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/projects')}>项目中心</Btn>}
        >
          <div className="space-y-3">
            <Chart
              height={180}
              empty={!charts.project_risk_dist?.length}
              option={pieOption({
                data: (charts.project_risk_dist ?? []).map((d: any) => ({
                  name: d.name,
                  value: d.value,
                  color:
                    d.key === 'HIGH' || d.key === 'CRITICAL'
                      ? '#EF4444'
                      : d.key === 'MEDIUM'
                        ? '#FACC15'
                        : '#22C55E',
                })),
                donut: false,
              })}
            />
            <StatLine
              items={[
                { label: '项目总数', value: summary.project_total ?? '—' },
                { label: '瀑布', value: summary.waterfall_count ?? 0 },
                { label: '敏捷', value: summary.agile_count ?? 0 },
                { label: '混合', value: summary.hybrid_count ?? 0 },
              ]}
            />
          </div>
        </Panel>

        {/* 能耗趋势 */}
        <Panel
          title="能耗与碳排趋势"
          subtitle="按月统计各类能源消耗与碳排"
          icon={<Activity size={15} />}
          className="xl:col-span-2"
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/energy')}>能源管理</Btn>}
        >
          <Chart
            height={248}
            empty={!charts.energy_trend?.length}
            option={lineOption({
              x: (charts.energy_trend ?? []).map((d: any) => d.month),
              series: [
                { name: '电力', data: (charts.energy_trend ?? []).map((d: any) => d.ELECTRICITY), color: '#2F80ED' },
                { name: '用水', data: (charts.energy_trend ?? []).map((d: any) => d.WATER), color: '#00D4FF' },
                { name: '燃气', data: (charts.energy_trend ?? []).map((d: any) => d.GAS), color: '#F97316' },
                { name: '光伏', data: (charts.energy_trend ?? []).map((d: any) => d.PV), color: '#22C55E' },
              ],
            })}
          />
        </Panel>

        {/* 安全状态 */}
        <Panel
          title="安全事件闭环"
          subtitle="按处理状态统计"
          icon={<ShieldCheck size={15} />}
          extra={<Btn size="sm" variant="ghost" onClick={() => nav('/safety')}>安全管理</Btn>}
        >
          <div className="space-y-4">
            <Chart
              height={168}
              empty={
                !charts.safety_status_dist?.length ||
                (charts.safety_status_dist ?? []).every((d: any) => !d.value)
              }
              option={pieOption({
                data: (charts.safety_status_dist ?? [])
                  .filter((d: any) => d.value > 0)
                  .map((d: any) => ({ name: d.name, value: d.value })),
                centerLabel: {
                  title: '安全指数',
                  value: summary.safety_score ?? '—',
                },
              })}
            />
            <StatLine
              items={[
                { label: '安全指数', value: summary.safety_score ?? '—' },
                { label: '状态', value: summary.safety_status ?? '—' },
                { label: '能耗异常', value: summary.energy_anomaly_count ?? 0 },
                { label: '待保养设备', value: summary.device_maintain_due ?? 0 },
              ]}
            />
          </div>
        </Panel>
      </div>

      {/* 告警 + AI 洞察 */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="实时告警"
          subtitle="需关注的异常与待办事项"
          icon={<AlertTriangle size={15} />}
          extra={
            alerts.data ? (
              <Tag tone="warn">{`${(alerts.data.items ?? alerts.data.alerts ?? []).length} 条`}</Tag>
            ) : null
          }
        >
          {alerts.loading ? (
            <Loading inline />
          ) : alerts.error ? (
            <ErrorState error={alerts.error} onRetry={alerts.reload} />
          ) : (
            (() => {
              const list = (alerts.data?.items ?? alerts.data?.alerts ?? []) as any[]
              if (list.length === 0) {
                return <EmptyState text="当前无告警" hint="系统运行正常" />
              }
              return (
                <div className="space-y-2">
                  {list.slice(0, 6).map((a, i) => (
                    <div
                      key={i}
                      className={cx(
                        'flex items-start gap-3 rounded-lg border px-3 py-2.5 transition',
                        a.severity === 'HIGH' || a.severity === 'CRITICAL' || a.level === 'danger'
                          ? 'border-state-danger/28 bg-state-danger/[0.07]'
                          : a.severity === 'MEDIUM' || a.level === 'warn'
                            ? 'border-state-warn/28 bg-state-warn/[0.07]'
                            : 'border-white/8 bg-white/[0.03]',
                      )}
                    >
                      <span
                        className={cx(
                          'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                          a.severity === 'HIGH' || a.severity === 'CRITICAL'
                            ? 'bg-state-danger'
                            : a.severity === 'MEDIUM'
                              ? 'bg-state-warn'
                              : 'bg-brand-400',
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] text-slate-200">{a.title ?? a.label}</p>
                        {a.description && (
                          <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                            {a.description}
                          </p>
                        )}
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          {a.module && <Tag>{a.module}</Tag>}
                          {a.count != null && <Tag tone="info">{`${a.count} 项`}</Tag>}
                        </div>
                      </div>
                      {a.link && (
                        <Btn size="sm" variant="ghost" onClick={() => nav(a.link)}>
                          处理
                        </Btn>
                      )}
                    </div>
                  ))}
                </div>
              )
            })()
          )}
        </Panel>

        <Panel
          title={
            <span className="flex items-center gap-2">
              AI 每日洞察
              <Tag tone="ai">
                <Sparkles size={10} /> 园智AI总管
              </Tag>
            </span>
          }
          subtitle="基于当前园区数据自动生成"
          icon={<Sparkles size={15} />}
        >
          {insight.loading ? (
            <Loading inline />
          ) : insight.error ? (
            <ErrorState error={insight.error} onRetry={insight.reload} />
          ) : (
            <div className="space-y-3">
              {/* 结论 */}
              <div className="rounded-lg border border-ai/25 bg-ai/[0.07] px-3.5 py-3">
                <p className="text-[11px] font-medium text-ai-light">结论</p>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-200">
                  {insight.data?.conclusion ?? insight.data?.summary ?? '暂无洞察结论'}
                </p>
              </div>

              {(() => {
                const d = insight.data ?? {}
                const signals = (d.signals ?? d.key_findings ?? []) as any[]
                const suggestions = (d.suggestions ?? d.actions ?? []) as any[]
                return (
                  <>
                    {signals.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-[11px] font-medium text-slate-400">关键信号</p>
                        <div className="space-y-1.5">
                          {signals.slice(0, 5).map((s, i) => (
                            <div key={i} className="flex items-start gap-2 text-[12px]">
                              <span
                                className={cx(
                                  'mt-1.5 h-1 w-1 shrink-0 rounded-full',
                                  s.level === 'danger'
                                    ? 'bg-state-danger'
                                    : s.level === 'warn'
                                      ? 'bg-state-warn'
                                      : 'bg-brand-400',
                                )}
                              />
                              <span className="leading-relaxed text-slate-300">
                                {typeof s === 'string' ? s : (s.text ?? s.conclusion ?? s.title)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {suggestions.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-[11px] font-medium text-slate-400">建议措施</p>
                        <div className="space-y-1.5">
                          {suggestions.slice(0, 4).map((s, i) => (
                            <div
                              key={i}
                              className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-[12px] leading-relaxed text-slate-300"
                            >
                              {typeof s === 'string'
                                ? s
                                : `${s.title ?? s.action ?? ''}${s.detail ? ` —— ${s.detail}` : ''}`}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {d.data_sufficient === false && (
                      <div className="flex items-start gap-2 rounded-lg border border-state-warn/28 bg-state-warn/[0.07] px-3 py-2 text-[11px] text-state-warn">
                        <Info size={13} className="mt-0.5 shrink-0" />
                        <span>
                          数据不足，AI 无法给出完整结论
                          {d.missing_data ? `（缺少：${Array.isArray(d.missing_data) ? d.missing_data.join('、') : d.missing_data}）` : ''}
                        </span>
                      </div>
                    )}

                    {signals.length === 0 && suggestions.length === 0 && !d.conclusion && !d.summary && (
                      <EmptyState text="暂无 AI 洞察" hint="系统需要更多数据才能生成洞察" />
                    )}
                  </>
                )
              })()}

              <Btn size="sm" variant="ai" onClick={() => nav('/ai')}>
                <Sparkles size={12} /> 进入 AI 对话深入分析
              </Btn>
            </div>
          )}
        </Panel>
      </div>

      {/* 项目与运维摘要 */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Panel title="项目管理摘要" subtitle="进度与里程碑">
          <div className="space-y-3">
            <StatLine
              items={[
                { label: '平均进度', value: `${summary.avg_project_progress ?? 0}%` },
              ]}
            />
            <ProgressBar value={summary.avg_project_progress ?? 0} showText />
            <StatLine
              items={[
                { label: '里程碑达成率', value: `${summary.milestone_completion_rate ?? 0}%` },
              ]}
            />
            <ProgressBar value={summary.milestone_completion_rate ?? 0} tone="ok" showText />
            <StatLine
              items={[
                { label: 'Sprint 完成率', value: `${summary.sprint_completion_rate ?? 0}%` },
              ]}
            />
            <ProgressBar value={summary.sprint_completion_rate ?? 0} tone="ai" showText />
          </div>
        </Panel>

        <Panel title="资产概况" subtitle="空间与楼栋">
          <div className="space-y-3">
            <StatLine
              items={[
                { label: '楼栋', value: `${summary.building_count ?? 0} 栋` },
                { label: '可租面积', value: `${((summary.total_rentable_area ?? 0) / 10000).toFixed(2)} 万㎡` },
              ]}
            />
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                <p className="text-[11px] text-slate-500">已租面积</p>
                <p className="mt-1 font-num text-lg text-brand-400">
                  {((summary.rented_area ?? 0) / 10000).toFixed(2)}
                  <span className="ml-0.5 text-[11px] text-slate-500">万㎡</span>
                </p>
              </div>
              <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                <p className="text-[11px] text-slate-500">空置面积</p>
                <p className="mt-1 font-num text-lg text-state-warn">
                  {((summary.vacant_area ?? 0) / 10000).toFixed(2)}
                  <span className="ml-0.5 text-[11px] text-slate-500">万㎡</span>
                </p>
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="经营概况" subtitle="企业、合同与收缴">
          <div className="space-y-3">
            <StatLine
              items={[
                { label: '入驻企业', value: `${summary.enterprise_settled ?? 0} 家` },
                { label: '风险企业', value: `${summary.enterprise_risk ?? 0} 家` },
              ]}
            />
            <StatLine
              items={[
                { label: '生效合同', value: `${summary.active_contracts ?? 0} 份` },
              ]}
            />
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[11px] text-slate-500">租金收缴率</span>
                <span className="font-num text-sm text-slate-200">
                  {summary.collection_rate ?? 0}%
                </span>
              </div>
              <ProgressBar
                value={summary.collection_rate ?? 0}
                tone={(summary.collection_rate ?? 0) >= 85 ? 'ok' : 'warn'}
              />
            </div>
          </div>
        </Panel>

        <Panel title="运维概况" subtitle="工单与安全">
          <div className="space-y-3">
            <StatLine
              items={[
                { label: '能耗异常', value: `${summary.energy_anomaly_count ?? 0} 处` },
                { label: '单位能耗', value: summary.unit_energy ?? '—' },
              ]}
            />
            <StatLine
              items={[
                { label: '待保养设备', value: `${summary.device_maintain_due ?? 0} 台` },
              ]}
            />
            <div className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-slate-500">安全指数</span>
                <span
                  className={cx(
                    'font-num text-base font-semibold',
                    (summary.safety_score ?? 0) >= 85
                      ? 'text-state-ok'
                      : (summary.safety_score ?? 0) >= 70
                        ? 'text-state-warn'
                        : 'text-state-danger',
                  )}
                >
                  {summary.safety_score ?? '—'}
                </span>
              </div>
              <p className="mt-0.5 text-[11px] text-slate-500">
                {summary.safety_status ?? '—'}
              </p>
            </div>
          </div>
        </Panel>
      </div>

      {/* 工单趋势 */}
      {charts.work_order_trend?.length > 0 && (
        <Panel title="工单趋势" subtitle="按月统计提交量、关闭量与超时量">
          <Chart
            height={220}
            option={barOption({
              x: charts.work_order_trend.map((d: any) => d.month),
              series: [
                { name: '提交', data: charts.work_order_trend.map((d: any) => d.total), color: '#2F80ED' },
                { name: '关闭', data: charts.work_order_trend.map((d: any) => d.closed), color: '#22C55E' },
                { name: '超时', data: charts.work_order_trend.map((d: any) => d.timeout), color: '#EF4444' },
              ],
            })}
          />
        </Panel>
      )}

      <p className="pb-2 text-center text-[11px] text-slate-600">
        <DemoBadge className="mr-1.5" />
        本平台运行于演示环境，全部业务数据由后端模拟生成，指标口径见各指标悬浮说明。
      </p>
    </div>
  )
}

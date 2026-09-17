/**
 * 能源管理 —— 用电/用水/用气/光伏 / 碳排 / 异常用能
 *
 * 「时段」与「峰谷」在模型未存字段，按记录小时由后端实时推导；
 * 碳排与单位面积能耗口径由后端下发（basis）。
 */
import { useMemo, useState } from 'react'
import { operationApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, lineOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const ENERGY_TYPE: Record<string, string> = {
  ELECTRICITY: '用电', WATER: '用水', GAS: '燃气', PV: '光伏发电', STEAM: '蒸汽',
}
const PEAK_TONE: Record<string, string> = { 尖峰: 'danger', 高峰: 'warn', 平段: 'info', 谷段: 'ok' }

export default function Energy() {
  const { activeParkId } = useAuth()
  const [energyType, setEnergyType] = useState('')
  const [buildingId, setBuildingId] = useState('')
  const [period, setPeriod] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const summary = useAsync(
    () => operationApi.energySummary({ park_id: activeParkId ?? undefined, days: 30 }),
    [activeParkId],
  )

  const records = useAsync(
    () => operationApi.energyRecords({
      park_id: activeParkId ?? undefined,
      energy_type: energyType || undefined,
      building_id: buildingId || undefined,
      period: period || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, energyType, buildingId, period, page],
  )

  const s = summary.data
  const t = s?.totals ?? {}
  const basis = s?.basis as Record<string, string> | undefined

  const trendOption = useMemo(() => {
    const trend: any[] = s?.trend ?? []
    return lineOption({
      x: trend.map((r) => String(r.month ?? '').slice(2)),
      series: [
        { name: '用电', data: trend.map((r) => r.ELECTRICITY), color: '#2F80ED' },
        { name: '用水', data: trend.map((r) => r.WATER), color: '#00D4FF' },
        { name: '燃气', data: trend.map((r) => r.GAS), color: '#FACC15' },
        { name: '光伏', data: trend.map((r) => r.PV), color: '#22C55E' },
      ],
      yName: '用量',
    })
  }, [s])

  const carbonOption = useMemo(() => {
    const trend: any[] = s?.trend ?? []
    return lineOption({
      x: trend.map((r) => String(r.month ?? '').slice(2)),
      series: [
        { name: '碳排放(kg)', data: trend.map((r) => r.carbon), color: '#7B61FF', area: true },
        { name: '能源成本(元)', data: trend.map((r) => r.cost), color: '#F97316' },
      ],
    })
  }, [s])

  const typeOption = useMemo(
    () =>
      pieOption({
        data: (s?.by_type ?? []).map((x: any) => ({
          name: ENERGY_TYPE[x.key ?? x.name] ?? (x.name ?? x.key),
          value: x.value ?? x.consumption ?? x.cost ?? x.count ?? 0,
        })),
        centerLabel: { title: '能源成本', value: `${((Number(t.cost) || 0) / 10000).toFixed(1)}万` },
      }),
    [s, t],
  )

  const buildingOption = useMemo(
    () =>
      barOption({
        x: (s?.by_building ?? []).map((x: any) => x.name ?? x.building_name ?? `#${x.building_id}`),
        series: [
          { name: '用电量', data: (s?.by_building ?? []).map((x: any) => x.ELECTRICITY ?? x.electricity ?? x.consumption ?? 0) },
          { name: '碳排(kg)', data: (s?.by_building ?? []).map((x: any) => x.carbon ?? 0) },
        ],
        horizontal: true,
      }),
    [s],
  )

  const rows: any[] = records.data?.items ?? []
  const total = records.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="space-y-5">
      <PageHeader
        title="能源管理"
        desc="能耗、碳排、峰谷时段与异常用能，均由后端基于能耗记录台账实时聚合。"
        demo
        extra={<Btn variant="ghost" onClick={() => { summary.reload(); records.reload() }}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {summary.loading ? (
        <Panel><Loading text="正在汇总能耗数据…" /></Panel>
      ) : summary.error ? (
        <Panel><ErrorState error={summary.error} onRetry={summary.reload} /></Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-6">
            <KpiCard label="本月用电" value={fmt(t.electricity_month, 0)} unit="kWh" />
            <KpiCard label="本月用水" value={fmt(t.water_month, 0)} unit="t" />
            <KpiCard
              label="碳排总量" value={fmt(t.carbon_ton, 2)} unit="吨"
              hint={basis?.carbon} tone="warn"
            />
            <KpiCard label="能源成本" value={`${((Number(t.cost) || 0) / 10000).toFixed(1)} 万`} unit="元" />
            <KpiCard
              label="单位面积能耗" value={fmt(t.unit_area_consumption, 2)} unit="kWh/㎡"
              hint={basis?.unit_area_consumption}
            />
            <KpiCard
              label="异常用能" value={t.anomaly_count ?? 0} unit="条"
              tone={Number(t.anomaly_count) > 0 ? 'risk' : 'ok'}
              hint={
                // has_hourly_detail=false 时后端返回 null：不能显示成"夜间占比 0.0%"，
                // 那会被读成"夜间几乎不用电"，而事实是这批数据没有小时级明细。
                t.has_hourly_detail
                  ? `夜间占比 ${fmt(t.night_consumption_ratio, 1)}%`
                  : '夜间占比 —（本批数据为月度台账，无小时级明细）'
              }
            />
          </div>

          {basis && (
            <Panel title="指标口径">
              <dl className="grid grid-cols-1 gap-x-8 gap-y-1.5 text-xs md:grid-cols-3">
                {Object.entries(basis).map(([k, v]) => (
                  <div key={k} className="flex gap-3 border-b border-white/5 py-1.5">
                    <dt className="w-32 shrink-0 font-num font-medium text-brand-300">{k}</dt>
                    <dd className="text-slate-400">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------- 趋势图 */}
      {s && (
        <>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Panel title="能耗趋势" subtitle="近 12 个月各能源类型用量">
              <Chart height={300} option={trendOption} empty={(s.trend ?? []).length === 0} />
            </Panel>
            <Panel title="碳排放与能源成本" subtitle="用于评估节能降碳成效">
              <Chart height={300} option={carbonOption} empty={(s.trend ?? []).length === 0} />
            </Panel>
          </div>

          {(s.by_type ?? []).length > 0 || (s.by_building ?? []).length > 0 ? (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
              <Panel title="能源类型构成" subtitle="按成本归集（窗口期）">
                <Chart height={300} option={typeOption} empty={(s.by_type ?? []).length === 0} />
              </Panel>
              <div className="xl:col-span-2">
                <Panel title="楼栋能耗对比" subtitle="用电量与碳排并列">
                  <Chart height={300} option={buildingOption} empty={(s.by_building ?? []).length === 0} />
                </Panel>
              </div>
            </div>
          ) : (
            <Panel title="能源结构分析">
              <EmptyState
                text="当前窗口内暂无分类型/分楼栋明细"
                hint="后端返回的 by_type 与 by_building 为空，通常说明所选园区在近 30 天内没有写入能耗记录。可切换园区或查看下方原始记录。"
              />
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------ 能耗记录 */}
      <Panel
        title="能耗记录明细"
        subtitle={`共 ${total} 条记录；时段与峰谷类型由后端按记录小时推导`}
        extra={
          <div className="flex items-center gap-2">
            <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
            <span className="font-num text-xs text-slate-500">{page} / {pages}</span>
            <Btn variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>下一页</Btn>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="能源类型">
            <select className={inputCls} value={energyType}
              onChange={(e) => { setEnergyType(e.target.value); setPage(1) }}>
              <option value="">全部</option>
              {Object.entries(ENERGY_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="楼栋 ID">
            <input className={inputCls} placeholder="按楼栋过滤" value={buildingId}
              onChange={(e) => { setBuildingId(e.target.value); setPage(1) }} />
          </Field>
          <Field label="时段">
            <select className={inputCls} value={period}
              onChange={(e) => { setPeriod(e.target.value); setPage(1) }}>
              <option value="">全部</option>
              <option value="日间">日间</option>
              <option value="夜间">夜间</option>
            </select>
          </Field>
          {(energyType || buildingId || period) && (
            <Btn variant="ghost" onClick={() => {
              setEnergyType(''); setBuildingId(''); setPeriod(''); setPage(1)
            }}>清空筛选</Btn>
          )}
        </div>

        <DataTable<any>
          columns={[
            { key: 'record_date', title: '日期', render: (r) => <span className="font-num">{r.record_date}</span> },
            {
              // record_hour 为空（月度台账）时不能默认成 00:00，那是编造的时刻
              key: 'record_hour', title: '时刻', align: 'right',
              render: (r) => (r.record_hour == null
                ? <span className="text-slate-600">—</span>
                : `${String(r.record_hour).padStart(2, '0')}:00`),
            },
            {
              key: 'energy_type', title: '类型',
              render: (r) => <Tag tone="muted">{ENERGY_TYPE[r.energy_type] ?? r.energy_type}</Tag>,
            },
            {
              key: 'period', title: '时段',
              render: (r) => (r.period
                ? <Tag tone={r.period === '夜间' ? 'ai' : 'info'}>{r.period}</Tag>
                : <span className="text-slate-600">—</span>),
            },
            {
              key: 'peak_type', title: '电价时段',
              render: (r) => (r.peak_type
                ? <Tag tone={PEAK_TONE[r.peak_type] ?? 'muted'}>{r.peak_type}</Tag>
                : <span className="text-slate-600">—</span>),
            },
            { key: 'consumption', title: '用量', align: 'right', render: (r) => fmt(r.consumption, 2) },
            { key: 'unit', title: '单位', render: (r) => r.unit ?? '—' },
            { key: 'cost', title: '成本(元)', align: 'right', render: (r) => fmt(r.cost) },
            { key: 'carbon_kg', title: '碳排(kg)', align: 'right', render: (r) => fmt(r.carbon_kg, 2) },
            { key: 'baseline', title: '基线', align: 'right', render: (r) => fmt(r.baseline, 2) },
            {
              key: 'is_anomaly', title: '异常',
              render: (r) => {
                if (!r.is_anomaly) return <span className="text-slate-600">—</span>
                return (
                  <span title={r.anomaly_note ?? ''}>
                    <Tag tone="danger">
                      超标 {r.anomaly_ratio != null ? `${fmt(Number(r.anomaly_ratio) * 100, 0)}%` : ''}
                    </Tag>
                  </span>
                )
              },
            },
          ]}
          rows={rows}
          loading={records.loading}
          error={records.error}
          onRetry={records.reload}
          rowKey={(r) => r.id}
          compact
          empty="没有匹配的能耗记录"
        />
      </Panel>
    </div>
  )
}

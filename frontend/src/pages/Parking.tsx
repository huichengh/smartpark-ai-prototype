/**
 * 停车与通行 —— 车位资源 / 车辆 / 门禁 / 访客
 *
 * 全部字段来自 /operation/parking/overview，前端不硬编码任何业务数字。
 */
import { useMemo, useState } from 'react'
import { operationApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const PLATE_TYPE: Record<string, string> = {
  MONTH: '月租车', TEMP: '临时车', VIP: 'VIP', VISITOR: '访客车', STAFF: '员工车',
}

export default function Parking() {
  const { activeParkId } = useAuth()
  const [visitorStatus, setVisitorStatus] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const overview = useAsync(
    () => operationApi.parkingOverview({ park_id: activeParkId ?? undefined }),
    [activeParkId],
  )

  // 访客明细走通知/停车明细接口的通行记录；此处复用 overview 的 visitors 汇总，
  // 明细列表若后端未提供独立分页端点则仅展示汇总。
  const o = overview.data
  const sp = o?.spaces ?? {}
  const vh = o?.vehicles ?? {}
  const ac = o?.access ?? {}
  const vs = o?.visitors ?? {}

  const spaceOption = useMemo(
    () =>
      pieOption({
        data: [
          { name: '已占用', value: Number(sp.occupied) || 0, color: '#2F80ED' },
          { name: '空闲可停', value: Number(sp.available) || 0, color: '#22C55E' },
          { name: '已预留', value: Number(sp.reserved) || 0, color: '#FACC15' },
        ],
        centerLabel: { title: '车位总数', value: sp.total ?? 0 },
      }),
    [sp],
  )

  const typeDistOption = useMemo(() => {
    const by = sp.by_type ?? {}
    const arr = Object.entries(by).map(([k, v]) => ({ name: k, value: Number(v) || 0 }))
    return barOption({
      x: arr.map((a) => a.name),
      series: [{ name: '车位数', data: arr.map((a) => a.value) }],
      showLegend: false,
    })
  }, [sp])

  const vehicleOption = useMemo(() => {
    const by = vh.by_type ?? {}
    const arr = Object.entries(by).map(([k, v]) => ({
      name: PLATE_TYPE[k] ?? k,
      value: Number(v) || 0,
    }))
    return pieOption({
      data: arr,
      centerLabel: { title: '车辆总数', value: vh.total ?? 0 },
    })
  }, [vh])

  const gateOption = useMemo(() => {
    const by = ac.by_gate ?? {}
    const arr = Object.entries(by).map(([k, v]) => ({ name: k, value: Number(v) || 0 }))
      .sort((a, b) => b.value - a.value)
    return barOption({
      x: arr.map((a) => a.name),
      series: [{ name: '通行次数', data: arr.map((a) => a.value) }],
      horizontal: true,
      showLegend: false,
    })
  }, [ac])

  return (
    <div className="space-y-5">
      <PageHeader
        title="停车与通行"
        desc="车位资源、车辆构成、门禁通行与访客管理，全部由后端实时统计。"
        demo
        extra={<Btn variant="ghost" onClick={() => overview.reload()}>刷新</Btn>}
      />

      {overview.loading ? (
        <Panel><Loading text="正在汇总停车数据…" /></Panel>
      ) : overview.error ? (
        <Panel><ErrorState error={overview.error} onRetry={overview.reload} /></Panel>
      ) : (
        <>
          {/* ------------------------------------------------------ KPI */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
            <KpiCard label="车位总数" value={sp.total ?? 0} unit="个" />
            <KpiCard label="已占用" value={sp.occupied ?? 0} unit="个" tone="brand" />
            <KpiCard label="空闲可停" value={sp.available ?? 0} unit="个" tone="ok" />
            <KpiCard
              label="车位占用率" value={fmt(sp.occupancy_rate, 1)} unit="%"
              tone={Number(sp.occupancy_rate) >= 90 ? 'warn' : 'ok'}
              hint="已占用 ÷ 车位总数"
            />
            <KpiCard label="登记车辆" value={vh.total ?? 0} unit="辆" />
            <KpiCard label="今日通行" value={ac.today ?? 0} unit="次" hint={`累计 ${fmt(ac.total_records, 0)} 次`} />
            <KpiCard
              label="在园访客" value={vs.in_park ?? 0} unit="人"
              tone="ai" hint={`待审批 ${vs.pending ?? 0} 人`}
            />
          </div>

          {/* ---------------------------------------------------- 图表 */}
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Panel title="车位使用构成" subtitle="占用 / 空闲 / 预留">
              <Chart height={280} option={spaceOption} empty={!sp.total} />
            </Panel>
            <Panel title="车辆类型构成" subtitle="按月租 / 临时 / 访客等归集">
              <Chart height={280} option={vehicleOption} empty={!vh.total} />
            </Panel>
            <Panel title="车位类型分布" subtitle="按车位类型统计">
              <Chart height={280} option={typeDistOption} empty={!sp.by_type || Object.keys(sp.by_type).length === 0} />
            </Panel>
          </div>

          {/* ---------------------------------------------------- 门禁 */}
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Panel title="各闸口通行量" subtitle="按通行次数降序">
              <Chart height={300} option={gateOption} empty={!ac.by_gate || Object.keys(ac.by_gate).length === 0} />
            </Panel>

            <Panel title="车位与车辆明细" subtitle="由 /operation/parking/overview 下发">
              <dl className="grid grid-cols-2 gap-3">
                {([
                  ['车位总数', `${sp.total ?? 0} 个`],
                  ['已占用', `${sp.occupied ?? 0} 个`],
                  ['空闲可停', `${sp.available ?? 0} 个`],
                  ['已预留', `${sp.reserved ?? 0} 个`],
                  ['登记车辆', `${vh.total ?? 0} 辆`],
                  ['月租车', `${vh.month_card ?? 0} 辆`],
                  ['新能源车', `${vh.new_energy ?? 0} 辆`],
                  ['累计通行', `${fmt(ac.total_records, 0)} 次`],
                  ['今日通行', `${ac.today ?? 0} 次`],
                  ['访客累计', `${vs.total ?? 0} 人`],
                  ['访客待审批', `${vs.pending ?? 0} 人`],
                  ['访客已批准', `${vs.approved ?? 0} 人`],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                    <dt className="text-xs text-slate-500">{k}</dt>
                    <dd className="mt-1 font-num text-base font-semibold text-slate-100">{v}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-4">
                <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500">
                  <span>车位占用率</span>
                  <span className="font-num">{fmt(sp.occupancy_rate, 1)}%</span>
                </div>
                <ProgressBar
                  value={Number(sp.occupancy_rate) || 0}
                  tone={Number(sp.occupancy_rate) >= 90 ? 'warn' : 'brand'}
                  height={8}
                />
              </div>
            </Panel>
          </div>

          {(!ac.by_gate || Object.keys(ac.by_gate).length === 0) && !overview.loading && (
            <Panel title="门禁数据">
              <EmptyState
                text="当前园区暂无门禁通行记录"
                hint="后端返回 by_gate 为空，通常说明该园区尚未写入通行流水。"
              />
            </Panel>
          )}
        </>
      )}

      <Panel title="访客管理说明" subtitle="访客明细由物业前台在通行记录中维护">
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400">
          <Tag tone="info">待审批 {vs.pending ?? 0}</Tag>
          <Tag tone="ai">在园 {vs.in_park ?? 0}</Tag>
          <Tag tone="ok">今日 {vs.today ?? 0}</Tag>
          <Tag tone="muted">已批准 {vs.approved ?? 0}</Tag>
          <span className="text-slate-500">
            访客审批流转位于「审批中心」，本页仅展示统计口径。
          </span>
        </div>
      </Panel>
    </div>
  )
}

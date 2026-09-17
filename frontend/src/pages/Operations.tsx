/**
 * 物业运维 —— 工单 / 设备台账 / 巡检
 *
 * 工单 SLA 超时、响应时长与满意度评分均由后端计算；
 * 设备健康度、维保到期判断同样由后端下发（maintain_due / maintain_overdue）。
 */
import { useMemo, useState } from 'react'
import { operationApi } from '@/api/modules'
import { useAsync, pushToast } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls, cx,
} from '@/components/ui'
import { Chart, barOption, lineOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const PRIORITY_TONE: Record<string, string> = {
  URGENT: 'danger', HIGH: 'warn', MEDIUM: 'info', LOW: 'muted',
}
const PRIORITY_LABEL: Record<string, string> = {
  URGENT: '紧急', HIGH: '高', MEDIUM: '中', LOW: '低',
}
const WO_STATUS_TONE: Record<string, string> = {
  SUBMITTED: 'info', DISPATCHED: 'info', ACCEPTED: 'brand' as unknown as string,
  PROCESSING: 'warn', FINISHED: 'ok', CLOSED: 'ok', CANCELLED: 'muted',
}
const DEVICE_STATUS_TONE: Record<string, string> = {
  RUNNING: 'ok', IDLE: 'muted', FAULT: 'danger', MAINTENANCE: 'warn', SCRAPPED: 'muted',
}
const DEVICE_STATUS_LABEL: Record<string, string> = {
  RUNNING: '运行中', IDLE: '闲置', FAULT: '故障', MAINTENANCE: '维保中', SCRAPPED: '已报废',
}

type Tab = 'order' | 'device'

export default function Operations() {
  const { activeParkId, can } = useAuth()
  const [tab, setTab] = useState<Tab>('order')
  const [orderType, setOrderType] = useState('')
  const [priority, setPriority] = useState('')
  const [woStatus, setWoStatus] = useState('')
  const [devStatus, setDevStatus] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 15

  const orders = useAsync(
    () => operationApi.workOrders({
      park_id: activeParkId ?? undefined,
      order_type: orderType || undefined,
      priority: priority || undefined,
      status: woStatus || undefined,
      is_timeout: overdueOnly ? true : undefined,
      page, page_size: pageSize,
    }),
    [activeParkId, orderType, priority, woStatus, overdueOnly, page],
    { enabled: tab === 'order' },
  )

  const stats = useAsync(
    () => operationApi.workOrderStats({ park_id: activeParkId ?? undefined }),
    [activeParkId],
  )

  const devices = useAsync(
    () => operationApi.devices({
      park_id: activeParkId ?? undefined,
      status: devStatus || undefined,
      page, page_size: pageSize,
    }),
    [activeParkId, devStatus, page],
    { enabled: tab === 'device' },
  )

  const orderStats = orders.data?.stats ?? {}
  const s = stats.data

  const typeOption = useMemo(
    () =>
      barOption({
        x: (s?.by_type ?? []).map((x: any) => x.name),
        series: [
          { name: '工单数', data: (s?.by_type ?? []).map((x: any) => x.total), color: '#2F80ED' },
          { name: '超时数', data: (s?.by_type ?? []).map((x: any) => x.timeout), color: '#EF4444' },
          { name: '未闭环', data: (s?.by_type ?? []).map((x: any) => x.open), color: '#FACC15' },
        ],
      }),
    [s],
  )

  const trendOption = useMemo(
    () =>
      lineOption({
        x: (s?.trend ?? []).map((x: any) => String(x.month ?? '').slice(2)),
        series: [
          { name: '受理', data: (s?.trend ?? []).map((x: any) => x.total), color: '#2F80ED' },
          { name: '完成', data: (s?.trend ?? []).map((x: any) => x.closed), color: '#22C55E' },
          { name: '超时', data: (s?.trend ?? []).map((x: any) => x.timeout), color: '#EF4444' },
        ],
      }),
    [s],
  )

  const deviceStats = devices.data?.stats ?? {}
  const deviceTypeOption = useMemo(
    () =>
      pieOption({
        data: Object.entries(deviceStats.by_type ?? {}).map(([k, v]) => ({
          name: k, value: Number(v) || 0,
        })).slice(0, 10),
        centerLabel: { title: '设备总数', value: deviceStats.total ?? 0 },
      }),
    [deviceStats],
  )

  const cur = tab === 'order' ? orders : devices
  const rows: any[] = cur.data?.items ?? []
  const total = cur.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const orderAction = async (o: any, action: string) => {
    try {
      await operationApi.workOrderAction(o.id, {
        action,
        assignee_name: action === 'ASSIGN' ? '张工程' : undefined,
        remark: '由运维工作台操作（演示）',
      })
      pushToast('ok', `工单 ${o.order_code} 已${
        { ASSIGN: '派单', ACCEPT: '接单', FINISH: '完工', CLOSE: '关闭' }[action] ?? action
      }`)
      orders.reload(); stats.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '操作失败')
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="物业运维"
        desc="工单受理、SLA 超时、设备台账与维保到期预警，全部由后端基于运维台账统计。"
        demo
        extra={<Btn variant="ghost" onClick={() => { orders.reload(); devices.reload(); stats.reload() }}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {s ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
          <KpiCard label="工单总量" value={s.total ?? 0} unit="单" />
          <KpiCard label="未闭环" value={s.open ?? 0} unit="单"
            tone={Number(s.open) > 0 ? 'warn' : 'ok'} />
          <KpiCard label="已完成" value={s.closed ?? 0} unit="单" tone="ok" />
          <KpiCard
            label="完成率" value={fmt(s.completion_rate, 1)} unit="%"
            tone={Number(s.completion_rate) >= 90 ? 'ok' : 'warn'}
          />
          <KpiCard
            label="超时工单" value={s.timeout_count ?? 0} unit="单"
            tone={Number(s.timeout_count) > 0 ? 'risk' : 'ok'}
            hint={`超时率 ${fmt(s.timeout_rate, 2)}%`}
          />
          <KpiCard label="平均处理时长" value={fmt(s.avg_handle_hours, 1)} unit="h" />
          <KpiCard
            label="平均满意度" value={fmt(s.avg_rating, 2)} unit="分"
            tone="ai" hint={`已评价 ${s.rated_count ?? 0} 单`}
          />
        </div>
      ) : (
        <Panel><Loading text="正在汇总运维指标…" /></Panel>
      )}

      {s && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Panel title="工单类型分布" subtitle="含超时与未闭环拆分">
            <Chart height={280} option={typeOption} empty={(s.by_type ?? []).length === 0} />
          </Panel>
          <Panel title="工单月度趋势" subtitle="受理 / 完成 / 超时">
            <Chart height={280} option={trendOption} empty={(s.trend ?? []).length === 0} />
          </Panel>
        </div>
      )}

      {/* ------------------------------------------------------ 台账列表 */}
      <Panel
        title={tab === 'order' ? '工单台账' : '设备台账'}
        subtitle={`共 ${total} 条`}
        extra={
          <div className="flex items-center gap-2">
            <Btn size="sm" variant={tab === 'order' ? 'primary' : 'ghost'}
                 onClick={() => { setTab('order'); setPage(1) }}>工单</Btn>
            <Btn size="sm" variant={tab === 'device' ? 'primary' : 'ghost'}
                 onClick={() => { setTab('device'); setPage(1) }}>设备</Btn>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
            <span className="font-num text-xs text-slate-500">{page} / {pages}</span>
            <Btn variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>下一页</Btn>
          </div>
        }
      >
        {tab === 'order' ? (
          <>
            <div className="mb-3 flex flex-wrap items-end gap-3">
              <Field label="工单类型">
                <select className={inputCls} value={orderType}
                  onChange={(e) => { setOrderType(e.target.value); setPage(1) }}>
                  <option value="">全部</option>
                  {(s?.by_type ?? []).map((t: any) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="优先级">
                <select className={inputCls} value={priority}
                  onChange={(e) => { setPriority(e.target.value); setPage(1) }}>
                  <option value="">全部</option>
                  {Object.entries(PRIORITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </Field>
              <Field label="状态">
                <select className={inputCls} value={woStatus}
                  onChange={(e) => { setWoStatus(e.target.value); setPage(1) }}>
                  <option value="">全部</option>
                  {['SUBMITTED', 'DISPATCHED', 'ACCEPTED', 'PROCESSING', 'FINISHED', 'CLOSED'].map((k) => (
                    <option key={k} value={k}>
                      {{ SUBMITTED: '已提交', DISPATCHED: '已派单', ACCEPTED: '已接单',
                         PROCESSING: '处理中', FINISHED: '已完工', CLOSED: '已关闭' }[k]}
                    </option>
                  ))}
                </select>
              </Field>
              <label className="flex cursor-pointer items-center gap-2 pb-2 text-xs text-slate-400">
                <input type="checkbox" checked={overdueOnly}
                  onChange={(e) => { setOverdueOnly(e.target.checked); setPage(1) }}
                  className="accent-brand-500" />
                仅看超时工单
              </label>
              {(orderType || priority || woStatus || overdueOnly) && (
                <Btn variant="ghost" onClick={() => {
                  setOrderType(''); setPriority(''); setWoStatus(''); setOverdueOnly(false); setPage(1)
                }}>清空筛选</Btn>
              )}
            </div>

            <DataTable<any>
              columns={[
                {
                  key: 'order_code', title: '工单号',
                  render: (r) => <span className="font-num text-xs">{r.order_code}</span>,
                },
                {
                  key: 'title', title: '工单内容',
                  render: (r) => (
                    <div className="min-w-0">
                      <div className="truncate font-medium text-slate-100">{r.title}</div>
                      <div className="truncate text-[11px] text-slate-500">
                        {r.building_name ?? '—'} {r.location ? `· ${r.location}` : ''}
                      </div>
                    </div>
                  ),
                },
                { key: 'order_type', title: '类型', render: (r) => <Tag tone="muted">{r.order_type ?? '—'}</Tag> },
                {
                  key: 'priority', title: '优先级',
                  render: (r) => (
                    <Tag tone={PRIORITY_TONE[r.priority] ?? 'muted'}>
                      {PRIORITY_LABEL[r.priority] ?? r.priority}
                    </Tag>
                  ),
                },
                {
                  key: 'status', title: '状态',
                  render: (r) => (
                    <Tag tone={WO_STATUS_TONE[r.status] ?? 'muted'}>{r.status_name ?? r.status}</Tag>
                  ),
                },
                { key: 'reporter_name', title: '报修人', render: (r) => r.reporter_name ?? '—' },
                { key: 'assignee_name', title: '处理人', render: (r) => r.assignee_name ?? <span className="text-slate-600">未派单</span> },
                {
                  key: 'response_minutes', title: '响应(min)', align: 'right',
                  render: (r) => (r.response_minutes != null ? fmt(r.response_minutes, 0) : <span className="text-slate-600">—</span>),
                },
                {
                  key: 'handle_hours', title: '处理(h)', align: 'right',
                  render: (r) => (r.handle_hours != null ? fmt(r.handle_hours, 1) : <span className="text-slate-600">—</span>),
                },
                {
                  key: 'sla_hours', title: 'SLA', align: 'right',
                  render: (r) => (r.sla_hours != null ? `${r.sla_hours}h` : '—'),
                },
                {
                  key: 'is_timeout', title: '超时',
                  render: (r) => (r.is_timeout
                    ? <Tag tone="danger">超时</Tag>
                    : <span className="text-slate-600">—</span>),
                },
                {
                  key: 'rating', title: '满意度', align: 'right',
                  render: (r) => (r.rating != null
                    ? <span className={Number(r.rating) >= 4 ? 'text-state-ok' : 'text-state-warn'}>
                        {fmt(r.rating, 1)}
                      </span>
                    : <span className="text-slate-600">—</span>),
                },
                {
                  key: 'ops', title: '操作',
                  render: (r) => (
                    can('property', 'EDIT') ? (
                      <div className="flex items-center gap-1.5">
                        {r.status === 'SUBMITTED' && <Btn size="sm" variant="ghost" onClick={() => orderAction(r, 'ASSIGN')}>派单</Btn>}
                        {r.status === 'DISPATCHED' && <Btn size="sm" variant="ghost" onClick={() => orderAction(r, 'ACCEPT')}>接单</Btn>}
                        {(r.status === 'ACCEPTED' || r.status === 'PROCESSING') && (
                          <Btn size="sm" variant="ghost" onClick={() => orderAction(r, 'FINISH')}>完工</Btn>
                        )}
                        {r.status === 'FINISHED' && <Btn size="sm" variant="ghost" onClick={() => orderAction(r, 'CLOSE')}>关闭</Btn>}
                      </div>
                    ) : null
                  ),
                },
              ]}
              rows={rows}
              loading={orders.loading}
              error={orders.error}
              onRetry={orders.reload}
              rowKey={(r) => r.id}
              compact
              empty="没有匹配的工单"
            />
          </>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-end gap-3">
              <Field label="设备状态">
                <select className={inputCls} value={devStatus}
                  onChange={(e) => { setDevStatus(e.target.value); setPage(1) }}>
                  <option value="">全部</option>
                  {Object.entries(DEVICE_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </Field>
              {devStatus && (
                <Btn variant="ghost" onClick={() => { setDevStatus(''); setPage(1) }}>清空筛选</Btn>
              )}
              <div className="ml-auto flex flex-wrap gap-4 text-xs text-slate-500">
                <span>在线率 <b className="font-num text-state-ok">{fmt(deviceStats.online_rate, 1)}%</b></span>
                <span>平均健康度 <b className="font-num text-slate-200">{fmt(deviceStats.avg_health_score, 1)}</b></span>
                <span>维保到期 <b className="font-num text-state-warn">{deviceStats.maintain_due ?? 0}</b></span>
                <span>维保超期 <b className="font-num text-state-danger">{deviceStats.maintain_overdue ?? 0}</b></span>
                <span>低健康度 <b className="font-num text-state-warn">{deviceStats.low_health_count ?? 0}</b></span>
              </div>
            </div>

            <DataTable<any>
              columns={[
                {
                  key: 'device_code', title: '设备编号',
                  render: (r) => <span className="font-num text-xs">{r.device_code}</span>,
                },
                {
                  key: 'device_name', title: '设备名称',
                  render: (r) => (
                    <div className="min-w-0">
                      <div className="truncate font-medium text-slate-100">{r.device_name}</div>
                      <div className="truncate text-[11px] text-slate-500">
                        {r.brand ?? '—'} {r.model ? `/ ${r.model}` : ''}
                      </div>
                    </div>
                  ),
                },
                { key: 'device_type', title: '类型', render: (r) => <Tag tone="muted">{r.device_type ?? '—'}</Tag> },
                { key: 'building_name', title: '所在楼栋', render: (r) => r.building_name ?? '—' },
                { key: 'location', title: '安装位置', render: (r) => r.location ?? '—' },
                {
                  key: 'status', title: '状态',
                  render: (r) => (
                    <Tag tone={DEVICE_STATUS_TONE[r.status] ?? 'muted'}>
                      {DEVICE_STATUS_LABEL[r.status] ?? r.status}
                    </Tag>
                  ),
                },
                {
                  key: 'health_score', title: '健康度', width: 130,
                  render: (r) => (
                    <div className="space-y-1">
                      <ProgressBar
                        value={Number(r.health_score) || 0}
                        tone={Number(r.health_score) >= 80 ? 'ok' : Number(r.health_score) >= 60 ? 'warn' : 'danger'}
                      />
                      <div className="font-num text-[10px] text-slate-500">
                        {r.health_score != null ? Number(r.health_score).toFixed(1) : '—'}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'is_online', title: '在线',
                  render: (r) => (
                    <span className={cx(
                      'inline-flex items-center gap-1 text-[11px]',
                      r.is_online ? 'text-state-ok' : 'text-slate-500',
                    )}>
                      <i className={cx('h-1.5 w-1.5 rounded-full', r.is_online ? 'bg-state-ok' : 'bg-slate-600')} />
                      {r.is_online ? '在线' : '离线'}
                    </span>
                  ),
                },
                {
                  key: 'is_iot_connected', title: '物联',
                  render: (r) => (r.is_iot_connected
                    ? <Tag tone="ai">已接入</Tag>
                    : <span className="text-slate-600">—</span>),
                },
                { key: 'last_inspect_date', title: '上次巡检', render: (r) => <span className="font-num">{r.last_inspect_date ?? '—'}</span> },
                {
                  key: 'next_maintain_date', title: '下次维保',
                  render: (r) => (
                    <span className={cx('font-num', r.maintain_overdue && 'text-state-danger')}>
                      {r.next_maintain_date ?? '—'}
                    </span>
                  ),
                },
                {
                  key: 'warranty_end', title: '保修到期',
                  render: (r) => <span className="font-num">{r.warranty_end ?? '—'}</span>,
                },
                { key: 'supplier', title: '供应商', render: (r) => r.supplier ?? '—' },
              ]}
              rows={rows}
              loading={devices.loading}
              error={devices.error}
              onRetry={devices.reload}
              rowKey={(r) => r.id}
              compact
              empty="没有匹配的设备"
            />
          </>
        )}
      </Panel>

      {tab === 'device' && Object.keys(deviceStats.by_type ?? {}).length > 0 && (
        <Panel title="设备类型构成" subtitle={`共 ${deviceStats.total ?? 0} 台设备`}>
          <Chart height={300} option={deviceTypeOption} />
        </Panel>
      )}
    </div>
  )
}

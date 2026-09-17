/**
 * 会议室管理 —— 预订台账与使用统计
 *
 * 数据来自 /operation/meeting-rooms/bookings（含 stats）。
 */
import { useMemo, useState } from 'react'
import { operationApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, Tag, inputCls, cx,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const STATUS_TONE: Record<string, string> = {
  BOOKED: 'info', ONGOING: 'warn', FINISHED: 'ok', CANCELLED: 'muted',
}
const STATUS_LABEL: Record<string, string> = {
  BOOKED: '已预订', ONGOING: '进行中', FINISHED: '已完成', CANCELLED: '已取消',
}

export default function Meeting() {
  const { activeParkId } = useAuth()
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const bookings = useAsync(
    () => operationApi.meetingBookings({
      park_id: activeParkId ?? undefined,
      status: status || undefined,
      keyword: keyword || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, status, keyword, page],
  )

  const rows: any[] = bookings.data?.items ?? []
  const stats = bookings.data?.stats ?? {}
  const total = bookings.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  /** 会议室使用频次（基于当前页数据，用于快速观察分布） */
  const roomOption = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) {
      const k = r.space_name ?? '未命名会议室'
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    const arr = [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12)
    return barOption({
      x: arr.map((a) => a[0]),
      series: [{ name: '预订次数', data: arr.map((a) => a[1]), color: '#7B61FF' }],
      horizontal: true,
      showLegend: false,
    })
  }, [rows])

  const attendeesOption = useMemo(() => {
    const buckets: Record<string, number> = { '≤5人': 0, '6-15人': 0, '16-30人': 0, '>30人': 0 }
    for (const r of rows) {
      const n = Number(r.attendees) || 0
      if (n <= 5) buckets['≤5人']++
      else if (n <= 15) buckets['6-15人']++
      else if (n <= 30) buckets['16-30人']++
      else buckets['>30人']++
    }
    return pieOption({
      data: Object.entries(buckets).map(([name, value]) => ({ name, value })),
      centerLabel: { title: '当前页预订', value: rows.length },
    })
  }, [rows])

  const statusOption = useMemo(
    () =>
      pieOption({
        data: Object.entries(stats.by_status ?? {}).map(([k, v]) => ({
          name: STATUS_LABEL[k] ?? k,
          value: Number(v) || 0,
        })),
        centerLabel: { title: '预订总数', value: stats.total ?? 0 },
      }),
    [stats],
  )

  return (
    <div className="space-y-5">
      <PageHeader
        title="会议室管理"
        desc="会议室预订台账与使用统计，费用与时长均由后端按预订记录统计。"
        demo
        extra={<Btn variant="ghost" onClick={() => bookings.reload()}>刷新</Btn>}
      />

      {bookings.loading && !bookings.data ? (
        <Panel><Loading text="正在加载会议室预订…" /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
          <KpiCard label="预订总数" value={stats.total ?? 0} unit="次" />
          <KpiCard
            label="累计场地费" value={`${((Number(stats.total_fee) || 0) / 10000).toFixed(2)} 万`} unit="元"
            tone="brand"
          />
          <KpiCard
            label="已完成" value={stats.by_status?.FINISHED ?? 0} unit="次" tone="ok"
          />
          <KpiCard
            label="已预订未开始" value={stats.by_status?.BOOKED ?? 0} unit="次" tone="brand"
          />
          <KpiCard
            label="已取消" value={stats.by_status?.CANCELLED ?? 0} unit="次"
            tone={Number(stats.by_status?.CANCELLED) > 0 ? 'warn' : 'ok'}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Panel title="会议室使用频次" subtitle="基于当前页预订记录统计">
            <Chart height={300} option={roomOption} empty={rows.length === 0} />
          </Panel>
        </div>
        <Panel title="参会人数分布" subtitle="基于当前页预订记录统计">
          <Chart height={300} option={attendeesOption} empty={rows.length === 0} />
        </Panel>
      </div>

      <Panel
        title="预订台账"
        subtitle={`共 ${total} 条预订记录`}
        extra={
          <div className="flex items-center gap-2">
            <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
            <span className="font-num text-xs text-slate-500">{page} / {pages}</span>
            <Btn variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>下一页</Btn>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="搜索">
            <input
              className={inputCls} placeholder="预订编号 / 企业 / 会议室"
              value={keyword}
              onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
            />
          </Field>
          <Field label="状态">
            <select className={inputCls} value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
              <option value="">全部</option>
              {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          {(status || keyword) && (
            <Btn variant="ghost" onClick={() => { setStatus(''); setKeyword(''); setPage(1) }}>清空筛选</Btn>
          )}
        </div>

        <DataTable<any>
          columns={[
            {
              key: 'booking_code', title: '预订编号',
              render: (r) => <span className="font-num text-xs">{r.booking_code}</span>,
            },
            { key: 'space_name', title: '会议室', render: (r) => r.space_name ?? '—' },
            { key: 'enterprise_name', title: '预订企业', render: (r) => r.enterprise_name ?? '—' },
            { key: 'booker', title: '预订人', render: (r) => r.booker ?? '—' },
            { key: 'book_date', title: '日期', render: (r) => <span className="font-num">{r.book_date ?? '—'}</span> },
            {
              key: 'start_time', title: '时间段',
              render: (r) => (
                <span className="font-num text-[11px]">
                  {String(r.start_time ?? '').slice(11, 16) || '—'}
                  <span className="text-slate-600"> → </span>
                  {String(r.end_time ?? '').slice(11, 16) || '—'}
                </span>
              ),
            },
            { key: 'attendees', title: '参会人数', align: 'right', render: (r) => r.attendees ?? '—' },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={STATUS_TONE[r.status] ?? 'muted'}>
                  {STATUS_LABEL[r.status] ?? r.status}
                </Tag>
              ),
            },
            {
              key: 'fee', title: '场地费(元)', align: 'right',
              render: (r) => (
                <span className={cx(Number(r.fee) > 0 ? 'text-slate-200' : 'text-slate-600')}>
                  {fmt(r.fee)}
                </span>
              ),
            },
          ]}
          rows={rows}
          loading={bookings.loading}
          error={bookings.error}
          onRetry={bookings.reload}
          rowKey={(r) => r.id}
          compact
          empty="没有匹配的预订记录"
        />
      </Panel>

      {stats.total != null && (
        <Panel title="预订状态分布" subtitle="由后端 stats 下发">
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Chart height={260} option={statusOption}
                   empty={Object.keys(stats.by_status ?? {}).length === 0} />
            <div className="xl:col-span-2">
              <dl className="grid grid-cols-2 gap-3 md:grid-cols-3">
                {Object.entries(STATUS_LABEL).map(([k, label]) => (
                  <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                    <dt className="text-xs text-slate-500">{label}</dt>
                    <dd className="mt-1 font-num text-lg font-semibold text-slate-100">
                      {stats.by_status?.[k] ?? 0} <span className="text-xs font-normal text-slate-500">次</span>
                    </dd>
                  </div>
                ))}
                <div className="rounded-lg border border-brand-500/25 bg-brand-500/[0.07] p-3">
                  <dt className="text-xs text-brand-300">累计场地费</dt>
                  <dd className="mt-1 font-num text-lg font-semibold text-brand-200">
                    {fmt(stats.total_fee, 0)} <span className="text-xs font-normal text-brand-300/70">元</span>
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </Panel>
      )}
    </div>
  )
}

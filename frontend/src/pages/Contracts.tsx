/**
 * 合同管理 —— 合同台账 / 到期预警 / 续约发起
 *
 * 到期分组（grouped）与「在险年租金」均由后端计算，前端只做展示。
 */
import { useMemo, useState } from 'react'
import { contractApi } from '@/api/modules'
import { useAsync, pushToast } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, pieOption, rankBarOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const wan = (v: any) => `${((Number(v) || 0) / 10000).toFixed(1)} 万`

const STATUS_TONE: Record<string, string> = {
  ACTIVE: 'ok', EXPIRING: 'warn', EXPIRED: 'danger',
  TERMINATED: 'muted', DRAFT: 'muted', PENDING: 'info',
}
const STATUS_LABEL: Record<string, string> = {
  ACTIVE: '生效中', EXPIRING: '即将到期', EXPIRED: '已到期',
  TERMINATED: '已终止', DRAFT: '草稿', PENDING: '待审批',
}
const BUCKET_TONE: Record<string, string> = {
  '30天内': 'danger', '31-60天': 'warn', '61-90天': 'info', '90天以上': 'muted',
}

export default function Contracts() {
  const { activeParkId, can } = useAuth()
  const [status, setStatus] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const expiring = useAsync(
    () => contractApi.expiring({ park_id: activeParkId ?? undefined, days: 90 }),
    [activeParkId],
  )

  const list = useAsync(
    () => contractApi.list({
      park_id: activeParkId ?? undefined,
      status: status || undefined,
      keyword: keyword || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, status, keyword, page],
  )

  const e = expiring.data
  const stats = list.data?.stats ?? {}

  const bucketOption = useMemo(() => {
    const g = e?.grouped ?? {}
    const rows = Object.entries(g).map(([k, v]: [string, any]) => ({
      name: k,
      count: Array.isArray(v) ? v.length : (v?.count ?? 0),
      rent: Array.isArray(v)
        ? v.reduce((s: number, x: any) => s + (Number(x.annual_rent) || 0), 0)
        : (Number(v?.annual_rent) || 0),
    }))
    return barOption({
      x: rows.map((r) => r.name),
      series: [
        { name: '合同数', data: rows.map((r) => r.count), color: '#2F80ED' },
        { name: '在险年租金(元)', data: rows.map((r) => r.rent), color: '#EF4444' },
      ],
    })
  }, [e])

  const parkOption = useMemo(
    () =>
      rankBarOption({
        names: (e?.by_park ?? []).map((p: any) => p.park_name ?? `#${p.park_id}`),
        values: (e?.by_park ?? []).map((p: any) => p.annual_rent),
        color: '#FACC15',
      }),
    [e],
  )

  const statusOption = useMemo(
    () =>
      pieOption({
        // stats.by_status 后端统一下发为字典 {状态: 数量}（与 Enterprise/Meeting 一致），
        // 早期这里按数组 .map() 调用，数据一到就抛 TypeError，整页渲染为空。
        data: Object.entries(stats.by_status ?? {}).map(([key, count]) => ({
          name: STATUS_LABEL[key as string] ?? key,
          value: Number(count) || 0,
        })),
        centerLabel: { title: '合同总数', value: stats.total ?? 0 },
      }),
    [stats],
  )

  const rows: any[] = list.data?.items ?? []
  const total = list.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const expiringItems: any[] = e?.items ?? []

  const doRenewIntent = async (c: any) => {
    try {
      await contractApi.renewIntent(c.id, '由合同台账发起续约意向（演示）')
      pushToast('ok', `已登记 ${c.contract_code} 的续约意向`)
      expiring.reload()
    } catch (err: any) {
      pushToast('err', err?.message ?? '发起续约失败')
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="合同管理"
        desc="合同台账、到期预警与在险租金，均由后端基于合同台账实时计算。"
        demo
        extra={<Btn variant="ghost" onClick={() => { list.reload(); expiring.reload() }}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {list.loading && !list.data ? (
        <Panel><Loading text="正在加载合同数据…" /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          <KpiCard label="合同总数" value={stats.total ?? 0} unit="份" />
          <KpiCard label="生效中" value={stats.active_count ?? 0} unit="份" tone="ok" />
          {/* 口径必须写在指标上：这个数曾因"已终止合同也被算入"而从 39 变 37，
              不给口径说明的话，使用者只会认为数据出错了。 */}
          <KpiCard label="90 天内到期" value={stats.expiring_90 ?? 0} unit="份" tone="warn"
                   hint="仅统计生效中/即将到期合同，已终止不计入" />
          <KpiCard label="30 天内到期" value={stats.expiring_30 ?? 0} unit="份" tone="risk"
                   hint="仅统计生效中/即将到期合同，已终止不计入" />
          <KpiCard label="在租面积" value={fmt(stats.total_leased_area, 0)} unit="㎡" />
          <KpiCard label="月租金合计" value={wan(stats.total_monthly_rent)} unit="元" tone="ai" />
        </div>
      )}

      {/* ------------------------------------------------------ 到期预警 */}
      {e && (
        <>
          <div className="rounded-xl border border-state-warn/28 bg-state-warn/[0.07] px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-state-warn">
                <span className="font-semibold">到期预警（{e.window_days ?? 90} 天窗口）</span>
                <span className="ml-3 text-xs">{e.basis}</span>
              </div>
              <div className="flex flex-wrap items-center gap-5 text-xs">
                <span className="text-slate-400">
                  在险年租金 <b className="font-num text-state-warn">{wan(e.total_annual_rent_at_risk)}</b> 元
                </span>
                <span className="text-slate-400">
                  在险面积 <b className="font-num text-state-warn">{fmt(e.total_leased_area_at_risk, 0)}</b> ㎡
                </span>
                <span className="text-slate-400">
                  共 <b className="font-num text-state-warn">{e.total ?? 0}</b> 份
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <Panel title="到期时间分布" subtitle="按剩余天数分桶，含合同数与在险年租金">
                <Chart height={280} option={bucketOption} empty={!e.grouped} />
              </Panel>
            </div>
            <Panel title="各园区在险年租金" subtitle="按年租金降序">
              <Chart height={280} option={parkOption} empty={(e.by_park ?? []).length === 0} />
            </Panel>
          </div>

          <Panel title="即将到期合同明细" subtitle={`按剩余天数升序，共 ${expiringItems.length} 份`}>
            <DataTable<any>
              columns={[
                {
                  key: 'contract_code', title: '合同编号',
                  render: (r) => <span className="font-num text-xs">{r.contract_code}</span>,
                },
                { key: 'enterprise_name', title: '企业名称', render: (r) => r.enterprise_name ?? '—' },
                { key: 'space_name', title: '房源', render: (r) => r.space_name ?? '—' },
                { key: 'leased_area', title: '面积(㎡)', align: 'right', render: (r) => fmt(r.leased_area, 2) },
                { key: 'monthly_rent', title: '月租金(元)', align: 'right', render: (r) => fmt(r.monthly_rent) },
                { key: 'annual_rent', title: '年租金(元)', align: 'right', render: (r) => fmt(r.annual_rent) },
                { key: 'end_date', title: '到期日', render: (r) => <span className="font-num">{r.end_date}</span> },
                {
                  key: 'days_left', title: '剩余天数', align: 'right',
                  render: (r) => {
                    const d = Number(r.days_left)
                    return (
                      <span className={d <= 30 ? 'text-state-danger' : d <= 60 ? 'text-state-warn' : 'text-slate-300'}>
                        {d} 天
                      </span>
                    )
                  },
                },
                {
                  key: 'bucket', title: '分桶',
                  render: (r) => <Tag tone={BUCKET_TONE[r.bucket] ?? 'muted'}>{r.bucket ?? '—'}</Tag>,
                },
                { key: 'owner_name', title: '负责人', render: (r) => r.owner_name ?? '—' },
                {
                  key: 'ops', title: '操作',
                  render: (r) => (can('contract', 'EDIT')
                    ? <Btn size="sm" variant="ghost" onClick={() => doRenewIntent(r)}>发起续约</Btn>
                    : null),
                },
              ]}
              rows={expiringItems}
              rowKey={(r) => r.id}
              compact
              empty="暂无即将到期的合同"
            />
          </Panel>
        </>
      )}

      {/* ------------------------------------------------------ 合同台账 */}
      <Panel
        title="合同台账"
        subtitle={`共 ${total} 份合同`}
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
              className={inputCls} placeholder="合同编号 / 名称 / 企业"
              value={keyword}
              onChange={(ev) => { setKeyword(ev.target.value); setPage(1) }}
            />
          </Field>
          <Field label="合同状态">
            <select
              className={inputCls} value={status}
              onChange={(ev) => { setStatus(ev.target.value); setPage(1) }}
            >
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
              key: 'contract_code', title: '合同编号',
              render: (r) => <span className="font-num text-xs">{r.contract_code}</span>,
            },
            {
              key: 'enterprise_name', title: '企业 / 合同名称',
              render: (r) => (
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{r.enterprise_name ?? '—'}</div>
                  <div className="truncate text-[11px] text-slate-500">{r.contract_name ?? '—'}</div>
                </div>
              ),
            },
            { key: 'space_name', title: '房源', render: (r) => r.space_name ?? '—' },
            { key: 'leased_area', title: '面积(㎡)', align: 'right', render: (r) => fmt(r.leased_area, 2) },
            { key: 'rent_price', title: '租金单价', align: 'right', render: (r) => fmt(r.rent_price) },
            { key: 'monthly_rent', title: '月租金(元)', align: 'right', render: (r) => fmt(r.monthly_rent) },
            {
              key: 'start_date', title: '租期',
              render: (r) => (
                <span className="font-num text-[11px]">
                  {r.start_date ?? '—'} <span className="text-slate-600">→</span> {r.end_date ?? '—'}
                </span>
              ),
            },
            {
              key: 'days_left', title: '剩余天数', align: 'right',
              render: (r) => {
                if (r.status !== 'ACTIVE' && r.status !== 'EXPIRING') {
                  return <span className="text-slate-600">—</span>
                }
                const d = Number(r.days_left)
                return (
                  <span className={d <= 30 ? 'text-state-danger' : d <= 90 ? 'text-state-warn' : ''}>
                    {d} 天
                  </span>
                )
              },
            },
            {
              key: 'collection_rate', title: '收缴率', width: 112,
              render: (r) => <ProgressBar value={Number(r.collection_rate) || 0} showText />,
            },
            {
              key: 'arrears', title: '欠费(元)', align: 'right',
              render: (r) => (
                <span className={Number(r.arrears) > 0 ? 'text-state-warn' : 'text-slate-500'}>
                  {fmt(r.arrears)}
                </span>
              ),
            },
            {
              key: 'status', title: '状态',
              render: (r) => <Tag tone={STATUS_TONE[r.status] ?? 'muted'}>{r.status_name ?? r.status}</Tag>,
            },
            { key: 'owner_name', title: '负责人', render: (r) => r.owner_name ?? '—' },
          ]}
          rows={rows}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          rowKey={(r) => r.id}
          compact
          empty="没有匹配的合同"
        />
      </Panel>

      {stats.total != null && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <Panel title="合同状态分布" subtitle="基于当前园区合同台账">
            <Chart height={260} option={statusOption} empty={Object.keys(stats.by_status ?? {}).length === 0} />
          </Panel>
          <div className="xl:col-span-2">
            <Panel title="合同经营摘要" subtitle="全部数值由后端 stats 下发">
              <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
                {([
                  ['生效合同', `${stats.active_count ?? 0} 份`],
                  ['90 天内到期', `${stats.expiring_90 ?? 0} 份`],
                  ['30 天内到期', `${stats.expiring_30 ?? 0} 份`],
                  ['在租面积', `${fmt(stats.total_leased_area, 0)} ㎡`],
                  ['月租金合计', `${fmt(stats.total_monthly_rent)} 元`],
                  ['合同欠费', `${fmt(stats.total_arrears)} 元`],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                    <dt className="text-xs text-slate-500">{k}</dt>
                    <dd className="mt-1 font-num text-base font-semibold text-slate-100">{v}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>
        </div>
      )}
    </div>
  )
}

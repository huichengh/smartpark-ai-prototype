/**
 * 空间管理 —— 楼栋 / 空间单元 / 楼层看板
 *
 * 数据来源全部为后端 /space 模块，前端不做任何指标硬编码。
 * 状态与图例文案消费后端下发（board.status_legend），避免前后端口径不一致。
 */
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { spaceApi } from '@/api/modules'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAsync, pushToast } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, cx, inputCls,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'

/* ------------------------------------------------------------------ 枚举 */

const SPACE_STATUS: Record<string, { label: string; tone: string }> = {
  RENTED: { label: '已出租', tone: 'ok' },
  AVAILABLE: { label: '可租', tone: 'info' },
  VACANT: { label: '空置', tone: 'info' },
  RESERVED: { label: '已预留', tone: 'warn' },
  MAINTENANCE: { label: '维修中', tone: 'risk' },
  SELF_USE: { label: '自用', tone: 'muted' },
  PUBLIC: { label: '公区', tone: 'muted' },
  DISABLED: { label: '停用', tone: 'muted' },
}

const SPACE_TYPE: Record<string, string> = {
  OFFICE: '办公', LAB: '实验室', WAREHOUSE: '仓储', SHOP: '商铺',
  FACTORY: '厂房', MEETING: '会议室', PARKING: '车位', PUBLIC: '公区',
  APARTMENT: '公寓',
}

const BUILDING_TYPE: Record<string, string> = {
  OFFICE: '办公楼', RND: '研发楼', FACTORY: '厂房', WAREHOUSE: '仓库',
  PARKING: '停车场', COMMERCIAL: '商业', DORMITORY: '宿舍', OTHER: '其他',
}

const text = (map: Record<string, string>, k?: string | null) =>
  k ? (map[k] ?? k) : '—'

type AnyRow = Record<string, any>

/* ------------------------------------------------------------------ 页面 */

export default function Space() {
  const nav = useNavigate()
  const { activeParkId } = useAuth()
  const [params, setParams] = useSearchParams()

  const buildingId = params.get('building') ? Number(params.get('building')) : null
  const [status, setStatus] = useState('')
  const [type, setType] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const buildings = useAsync(
    () => spaceApi.buildings(activeParkId ?? undefined, 100),
    [activeParkId],
  )

  const spaces = useAsync(
    () => spaceApi.spaces({
      park_id: activeParkId ?? undefined,
      building_id: buildingId ?? undefined,
      status: status || undefined,
      space_type: type || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, buildingId, status, type, page],
  )

  // 空间详情抽屉：楼层看板的每个格子都能点开看到是谁在租、租到什么时候
  const [spaceDetail, setSpaceDetail] = useState<any>(null)
  const [spaceLoading, setSpaceLoading] = useState(false)

  const openSpace = async (spaceId: number) => {
    setSpaceLoading(true)
    setSpaceDetail({ id: spaceId })
    try {
      setSpaceDetail(await spaceApi.space(spaceId))
    } catch (e: any) {
      pushToast('err', e?.message || '空间详情加载失败')
      setSpaceDetail(null)
    } finally {
      setSpaceLoading(false)
    }
  }

  const board = useAsync(
    () => spaceApi.board(buildingId as number),
    [buildingId],
    { enabled: buildingId != null },
  )

  useEffect(() => { setPage(1) }, [activeParkId, buildingId, status, type])

  /* ------------------------------------------------------------- KPI 汇总 */
  const rows: AnyRow[] = useMemo(() => {
    const d: any = buildings.data
    if (!d) return []
    const list = Array.isArray(d) ? d : (d.items ?? d.list ?? d.buildings ?? [])
    return Array.isArray(list) ? list : []
  }, [buildings.data])

  const kpi = useMemo(() => {
    const num = (v: any) => (typeof v === 'number' ? v : Number(v) || 0)
    const sum = (k: string) => rows.reduce((s, r) => s + num(r[k]), 0)
    const rentable = sum('rentable_area')
    const rented = sum('rented_area')
    return {
      buildings: rows.length,
      spaces: sum('space_count'),
      rentable,
      rented,
      vacant: Math.max(0, rentable - rented),
      rate: rentable > 0 ? (rented / rentable) * 100 : 0,
    }
  }, [rows])

  const buildingChart = useMemo(
    () =>
      [...rows]
        .filter((r) => r.occupancy_rate != null)
        .sort((a, b) => Number(b.occupancy_rate) - Number(a.occupancy_rate))
        .slice(0, 12),
    [rows],
  )

  const typeDist = useMemo(() => {
    const d: any = spaces.data
    const list: AnyRow[] = d?.items ?? d?.rows ?? []
    const m = new Map<string, number>()
    for (const r of list) {
      const k = text(SPACE_TYPE, r.space_type)
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    return [...m.entries()].map(([name, value]) => ({ name, value }))
  }, [spaces.data])

  const list: AnyRow[] = spaces.data?.items ?? spaces.data?.rows ?? []
  const total = spaces.data?.total ?? list.length
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const clearFilters = () => {
    setType('')
    setStatus('')
    const next = new URLSearchParams(params)
    next.delete('building')
    setParams(next, { replace: true })
  }

  const toggleBuilding = (id: number) => {
    const next = new URLSearchParams(params)
    if (buildingId === id) next.delete('building')
    else next.set('building', String(id))
    setParams(next, { replace: true })
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="空间管理"
        desc="楼栋、空间单元与楼层出租状态，全部由后端实时汇总。"
        demo
      />

      {/* ------------------------------------------------------------ KPI */}
      {buildings.loading ? (
        <Panel><Loading text="正在汇总资产指标…" /></Panel>
      ) : buildings.error ? (
        <Panel><ErrorState error={buildings.error} onRetry={buildings.reload} /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          <KpiCard label="楼栋数" value={kpi.buildings} unit="栋" hint="当前园区在库楼栋" />
          <KpiCard label="空间单元" value={kpi.spaces} unit="个" hint="各楼栋空间数求和" />
          <KpiCard label="可租面积" value={kpi.rentable.toLocaleString()} unit="㎡" hint="rentable_area 求和" />
          <KpiCard label="已租面积" value={kpi.rented.toLocaleString()} unit="㎡" hint="rented_area 求和" tone="ok" />
          <KpiCard label="空置面积" value={kpi.vacant.toLocaleString()} unit="㎡" hint="可租 − 已租" tone="warn" />
          <KpiCard label="整体出租率" value={kpi.rate.toFixed(1)} unit="%" hint="已租 ÷ 可租" tone="ai" />
        </div>
      )}

      {/* -------------------------------------------------------- 楼栋列表 */}
      <Panel
        title="楼栋资产"
        subtitle="点击卡片进入该楼栋的楼层看板"
        extra={<span className="text-xs text-slate-500">共 {rows.length} 栋</span>}
      >
        {rows.length === 0 ? (
          <EmptyState text="暂无楼栋数据" hint="当前园区尚未录入楼栋资产。" />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((b) => {
              const rate = Number(b.occupancy_rate) || 0
              const active = buildingId === b.id
              return (
                <button
                  key={b.id}
                  onClick={() => toggleBuilding(b.id)}
                  className={cx(
                    'group rounded-xl border p-4 text-left transition-all',
                    active
                      ? 'border-brand-400/60 bg-brand-500/10 shadow-glow-brand'
                      : 'border-white/10 bg-white/[0.04] hover:border-brand-400/45 hover:bg-white/[0.06]',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-100">
                        {b.building_name ?? b.name ?? `楼栋 #${b.id}`}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">
                        {b.building_code ?? '—'} · {text(BUILDING_TYPE, b.building_type)}
                        {b.floor_count != null && ` · ${b.floor_count} 层`}
                      </div>
                    </div>
                    <Tag tone={rate >= 90 ? 'ok' : rate >= 70 ? 'info' : 'warn'}>
                      {rate.toFixed(1)}%
                    </Tag>
                  </div>

                  <div className="mt-3">
                    <ProgressBar value={rate} />
                  </div>

                  <div className="mt-3 flex items-center gap-4 text-[11px]">
                    <span className="text-slate-500">
                      空间 <b className="font-num text-slate-200">{b.space_count ?? '—'}</b>
                    </span>
                    <span className="text-slate-500">
                      已租 <b className="font-num text-state-ok">{b.rented_count ?? '—'}</b>
                    </span>
                    <span className="text-slate-500">
                      空置 <b className="font-num text-state-warn">{b.vacant_count ?? '—'}</b>
                    </span>
                  </div>

                  <div className="mt-3 flex items-center justify-between text-[11px] text-slate-600">
                    <span>可租 {(Number(b.rentable_area) || 0).toLocaleString()} ㎡</span>
                    {b.enterprise_count != null && <span>{b.enterprise_count} 家企业</span>}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </Panel>

      {/* ------------------------------------------------------ 楼层看板 */}
      {buildingId != null && (
        <Panel
          title="楼层看板"
          subtitle={board.data?.building?.building_name ?? '按楼层展示空间出租状态'}
          extra={<Btn variant="ghost" onClick={() => toggleBuilding(buildingId)}>关闭</Btn>}
        >
          {board.loading ? (
            <Loading text="正在加载楼层数据…" />
          ) : board.error ? (
            <ErrorState error={board.error} onRetry={board.reload} />
          ) : (
            <BoardView data={board.data} onOpen={openSpace} />

          )}
        </Panel>
      )}

      {/* ------------------------------------------------------ 空间列表 */}
      <Panel
        title="空间单元"
        subtitle={`共 ${total} 个单元`}
        extra={
          <div className="flex items-center gap-2">
            <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
            <span className="font-num text-xs text-slate-500">{page} / {pages}</span>
            <Btn variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>下一页</Btn>
          </div>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <Field label="空间类型">
            <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">全部类型</option>
              {Object.entries(SPACE_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="出租状态">
            <select className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">全部状态</option>
              {Object.entries(SPACE_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </Field>
          {(type || status || buildingId != null) && (
            <Btn variant="ghost" onClick={clearFilters}>清空筛选</Btn>
          )}
        </div>

        <DataTable
          columns={[
            { key: 'space_code', title: '编号' },
            { key: 'space_name', title: '名称' },
            { key: 'building_name', title: '所属楼栋', render: (r) => r.building_name ?? '—' },
            { key: 'floor_no', title: '楼层', render: (r) => r.floor_no ?? '—' },
            { key: 'space_type', title: '类型', render: (r) => text(SPACE_TYPE, r.space_type) },
            { key: 'area', title: '面积(㎡)', align: 'right', render: (r) => Number(r.area ?? 0).toLocaleString() },
            {
              key: 'status', title: '状态',
              render: (r) => {
                const s = SPACE_STATUS[r.status] ?? { label: r.status ?? '—', tone: 'muted' }
                return <Tag tone={s.tone}>{s.label}</Tag>
              },
            },
            {
              key: 'enterprise_name', title: '承租企业',
              render: (r) => r.enterprise_name ?? r.tenant_name ?? <span className="text-slate-600">空置</span>,
            },
            {
              key: 'property_price', title: '物业费', align: 'right',
              render: (r) => (r.property_price != null
                ? `${Number(r.property_price).toFixed(2)} 元/㎡`
                : <span className="text-slate-600">—</span>),
            },
          ]}
          rows={list}
          loading={spaces.loading}
          error={spaces.error}
          onRetry={spaces.reload}
          rowKey={(r) => r.id}
          empty="没有匹配的空间单元"
        />
      </Panel>

      {/* --------------------------------------------------------- 图表 */}
      {buildingChart.length > 0 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <Panel title="楼栋出租率排行" subtitle="按 occupancy_rate 降序取前 12 栋">
              <Chart
                height={300}
                option={barOption({
                  x: buildingChart.map((b) => Number(b.occupancy_rate) || 0),
                  series: [{ name: '出租率(%)', data: buildingChart.map((b) => Number(b.occupancy_rate) || 0) }],
                  horizontal: true,
                  showLegend: false,
                })}
              />
            </Panel>
          </div>
          <Panel title="空间类型分布" subtitle="基于当前筛选结果统计">
            <Chart height={300} option={pieOption({ data: typeDist })} empty={typeDist.length === 0} />
          </Panel>
        </div>
      )}
      {/* ---------------------------------------------- 空间详情抽屉 */}
      {spaceDetail && createPortal(
        <div
          className="fixed inset-0 flex justify-end bg-black/55 backdrop-blur-sm"
          style={{ zIndex: 9200 }}
          onClick={() => setSpaceDetail(null)}
        >
          <div
            className="h-full w-full max-w-md overflow-y-auto border-l border-white/10"
            style={{ backgroundColor: '#0D1B2A' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="sticky top-0 flex items-start justify-between gap-3 border-b border-white/8 px-5 py-4"
              style={{ backgroundColor: '#0D1B2A' }}
            >
              <div>
                <h3 className="text-[15px] font-semibold text-slate-100">
                  {spaceDetail.space?.space_name ?? spaceDetail.space?.space_code ?? '空间详情'}
                </h3>
                <p className="mt-0.5 text-xs text-slate-500">
                  {spaceLoading ? '加载中…' : [
                    spaceDetail.building?.building_name,
                    spaceDetail.floor?.floor_name,
                    spaceDetail.space?.space_code,
                  ].filter(Boolean).join(' · ')}
                </p>
              </div>
              <Btn size="sm" variant="ghost" onClick={() => setSpaceDetail(null)}>关闭</Btn>
            </div>

            {spaceLoading ? (
              <div className="p-5"><Loading text="正在读取空间信息…" /></div>
            ) : (
              <div className="space-y-5 p-5">
                {/* 基本属性 */}
                <section className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border border-white/8 px-3 py-2">
                    <p className="text-[10px] text-slate-500">状态</p>
                    <div className="mt-1">
                      <Tag tone={(SPACE_STATUS[spaceDetail.space?.status]?.tone ?? 'muted') as any}>
                        {SPACE_STATUS[spaceDetail.space?.status]?.label ?? spaceDetail.space?.status ?? '—'}
                      </Tag>
                    </div>
                  </div>
                  <div className="rounded-lg border border-white/8 px-3 py-2">
                    <p className="text-[10px] text-slate-500">可租面积</p>
                    <p className="mt-0.5 font-num text-sm text-slate-200">
                      {Number(spaceDetail.space?.rentable_area ?? spaceDetail.space?.area ?? 0).toLocaleString()} ㎡
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/8 px-3 py-2">
                    <p className="text-[10px] text-slate-500">挂牌租金</p>
                    <p className="mt-0.5 font-num text-sm text-slate-200">
                      {spaceDetail.space?.rent_price ?? '—'} 元/㎡/月
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/8 px-3 py-2">
                    <p className="text-[10px] text-slate-500">物业费</p>
                    <p className="mt-0.5 font-num text-sm text-slate-200">
                      {spaceDetail.space?.property_price ?? '—'} 元/㎡/月
                    </p>
                  </div>
                  {spaceDetail.space?.vacant_since && (
                    <div className="col-span-2 rounded-lg border border-state-warn/25 bg-state-warn/[0.06] px-3 py-2 text-[11px] text-state-warn">
                      空置起始于 {spaceDetail.space.vacant_since}，
                      已空置 {Math.max(0, Math.floor((Date.now() - new Date(spaceDetail.space.vacant_since).getTime()) / 86400000))} 天
                    </div>
                  )}
                </section>

                {/* 承租企业 */}
                <section>
                  <h4 className="mb-2 text-[13px] font-medium text-slate-200">承租企业</h4>
                  {spaceDetail.enterprise ? (
                    <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-[13px] text-slate-100">{spaceDetail.enterprise.enterprise_name}</span>
                        <Tag tone="ok">{spaceDetail.enterprise.status === 'SETTLED' ? '入驻' : spaceDetail.enterprise.status === 'GROWING' ? '成长' : spaceDetail.enterprise.status}</Tag>
                      </div>
                      <p className="mt-1 text-[11px] text-slate-500">{spaceDetail.enterprise.industry ?? '行业未填写'}</p>
                      <Btn size="sm" variant="ghost" className="mt-2"
                           onClick={() => { setSpaceDetail(null); nav(`/enterprise?id=${spaceDetail.enterprise.id}`) }}>
                        查看企业档案
                      </Btn>
                    </div>
                  ) : (
                    <p className="rounded-lg border border-white/8 px-3 py-2 text-xs text-slate-500">
                      该空间暂无承租企业
                    </p>
                  )}
                </section>

                {/* 合同 */}
                <section>
                  <h4 className="mb-2 text-[13px] font-medium text-slate-200">
                    租赁合同 <span className="ml-1 text-[11px] text-slate-500">{spaceDetail.contracts?.length ?? 0} 份</span>
                  </h4>
                  {(spaceDetail.contracts ?? []).length === 0 ? (
                    <p className="rounded-lg border border-white/8 px-3 py-2 text-xs text-slate-500">无合同记录</p>
                  ) : (
                    <ul className="space-y-2">
                      {spaceDetail.contracts.map((c: any) => (
                        <li key={c.id} className="rounded-lg border border-white/8 px-3 py-2">
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-[12px] text-slate-200">{c.contract_code}</span>
                            <Tag tone={c.status === 'ACTIVE' ? 'ok' : c.status === 'EXPIRING' ? 'warn' : 'muted'}>
                              {c.status === 'ACTIVE' ? '生效中' : c.status === 'EXPIRING' ? '即将到期' : c.status}
                            </Tag>
                          </div>
                          <p className="mt-1 text-[11px] text-slate-500">
                            {c.start_date ?? '—'} 至 {c.end_date ?? '—'} · 月租金 {Number(c.monthly_rent ?? 0).toLocaleString()} 元
                            {c.multi_space ? ' · 合并签约，覆盖该企业多间空间' : ''}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {/* 工单 */}
                {(spaceDetail.work_orders ?? []).length > 0 && (
                  <section>
                    <h4 className="mb-2 text-[13px] font-medium text-slate-200">相关工单</h4>
                    <ul className="space-y-1.5">
                      {spaceDetail.work_orders.slice(0, 5).map((o: any) => (
                        <li key={o.id} className="flex items-center justify-between gap-2 text-[12px] text-slate-300">
                          <span className="truncate">{o.title}</span>
                          <span className="shrink-0 text-[11px] text-slate-500">{o.status}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <p className="pt-1 text-[11px] text-slate-600">
                  租用登记与合同变更请到「合同管理」办理，这里只做查看，避免出现"已出租但无合同"的状态。
                </p>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}

    </div>
  )
}

/* -------------------------------------------------------- 楼层看板子组件 */

function BoardView({ data, onOpen }: { data: any; onOpen: (id: number) => void }) {
  if (!data) return <EmptyState text="暂无楼层数据" />

  const rows: AnyRow[] = data.rows ?? []
  const legend: AnyRow[] = data.status_legend ?? []

  const colorOf = (status?: string | null) => {
    const hit = legend.find((l) => l.status === status || l.key === status)
    return hit?.color ?? '#2F80ED'
  }
  const labelOf = (status?: string | null) => {
    const hit = legend.find((l) => l.status === status || l.key === status)
    return hit?.label ?? hit?.name ?? SPACE_STATUS[status ?? '']?.label ?? status ?? '—'
  }

  const hasSpaces = rows.some((r) => Array.isArray(r.spaces))

  return (
    <div className="space-y-4">
      {legend.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          {legend.map((l) => (
            <span key={l.status ?? l.key} className="flex items-center gap-1.5 text-xs text-slate-400">
              <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: l.color ?? '#2F80ED' }} />
              {l.label ?? l.name}
            </span>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState text="该楼栋暂无空间数据" />
      ) : hasSpaces ? (
        <div className="space-y-3">
          {rows.map((f, i) => (
            <div key={f.floor_no ?? f.floor ?? i} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-200">
                  {f.floor_name ?? `${f.floor_no ?? f.floor ?? i + 1} 层`}
                </span>
                <span className="text-slate-500">
                  {f.space_count ?? f.spaces?.length ?? 0} 个单元 · 出租率 {Number(f.occupancy_rate ?? 0).toFixed(1)}%
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(f.spaces ?? []).map((s: AnyRow) => (
                  // 按楼层分组的看板才是实际渲染的那一支；原来这里是不可点的 div，
                  // 点不进去也看不到承租企业
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => onOpen(s.id)}
                    title={`${s.space_code ?? ''} ${s.space_name ?? ''}｜${labelOf(s.status)}｜${Number(s.area ?? 0).toLocaleString()}㎡（点击查看详情）`}
                    className="h-9 w-16 rounded border transition-transform hover:scale-105 hover:brightness-150 focus:outline-none focus:ring-1 focus:ring-brand-400"
                    style={{ background: `${colorOf(s.status)}33`, borderColor: `${colorOf(s.status)}88` }}
                  >
                    <span className="flex h-full items-center justify-center text-[10px] font-medium text-slate-100">
                      {String(s.space_code ?? s.space_name ?? '').slice(-5)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {rows.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onOpen(s.id)}
              title={`${s.space_code ?? ''} ${s.space_name ?? ''}｜${labelOf(s.status)}｜${Number(s.area ?? 0).toLocaleString()}㎡（点击查看详情）`}
              className="rounded-lg border p-2.5 text-left transition-transform hover:scale-[1.03] hover:brightness-125"
              style={{ background: `${colorOf(s.status)}22`, borderColor: `${colorOf(s.status)}66` }}
            >
              <div className="truncate text-[11px] font-medium text-slate-100">{s.space_code ?? `#${s.id}`}</div>
              <div className="mt-1 text-[10px] text-slate-400">{labelOf(s.status)}</div>
              <div className="font-num text-[10px] text-slate-500">{Number(s.area ?? 0).toLocaleString()} ㎡</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * 园区数字孪生
 *
 * 数据来源：GET /space/parks/{id}/twin
 *  - nodes[]：楼栋节点，含 2.5D 定位（map_x/map_y/map_w/map_d/map_h）
 *    以及运营画像（出租率、空间数、设备数、未闭环工单/事件）
 *  - legend[]：楼栋运营等级 -> 颜色（由后端统一定义，前端不重复维护）
 *  - stats{}：园区整体统计
 *
 * 渲染：SVG 等轴测投影。不引入 3D 库，保证构建体积与渲染稳定性。
 * 楼栋颜色一律取自后端 legend，避免前后端配色口径不一致。
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Boxes,
  Building2,
  Info,
  Layers,
  RefreshCw,
  TriangleAlert,
  Wrench,
} from 'lucide-react'
import { spaceApi } from '@/api/modules'
import { useAuth } from '@/context/AuthContext'
import { useAsync } from '@/hooks/useAsync'
import {
  Btn,
  DemoBadge,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Panel,
  ProgressBar,
  StatLine,
  Tag,
  cx,
} from '@/components/ui'
import { Chart, pieOption } from '@/components/Charts'

interface TwinNode {
  id: number
  building_code: string
  building_name: string
  building_type?: string
  floor_count?: number | null
  build_area?: number | null
  rentable_area?: number | null
  rented_area?: number | null
  occupancy_rate?: number | null
  space_count?: number | null
  rented_count?: number | null
  vacant_count?: number | null
  vacant_area?: number | null
  enterprise_count?: number | null
  device_count?: number | null
  device_fault?: number | null
  open_work_order?: number | null
  open_incident?: number | null
  level?: string
  map_x?: number | null
  map_y?: number | null
  map_w?: number | null
  map_d?: number | null
  map_h?: number | null
  status?: string
}

const FALLBACK_COLOR = '#2F80ED'

/** 等轴测投影 */
const ISO_X = 0.866
const ISO_Y = 0.5

export default function Twin() {
  const { activeParkId, visibleParkIds, setActiveParkId } = useAuth()
  const nav = useNavigate()

  const parks = useAsync(() => spaceApi.parks(), [])
  const parkList = useMemo(() => {
    const list = ((parks.data as any)?.items ?? []) as any[]
    return visibleParkIds ? list.filter((p) => visibleParkIds.includes(p.id)) : list
  }, [parks.data, visibleParkIds])

  const parkId = activeParkId ?? parkList[0]?.id ?? null
  const twin = useAsync(
    () => (parkId ? spaceApi.twin(parkId) : Promise.resolve(null)),
    [parkId],
    { enabled: !!parkId },
  )

  const nodes = useMemo<TwinNode[]>(() => ((twin.data as any)?.nodes ?? []) as TwinNode[], [twin.data])
  const stats = (twin.data as any)?.stats ?? {}
  const parkInfo = (twin.data as any)?.park ?? {}
  const legend = ((twin.data as any)?.legend ?? []) as { key: string; name: string; color: string }[]

  const colorOf = useMemo(() => {
    const m = new Map(legend.map((l) => [l.key, l.color]))
    return (key?: string) => m.get(key ?? '') ?? FALLBACK_COLOR
  }, [legend])

  const [hover, setHover] = useState<number | null>(null)
  const [selected, setSelected] = useState<TwinNode | null>(null)

  // 投影范围
  const proj = useMemo(() => {
    if (nodes.length === 0) return null
    const xs = nodes.map((b) => b.map_x ?? 0)
    const ys = nodes.map((b) => b.map_y ?? 0)
    const minX = Math.min(...xs)
    const minY = Math.min(...ys)
    return {
      minX,
      minY,
      spanX: Math.max(Math.max(...xs) - minX, 1),
      spanY: Math.max(Math.max(...ys) - minY, 1),
    }
  }, [nodes])

  if (parks.loading) return <Loading text="正在加载园区列表…" />
  if (parks.error) return <ErrorState error={parks.error} onRetry={parks.reload} />
  if (parkList.length === 0) return <EmptyState text="当前账号没有可见园区" />

  return (
    <div className="space-y-4">
      <PageHeader
        title="园区数字孪生"
        demo
        desc={`${parkInfo.park_name ?? '园区'} · 楼栋 2.5D 布局与运营状态可视化，配色由后端 legend 统一下发`}
        extra={
          <>
            {parkList.length > 1 && (
              <select
                value={parkId ?? ''}
                onChange={(e) => setActiveParkId(Number(e.target.value))}
                className="rounded-lg border border-white/12 bg-white/[0.05] px-2.5 py-1.5 text-[13px] text-slate-200 outline-none"
              >
                {parkList.map((p) => (
                  <option key={p.id} value={p.id} className="bg-nav-panel">
                    {p.park_name}
                  </option>
                ))}
              </select>
            )}
            <Btn onClick={twin.reload} loading={twin.loading}>
              <RefreshCw size={13} /> 刷新
            </Btn>
          </>
        }
      />

      {/* 图例：直接消费后端 legend */}
      {legend.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-white/8 bg-panel-grad px-4 py-2.5 text-[11px] backdrop-blur-[14px]">
          <span className="text-slate-400">楼栋状态图例：</span>
          {legend.map((l) => (
            <span key={l.key} className="flex items-center gap-1.5 text-slate-400">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: l.color }} />
              {l.name}
            </span>
          ))}
          <span className="ml-auto flex items-center gap-1.5 text-slate-500">
            <Info size={12} /> 体块高度按 map_h 等比映射，仅示意
          </span>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.55fr_1fr]">
        {/* 2.5D */}
        <Panel
          title="园区楼栋布局（2.5D 等轴测）"
          subtitle="点击楼栋查看运营画像"
          icon={<Boxes size={15} />}
          padded={false}
        >
          {twin.loading ? (
            <Loading />
          ) : twin.error ? (
            <div className="p-4">
              <ErrorState error={twin.error} onRetry={twin.reload} />
            </div>
          ) : nodes.length === 0 ? (
            <div className="p-4">
              <EmptyState
                text="该园区尚未配置楼栋坐标"
                hint="数字孪生视图依赖楼栋的 map_x / map_y / map_w / map_d / map_h 定位字段"
              />
            </div>
          ) : (
            <div className="relative p-4">
              <svg viewBox="0 0 720 480" className="w-full" style={{ maxHeight: 480 }}>
                <defs>
                  <linearGradient id="twinGround" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(47,128,237,0.12)" />
                    <stop offset="100%" stopColor="rgba(47,128,237,0.02)" />
                  </linearGradient>
                </defs>

                <rect x="0" y="0" width="720" height="480" fill="url(#twinGround)" rx="12" />
                {/* 地面网格 */}
                {Array.from({ length: 15 }).map((_, i) => (
                  <line key={`gx-${i}`} x1={i * 52} y1="0" x2={i * 52} y2="480"
                    stroke="rgba(80,180,255,0.05)" strokeWidth="1" />
                ))}
                {Array.from({ length: 10 }).map((_, i) => (
                  <line key={`gy-${i}`} x1="0" y1={i * 52} x2="720" y2={i * 52}
                    stroke="rgba(80,180,255,0.05)" strokeWidth="1" />
                ))}

                {proj &&
                  nodes.map((b) => {
                    const nx = ((b.map_x ?? 0) - proj.minX) / proj.spanX
                    const ny = ((b.map_y ?? 0) - proj.minY) / proj.spanY
                    const w = ((b.map_w ?? 10) / proj.spanX) * 380
                    const d = ((b.map_d ?? 10) / proj.spanY) * 190
                    // map_h 是相对高度（实测取值 30-60），压缩到 20-90px 视觉区间
                    const h = Math.max(22, Math.min(96, ((b.map_h ?? 30) / 60) * 92))

                    const ox = 118 + nx * 380
                    const oy = 150 + ny * 180
                    const iso = (x: number, y: number) => ({
                      sx: ox + (x - y) * ISO_X,
                      sy: oy + (x + y) * ISO_Y,
                    })
                    const p0 = iso(0, 0)
                    const p1 = iso(w, 0)
                    const p2 = iso(w, d)
                    const p3 = iso(0, d)
                    const up = (p: { sx: number; sy: number }) => ({ sx: p.sx, sy: p.sy - h })
                    const t0 = up(p0)
                    const t1 = up(p1)
                    const t2 = up(p2)
                    const t3 = up(p3)

                    const isHover = hover === b.id
                    const isSel = selected?.id === b.id
                    const color = colorOf(b.level)
                    const dim = hover !== null && !isHover && !isSel

                    return (
                      <g
                        key={b.id}
                        className="cursor-pointer"
                        opacity={dim ? 0.6 : 1}
                        onMouseEnter={() => setHover(b.id)}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => setSelected(b)}
                      >
                        {/* 左面（较暗） */}
                        <polygon
                          points={`${p3.sx},${p3.sy} ${p2.sx},${p2.sy} ${t2.sx},${t2.sy} ${t3.sx},${t3.sy}`}
                          fill={color}
                          opacity="0.32"
                        />
                        {/* 右面（中等） */}
                        <polygon
                          points={`${p1.sx},${p1.sy} ${p2.sx},${p2.sy} ${t2.sx},${t2.sy} ${t1.sx},${t1.sy}`}
                          fill={color}
                          opacity="0.52"
                        />
                        {/* 顶面（最亮） */}
                        <polygon
                          points={`${t0.sx},${t0.sy} ${t1.sx},${t1.sy} ${t2.sx},${t2.sy} ${t3.sx},${t3.sy}`}
                          fill={color}
                          opacity={isHover || isSel ? 0.95 : 0.78}
                          stroke={isSel ? '#00D4FF' : color}
                          strokeWidth={isSel ? 2 : 1}
                          strokeLinejoin="round"
                        />
                        {/* 有未闭环安全事件时加警示角标 */}
                        {(b.open_incident ?? 0) > 0 && (
                          <g>
                            <circle cx={t1.sx} cy={t1.sy} r="6" fill="#EB5757" />
                            <text x={t1.sx} y={t1.sy + 3.2} fontSize="8" fill="#fff"
                              textAnchor="middle" fontWeight="bold">
                              !
                            </text>
                          </g>
                        )}
                        {/* 悬浮/选中标签 */}
                        {(isHover || isSel) && (
                          <g>
                            <rect
                              x={t0.sx - 62}
                              y={t0.sy - 34}
                              width="136"
                              height="26"
                              rx="5"
                              fill="rgba(7,17,31,0.95)"
                              stroke="rgba(255,255,255,0.2)"
                            />
                            <text x={t0.sx + 6} y={t0.sy - 17} fill="#E2E8F0"
                              fontSize="10.5" textAnchor="middle">
                              {b.building_name} · 出租 {b.occupancy_rate ?? 0}%
                            </text>
                          </g>
                        )}
                      </g>
                    )
                  })}
              </svg>

              {/* 楼栋快捷选择 */}
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
                {nodes.map((b) => (
                  <button
                    key={b.id}
                    onMouseEnter={() => setHover(b.id)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => setSelected(b)}
                    className={cx(
                      'flex items-center gap-1.5 text-[11px] transition',
                      selected?.id === b.id
                        ? 'text-brand-300'
                        : 'text-slate-400 hover:text-slate-200',
                    )}
                  >
                    <span
                      className="h-2 w-2 rounded-sm"
                      style={{ background: colorOf(b.level) }}
                    />
                    {b.building_name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </Panel>

        {/* 右栏 */}
        <div className="space-y-4">
          <Panel title="园区概况" subtitle={parkInfo.park_name} icon={<Building2 size={15} />}>
            <div className="space-y-3.5">
              <StatLine
                items={[
                  { label: '楼栋', value: `${stats.building_count ?? nodes.length} 栋` },
                  { label: '空间单元', value: `${stats.space_count ?? 0} 个` },
                ]}
              />
              <StatLine
                items={[
                  { label: '入驻企业', value: `${stats.enterprise_count ?? 0} 家` },
                  {
                    label: '招商压力楼栋',
                    value: `${stats.vacant_building_count ?? 0} 栋`,
                    tone: (stats.vacant_building_count ?? 0) > 0 ? '#F2994A' : undefined,
                  },
                ]}
              />
              <div>
                <div className="mb-1 flex items-baseline justify-between text-[11px]">
                  <span className="text-slate-500">整体出租率</span>
                  <span className="font-num text-slate-300">{stats.occupancy_rate ?? 0}%</span>
                </div>
                <ProgressBar
                  value={stats.occupancy_rate ?? 0}
                  tone={(stats.occupancy_rate ?? 0) >= 60 ? 'ok' : 'warn'}
                />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 border-t border-white/8 pt-3 text-[11px]">
                <span className="text-slate-500">
                  建筑面积 <span className="font-num text-slate-300">{((parkInfo.build_area ?? 0) / 10000).toFixed(2)} 万㎡</span>
                </span>
                <span className="text-slate-500">
                  占地面积 <span className="font-num text-slate-300">{((parkInfo.total_area ?? 0) / 10000).toFixed(2)} 万㎡</span>
                </span>
              </div>
              {parkInfo.address && (
                <p className="text-[11px] leading-relaxed text-slate-500">
                  {parkInfo.city ?? ''} {parkInfo.address}
                </p>
              )}
            </div>
          </Panel>

          {selected ? (
            <Panel
              title={selected.building_name}
              subtitle={`${selected.building_code} · ${selected.floor_count ?? 0} 层 · ${selected.building_type ?? ''}`}
              icon={<Layers size={15} />}
              extra={
                <Btn size="sm" variant="ghost" onClick={() => setSelected(null)}>
                  关闭
                </Btn>
              }
            >
              <div className="space-y-3.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-slate-500">运营状态</span>
                  <Tag
                    tone={
                      selected.level === 'GOOD'
                        ? 'ok'
                        : selected.level === 'RISK'
                          ? 'danger'
                          : selected.level === 'VACANT'
                            ? 'warn'
                            : 'info'
                    }
                  >
                    {legend.find((l) => l.key === selected.level)?.name ?? selected.level ?? '—'}
                  </Tag>
                </div>

                <StatLine
                  items={[
                    { label: '空间', value: `${selected.space_count ?? 0} 个` },
                    { label: '已租', value: `${selected.rented_count ?? 0} 个` },
                    { label: '空置', value: `${selected.vacant_count ?? 0} 个` },
                  ]}
                />

                <div>
                  <div className="mb-1 flex items-baseline justify-between text-[11px]">
                    <span className="text-slate-500">出租率</span>
                    <span className="font-num text-slate-300">
                      {selected.rented_area ?? 0} / {selected.rentable_area ?? 0} ㎡
                    </span>
                  </div>
                  <ProgressBar
                    value={selected.occupancy_rate ?? 0}
                    tone={(selected.occupancy_rate ?? 0) >= 60 ? 'ok' : 'warn'}
                  />
                </div>

                <div className="grid grid-cols-2 gap-2.5">
                  <div className="rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                    <p className="text-[10px] text-slate-500">入驻企业</p>
                    <p className="mt-0.5 font-num text-base text-slate-200">
                      {selected.enterprise_count ?? 0}
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                    <p className="text-[10px] text-slate-500">设备总数</p>
                    <p className="mt-0.5 font-num text-base text-slate-200">
                      {selected.device_count ?? 0}
                    </p>
                  </div>
                  <div
                    className={cx(
                      'rounded-lg border p-2.5',
                      (selected.device_fault ?? 0) > 0
                        ? 'border-state-warn/28 bg-state-warn/[0.07]'
                        : 'border-white/8 bg-white/[0.03]',
                    )}
                  >
                    <p className="flex items-center gap-1 text-[10px] text-slate-500">
                      <Wrench size={10} /> 设备故障
                    </p>
                    <p
                      className={cx(
                        'mt-0.5 font-num text-base',
                        (selected.device_fault ?? 0) > 0 ? 'text-state-warn' : 'text-slate-200',
                      )}
                    >
                      {selected.device_fault ?? 0}
                    </p>
                  </div>
                  <div
                    className={cx(
                      'rounded-lg border p-2.5',
                      (selected.open_work_order ?? 0) > 0
                        ? 'border-brand-500/28 bg-brand-500/[0.07]'
                        : 'border-white/8 bg-white/[0.03]',
                    )}
                  >
                    <p className="flex items-center gap-1 text-[10px] text-slate-500">
                      <Wrench size={10} /> 未闭环工单
                    </p>
                    <p className="mt-0.5 font-num text-base text-slate-200">
                      {selected.open_work_order ?? 0}
                    </p>
                  </div>
                  {(selected.open_incident ?? 0) > 0 && (
                    <div className="col-span-2 flex items-center gap-2 rounded-lg border border-state-danger/28 bg-state-danger/[0.07] px-2.5 py-2">
                      <TriangleAlert size={13} className="text-state-danger" />
                      <span className="text-[11px] text-state-danger">
                        有 {selected.open_incident} 起未闭环安全事件
                      </span>
                    </div>
                  )}
                </div>

                <Btn size="sm" onClick={() => nav(`/space?building=${selected.id}`)}>
                  查看空间明细
                </Btn>
              </div>
            </Panel>
          ) : (
            <Panel title="楼栋出租率排行" subtitle="点击查看运营画像" icon={<Layers size={15} />}>
              {nodes.length === 0 ? (
                <EmptyState text="暂无楼栋数据" />
              ) : (
                <div className="space-y-2.5">
                  {[...nodes]
                    .sort((a, b) => (b.occupancy_rate ?? 0) - (a.occupancy_rate ?? 0))
                    .map((b) => (
                      <button
                        key={b.id}
                        onClick={() => setSelected(b)}
                        onMouseEnter={() => setHover(b.id)}
                        onMouseLeave={() => setHover(null)}
                        className="flex w-full items-center gap-3 text-left"
                      >
                        <span className="w-24 shrink-0 truncate text-[12px] text-slate-300">
                          {b.building_name}
                        </span>
                        <div className="flex-1">
                          <ProgressBar
                            value={b.occupancy_rate ?? 0}
                            tone={(b.occupancy_rate ?? 0) >= 60 ? 'ok' : 'warn'}
                          />
                        </div>
                        <span className="w-12 shrink-0 text-right font-num text-[11px] text-slate-400">
                          {b.occupancy_rate ?? 0}%
                        </span>
                      </button>
                    ))}
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>

      {/* 楼栋对比 */}
      {nodes.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="空间状态构成" subtitle="全园区空间单元状态分布">
            <Chart
              height={236}
              empty={nodes.reduce((s, b) => s + (b.space_count ?? 0), 0) === 0}
              option={pieOption({
                data: [
                  {
                    name: '已租',
                    value: nodes.reduce((s, b) => s + (b.rented_count ?? 0), 0),
                    color: '#22C55E',
                  },
                  {
                    name: '空置',
                    value: nodes.reduce((s, b) => s + (b.vacant_count ?? 0), 0),
                    color: '#64748B',
                  },
                ],
                centerLabel: {
                  title: '空间总数',
                  value: nodes.reduce((s, b) => s + (b.space_count ?? 0), 0),
                },
              })}
            />
          </Panel>

          <Panel title="楼栋运营对比" subtitle="出租率 / 入驻企业 / 未闭环工单">
            <div className="space-y-3">
              {nodes.map((b) => (
                <div key={b.id} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => setSelected(b)}
                      onMouseEnter={() => setHover(b.id)}
                      onMouseLeave={() => setHover(null)}
                      className="truncate text-[12px] text-slate-300 hover:text-brand-300"
                    >
                      {b.building_name}
                    </button>
                    <div className="flex shrink-0 items-center gap-3 font-num text-[11px]">
                      <span className="text-slate-400">
                        {b.enterprise_count ?? 0} 家企业
                      </span>
                      <span
                        className={cx(
                          (b.open_work_order ?? 0) > 0 ? 'text-state-warn' : 'text-slate-500',
                        )}
                      >
                        {b.open_work_order ?? 0} 工单
                      </span>
                      <span
                        className={cx(
                          (b.open_incident ?? 0) > 0 ? 'text-state-danger' : 'text-slate-500',
                        )}
                      >
                        {b.open_incident ?? 0} 事件
                      </span>
                    </div>
                  </div>
                  <ProgressBar
                    value={b.occupancy_rate ?? 0}
                    tone={(b.occupancy_rate ?? 0) >= 60 ? 'ok' : 'warn'}
                    showText
                  />
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-slate-600">
        <DemoBadge className="mr-1.5" />
        楼栋坐标与运营指标由后端实时聚合，颜色口径见顶部图例。
      </p>
    </div>
  )
}

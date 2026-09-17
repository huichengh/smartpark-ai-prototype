/**
 * 数据中心 —— 数据资产 / 质量 / 血缘 / 导入
 *
 * 设计要点：
 *  - 行数、质量分、血缘链路全部由后端实时统计（/data/overview|catalog|quality|lineage），
 *    前端不做任何本地累加。
 *  - 「可见行数」是后端按当前账号数据权限过滤后的结果，与「总行数」并列展示，
 *    让数据权限范围可见、可验证。
 *  - 质量六维评分与血缘公式原样展示，保证口径可追溯（不隐藏计算方法）。
 */
import { useState } from 'react'
import { dataApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Segmented, Tag,
} from '@/components/ui'
import { Chart, pieOption } from '@/components/Charts'
import { Database, GitBranch, Layers, RefreshCw, ShieldCheck, Upload } from 'lucide-react'

type AnyRow = Record<string, any>

/** 资产表中文名（纯展示映射，后端 assets 只回计数） */
const ASSET_LABELS: Record<string, string> = {
  parks: '园区', buildings: '楼宇', spaces: '空间单元', enterprises: '企业',
  contracts: '租赁合同', bills: '应收账单', payments: '收款流水', leads: '招商线索',
  projects: '项目', wbs: 'WBS 任务', work_orders: '工单', devices: '设备',
  energy_records: '能耗记录', safety_incidents: '安全事件', safety_hazards: '安全隐患',
}

const QUALITY_DIMS: { key: string; label: string; hint: string }[] = [
  { key: 'completeness', label: '完整性', hint: '非空字段占比' },
  { key: 'uniqueness', label: '唯一性', hint: '去重后占比' },
  { key: 'validity', label: '有效性', hint: '通过格式/枚举校验占比' },
  { key: 'consistency', label: '一致性', hint: '跨表勾稽一致占比' },
  { key: 'timeliness', label: '时效性', hint: '在更新周期内占比' },
]

const scoreTone = (v: number) => (v >= 95 ? 'ok' : v >= 85 ? 'brand' : v >= 70 ? 'warn' : 'danger')

const fmtNum = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: d })

export default function DataCenter() {
  const [tab, setTab] = useState<'asset' | 'quality' | 'lineage' | 'upload'>('asset')

  const overview = useAsync(() => dataApi.overview(), [])
  const catalog = useAsync(() => dataApi.catalog(), [], { enabled: tab === 'asset' })
  const quality = useAsync(() => dataApi.quality(), [], { enabled: tab === 'quality' })
  const lineage = useAsync(() => dataApi.lineage(), [], { enabled: tab === 'lineage' })
  const uploads = useAsync(() => dataApi.uploads({ page: 1, page_size: 20 }), [], {
    enabled: tab === 'upload',
  })

  const assets: AnyRow = overview.data?.assets ?? {}
  const cat: AnyRow = catalog.data ?? {}
  const q: AnyRow = quality.data?.summary ?? {}
  const chains: AnyRow[] = lineage.data?.chains ?? []
  const up: AnyRow = uploads.data ?? {}
  const upStats: AnyRow = up.stats ?? {}

  const refreshAll = () => {
    overview.reload(); catalog.reload(); quality.reload(); lineage.reload(); uploads.reload()
  }

  const domainOption = pieOption({
    data: (cat.domains ?? []).map((d: AnyRow) => ({ name: d.domain, value: Number(d.rows) || 0 })),
    centerLabel: { title: '总行数', value: fmtNum(cat.summary?.row_total) },
  })

  return (
    <div className="space-y-5">
      <PageHeader
        title="数据中心"
        desc="数据资产盘点、质量评分、指标血缘追溯与导入记录；行数均为数据库实时 COUNT 结果。"
        demo
        extra={<Btn variant="ghost" onClick={refreshAll}><RefreshCw size={13} /> 刷新</Btn>}
      />

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: 'asset', label: '数据资产' },
          { value: 'quality', label: '数据质量' },
          { value: 'lineage', label: '指标血缘' },
          { value: 'upload', label: '数据导入' },
        ]}
      />

      {/* ============================================ 数据资产 */}
      {tab === 'asset' && (
        <>
          {overview.loading ? (
            <Panel><Loading text="正在盘点数据资产…" /></Panel>
          ) : overview.error ? (
            <Panel><ErrorState error={overview.error} onRetry={overview.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <KpiCard
                  label="数据表" value={cat.summary?.table_total ?? '—'} unit="张" tone="brand"
                  hint={`${cat.summary?.domain_total ?? 0} 个业务域`}
                />
                <KpiCard
                  label="数据总行数" value={fmtNum(cat.summary?.row_total)} unit="行" tone="ai"
                />
                <KpiCard
                  label="可见行数" value={fmtNum(cat.summary?.visible_row_total)} unit="行"
                  hint="按当前账号数据权限过滤"
                />
                <KpiCard
                  label="导入批次" value={upStats.total ?? overview.data?.uploads?.total ?? 0} unit="批"
                  hint={`涉及 ${fmtNum(overview.data?.uploads?.rows)} 行`}
                />
              </div>

              <Panel title="核心数据资产" subtitle="各业务对象的实时记录数">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
                  {Object.entries(assets).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                      <div className="truncate text-[11px] text-slate-500">
                        {ASSET_LABELS[k] ?? k}
                      </div>
                      <div className="mt-1 font-num text-lg font-semibold text-slate-100">
                        {fmtNum(v)}
                      </div>
                      <div className="mt-0.5 font-num text-[10px] text-slate-600">{k}</div>
                    </div>
                  ))}
                </div>
              </Panel>

              <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
                <Panel title="业务域行数占比" subtitle="按业务域归集">
                  <Chart
                    height={280}
                    option={domainOption}
                    empty={!(cat.domains ?? []).length}
                  />
                </Panel>
                <Panel title="业务域汇总" subtitle="数据表 / 行数" className="xl:col-span-2">
                  <DataTable<AnyRow>
                    columns={[
                      { key: 'domain', title: '业务域', width: 140 },
                      { key: 'tables', title: '表数', width: 80, align: 'right' },
                      {
                        key: 'rows', title: '行数', width: 120, align: 'right',
                        render: (r) => fmtNum(r.rows),
                      },
                      {
                        key: 'table_list', title: '包含数据表',
                        render: (r) => (
                          <div className="flex flex-wrap gap-1">
                            {(r.table_list ?? []).map((t: string) => (
                              <span
                                key={t}
                                className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        ),
                      },
                    ]}
                    rows={cat.domains ?? []}
                    loading={catalog.loading}
                    error={catalog.error}
                    onRetry={catalog.reload}
                    empty="暂无数据域"
                    rowKey={(r) => r.domain}
                    compact
                  />
                </Panel>
              </div>

              <Panel
                title="数据表清单"
                subtitle="行数为数据库实时统计；「可见行数」按当前账号数据权限过滤"
                padded={false}
              >
                <DataTable<AnyRow>
                  columns={[
                    {
                      key: 'name', title: '数据表', width: 160,
                      render: (r) => (
                        <div>
                          <div className="text-[13px] text-slate-100">{r.name}</div>
                          <div className="font-num text-[10px] text-slate-500">{r.table}</div>
                        </div>
                      ),
                    },
                    { key: 'domain', title: '业务域', width: 110 },
                    { key: 'description', title: '说明', render: (r) => r.description ?? '—' },
                    {
                      key: 'row_count', title: '总行数', width: 110, align: 'right',
                      render: (r) => fmtNum(r.row_count),
                    },
                    {
                      key: 'visible_row_count', title: '可见行数', width: 110, align: 'right',
                      render: (r) => (
                        <span className={Number(r.visible_row_count) < Number(r.row_count) ? 'text-state-warn' : ''}>
                          {fmtNum(r.visible_row_count)}
                        </span>
                      ),
                    },
                    {
                      key: 'park_scoped', title: '园区隔离', width: 90, align: 'center',
                      render: (r) => (r.park_scoped ? <Tag tone="ok">是</Tag> : <Tag tone="muted">否</Tag>),
                    },
                  ]}
                  rows={cat.items ?? []}
                  loading={catalog.loading}
                  error={catalog.error}
                  onRetry={catalog.reload}
                  empty="暂无数据表"
                  rowKey={(r) => r.table}
                  compact
                />
              </Panel>

              {cat.note && (
                <Panel title="口径说明">
                  <p className="text-xs leading-relaxed text-slate-400">{cat.note}</p>
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {/* ============================================ 数据质量 */}
      {tab === 'quality' && (
        <>
          {quality.loading ? (
            <Panel><Loading text="正在计算数据质量分…" /></Panel>
          ) : quality.error ? (
            <Panel><ErrorState error={quality.error} onRetry={quality.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <KpiCard
                  label="综合质量分" value={q.overall_score ?? '—'} unit="分"
                  tone={scoreTone(Number(q.overall_score) || 0)}
                  hint="六维加权"
                />
                <KpiCard label="纳管数据类型" value={q.data_type_total ?? 0} unit="类" />
                <KpiCard label="质量问题" value={q.issue_total ?? 0} unit="项" tone="warn" />
                <KpiCard
                  label="未处理问题" value={q.issue_unhandled ?? 0} unit="项"
                  tone={Number(q.issue_unhandled) > 0 ? 'risk' : 'ok'}
                />
              </div>

              <Panel title="六维质量评分" subtitle="每项满分为 100">
                <div className="space-y-4">
                  {QUALITY_DIMS.map((d) => {
                    const v = Number(q[d.key]) || 0
                    return (
                      <div key={d.key}>
                        <div className="mb-1.5 flex items-center justify-between text-xs">
                          <span className="text-slate-300">
                            {d.label}
                            <span className="ml-2 text-slate-500">{d.hint}</span>
                          </span>
                          <span className="font-num text-slate-200">{v.toFixed(1)}</span>
                        </div>
                        <ProgressBar value={v} tone={scoreTone(v)} height={8} />
                      </div>
                    )
                  })}
                </div>
              </Panel>

              {(quality.data?.items ?? []).length === 0 ? (
                <Panel title="质量问题清单">
                  <EmptyState
                    text="当前没有登记的质量问题"
                    hint="问题清单由数据校验任务写入。当前演示库未生成质量问题记录，上方评分由各维度的实时校验结果直接计算得出。"
                  />
                </Panel>
              ) : (
                <Panel title="质量问题清单" padded={false}>
                  <DataTable<AnyRow>
                    columns={[
                      { key: 'data_type', title: '数据类型', width: 140 },
                      { key: 'issue_type', title: '问题类型', width: 140 },
                      { key: 'severity', title: '严重度', width: 90 },
                      { key: 'description', title: '说明' },
                    ]}
                    rows={quality.data?.items ?? []}
                    rowKey={(r) => r.id ?? r.data_type}
                    compact
                  />
                </Panel>
              )}

              {quality.data?.note && (
                <Panel title="评分口径" subtitle="六维质量模型定义">
                  <p className="text-xs leading-relaxed text-slate-400">{quality.data.note}</p>
                </Panel>
              )}

              {Object.keys(quality.data?.issue_by_severity ?? {}).length > 0 && (
                <Panel title="问题严重度分布">
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(quality.data.issue_by_severity).map(([k, v]) => (
                      <Tag key={k} tone="warn">{k}：{String(v)}</Tag>
                    ))}
                  </div>
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {/* ============================================ 指标血缘 */}
      {tab === 'lineage' && (
        <>
          {lineage.loading ? (
            <Panel><Loading text="加载指标血缘…" /></Panel>
          ) : lineage.error ? (
            <Panel><ErrorState error={lineage.error} onRetry={lineage.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <KpiCard
                  label="纳管指标" value={lineage.data?.summary?.metric_total ?? chains.length} unit="个"
                  tone="brand"
                />
                <KpiCard
                  label="涉及数据表"
                  value={new Set(chains.flatMap((c) => (c.sources ?? []).map((s: AnyRow) => s.table))).size}
                  unit="张" tone="ai"
                />
                <KpiCard label="链路总数" value={chains.length} unit="条" />
                <KpiCard
                  label="数据来源" value={overview.data?.assets ? '业务库直连' : '—'}
                  hint="所有指标均由 SQL 实时计算"
                  tone="ok"
                />
              </div>

              <div className="space-y-3">
                {chains.map((c) => (
                  <Panel
                    key={c.metric}
                    title={c.metric}
                    subtitle="指标定义与计算链路"
                    icon={<GitBranch size={14} />}
                  >
                    <div className="space-y-3">
                      <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] p-3">
                        <div className="text-[11px] text-brand-300">计算公式</div>
                        <code className="mt-1 block font-num text-[12px] leading-relaxed text-slate-200">
                          {c.formula}
                        </code>
                      </div>

                      <div>
                        <div className="mb-1.5 text-[11px] text-slate-500">数据来源</div>
                        <div className="space-y-2">
                          {(c.sources ?? []).map((s: AnyRow, i: number) => (
                            <div
                              key={`${s.table}-${i}`}
                              className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2"
                            >
                              <span className="text-[12px] text-slate-200">{s.name ?? s.table}</span>
                              <span className="font-num text-[11px] text-slate-500">{s.table}</span>
                              {s.field && (
                                <span className="font-num text-[11px] text-brand-300">{s.field}</span>
                              )}
                              {s.rows != null && (
                                <span className="font-num text-[11px] text-slate-500">
                                  {fmtNum(s.rows)} 行
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>

                      {c.business_rule && (
                        <div className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                          <div className="text-[11px] text-slate-500">业务规则</div>
                          <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{c.business_rule}</p>
                        </div>
                      )}

                      {c.refresh && (
                        <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                          <Layers size={11} /> 刷新机制：{c.refresh}
                        </div>
                      )}
                    </div>
                  </Panel>
                ))}
              </div>

              {lineage.data?.note && (
                <Panel title="血缘说明">
                  <p className="text-xs leading-relaxed text-slate-400">{lineage.data.note}</p>
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {/* ============================================ 数据导入 */}
      {tab === 'upload' && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <KpiCard label="导入批次" value={upStats.total ?? 0} unit="批" tone="brand" />
            <KpiCard label="导入行数" value={fmtNum(upStats.rows)} unit="行" />
            <KpiCard label="错误行" value={upStats.errors ?? 0} unit="行" tone={Number(upStats.errors) > 0 ? 'risk' : 'ok'} />
            <KpiCard label="告警行" value={upStats.warnings ?? 0} unit="行" tone="warn" />
            <KpiCard label="平均质量分" value={upStats.avg_quality ?? '—'} unit="分" tone="ai" />
          </div>

          <Panel
            title="导入记录"
            subtitle="外部数据（政策库、企业名录、能耗抄表等）的导入批次与校验结果"
            padded={false}
            extra={<Tag tone="muted"><Upload size={10} /> {up.data_label ?? ''}</Tag>}
          >
            {uploads.loading ? (
              <Loading />
            ) : uploads.error ? (
              <ErrorState error={uploads.error} onRetry={uploads.reload} />
            ) : (up.items ?? []).length === 0 ? (
              <EmptyState
                text="暂无导入批次"
                hint="演示库未生成导入记录。该模块用于登记 Excel/CSV 导入批次、行数、错误与告警统计，实际部署后由导入口写入。"
              />
            ) : (
              <DataTable<AnyRow>
                columns={[
                  { key: 'upload_code', title: '批次号', width: 150 },
                  { key: 'data_type', title: '数据类型', width: 130 },
                  { key: 'file_name', title: '文件名' },
                  { key: 'row_count', title: '行数', width: 90, align: 'right' },
                  { key: 'error_count', title: '错误', width: 80, align: 'right' },
                  { key: 'status', title: '状态', width: 100 },
                  { key: 'created_at', title: '导入时间', width: 160 },
                ]}
                rows={up.items ?? []}
                rowKey={(r) => r.id}
                compact
              />
            )}
          </Panel>

          {Object.keys(upStats.by_type ?? {}).length > 0 && (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <Panel title="按数据类型分布">
                <div className="flex flex-wrap gap-3">
                  {Object.entries(upStats.by_type).map(([k, v]) => (
                    <Tag key={k} tone="muted">{k}：{String(v)}</Tag>
                  ))}
                </div>
              </Panel>
              <Panel title="按状态分布">
                <div className="flex flex-wrap gap-3">
                  {Object.entries(upStats.by_status).map(([k, v]) => (
                    <Tag key={k} tone="info">{k}：{String(v)}</Tag>
                  ))}
                </div>
              </Panel>
            </div>
          )}
        </>
      )}

      {/* 底部：数据能力说明（始终展示） */}
      <Panel title="数据能力说明">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="flex gap-2">
            <Database size={15} className="mt-0.5 shrink-0 text-brand-300" />
            <div>
              <div className="text-[13px] font-medium text-slate-200">实时统计</div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                所有行数为数据库 COUNT 实时结果，不使用缓存或预聚合表。
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-state-ok" />
            <div>
              <div className="text-[13px] font-medium text-slate-200">行列级权限</div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                行级按园区范围过滤（visible_row_count），列级由模块权限点控制。
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <GitBranch size={15} className="mt-0.5 shrink-0 text-ai-light" />
            <div>
              <div className="text-[13px] font-medium text-slate-200">口径可穿透</div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                任一页面指标均可通过「指标血缘」回溯到源表与计算公式。
              </p>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}

/**
 * 报表中心 —— 园区月报 / 报表归档 / 项目报告
 *
 * 设计要点：
 *  - 月报为十段式结构（后端 sections[]），每项指标都带 basis 口径说明，
 *    并携带 yoy / mom，前端不做任何计算。
 *  - 报告全部由后端实时生成（/report/generate），归档记录可导出原始文件。
 *  - 数据不足的段落由后端标记 data_sufficient=false + missing_data，前端显式提示，
 *    避免「用 0 冒充真实值」。
 */
import { useState } from 'react'
import { projectApi, reportApi } from '@/api/modules'
import { saveBlob } from '@/api/client'
import { pushToast, useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, Segmented, Tag, Field, inputCls,
} from '@/components/ui'
import { Download, FileBarChart, FileText, RefreshCw, Sparkles } from 'lucide-react'

type AnyRow = Record<string, any>

/** 历史报表类型展示映射（后端 REPORT_TYPES 只列出当前可生成的类型） */
const TYPE_LABELS: Record<string, string> = {
  PARK_MONTHLY: '园区经营月报', PROJECT: '项目报告', GROUP: '集团报告',
  PROJECT_RISK: '项目风险报告', PROJECT_REVIEW: '项目复盘报告',
  LEASING: '招商分析报告', FINANCE: '财务分析报告', SAFETY: '安全分析报告',
  PROPERTY: '物业运维报告', ENERGY: '能源分析报告', OPERATING: '经营分析报告',
}
const STATUS_TONE: Record<string, string> = {
  GENERATED: 'ok', GENERATING: 'warn', DONE: 'ok', FAILED: 'danger',
}
const LEVEL_TONE: Record<string, string> = {
  CRITICAL: 'danger', HIGH: 'risk', RISK: 'risk',
  MEDIUM: 'warn', WARNING: 'warn', LOW: 'info', INFO: 'info',
}
const HEALTH_TONE: Record<string, string> = {
  GREEN: 'ok', YELLOW: 'warn', RED: 'danger',
}
const HEALTH_LABEL: Record<string, string> = {
  GREEN: '健康', YELLOW: '关注', RED: '告警',
}

const fmtTime = (s?: string | null) => (s ? String(s).replace('T', ' ').slice(0, 19) : '—')
const fmtNum = (v: any) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

/** 渲染后端下发的 sections[]（月报与项目报告共用） */
function Sections({ sections }: { sections: AnyRow[] }) {
  return (
    <div className="space-y-4">
      {sections.map((sec, i) => (
        <div key={i} className="rounded-lg border border-white/8 bg-white/[0.02] p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h4 className="text-[14px] font-semibold text-slate-100">{sec.title}</h4>
            {sec.data_sufficient === false && <Tag tone="warn">数据不足</Tag>}
          </div>

          {(sec.metrics ?? []).length > 0 && (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {(sec.metrics ?? []).map((m: AnyRow, j: number) => (
                <div key={`${m.label}-${j}`} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                  <div className="truncate text-[11px] text-slate-500">{m.label}</div>
                  <div className="mt-1 flex items-baseline gap-1">
                    <span className="font-num text-base font-semibold text-slate-100">
                      {fmtNum(m.value)}
                    </span>
                    {m.unit && <span className="text-[11px] text-slate-400">{m.unit}</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-[10px]">
                    {m.yoy != null && (
                      <span className={Number(m.yoy) >= 0 ? 'text-state-danger' : 'text-state-ok'}>
                        同比 {Number(m.yoy) > 0 ? '+' : ''}{fmtNum(m.yoy)}%
                      </span>
                    )}
                    {m.mom != null && (
                      <span className={Number(m.mom) >= 0 ? 'text-state-danger' : 'text-state-ok'}>
                        环比 {Number(m.mom) > 0 ? '+' : ''}{fmtNum(m.mom)}%
                      </span>
                    )}
                  </div>
                  {m.basis && (
                    <div className="mt-1.5 text-[10px] leading-snug text-slate-500">{m.basis}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {sec.notes && (
            <p className="mt-3 text-[12px] leading-relaxed text-slate-400">{String(sec.notes)}</p>
          )}

          {(sec.missing_data ?? []).length > 0 && (
            <p className="mt-2 text-[11px] text-state-warn">
              缺失数据：{(sec.missing_data ?? []).join('、')}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

export default function Report() {
  const { activeParkId, can } = useAuth()
  const [tab, setTab] = useState<'monthly' | 'archive' | 'project'>('monthly')
  const [page, setPage] = useState(1)
  const [genType, setGenType] = useState('PARK_MONTHLY')
  const [genPeriod, setGenPeriod] = useState('')
  const [generating, setGenerating] = useState(false)
  const [archiveDetail, setArchiveDetail] = useState<AnyRow | null>(null)
  const [projectId, setProjectId] = useState<number | null>(null)
  const pageSize = 15

  const types = useAsync(() => reportApi.types(), [])
  const summaryR = useAsync(() => reportApi.summary(), [])
  const monthly = useAsync(
    () => reportApi.parkMonthly(activeParkId ? { park_id: activeParkId } : {}),
    [activeParkId],
    { enabled: tab === 'monthly' },
  )
  const archive = useAsync(
    () => reportApi.archive({ page, page_size: pageSize, park_id: activeParkId ?? undefined }),
    [page, activeParkId],
    { enabled: tab === 'archive' },
  )
  const projects = useAsync(
    () => projectApi.list({ page: 1, page_size: 50, park_id: activeParkId ?? undefined }),
    [activeParkId],
    { enabled: tab === 'project' },
  )
  const projectReport = useAsync(
    () => reportApi.project(projectId as number),
    [projectId],
    { enabled: tab === 'project' && projectId != null },
  )

  const typeOptions: AnyRow[] = types.data?.items ?? []
  const sum: AnyRow = summaryR.data ?? {}

  async function doGenerate() {
    setGenerating(true)
    try {
      const res: any = await reportApi.generate({
        report_type: genType,
        park_id: activeParkId,
        period: genPeriod || undefined,
      })
      pushToast('ok', res?.message ?? '报表已生成')
      summaryR.reload()
      archive.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  async function doExport(id: number, name: string) {
    try {
      const { blob, filename } = await reportApi.exportArchive(id)
      saveBlob(blob, filename || `${name}.md`)
      pushToast('ok', '已开始下载')
    } catch (e: any) {
      pushToast('err', e?.message ?? '导出失败')
    }
  }

  async function openArchive(id: number) {
    try {
      const d = await reportApi.archiveDetail(id)
      setArchiveDetail(d)
    } catch (e: any) {
      pushToast('err', e?.message ?? '读取失败')
    }
  }

  const summary = monthly.data?.executive_summary

  return (
    <div className="space-y-5">
      <PageHeader
        title="报表中心"
        desc="园区经营月报、项目报告与历史归档；所有指标由后端实时汇总，附口径说明与同比环比。"
        demo
        extra={
          <Btn variant="ghost" onClick={() => { monthly.reload(); archive.reload(); summaryR.reload() }}>
            <RefreshCw size={13} /> 刷新
          </Btn>
        }
      />

      {/* 报表概览 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label="累计报表" value={sum.total ?? 0} unit="份" tone="brand" />
        <KpiCard
          label="可生成类型" value={(sum.available_types ?? []).length} unit="种"
          hint={(sum.available_types ?? []).map((t: AnyRow) => t.label).join(' / ')}
        />
        <KpiCard
          label="生成成功" value={sum.by_status?.GENERATED ?? sum.by_status?.DONE ?? 0} unit="份" tone="ok"
        />
        <KpiCard
          label="生成失败" value={sum.by_status?.FAILED ?? 0} unit="份"
          tone={Number(sum.by_status?.FAILED) > 0 ? 'risk' : 'ok'}
        />
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: 'monthly', label: '园区经营月报' },
          { value: 'project', label: '项目报告' },
          { value: 'archive', label: '报表归档' },
        ]}
      />

      {/* ============================================ 园区月报 */}
      {tab === 'monthly' && (
        <>
          {monthly.loading ? (
            <Panel><Loading text="正在生成园区经营月报…" /></Panel>
          ) : monthly.error ? (
            <Panel><ErrorState error={monthly.error} onRetry={monthly.reload} /></Panel>
          ) : (
            <>
              <Panel
                title={monthly.data?.report_name ?? '园区经营月报'}
                subtitle={`报告期 ${monthly.data?.period ?? '—'} · 生成于 ${fmtTime(monthly.data?.generated_at)} · ${monthly.data?.generated_by ?? ''}`}
                icon={<FileBarChart size={14} />}
                extra={
                  <div className="flex items-center gap-2">
                    <Tag tone="muted">{monthly.data?.template ?? ''}</Tag>
                    {monthly.data?.data_label && <Tag tone="warn">{monthly.data.data_label}</Tag>}
                  </div>
                }
              >
                {monthly.data?.scope && (
                  <div className="mb-4 flex flex-wrap gap-4 text-[11px] text-slate-500">
                    <span>数据范围：{monthly.data.scope.data_scope ?? '—'}</span>
                    <span>角色：{monthly.data.scope.role ?? '—'}</span>
                    <span>园区：{monthly.data.scope.park_id ?? '全部（授权范围内）'}</span>
                  </div>
                )}

                {summary && (
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div className="rounded-lg border border-state-ok/22 bg-state-ok/[0.06] p-3.5">
                      <div className="mb-2 text-xs font-semibold text-state-ok">本期亮点</div>
                      {(summary.highlights ?? []).length === 0 ? (
                        <p className="text-[12px] text-slate-500">本期无明显亮点</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {(summary.highlights ?? []).map((h: string, i: number) => (
                            <li key={i} className="text-[12px] leading-relaxed text-slate-300">{h}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="rounded-lg border border-state-warn/22 bg-state-warn/[0.06] p-3.5">
                      <div className="mb-2 text-xs font-semibold text-state-warn">
                        风险提示（{summary.warning_count ?? (summary.warnings ?? []).length}）
                      </div>
                      {(summary.warnings ?? []).length === 0 ? (
                        <p className="text-[12px] text-slate-500">本期无风险提示</p>
                      ) : (
                        <ul className="space-y-1.5">
                          {(summary.warnings ?? []).map((w: string, i: number) => (
                            <li key={i} className="text-[12px] leading-relaxed text-slate-300">{w}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                )}
              </Panel>

              <Sections sections={monthly.data?.sections ?? []} />

              {monthly.data?.evidence && (
                <Panel title="数据来源" subtitle="报告计算依据">
                  <div className="flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-slate-400">
                    <span>来源：{monthly.data.evidence.data_source ?? '—'}</span>
                    {monthly.data.evidence.record_count != null && (
                      <span>记录数：{fmtNum(monthly.data.evidence.record_count)}</span>
                    )}
                    {monthly.data.evidence.generated_at && (
                      <span>生成时间：{fmtTime(monthly.data.evidence.generated_at)}</span>
                    )}
                  </div>
                  {(monthly.data.evidence.tables ?? []).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(monthly.data.evidence.tables ?? []).map((t: string) => (
                        <span
                          key={t}
                          className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-num text-[10px] text-slate-400"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {/* ============================================ 项目报告 */}
      {tab === 'project' && (
        <>
          <Panel title="选择项目" subtitle="项目报告包含健康度、信号与建议">
            <Field label="项目">
              <select
                className={inputCls}
                value={projectId ?? ''}
                onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">请选择项目</option>
                {(projects.data?.items ?? []).map((p: AnyRow) => (
                  <option key={p.id} value={p.id}>
                    {p.project_code} · {p.project_name}
                  </option>
                ))}
              </select>
            </Field>
          </Panel>

          {projectId == null ? (
            <Panel title="项目报告">
              <EmptyState text="请先选择项目" hint="选定项目后将实时生成该项目的周报，包含进度、成本、风险与建议。" />
            </Panel>
          ) : projectReport.loading ? (
            <Panel><Loading text="正在生成项目报告…" /></Panel>
          ) : projectReport.error ? (
            <Panel><ErrorState error={projectReport.error} onRetry={projectReport.reload} /></Panel>
          ) : (
            <>
              <Panel
                title={projectReport.data?.report_name}
                subtitle={`${projectReport.data?.project_code} · ${projectReport.data?.period} · 管理方式 ${projectReport.data?.management_method ?? '—'}`}
                icon={<FileText size={14} />}
                extra={
                  projectReport.data?.executive_summary?.health && (
                    <Tag tone={HEALTH_TONE[projectReport.data.executive_summary.health] ?? 'muted'}>
                      健康度 {HEALTH_LABEL[projectReport.data.executive_summary.health] ?? projectReport.data.executive_summary.health}
                    </Tag>
                  )
                }
              >
                {projectReport.data?.executive_summary?.conclusion && (
                  <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] p-3.5">
                    <div className="mb-1 text-xs font-semibold text-brand-300">结论</div>
                    <p className="text-[13px] leading-relaxed text-slate-100">
                      {projectReport.data.executive_summary.conclusion}
                    </p>
                  </div>
                )}

                {(projectReport.data?.executive_summary?.signals ?? []).length > 0 && (
                  <div className="mt-3 space-y-2">
                    {(projectReport.data.executive_summary.signals ?? []).map((sig: AnyRow, i: number) => (
                      <div key={i} className="flex items-start gap-2 rounded-lg border border-white/8 bg-white/[0.03] p-2.5">
                        <Tag tone={LEVEL_TONE[sig.level] ?? 'muted'}>{sig.level}</Tag>
                        <span className="text-[12px] leading-relaxed text-slate-300">
                          <b className="text-slate-200">{sig.type}：</b>{sig.text}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {(projectReport.data?.executive_summary?.suggestions ?? []).length > 0 && (
                  <div className="mt-3">
                    <div className="mb-1.5 text-xs font-medium text-slate-400">建议措施</div>
                    <ul className="space-y-1.5">
                      {(projectReport.data.executive_summary.suggestions ?? []).map((s: string, i: number) => (
                        <li key={i} className="flex gap-2 text-[12px] leading-relaxed text-slate-300">
                          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                          <span>{s}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Panel>

              <Sections sections={projectReport.data?.sections ?? []} />
            </>
          )}
        </>
      )}

      {/* ============================================ 报表归档 */}
      {tab === 'archive' && (
        <>
          <Panel title="生成新报表" subtitle="报表由后端实时取数生成，生成后进入归档">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[200px]">
                <Field label="报表类型">
                  <select className={inputCls} value={genType} onChange={(e) => setGenType(e.target.value)}>
                    {typeOptions.map((t) => (
                      <option key={t.key} value={t.key}>{t.label}（{t.frequency}）</option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="min-w-[160px]">
                <Field label="报告期" hint="留空则由后端按当前期间生成">
                  <input
                    className={inputCls}
                    placeholder="如 2026年9月"
                    value={genPeriod}
                    onChange={(e) => setGenPeriod(e.target.value)}
                  />
                </Field>
              </div>
              <Btn
                variant="primary"
                loading={generating}
                disabled={!can('report', 'ADD')}
                onClick={() => void doGenerate()}
              >
                <Sparkles size={13} /> 生成报表
              </Btn>
            </div>
            {typeOptions.length > 0 && (
              <div className="mt-3 space-y-1.5">
                {typeOptions.map((t) => (
                  <p key={t.key} className="text-[11px] leading-relaxed text-slate-500">
                    <b className="text-slate-400">{t.label}</b>：{t.description}
                  </p>
                ))}
              </div>
            )}
          </Panel>

          {Object.keys(sum.by_type ?? {}).length > 0 && (
            <Panel title="归档类型分布">
              <div className="flex flex-wrap gap-3">
                {Object.entries(sum.by_type).map(([k, v]) => (
                  <Tag key={k} tone="muted">{TYPE_LABELS[k] ?? k}：{String(v)}</Tag>
                ))}
              </div>
            </Panel>
          )}

          <Panel
            title="报表归档"
            subtitle={`共 ${archive.data?.total ?? 0} 份`}
            padded={false}
          >
            <DataTable<AnyRow>
              columns={[
                {
                  key: 'report_name', title: '报表名称', width: 300,
                  render: (r) => (
                    <div className="min-w-0">
                      <div className="truncate text-[13px] text-slate-100">{r.report_name}</div>
                      <div className="font-num text-[10px] text-slate-500">{r.report_code}</div>
                    </div>
                  ),
                },
                {
                  key: 'report_type', title: '类型', width: 140,
                  render: (r) => TYPE_LABELS[r.report_type] ?? r.report_type,
                },
                { key: 'period', title: '报告期', width: 110, render: (r) => r.period ?? '—' },
                { key: 'format', title: '格式', width: 90, render: (r) => r.format ?? '—' },
                { key: 'generated_by', title: '生成人', width: 120, render: (r) => r.generated_by ?? '—' },
                {
                  key: 'status', title: '状态', width: 90,
                  render: (r) => (
                    <Tag tone={STATUS_TONE[r.status] ?? 'muted'}>{r.status ?? '—'}</Tag>
                  ),
                },
                {
                  key: 'created_at', title: '生成时间', width: 150,
                  render: (r) => fmtTime(r.created_at),
                },
                {
                  key: 'act', title: '操作', width: 150, align: 'right',
                  render: (r) => (
                    <div className="flex justify-end gap-1.5">
                      <Btn size="sm" variant="ghost" onClick={() => void openArchive(r.id)}>查看</Btn>
                      <Btn
                        size="sm" variant="default"
                        disabled={!can('report', 'EXPORT')}
                        onClick={() => void doExport(r.id, r.report_code)}
                      >
                        <Download size={11} /> 导出
                      </Btn>
                    </div>
                  ),
                },
              ]}
              rows={archive.data?.items ?? []}
              loading={archive.loading}
              error={archive.error}
              onRetry={archive.reload}
              empty="暂无归档报表"
              rowKey={(r) => r.id}
              compact
            />

            {Number(archive.data?.pages) > 1 && (
              <div className="flex items-center justify-between border-t border-white/8 px-5 py-3">
                <span className="text-xs text-slate-500">
                  第 {archive.data?.page ?? page} / {archive.data?.pages} 页
                </span>
                <div className="flex gap-2">
                  <Btn size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
                  <Btn size="sm" disabled={page >= Number(archive.data?.pages ?? 1)} onClick={() => setPage((p) => p + 1)}>
                    下一页
                  </Btn>
                </div>
              </div>
            )}
          </Panel>

          {archiveDetail && (
            <Panel
              title={archiveDetail.report_name}
              subtitle={`${archiveDetail.report_code} · ${archiveDetail.period ?? ''} · ${archiveDetail.format ?? ''}`}
              extra={
                <div className="flex gap-2">
                  <Btn size="sm" variant="ghost" onClick={() => setArchiveDetail(null)}>关闭</Btn>
                  <Btn size="sm" variant="default" onClick={() => void doExport(archiveDetail.id, archiveDetail.report_code)}>
                    <Download size={11} /> 导出
                  </Btn>
                </div>
              }
            >
              <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-slate-300">
                {archiveDetail.content ?? '（该报表未保存正文）'}
              </pre>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

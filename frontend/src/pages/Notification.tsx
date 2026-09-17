/**
 * 消息通知 —— 通知中心 / 时间线
 *
 * 设计要点：
 *  - 每条通知都带 trigger_value 与 threshold，可解释「为什么推给我」，不做黑箱推送。
 *  - 类型 / 严重度 / 模块的中文标签全部由 /notification/meta/dict 下发，
 *    前端不维护任何枚举字典（此前后端映射表缺口导致界面出现英文枚举）。
 *  - 统计口径取自 /notification/stats（与列表分页解耦，翻页后依然稳定）。
 */
import { useState } from 'react'
import { notificationApi } from '@/api/modules'
import { pushToast, useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, Segmented, Tag, inputCls,
} from '@/components/ui'
import { Chart, pieOption, rankBarOption } from '@/components/Charts'
import {
  AlertTriangle, Bell, CheckCheck, Clock, ListTodo, RefreshCw,
} from 'lucide-react'

type AnyRow = Record<string, any>

const SEV_TONE: Record<string, string> = {
  CRITICAL: 'danger', RISK: 'risk', WARNING: 'warn', INFO: 'info',
}
const SEV_COLOR: Record<string, string> = {
  CRITICAL: '#EF4444', RISK: '#F97316', WARNING: '#FACC15', INFO: '#2F80ED',
}

const fmtTime = (s?: string | null) => (s ? String(s).replace('T', ' ').slice(0, 16) : '—')

export default function Notification() {
  const { can } = useAuth()
  const [tab, setTab] = useState<'list' | 'timeline'>('list')
  const [typeFilter, setTypeFilter] = useState('')
  const [sevFilter, setSevFilter] = useState('')
  const [readFilter, setReadFilter] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const dict = useAsync(() => notificationApi.dict(), [])
  const stats = useAsync(() => notificationApi.stats(), [])
  const list = useAsync(
    () =>
      notificationApi.list({
        page,
        page_size: pageSize,
        notice_type: typeFilter || undefined,
        severity: sevFilter || undefined,
        is_read: readFilter === '' ? undefined : readFilter === 'read',
      }),
    [page, typeFilter, sevFilter, readFilter],
    { enabled: tab === 'list' },
  )
  const timeline = useAsync(() => notificationApi.timeline(20), [], {
    enabled: tab === 'timeline',
  })

  const types: AnyRow[] = dict.data?.types ?? []
  const severities: AnyRow[] = dict.data?.severities ?? []
  const modules: AnyRow[] = dict.data?.modules ?? []
  const typeLabel = (k?: string) => types.find((t) => t.key === k)?.label ?? k ?? '—'
  const sevLabel = (k?: string) => severities.find((s) => s.key === k)?.label ?? k ?? '—'
  const modLabel = (k?: string) => modules.find((m) => m.key === k)?.label ?? k ?? '—'

  const rows: AnyRow[] = list.data?.items ?? []
  const s: AnyRow = stats.data ?? {}

  const refresh = () => { list.reload(); stats.reload(); timeline.reload() }

  async function doRead(id: number) {
    try {
      await notificationApi.markRead(id)
      pushToast('ok', '已标记为已读')
      refresh()
    } catch (e: any) {
      pushToast('err', e?.message ?? '操作失败')
    }
  }

  async function doReadAll() {
    try {
      await notificationApi.markAllRead()
      pushToast('ok', '已全部标记为已读')
      refresh()
    } catch (e: any) {
      pushToast('err', e?.message ?? '操作失败')
    }
  }

  async function doHandle(id: number) {
    const note = window.prompt('请填写处理说明（将记入日志审计）', '已按流程处理')
    if (note === null) return
    try {
      await notificationApi.handle(id, note || undefined)
      pushToast('ok', '已处理')
      refresh()
    } catch (e: any) {
      pushToast('err', e?.message ?? '操作失败')
    }
  }

  const sevOption = pieOption({
    data: severities
      .map((x) => ({
        name: x.label,
        value: Number(s.by_severity?.[x.key]) || 0,
        color: SEV_COLOR[x.key],
      }))
      .filter((d) => d.value > 0),
    centerLabel: { title: '通知总数', value: s.total ?? 0 },
  })

  const typeOption = rankBarOption({
    names: types.map((t) => t.label),
    values: types.map((t) => Number(s.by_type?.[t.key]) || 0),
    color: '#2F80ED',
  })

  const modOption = rankBarOption({
    names: modules.map((m) => m.label),
    values: modules.map((m) => Number(s.by_module?.[m.key]) || 0),
    color: '#7B61FF',
  })

  return (
    <div className="space-y-5">
      <PageHeader
        title="消息通知"
        desc="阈值越限、到期提醒、SLA 超时与 AI 洞察统一汇聚；每条通知均可追溯触发值与阈值。"
        demo
        extra={
          <>
            <Btn variant="ghost" onClick={refresh}><RefreshCw size={13} /> 刷新</Btn>
            <Btn
              variant="default"
              disabled={!can('notification', 'EDIT') || !(s.unread > 0)}
              onClick={() => void doReadAll()}
            >
              <CheckCheck size={13} /> 全部已读
            </Btn>
          </>
        }
      />

      {/* ------------------------------------------------ 统计 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <KpiCard label="通知总数" value={s.total ?? 0} unit="条" />
        <KpiCard label="未读" value={s.unread ?? 0} unit="条" tone="brand" />
        <KpiCard label="未处理" value={s.unhandled ?? 0} unit="条" tone="warn" />
        <KpiCard
          label="紧急未读" value={s.critical_unread ?? 0} unit="条" tone="risk"
          hint="CRITICAL 且未读"
        />
        <KpiCard
          label="已逾期" value={s.overdue ?? 0} unit="条" tone="warn"
          hint="超过处理时限且未处理"
        />
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: 'list', label: '通知列表' },
          { value: 'timeline', label: '时间线' },
        ]}
      />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_380px]">
        {/* ------------------------------------------------ 主区 */}
        <div className="space-y-4">
          {tab === 'list' && (
            <Panel title="筛选" subtitle="类型 / 严重度 / 阅读状态">
              <div className="flex flex-wrap gap-3">
                <select
                  className={`${inputCls} max-w-[220px]`}
                  value={typeFilter}
                  onChange={(e) => { setTypeFilter(e.target.value); setPage(1) }}
                >
                  <option value="">全部类型</option>
                  {types.map((t) => (
                    <option key={t.key} value={t.key}>{t.label}</option>
                  ))}
                </select>
                <select
                  className={`${inputCls} max-w-[160px]`}
                  value={sevFilter}
                  onChange={(e) => { setSevFilter(e.target.value); setPage(1) }}
                >
                  <option value="">全部严重度</option>
                  {severities.map((x) => (
                    <option key={x.key} value={x.key}>{x.label}</option>
                  ))}
                </select>
                <select
                  className={`${inputCls} max-w-[140px]`}
                  value={readFilter}
                  onChange={(e) => { setReadFilter(e.target.value); setPage(1) }}
                >
                  <option value="">全部状态</option>
                  <option value="unread">仅未读</option>
                  <option value="read">仅已读</option>
                </select>
              </div>
            </Panel>
          )}

          {tab === 'list' ? (
            <>
              {list.loading ? (
                <Panel><Loading text="加载通知…" /></Panel>
              ) : list.error ? (
                <Panel><ErrorState error={list.error} onRetry={list.reload} /></Panel>
              ) : rows.length === 0 ? (
                <Panel>
                  <EmptyState
                    text="没有符合条件的通知"
                    hint="可调整上方筛选条件，或等待业务阈值触发新的提醒。"
                  />
                </Panel>
              ) : (
                <div className="space-y-3">
                  {rows.map((n) => (
                    <div
                      key={n.id}
                      className={`rounded-card border p-4 shadow-glass backdrop-blur-[14px] transition ${
                        n.is_read
                          ? 'border-white/8 bg-panel-grad'
                          : 'border-brand-500/28 bg-brand-500/[0.06]'
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="flex min-w-0 items-start gap-2">
                          {!n.is_read && (
                            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-400" />
                          )}
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[14px] font-medium text-slate-100">{n.title}</span>
                              <Tag tone={SEV_TONE[n.severity] ?? 'muted'}>{n.severity_label ?? n.severity}</Tag>
                              <Tag tone="muted">{n.notice_type_label ?? n.notice_type}</Tag>
                              {n.is_handled ? (
                                <Tag tone="ok">已处理</Tag>
                              ) : (
                                <Tag tone="warn">待处理</Tag>
                              )}
                            </div>
                            <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 font-num text-[11px] text-slate-500">
                              <span>{n.notice_code}</span>
                              <span>{fmtTime(n.occurred_at)}</span>
                              {n.related_module && <span>模块：{modLabel(n.related_module)}</span>}
                            </div>
                          </div>
                        </div>
                        <div className="flex shrink-0 gap-1.5">
                          {!n.is_read && (
                            <Btn size="sm" variant="ghost" onClick={() => void doRead(n.id)}>标记已读</Btn>
                          )}
                          {!n.is_handled && (
                            <Btn
                              size="sm" variant="default"
                              disabled={!can('notification', 'EDIT')}
                              onClick={() => void doHandle(n.id)}
                            >
                              处理
                            </Btn>
                          )}
                        </div>
                      </div>

                      <p className="mt-2 text-[13px] leading-relaxed text-slate-300">{n.content}</p>

                      {/* 触发依据：可解释「为什么推给我」 */}
                      {(n.trigger_value != null || n.threshold != null) && (
                        <div className="mt-2 flex flex-wrap items-center gap-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-[11px]">
                          <span className="text-slate-500">触发依据</span>
                          <span className="font-num text-slate-300">
                            实际值 <b className="text-state-warn">{String(n.trigger_value ?? '—')}</b>
                            {n.threshold != null && (
                              <> ／ 阈值 <b className="text-slate-200">{String(n.threshold)}</b></>
                            )}
                          </span>
                        </div>
                      )}

                      {n.suggestion && (
                        <p className="mt-2 text-[12px] leading-relaxed text-brand-300">
                          建议：{n.suggestion}
                        </p>
                      )}

                      {n.deadline && (
                        <div className="mt-2 inline-flex items-center gap-1 text-[11px] text-slate-500">
                          <Clock size={11} /> 处理时限 {fmtTime(n.deadline)}
                        </div>
                      )}
                    </div>
                  ))}

                  {Number(list.data?.pages) > 1 && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">
                        第 {list.data?.page ?? page} / {list.data?.pages} 页 · 共 {list.data?.total ?? 0} 条
                      </span>
                      <div className="flex gap-2">
                        <Btn size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Btn>
                        <Btn
                          size="sm" disabled={page >= Number(list.data?.pages ?? 1)}
                          onClick={() => setPage((p) => p + 1)}
                        >
                          下一页
                        </Btn>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <Panel title="最近通知时间线" subtitle="按发生时间倒序" padded={false}>
              {timeline.loading ? (
                <Loading />
              ) : timeline.error ? (
                <ErrorState error={timeline.error} onRetry={timeline.reload} />
              ) : (timeline.data?.items ?? []).length === 0 ? (
                <EmptyState text="近期没有通知" />
              ) : (
                <div className="p-5">
                  <ol className="relative space-y-4 border-l border-white/10 pl-5">
                    {(timeline.data?.items ?? []).map((t: AnyRow, i: number) => (
                      <li key={i} className="relative">
                        <span
                          className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full"
                          style={{ background: SEV_COLOR[t.severity] ?? '#64748B' }}
                        />
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[13px] font-medium text-slate-100">{t.title}</span>
                          <Tag tone={SEV_TONE[t.severity] ?? 'muted'}>{sevLabel(t.severity)}</Tag>
                          <Tag tone="muted">{typeLabel(t.type)}</Tag>
                          {!t.is_read && <Tag tone="info">未读</Tag>}
                        </div>
                        <div className="mt-0.5 flex flex-wrap gap-x-3 font-num text-[11px] text-slate-500">
                          <span>{fmtTime(t.at)}</span>
                          {t.module && <span>{modLabel(t.module)}</span>}
                          {t.object?.id != null && <span>对象 #{t.object.id}</span>}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </Panel>
          )}
        </div>

        {/* ------------------------------------------------ 侧栏统计 */}
        <div className="space-y-4">
          <Panel title="严重度分布">
            <Chart
              height={240}
              option={sevOption}
              empty={!s.by_severity || Object.values(s.by_severity).every((v) => !Number(v))}
            />
          </Panel>
          <Panel title="通知类型 Top" subtitle="按类型计数">
            <Chart
              height={Math.max(200, types.length * 26)}
              option={typeOption}
              empty={!s.by_type || Object.values(s.by_type).every((v) => !Number(v))}
            />
          </Panel>
          <Panel title="来源模块分布" subtitle="按关联业务模块计数">
            <Chart
              height={Math.max(200, modules.length * 24)}
              option={modOption}
              empty={!s.by_module || Object.values(s.by_module).every((v) => !Number(v))}
            />
          </Panel>

          <Panel title="通知机制说明">
            <div className="space-y-2 text-[12px] leading-relaxed text-slate-400">
              <div className="flex items-start gap-2">
                <Bell size={13} className="mt-0.5 shrink-0 text-brand-300" />
                <span>通知由业务阈值实时判定（如欠费率、空置天数、SLA 超时），不做定时群发。</span>
              </div>
              <div className="flex items-start gap-2">
                <AlertTriangle size={13} className="mt-0.5 shrink-0 text-state-warn" />
                <span>标记已读不改变业务状态；「处理」会写入日志审计，需 notification:EDIT 权限。</span>
              </div>
              <div className="flex items-start gap-2">
                <ListTodo size={13} className="mt-0.5 shrink-0 text-ai-light" />
                <span>待审批类通知与「审批中心」同源，处理动作请前往审批中心完成。</span>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

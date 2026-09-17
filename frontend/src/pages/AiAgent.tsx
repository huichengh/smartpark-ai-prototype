/**
 * AI 助手中心 —— 主 Agent + 11 个子 Agent 的多智能体协同
 *
 * 设计要点（对齐需求文档第 36 / 37 节）：
 *  - 回答统一渲染为八段式：【结论】【关键数据】【原因分析】【建议措施】
 *    【影响范围】【风险】【责任部门/角色】【决策状态】
 *  - 三级权限：L1 信息查询 / L2 分析与建议 / L3 高影响动作。
 *    L3 时 AI 只能生成审批请求，**必须人工审批后由人执行**，
 *    前端显式阻断「直接执行」的交互，避免出现「AI 自行操作业务」的假象。
 *  - 每条回答附带证据链（数据来源表 / 记录数 / 筛选条件），可追溯到原始数据。
 *  - 八段式字段名与权限模型均由后端下发，前端不硬编码任何指标。
 */
import { useEffect, useRef, useState } from 'react'
import { agentApi, type AgentChatReply, type AgentExtraItem } from '@/api/modules'
import { ApiException } from '@/api/client'
import { pushToast, useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, Segmented, Tag, inputCls,
} from '@/components/ui'
import {
  AlertTriangle, BarChart3, Bot, Boxes, Briefcase, Building2, FileText,
  Landmark, Lightbulb, RefreshCw, Send, ShieldCheck, Sparkles, Target,
  ThumbsDown, ThumbsUp, Wallet, Wrench, Zap,
} from 'lucide-react'

type AnyRow = Record<string, any>

/** 子 Agent 图标映射（后端下发 icon 名称，未知则退化为主 Agent 图标） */
const AGENT_ICONS: Record<string, any> = {
  target: Target, leasing: Target,
  building: Building2, enterprise: Building2,
  space: Boxes, project: Briefcase, contract: FileText,
  property: Wrench, energy: Zap, safety: ShieldCheck,
  policy: Landmark, finance: Wallet, operations: BarChart3,
  sparkles: Sparkles, chief: Sparkles,
}

const fmtNum = (v: any, d = 2) => {
  if (v == null) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: d })
}

const fmtTime = (s?: string | null) =>
  s ? String(s).replace('T', ' ').slice(0, 16) : '—'

/** 把 string | string[] 统一为 string[]，避免后端返回形态差异导致渲染失败 */
const asList = (v: any): string[] => {
  if (v == null) return []
  if (Array.isArray(v)) {
    return v.filter((x) => x != null).map((x) => (typeof x === 'string' ? x : String(x)))
  }
  return [String(v)]
}

/** 权限等级视觉映射（L3 需人工审批） */
const LEVEL_META: Record<string, { label: string; tone: string; desc: string }> = {
  L1: { label: 'L1 信息查询', tone: 'info', desc: '直接读取数据回答，不改变业务状态' },
  L2: { label: 'L2 分析与建议', tone: 'ai', desc: '输出分析与建议，由人工决定是否采纳' },
  L3: { label: 'L3 高影响动作', tone: 'warn', desc: '只能生成审批请求，须人工审批后由人执行' },
}

/** 严重度 → Tag 色调 */
const SEV_TONE: Record<string, string> = {
  CRITICAL: 'danger', HIGH: 'risk', RISK: 'risk',
  MEDIUM: 'warn', WARNING: 'warn', LOW: 'info', INFO: 'info',
}

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-slate-400">{title}</div>
      <ul className="space-y-1.5">
        {items.map((t, i) => (
          <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-slate-200">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 八段式回答渲染 */
function StructuredAnswer({ reply }: { reply: AgentChatReply }) {
  const s: AnyRow = reply.response ?? {}
  const level = reply.permission_level ?? ''
  const meta = LEVEL_META[level]
  const metrics: AnyRow[] = Array.isArray(s['关键数据']) ? s['关键数据'] : []
  const reasons = asList(s['原因分析'])
  const actions = asList(s['建议措施'])
  const risks = asList(s['风险'])
  const owners = asList(s['责任部门/角色'])
  const scope = s['影响范围']
  const decision = s['决策状态']

  return (
    <div className="space-y-4">
      {/* 头部：Agent 身份 + 权限等级 + 耗时 */}
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone="ai">{s.agent_name ?? reply.intent_label ?? 'AI'}</Tag>
        {meta && (
          <span title={meta.desc}>
            <Tag tone={meta.tone}>{meta.label}</Tag>
          </span>
        )}
        {reply.data_sufficient === false && <Tag tone="warn">数据不足</Tag>}
        {reply.latency_ms != null && (
          <span className="font-num text-[11px] text-slate-500">
            {fmtNum(reply.latency_ms, 0)} ms
          </span>
        )}
      </div>

      {/* L3 审批门禁 —— AI 不得自行执行高影响动作 */}
      {level === 'L3' && (
        <div className="flex items-start gap-2 rounded-lg border border-state-warn/30 bg-state-warn/[0.08] p-3">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-state-warn" />
          <div className="text-xs leading-relaxed text-slate-300">
            <b className="text-state-warn">该回答涉及高影响动作（L3）。</b>
            AI 只能生成审批请求，<b>不会自行执行</b>任何业务写操作；
            须由具备审批权限的角色在「审批中心」人工审批通过后，由人执行。
          </div>
        </div>
      )}

      {/* 【结论】 */}
      {s['结论'] && (
        <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] p-3.5">
          <div className="mb-1 text-xs font-semibold tracking-wide text-brand-300">结论</div>
          <p className="text-[13px] leading-relaxed text-slate-100">{s['结论']}</p>
        </div>
      )}

      {/* 【关键数据】 */}
      {metrics.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-medium text-slate-400">关键数据</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            {metrics.map((m, i) => (
              <div key={`${m.label}-${i}`} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                <div className="truncate text-xs text-slate-500">{m.label}</div>
                <div className="mt-1 flex items-baseline gap-1">
                  <span className="font-num text-lg font-semibold text-slate-100">
                    {fmtNum(m.value)}
                  </span>
                  {m.unit && <span className="text-xs text-slate-400">{m.unit}</span>}
                </div>
                {m.basis && (
                  <div className="mt-1 text-[11px] leading-snug text-slate-500">{m.basis}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Bullets title="原因分析" items={reasons} />
        <Bullets title="建议措施" items={actions} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div>
          <div className="mb-1.5 text-xs font-medium text-slate-400">影响范围</div>
          <p className="text-[13px] leading-relaxed text-slate-200">
            {scope ? String(scope) : '—'}
          </p>
        </div>
        <Bullets title="风险" items={risks} />
        <div>
          <div className="mb-1.5 text-xs font-medium text-slate-400">责任部门/角色</div>
          <div className="flex flex-wrap gap-1.5">
            {owners.length
              ? owners.map((o, i) => <Tag key={i} tone="muted">{o}</Tag>)
              : <span className="text-[13px] text-slate-500">—</span>}
          </div>
          <div className="mt-3 mb-1.5 text-xs font-medium text-slate-400">决策状态</div>
          <Tag tone={decision === 'AI建议' ? 'ai' : 'muted'}>{decision ?? '—'}</Tag>
        </div>
      </div>

      {reply.data_sufficient === false && (
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3 text-xs text-slate-400">
          <b className="text-state-warn">数据不足，缺失：</b>
          {(reply.missing_data ?? []).join('、') || '未说明'}
        </div>
      )}

      {/* 证据链 —— 可追溯到原始表 */}
      {reply.evidence && (
        <details className="rounded-lg border border-white/8 bg-white/[0.02]">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-400 transition hover:text-slate-200">
            证据链（数据来源与计算口径）
          </summary>
          <div className="space-y-2 border-t border-white/6 px-3 py-2.5 text-[11px] leading-relaxed text-slate-400">
            <div>数据来源：{reply.evidence.data_source ?? '—'}</div>
            {reply.evidence.record_count != null && (
              <div>命中记录数：{fmtNum(reply.evidence.record_count, 0)}</div>
            )}
            {Array.isArray(reply.evidence.tables) && reply.evidence.tables.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span>涉及数据表：</span>
                {reply.evidence.tables.map((t: string) => (
                  <span key={t} className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-num">
                    {t}
                  </span>
                ))}
              </div>
            )}
            {reply.evidence.filters && (
              <div>筛选条件：{JSON.stringify(reply.evidence.filters)}</div>
            )}
            {reply.evidence.generated_at && (
              <div>生成时间：{fmtTime(reply.evidence.generated_at)}</div>
            )}
          </div>
        </details>
      )}

      {/* AI 补充建议卡片 */}
      {Array.isArray(reply.extra) && reply.extra.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-400">
            <Lightbulb size={13} className="text-state-warn" /> AI 补充建议（{reply.extra.length}）
          </div>
          <div className="space-y-2">
            {reply.extra.map((x: AgentExtraItem, i: number) => (
              <div key={i} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Tag tone={SEV_TONE[x.level ?? ''] ?? 'muted'}>{x.level ?? '—'}</Tag>
                  {x.category && <Tag tone="muted">{x.category}</Tag>}
                  <span className="text-[13px] font-medium text-slate-100">{x.title}</span>
                </div>
                {x.detail && <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{x.detail}</p>}
                {x.suggestion && (
                  <p className="mt-1.5 text-xs leading-relaxed text-brand-300">建议：{x.suggestion}</p>
                )}
                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                  {x.owner && <span>责任方：{x.owner}</span>}
                  {x.evidence && <span>{x.evidence}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function AiAgent() {
  const { activeParkId, can } = useAuth()
  const [tab, setTab] = useState<'qa' | 'insight' | 'rec' | 'agents'>('qa')
  const [agentKey, setAgentKey] = useState<string>('chief')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [turns, setTurns] = useState<
    { role: 'user' | 'ai'; text?: string; reply?: AgentChatReply }[]
  >([])
  const [convId, setConvId] = useState<number | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  const canAi = can('ai', 'AI')

  const catalog = useAsync(() => agentApi.agents(), [])
  const insight = useAsync(() => agentApi.dailyInsight(activeParkId), [activeParkId], {
    enabled: tab === 'insight',
  })
  const rec = useAsync(() => agentApi.recommendations({ page: 1, page_size: 20 }), [], {
    enabled: tab === 'rec',
  })

  useEffect(() => {
    if (tab === 'qa') endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, tab])

  const agents: AnyRow[] = catalog.data?.agents ?? []
  const mainAgent: AnyRow = catalog.data?.main_agent ?? {}
  const permModel: AnyRow = catalog.data?.permission_model ?? {}
  const outputFormat: string[] = catalog.data?.output_format ?? []
  const tools: AnyRow[] = catalog.data?.tools ?? []

  async function send(q: string) {
    const question = q.trim()
    if (!question || sending) return
    if (!canAi) {
      pushToast('err', '当前账号缺少 ai:AI 权限，无法调用 AI 分析')
      return
    }
    setTurns((t) => [...t, { role: 'user', text: question }])
    setDraft('')
    setSending(true)
    try {
      const res = await agentApi.chat({
        question,
        conversation_id: convId,
        agent_key: agentKey === 'chief' ? undefined : agentKey,
        park_id: activeParkId,
      })
      setConvId(res.conversation_id)
      setTurns((t) => [...t, { role: 'ai', reply: res }])
    } catch (e) {
      const msg = e instanceof ApiException ? e.message : 'AI 分析失败'
      pushToast('err', msg)
      setTurns((t) => [...t, { role: 'ai', text: `【调用失败】${msg}` }])
    } finally {
      setSending(false)
    }
  }

  async function doAdopt(id: number) {
    try {
      await agentApi.adopt(id)
      pushToast('ok', '已采纳该建议')
      rec.reload()
    } catch (e) {
      pushToast('err', e instanceof ApiException ? e.message : '操作失败')
    }
  }

  async function doReject(id: number) {
    const reason = window.prompt('请输入驳回理由（将记入日志审计）', '与当前经营策略不符')
    if (reason === null) return
    try {
      await agentApi.reject(id, reason || undefined)
      pushToast('ok', '已驳回该建议')
      rec.reload()
    } catch (e) {
      pushToast('err', e instanceof ApiException ? e.message : '操作失败')
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI 助手中心"
        desc="园智AI总管统一路由至 11 个业务子 Agent，全部结论由后端实时取数计算，并附证据链。"
        demo
        extra={
          tab === 'qa' && turns.length > 0 ? (
            <Btn variant="ghost" onClick={() => { setTurns([]); setConvId(null) }}>
              新对话
            </Btn>
          ) : null
        }
      />

      {/* 权限模型（由后端下发） */}
      {Object.keys(permModel).length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {Object.entries(permModel).map(([k, v]: [string, any]) => (
            <div
              key={k}
              className="rounded-card border border-white/8 bg-panel-grad p-4 shadow-glass backdrop-blur-[14px]"
            >
              <div className="flex items-center justify-between">
                <Tag tone={LEVEL_META[k]?.tone ?? 'muted'}>{k}</Tag>
                {v?.need_approval ? <Tag tone="warn">需人工审批</Tag> : <Tag tone="ok">可直接回答</Tag>}
              </div>
              <div className="mt-2 text-sm font-medium text-slate-100">{v?.name ?? k}</div>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">{v?.desc}</p>
            </div>
          ))}
        </div>
      )}

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: 'qa', label: '智能问答' },
          { value: 'insight', label: '每日洞察' },
          { value: 'rec', label: '建议中心' },
          { value: 'agents', label: 'Agent 与工具' },
        ]}
      />

      {/* ============================================ 智能问答 */}
      {tab === 'qa' && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[280px_1fr]">
          <Panel title="选择分析 Agent" subtitle="默认由主 Agent 自动路由，也可指定" padded={false}>
            <div className="max-h-[620px] space-y-1 overflow-y-auto p-3">
              <button
                onClick={() => setAgentKey('chief')}
                className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                  agentKey === 'chief'
                    ? 'border-ai/40 bg-ai/[0.12]'
                    : 'border-white/8 bg-white/[0.03] hover:border-brand-400/40'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Sparkles size={14} className="text-ai-light" />
                  <span className="text-[13px] font-medium text-slate-100">
                    {mainAgent.name ?? '园智AI总管'}
                  </span>
                </div>
                <p className="mt-1 pl-6 text-[11px] leading-snug text-slate-500">
                  {mainAgent.description ?? '意图识别、任务路由、结果汇总'}
                </p>
              </button>

              {agents.map((a) => {
                const Icon = AGENT_ICONS[a.icon] ?? AGENT_ICONS[a.key] ?? Bot
                const on = agentKey === a.key
                return (
                  <button
                    key={a.key}
                    onClick={() => setAgentKey(a.key)}
                    className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                      on
                        ? 'border-brand-400/45 bg-brand-500/[0.12]'
                        : 'border-white/8 bg-white/[0.03] hover:border-brand-400/40'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon size={14} className={on ? 'text-brand-300' : 'text-slate-400'} />
                      <span className="text-[13px] font-medium text-slate-100">{a.name}</span>
                      <span className="ml-auto font-num text-[10px] text-slate-500">
                        {a.tool_count} 工具
                      </span>
                    </div>
                    <p className="mt-1 pl-6 text-[11px] leading-snug text-slate-500">
                      {a.description}
                    </p>
                  </button>
                )
              })}
            </div>
          </Panel>

          <Panel padded={false} className="overflow-hidden">
            <div className="max-h-[660px] space-y-5 overflow-y-auto p-5">
              {turns.length === 0 && (
                <EmptyState
                  text="向 AI 提出你的第一个问题"
                  hint="例如：本月园区经营情况如何 / 哪些企业存在欠费风险 / 分析项目的健康度与风险"
                />
              )}
              {turns.map((t, i) => (
                <div key={i}>
                  {t.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[80%] rounded-xl rounded-br-sm border border-brand-500/25 bg-brand-500/[0.12] px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-100">
                        {t.text}
                      </div>
                    </div>
                  ) : t.reply ? (
                    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4">
                      <StructuredAnswer reply={t.reply} />
                    </div>
                  ) : (
                    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-4 text-[13px] text-slate-300">
                      {t.text}
                    </div>
                  )}
                </div>
              ))}
              {sending && <Loading text="AI 正在调用业务数据并分析…" inline />}
              <div ref={endRef} />
            </div>

            <div className="border-t border-white/8 p-4">
              <div className="flex gap-2">
                <input
                  className={inputCls}
                  value={draft}
                  placeholder={canAi ? '输入问题，回车发送…' : '当前账号无 ai:AI 权限，仅可浏览'}
                  disabled={!canAi || sending}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void send(draft)
                  }}
                />
                <Btn
                  variant="ai"
                  loading={sending}
                  disabled={!canAi || !draft.trim()}
                  onClick={() => void send(draft)}
                >
                  <Send size={13} /> 发送
                </Btn>
              </div>
              {outputFormat.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                  <span>统一输出格式：</span>
                  {outputFormat.map((f) => (
                    <span key={f} className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5">
                      {f}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </div>
      )}

      {/* ============================================ 每日洞察 */}
      {tab === 'insight' && (
        <>
          {insight.loading ? (
            <Panel><Loading text="正在生成每日洞察…" /></Panel>
          ) : insight.error ? (
            <Panel><ErrorState error={insight.error} onRetry={insight.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                <KpiCard label="洞察条数" value={insight.data?.total ?? 0} unit="条" tone="ai" />
                <KpiCard label="紧急" value={insight.data?.severity_count?.CRITICAL ?? 0} unit="条" tone="risk" />
                <KpiCard label="风险" value={insight.data?.severity_count?.RISK ?? 0} unit="条" tone="warn" />
                <KpiCard label="预警" value={insight.data?.severity_count?.WARNING ?? 0} unit="条" tone="warn" />
                <KpiCard label="提示" value={insight.data?.severity_count?.INFO ?? 0} unit="条" />
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {(insight.data?.items ?? []).map((it: AnyRow, i: number) => (
                  <Panel
                    key={i}
                    title={it.title}
                    subtitle={`${it.category ?? ''} · ${it.agent_name ?? ''}`}
                    extra={<Tag tone={SEV_TONE[it.level ?? ''] ?? 'muted'}>{it.level ?? '—'}</Tag>}
                  >
                    <p className="text-[13px] leading-relaxed text-slate-300">{it.detail}</p>
                    {it.suggestion && (
                      <p className="mt-2 text-[13px] leading-relaxed text-brand-300">
                        建议：{it.suggestion}
                      </p>
                    )}
                    {it.metrics && Object.keys(it.metrics).length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
                        {Object.entries(it.metrics).map(([k, v]) => (
                          <span key={k} className="text-[11px] text-slate-500">
                            {k} <b className="font-num text-slate-200">{fmtNum(v, 0)}</b>
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      {it.evidence && <span className="truncate">{it.evidence}</span>}
                      {it.decision_status && <Tag tone="muted">{it.decision_status}</Tag>}
                    </div>
                  </Panel>
                ))}
              </div>

              {insight.data?.basis && (
                <Panel title="洞察生成口径">
                  <p className="text-xs leading-relaxed text-slate-400">{insight.data.basis}</p>
                  <p className="mt-1 font-num text-[11px] text-slate-600">
                    生成时间：{fmtTime(insight.data.generated_at)}
                  </p>
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {/* ============================================ 建议中心 */}
      {tab === 'rec' && (
        <>
          {rec.data?.stats && (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
              <KpiCard label="建议总数" value={rec.data.stats.total ?? 0} unit="条" />
              <KpiCard label="待处理" value={rec.data.stats.pending ?? 0} unit="条" tone="warn" />
              <KpiCard label="已采纳" value={rec.data.stats.adopted ?? 0} unit="条" tone="ok" />
              <KpiCard label="已驳回" value={rec.data.stats.rejected ?? 0} unit="条" />
              <KpiCard
                label="需人工审批" value={rec.data.stats.needs_approval ?? 0} unit="条" tone="risk"
                hint="L3 高影响动作建议"
              />
              <KpiCard label="当前页" value={(rec.data.items ?? []).length} unit="条" tone="ai" />
            </div>
          )}

          <Panel
            title="AI 建议清单"
            subtitle="采纳后写入业务待办，驳回需填写理由并记入日志审计"
            padded={false}
            extra={
              <Btn variant="ghost" size="sm" onClick={() => rec.reload()}>
                <RefreshCw size={12} /> 刷新
              </Btn>
            }
          >
            <DataTable<AnyRow>
              columns={[
                {
                  key: 'title', title: '建议', width: 300,
                  render: (r) => (
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[13px] font-medium text-slate-100">{r.title}</span>
                        <Tag tone={SEV_TONE[r.severity ?? ''] ?? 'muted'}>{r.severity ?? '—'}</Tag>
                      </div>
                      {r.summary && (
                        <div className="mt-0.5 truncate text-[11px] text-slate-500">{r.summary}</div>
                      )}
                    </div>
                  ),
                },
                { key: 'agent_key', title: '来源', width: 110, render: (r) => r.agent_key ?? '—' },
                { key: 'category', title: '分类', width: 150, render: (r) => r.category ?? '—' },
                {
                  key: 'confidence', title: '置信度', width: 90, align: 'right',
                  render: (r) =>
                    r.confidence != null ? `${(Number(r.confidence) * 100).toFixed(1)}%` : '—',
                },
                {
                  key: 'permission_level', title: '权限级', width: 80,
                  render: (r) => (
                    <Tag tone={LEVEL_META[r.permission_level ?? '']?.tone ?? 'muted'}>
                      {r.permission_level ?? '—'}
                    </Tag>
                  ),
                },
                {
                  key: 'decision_status', title: '决策状态', width: 100,
                  render: (r) => <Tag tone="muted">{r.decision_status ?? '—'}</Tag>,
                },
                {
                  key: 'act', title: '操作', width: 160, align: 'right',
                  render: (r) => (
                    <div className="flex justify-end gap-1.5">
                      <Btn
                        size="sm" variant="primary"
                        disabled={!can('ai', 'EDIT') || r.decision_status === '已采纳'}
                        onClick={() => void doAdopt(r.id)}
                      >
                        <ThumbsUp size={11} /> 采纳
                      </Btn>
                      <Btn
                        size="sm" variant="danger"
                        disabled={!can('ai', 'EDIT') || r.decision_status === '已驳回'}
                        onClick={() => void doReject(r.id)}
                      >
                        <ThumbsDown size={11} /> 驳回
                      </Btn>
                    </div>
                  ),
                },
              ]}
              rows={rec.data?.items ?? []}
              loading={rec.loading}
              error={rec.error}
              onRetry={rec.reload}
              empty="暂无 AI 建议"
              rowKey={(r) => r.id}
              compact
            />
          </Panel>
        </>
      )}

      {/* ============================================ Agent 与工具 */}
      {tab === 'agents' && (
        <>
          {catalog.loading ? (
            <Panel><Loading text="加载 Agent 注册表…" /></Panel>
          ) : catalog.error ? (
            <Panel><ErrorState error={catalog.error} onRetry={catalog.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <KpiCard
                  label="主 Agent" value={mainAgent.name ?? '—'}
                  hint={mainAgent.description} tone="ai"
                />
                <KpiCard label="业务子 Agent" value={catalog.data?.total ?? 0} unit="个" />
                <KpiCard label="注册工具" value={catalog.data?.tool_count ?? 0} unit="个" />
                <KpiCard
                  label="输出段落" value={outputFormat.length} unit="段"
                  hint={outputFormat.join(' / ')}
                />
              </div>

              <Panel title="业务子 Agent" subtitle="每个子 Agent 仅挂载所属领域的工具，避免越权取数">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {agents.map((a) => {
                    const Icon = AGENT_ICONS[a.icon] ?? AGENT_ICONS[a.key] ?? Bot
                    return (
                      <div key={a.key} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                        <div className="flex items-center gap-2">
                          <Icon size={14} className="text-brand-300" />
                          <span className="text-[13px] font-medium text-slate-100">{a.name}</span>
                          <span className="ml-auto font-num text-[10px] text-slate-500">
                            {a.tool_count} 工具
                          </span>
                        </div>
                        <p className="mt-1.5 text-[11px] leading-snug text-slate-400">{a.description}</p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {(a.tools ?? []).map((t: string) => (
                            <span
                              key={t}
                              className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-num text-[10px] text-slate-400"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </Panel>

              <Panel
                title="工具注册表"
                subtitle="Agent 只能通过受控工具访问业务数据，全部返回 data + evidence + data_sufficient"
                padded={false}
              >
                <DataTable<AnyRow>
                  columns={[
                    {
                      key: 'name', title: '工具名', width: 230,
                      render: (r) => <span className="font-num text-slate-200">{r.name}</span>,
                    },
                    { key: 'description', title: '能力说明', render: (r) => r.description ?? '—' },
                    {
                      key: 'returns', title: '返回结构', width: 250,
                      render: (r) => (
                        <span className="font-num text-[11px] text-slate-400">{r.returns ?? '—'}</span>
                      ),
                    },
                  ]}
                  rows={tools}
                  loading={catalog.loading}
                  error={catalog.error}
                  onRetry={catalog.reload}
                  empty="暂无工具"
                  rowKey={(r) => r.name}
                  compact
                />
              </Panel>
            </>
          )}
        </>
      )}
    </div>
  )
}

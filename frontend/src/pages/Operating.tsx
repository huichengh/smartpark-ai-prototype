/**
 * 经营决策工作台 —— 指标 → 沙盘推演 → 续租风险 → 任务闭环
 *
 * 设计原则（对齐《分模块改进提示词》02–05 与建议书 3.1–3.4）：
 * 1. **所有金额、比率、回本月份都由后端确定性函数算出**，本页只做展示与入参，
 *    前端不做任何财务运算——否则同一个数在页面和接口上会对不上。
 * 2. **风险不是概率**：页面显式展示「规则标签，非统计概率」，
 *    并允许业务人员确认或解除误报（规则必然有误报）。
 * 3. **决策必须由人做**：沙盘只给方案与差额，不下"应该选哪个"的结论；
 *    任务必须经审批才能进入执行，AI 不代批。
 */
import { useMemo, useState } from 'react'
import { operatingApi } from '@/api/modules'
import { useAsync, pushToast } from '@/hooks/useAsync'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, Segmented, Tag, inputCls,
} from '@/components/ui'
import { Chart, lineOption } from '@/components/Charts'

const fmt = (v: any, d = 0) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: d })
const wan = (v: any) => (v == null ? '—' : `${(Number(v) / 10000).toFixed(1)} 万`)

const LEVEL_TONE: Record<string, string> = {
  HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok', UNKNOWN: 'muted',
}
const STATUS_TONE: Record<string, string> = {
  DRAFT: 'muted', PENDING_APPROVAL: 'warn', APPROVED: 'info', REJECTED: 'danger',
  IN_PROGRESS: 'brand', PENDING_REVIEW: 'warn', CLOSED: 'ok', CANCELLED: 'muted',
}
const NEXT_ACTION: Record<string, [string, string]> = {
  DRAFT: ['PENDING_APPROVAL', '提交审批'],
  PENDING_APPROVAL: ['APPROVED', '批准'],
  APPROVED: ['IN_PROGRESS', '开始执行'],
  IN_PROGRESS: ['PENDING_REVIEW', '提交验收'],
  PENDING_REVIEW: ['CLOSED', '验收关闭'],
}

type Tab = 'overview' | 'sandbox' | 'risk' | 'actions'

export default function Operating() {
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <div className="space-y-5">
      <PageHeader
        title="经营决策工作台"
        desc="以经营目标为中心：先看指标口径，再推演方案，随后处理续租风险，最后把建议推成可验收的任务。"
        demo
      />
      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { value: 'overview', label: '经营概览' },
          { value: 'sandbox', label: '收益沙盘' },
          { value: 'risk', label: '续租风险' },
          { value: 'actions', label: '执行任务' },
        ]}
      />
      {tab === 'overview' && <Overview />}
      {tab === 'sandbox' && <Sandbox />}
      {tab === 'risk' && <RiskList />}
      {tab === 'actions' && <Actions />}
    </div>
  )
}

/* ------------------------------------------------------------------ 概览 */
function Overview() {
  const { data, loading, error } = useAsync(() => operatingApi.metrics(), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(data?.kpis ?? []).map((k: any) => (
          <KpiCard
            key={k.key}
            label={k.label}
            value={k.value == null ? '—' : fmt(k.value, k.unit === '%' ? 2 : 0)}
            unit={k.unit}
            hint={k.unavailable_reason || k.basis}
            tone={k.key === 'occupancy_rate' ? 'brand' : k.key === 'vacant_area' ? 'warn' : undefined}
          />
        ))}
      </div>

      {data?.missing_data?.length > 0 && (
        <Panel title="数据缺口（不填 0，直接标缺）" subtitle="缺失数据不会被估算成 0，以免误读为真实值">
          <ul className="space-y-1.5 text-sm text-slate-300">
            {data.missing_data.map((m: string) => (
              <li key={m} className="flex gap-2">
                <span className="text-state-warn">·</span>
                <span>{m}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title="指标口径" subtitle="同一口径在看板、沙盘与报表之间保持一致">
        <DataTable<any>
          columns={[
            { key: 'label', title: '指标' },
            { key: 'value', title: '当前值', render: (r) => `${fmt(r.value, 2)} ${r.unit ?? ''}` },
            { key: 'basis', title: '计算口径' },
          ]}
          rows={data?.kpis ?? []}
          rowKey={(r) => r.key}
        />
      </Panel>
    </div>
  )
}

/* ------------------------------------------------------------------ 沙盘 */
const DEFAULT_FORM = {
  area: 1200, list_rent: 45, lease_months: 36, vacancy_days: 90,
  discount: 0, rent_free_months: 0, commission_months: 0.5,
  fitout_per_sqm: 0, service_cost_monthly: 8000, payment_cycle_days: 30,
}

function Sandbox() {
  const [form, setForm] = useState({ ...DEFAULT_FORM })
  const [spaceId, setSpaceId] = useState<number | null>(null)
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const { data: spacePage } = useAsync(() => operatingApi.spaces({ page_size: 50 }), [])

  const spaces = spacePage?.items ?? []

  const pickSpace = (id: number) => {
    const s = spaces.find((x: any) => x.id === id)
    if (!s) return
    setSpaceId(id)
    setForm((f) => ({
      ...f,
      area: Math.max(1, Math.round(s.rentable_area || f.area)),
      list_rent: s.list_rent || f.list_rent,
      vacancy_days: s.vacant_days ?? f.vacancy_days,
    }))
  }

  const run = async () => {
    setBusy(true)
    try {
      const r = await operatingApi.compare({ ...form, space_id: spaceId })
      setResult(r)
      pushToast('ok', '推演完成：三方案已生成')
    } catch (e: any) {
      pushToast('err', e?.message || '推演失败：请检查输入参数')
    } finally {
      setBusy(false)
    }
  }

  const chart = useMemo(() => {
    if (!result?.scenarios?.length) return null
    const rows = result.scenarios
    const months = rows[0].cash_flow?.length ?? 0
    const series = rows.map((s: any, i: number) => ({
      name: s.label,
      data: Array.from({ length: months }, (_, k) => s.cash_flow[k]?.cumulative ?? 0),
      color: ['#2F80ED', '#00D4FF', '#7B61FF'][i % 3],
    }))
    return lineOption({
      x: Array.from({ length: months }, (_, k) => `${k + 1}月`),
      series,
    })
  }, [result])

  return (
    <div className="space-y-5">
      <Panel title="推演参数" subtitle="默认值仅为演示假设；空置期是「从今天到起租」的月数来源">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Field label="选择空间（自动带出面积与挂牌价）">
            <select className={inputCls} value={spaceId ?? ''}
                    onChange={(e) => pickSpace(Number(e.target.value))}>
              <option value="">不选，手动填写</option>
              {spaces.map((s: any) => (
                <option key={s.id} value={s.id}>
                  {s.space_name} · {fmt(s.rentable_area, 0)}㎡
                </option>
              ))}
            </select>
          </Field>
          {([
            ['area', '面积（㎡）'], ['list_rent', '挂牌租金（元/㎡/月）'],
            ['lease_months', '租期（月）'], ['vacancy_days', '预计空置（天）'],
            ['discount', '让价比例（0–0.5）'], ['rent_free_months', '免租期（月）'],
            ['commission_months', '佣金（月租倍数）'], ['fitout_per_sqm', '装修补贴（元/㎡）'],
            ['service_cost_monthly', '持有成本（元/月）'], ['payment_cycle_days', '回款周期（天）'],
          ] as const).map(([key, label]) => (
            <Field key={key} label={label}>
              <input
                className={inputCls}
                type="number"
                step="any"
                value={(form as any)[key]}
                onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })}
              />
            </Field>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Btn onClick={run} disabled={busy}>{busy ? '推演中…' : '生成三方案对比'}</Btn>
          <span className="text-xs text-slate-500">
            让价超过 50%、免租期 ≥ 租期等异常输入会被后端拒算并说明原因，不会返回兜底数字。
          </span>
        </div>
      </Panel>

      {!result ? (
        <EmptyState text="还没有推演结果" hint="选择空间或手动填写参数后，点「生成三方案对比」" />
      ) : (
        <>
          <Panel title="三方案对比" subtitle="净经营贡献 = 租期实收租金 − 佣金 − 装修补贴 − 持有成本">
            <DataTable<any>
              columns={[
                { key: 'label', title: '方案' },
                { key: 'effective_rent', title: '实收单价', render: (r) => `${fmt(r.effective_rent, 2)} 元/㎡/月` },
                { key: 'net_contribution', title: '净经营贡献', render: (r) => wan(r.net_contribution) },
                { key: 'delta_vs_a', title: '较 A 差额', render: (r) => (
                  <span className={r.delta_vs_a < 0 ? 'text-state-risk' : 'text-state-ok'}>
                    {r.delta_vs_a > 0 ? '+' : ''}{wan(r.delta_vs_a)}
                  </span>
                ) },
                { key: 'vacancy_days', title: '空置', render: (r) => `${r.vacancy_days} 天` },
                { key: 'first_cash_month', title: '首次回款', render: (r) => r.first_cash_month ? `第 ${r.first_cash_month} 月` : '—' },
                { key: 'payback_month', title: '现金流回正', render: (r) => r.payback_month ? `第 ${r.payback_month} 月` : '租期内未回正' },
              ]}
              rows={result.scenarios}
              rowKey={(r) => r.key}
            />
            <div className="mt-3 space-y-1 text-xs text-slate-400">
              {(result.notes ?? []).map((n: string) => <div key={n}>· {n}</div>)}
              <div className="text-slate-500">现金流从今天起算（含空置期），因此空置越久回正越晚。</div>
            </div>
          </Panel>

          {chart && (
            <Panel title="累计净现金流" subtitle="横轴为从今天起的月份；跨过 0 线即回本">
              <Chart option={chart} height={300} />
            </Panel>
          )}

          <Panel title="敏感性分析" subtitle="单变量扰动，其余参数保持不变">
            <DataTable<any>
              columns={[
                { key: 'name', title: '情景' },
                { key: 'net_contribution', title: '净经营贡献', render: (r) => wan(r.net_contribution) },
                { key: 'delta', title: '相对基准', render: (r) => (
                  <span className={r.delta < 0 ? 'text-state-risk' : 'text-state-ok'}>
                    {r.delta > 0 ? '+' : ''}{wan(r.delta)}
                  </span>
                ) },
                { key: 'payback_month', title: '回正月份', render: (r) => r.payback_month ? `第 ${r.payback_month} 月` : '—' },
              ]}
              rows={result.sensitivity?.rows ?? []}
              rowKey={(r) => r.name}
            />
            <div className="mt-2 text-xs text-slate-500">{result.sensitivity?.note}</div>
          </Panel>

          <div className="rounded-xl border border-state-info/25 bg-state-info/[0.06] px-4 py-3 text-xs text-slate-300">
            <b className="text-state-info">决策提示</b>：以上为推演结果，价格为参数假设，不构成报价；
            调价、改合同、减免账单等高影响动作必须经人工审批，系统不会自动写入。
          </div>
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ 风险 */
function RiskList() {
  const [expanded, setExpanded] = useState<number | null>(null)
  const { data, loading, error, reload } = useAsync(() => operatingApi.renewalRisks({ window_days: 90 }), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />

  const review = async (id: number, decision: 'CONFIRMED' | 'DISMISSED') => {
    const reason = decision === 'DISMISSED' ? window.prompt('请填写解除误报的理由（会被记录）') ?? '' : undefined
    try {
      await operatingApi.reviewRisk(id, decision, reason)
      pushToast('ok', decision === 'DISMISSED' ? '已标记为误报' : '已确认为真实风险')
      reload()
    } catch (e: any) {
      pushToast('err', e?.message || '复核失败')
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title={`续租风险待核实（${data?.total ?? 0}）`}
        subtitle="规则标签，不是统计概率；每条结论都能回溯到原始记录"
      >
        <div className="mb-3 flex flex-wrap gap-2 text-xs">
          {Object.entries(data?.by_level ?? {}).map(([k, v]) => (
            <Tag key={k} tone={LEVEL_TONE[k] as any}>{data.level_labels?.[k] ?? k} {v as number}</Tag>
          ))}
          <span className="ml-auto text-slate-500">{data?.rule_version}</span>
        </div>

        <div className="space-y-2">
          {(data?.items ?? []).slice(0, 50).map((r: any) => (
            <div key={r.contract_id} className="rounded-lg border border-white/8 bg-white/[0.02]">
              <button
                className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left"
                onClick={() => setExpanded(expanded === r.contract_id ? null : r.contract_id)}
              >
                <Tag tone={LEVEL_TONE[r.level] as any}>{r.level_label}</Tag>
                <span className="text-sm font-medium text-slate-200">{r.enterprise_name ?? '未知企业'}</span>
                <span className="text-xs text-slate-500">{r.contract_code}</span>
                <span className="text-xs text-slate-400">
                  剩余 {r.days_left ?? '—'} 天 · 到期 {r.end_date ?? '—'} · 得分 {r.score}
                </span>
                <span className="ml-auto text-xs text-slate-500">
                  {r.signal_count} 条信号 {expanded === r.contract_id ? '收起' : '展开证据'}
                </span>
              </button>
              {expanded === r.contract_id && (
                <div className="border-t border-white/8 px-4 py-3 text-xs">
                  {(r.signals ?? []).map((s: any) => (
                    <div key={s.code} className="mb-2">
                      <div className="text-slate-300">
                        <b>{s.label}</b>（权重 {s.weight}）：{s.fact}
                        <span className="ml-2 text-slate-500">来源 {s.source}</span>
                      </div>
                      {s.evidence?.length > 0 && (
                        <div className="mt-1 text-slate-500">
                          {s.evidence.map((e: any, i: number) => (
                            <div key={i}>· {Object.entries(e).map(([k, v]) => `${k}=${v ?? '—'}`).join('，')}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {r.missing_data?.length > 0 && (
                    <div className="mt-2 text-state-warn">证据不足：{r.missing_data.join('；')}</div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Btn size="sm" onClick={() => review(r.contract_id, 'CONFIRMED')}>确认风险</Btn>
                    <Btn size="sm" variant="ghost" onClick={() => review(r.contract_id, 'DISMISSED')}>
                      解除误报
                    </Btn>
                    {r.review && (
                      <span className="self-center text-slate-500">
                        已复核：{r.review.decision === 'DISMISSED' ? '误报' : '确认'}（{r.review.decided_by_name}）
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs text-slate-500">{data?.disclaimer}</div>
      </Panel>
    </div>
  )
}

/* ------------------------------------------------------------------ 任务 */
function Actions() {
  const { data, loading, error, reload } = useAsync(() => operatingApi.actions({ page_size: 50 }), [])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />

  const advance = async (a: any, to: string) => {
    try {
      await operatingApi.transition(a.id, to, '工作台推进')
      pushToast('ok', `已推进到「${to}」`)
      reload()
    } catch (e: any) {
      pushToast('err', e?.message || '推进失败')
    }
  }

  return (
    <Panel
      title={`执行任务（${data?.total ?? 0}）`}
      subtitle="建议单 → 审批 → 执行 → 验收 → 关闭；审批人不能是创建人"
    >
      {!data?.items?.length ? (
        <EmptyState text="还没有执行任务" hint="从「续租风险」中确认风险后即可创建跟进任务" />
      ) : (
        <DataTable<any>
          columns={[
            { key: 'action_code', title: '任务号' },
            { key: 'title', title: '标题' },
            { key: 'status', title: '状态', render: (r) => (
              <Tag tone={STATUS_TONE[r.status] as any}>{r.status_label}</Tag>
            ) },
            { key: 'priority', title: '优先级' },
            { key: 'owner_role', title: '责任角色', render: (r) => r.owner_role ?? '—' },
            { key: 'due_date', title: '截止' },
            { key: 'created_by_name', title: '创建人' },
            { key: 'op', title: '操作', render: (r) => {
              const next = NEXT_ACTION[r.status]
              if (!next) return <span className="text-slate-500">已结束</span>
              return (
                <Btn size="sm" variant="ghost" onClick={() => advance(r, next[0])}>{next[1]}</Btn>
              )
            } },
          ]}
          rows={data.items}
          rowKey={(r) => r.id}
        />
      )}
      <div className="mt-3 text-xs text-slate-500">
        非法状态迁移会被后端拒绝并返回当前可选状态；审批动作需要 <code>operating:APPROVE</code> 权限。
      </div>
    </Panel>
  )
}

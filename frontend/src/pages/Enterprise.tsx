/**
 * 企业管理 —— 企业台账 / 政策匹配 / 风险信号
 *
 * 企业画像、风险信号与政策匹配评分均来自后端：
 *  - /enterprise/enterprises       列表 + stats
 *  - /enterprise/enterprises/{id}  详情（enterprise / kpi / risk_signals / spaces / contracts / bills / contacts）
 *  - /enterprise/policies          政策库
 *  - /enterprise/policy-matches    匹配结果（match_score / match_level / match_reason）
 */
import { useMemo, useState } from 'react'
import { enterpriseApi } from '@/api/modules'
import { useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls, cx,
} from '@/components/ui'
import { Chart, barOption, pieOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const wan = (v: any) => `${((Number(v) || 0) / 10000).toFixed(1)} 万`

const RISK_TONE: Record<string, string> = { HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok' }
const STATUS_TONE: Record<string, string> = {
  SETTLED: 'ok', GROWING: 'info', POTENTIAL: 'muted',
  EXITED: 'muted', WARNING: 'warn', RISK: 'danger',
}

export default function Enterprise() {
  const { activeParkId } = useAuth()
  const [status, setStatus] = useState('')
  const [industry, setIndustry] = useState('')
  const [risk, setRisk] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number | null>(null)
  const [tab, setTab] = useState<'profile' | 'policy'>('profile')
  const pageSize = 15

  const list = useAsync(
    () => enterpriseApi.list({
      park_id: activeParkId ?? undefined,
      status: status || undefined,
      industry: industry || undefined,
      risk_level: risk || undefined,
      keyword: keyword || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, status, industry, risk, keyword, page],
  )

  const detail = useAsync(
    () => enterpriseApi.detail(selected as number),
    [selected],
    { enabled: selected != null },
  )

  const policies = useAsync(() => enterpriseApi.policies({ page_size: 50 }), [], {})
  const matches = useAsync(
    () => enterpriseApi.matches({ enterprise_id: selected ?? undefined, page_size: 50 }),
    [selected],
    { enabled: selected != null && tab === 'policy' },
  )

  const stats = list.data?.stats ?? {}
  const rows: any[] = list.data?.items ?? []
  const total = list.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const indOption = useMemo(() => {
    const arr = Object.entries(stats.by_industry ?? {}).map(([name, value]) => ({
      name, value: Number(value) || 0,
    }))
    arr.sort((a, b) => b.value - a.value)
    return pieOption({ data: arr.slice(0, 8), centerLabel: { title: '企业总数', value: stats.total ?? 0 } })
  }, [stats])

  const statusOption = useMemo(() => {
    const label: Record<string, string> = {
      SETTLED: '已入驻', GROWING: '成长企业', POTENTIAL: '潜在企业',
      EXITED: '已退出', WARNING: '预警', RISK: '风险', NEW: '新入驻',
    }
    return barOption({
      x: Object.keys(stats.by_status ?? {}).map((k) => label[k] ?? k),
      series: [{
        name: '企业数',
        data: Object.values(stats.by_status ?? {}).map((v) => Number(v) || 0),
      }],
      showLegend: false,
    })
  }, [stats])

  const e = detail.data
  const ent = e?.enterprise
  const k = e?.kpi ?? {}
  const signals: any[] = e?.risk_signals ?? []
  const policyRows: any[] = matches.data?.items ?? []
  const policyLib: any[] = policies.data?.items ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="企业管理"
        desc="企业台账、经营画像、风险信号与政策匹配，评分与风险均由后端基于账单与合同台账推导。"
        demo
        extra={<Btn variant="ghost" onClick={() => list.reload()}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {list.loading && !list.data ? (
        <Panel><Loading text="正在加载企业数据…" /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          <KpiCard label="企业总数" value={stats.total ?? 0} unit="家" />
          <KpiCard label="高新技术企业" value={stats.high_tech_count ?? 0} unit="家" tone="ai" />
          <KpiCard
            label="风险企业" value={stats.risk_count ?? 0} unit="家"
            tone={Number(stats.risk_count) > 0 ? 'risk' : 'ok'}
          />
          <KpiCard label="欠费企业" value={stats.with_arrears ?? 0} unit="家" tone="warn" />
          <KpiCard label="在租面积" value={fmt(stats.total_leased_area, 0)} unit="㎡" />
          <KpiCard
            label="当前页"
            value={`${rows.filter((r) => r.is_high_tech).length}`} unit="家高企"
            hint={`本页共 ${rows.length} 家`}
          />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Panel title="行业分布" subtitle="按 industry 归集（取前 8）">
          <Chart height={270} option={indOption} empty={Object.keys(stats.by_industry ?? {}).length === 0} />
        </Panel>
        <div className="xl:col-span-2">
          <Panel title="企业状态分布" subtitle="按 status 归集">
            <Chart height={270} option={statusOption} empty={Object.keys(stats.by_status ?? {}).length === 0} />
          </Panel>
        </div>
      </div>

      {/* ------------------------------------------------------ 企业列表 */}
      <Panel
        title="企业台账"
        subtitle={`共 ${total} 家企业，点击行查看详情`}
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
              className={inputCls} placeholder="企业名称 / 统一社会信用代码"
              value={keyword}
              onChange={(ev) => { setKeyword(ev.target.value); setPage(1) }}
            />
          </Field>
          <Field label="状态">
            <select className={inputCls} value={status}
              onChange={(ev) => { setStatus(ev.target.value); setPage(1) }}>
              <option value="">全部</option>
              {['SETTLED', 'GROWING', 'POTENTIAL', 'EXITED'].map((k2) => (
                <option key={k2} value={k2}>
                  {{ SETTLED: '已入驻', GROWING: '成长企业', POTENTIAL: '潜在企业', EXITED: '已退出' }[k2]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="风险等级">
            <select className={inputCls} value={risk}
              onChange={(ev) => { setRisk(ev.target.value); setPage(1) }}>
              <option value="">全部</option>
              {['HIGH', 'MEDIUM', 'LOW'].map((k2) => (
                <option key={k2} value={k2}>
                  {{ HIGH: '高', MEDIUM: '中', LOW: '低' }[k2]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="行业">
            <input className={inputCls} placeholder="如：软件和信息技术服务业"
              value={industry} onChange={(ev) => { setIndustry(ev.target.value); setPage(1) }} />
          </Field>
          {(status || risk || industry || keyword) && (
            <Btn variant="ghost" onClick={() => {
              setStatus(''); setRisk(''); setIndustry(''); setKeyword(''); setPage(1)
            }}>清空筛选</Btn>
          )}
        </div>

        <DataTable<any>
          columns={[
            {
              key: 'enterprise_name', title: '企业名称',
              render: (r) => (
                <div className="flex min-w-0 items-center gap-2">
                  <span className={cx(
                    'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
                    r.is_high_tech ? 'bg-ai' : 'bg-brand-500',
                  )} />
                  <div className="min-w-0">
                    <div className="truncate font-medium text-slate-100">{r.enterprise_name}</div>
                    <div className="font-num text-[11px] text-slate-500">
                      {r.enterprise_code} · {r.industry ?? '—'}
                    </div>
                  </div>
                </div>
              ),
            },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={STATUS_TONE[r.status] ?? 'muted'}>{r.status_name ?? r.status}</Tag>
              ),
            },
            {
              key: 'flags', title: '资质',
              render: (r) => (
                <div className="flex flex-wrap gap-1">
                  {r.is_high_tech && <Tag tone="ai">高企</Tag>}
                  {r.is_specialized && <Tag tone="warn">专精特新</Tag>}
                  {r.is_little_giant && <Tag tone="warn">小巨人</Tag>}
                  {r.is_tech_sme && <Tag tone="info">科小</Tag>}
                </div>
              ),
            },
            { key: 'legal_person', title: '法人', render: (r) => r.legal_person ?? '—' },
            { key: 'employee_count', title: '员工', align: 'right', render: (r) => r.employee_count ?? '—' },
            { key: 'annual_revenue', title: '年营收(元)', align: 'right', render: (r) => fmt(r.annual_revenue, 0) },
            { key: 'annual_tax', title: '年纳税(元)', align: 'right', render: (r) => fmt(r.annual_tax, 0) },
            { key: 'ip_count', title: '知识产权', align: 'right', render: (r) => r.ip_count ?? 0 },
            { key: 'leased_area', title: '在租面积(㎡)', align: 'right', render: (r) => fmt(r.leased_area, 0) },
            {
              key: 'arrears', title: '欠费(元)', align: 'right',
              render: (r) => (
                <span className={Number(r.arrears) > 0 ? 'text-state-warn' : 'text-slate-500'}>
                  {fmt(r.arrears, 0)}
                </span>
              ),
            },
            {
              key: 'risk_level', title: '风险',
              render: (r) => (r.risk_level
                ? <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>{r.risk_level}</Tag>
                : <span className="text-slate-600">—</span>),
            },
            {
              key: 'ops', title: '操作',
              render: (r) => (
                <Btn size="sm" variant="ghost" onClick={() => { setSelected(r.id); setTab('profile') }}>
                  详情
                </Btn>
              ),
            },
          ]}
          rows={rows}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          rowKey={(r) => r.id}
          onRowClick={(r) => { setSelected(r.id); setTab('profile') }}
          compact
          empty="没有匹配的企业"
        />
      </Panel>

      {/* ------------------------------------------------------ 企业详情 */}
      {selected != null && (
        <Panel
          title={ent?.enterprise_name ?? '企业详情'}
          subtitle={ent ? `${ent.enterprise_code} · ${ent.industry ?? '—'} · ${ent.status_name ?? ent.status}` : ''}
          extra={
            <div className="flex items-center gap-2">
              <Btn size="sm" variant={tab === 'profile' ? 'primary' : 'ghost'} onClick={() => setTab('profile')}>经营画像</Btn>
              <Btn size="sm" variant={tab === 'policy' ? 'primary' : 'ghost'} onClick={() => setTab('policy')}>政策匹配</Btn>
              <Btn size="sm" variant="ghost" onClick={() => setSelected(null)}>关闭</Btn>
            </div>
          }
        >
          {detail.loading ? (
            <Loading text="正在加载企业画像…" />
          ) : detail.error ? (
            <ErrorState error={detail.error} onRetry={detail.reload} />
          ) : tab === 'profile' ? (
            <div className="space-y-5">
              {/* KPI */}
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-7">
                <KpiCard label="在租面积" value={fmt(k.leased_area, 0)} unit="㎡" />
                <KpiCard label="空间单元" value={k.space_count ?? 0} unit="间" />
                <KpiCard label="有效合同" value={`${k.active_contract_count ?? 0}/${k.contract_count ?? 0}`} />
                <KpiCard label="月租金" value={fmt(k.monthly_rent, 0)} unit="元" />
                <KpiCard label="累计应收" value={wan(k.total_receivable)} unit="元" />
                <KpiCard label="累计实收" value={wan(k.total_received)} unit="元" tone="ok" />
                <KpiCard
                  label="收缴率" value={fmt(k.collection_rate, 1)} unit="%"
                  tone={Number(k.collection_rate) >= 90 ? 'ok' : 'warn'}
                  hint={Number(k.arrears) > 0 ? `欠费 ${fmt(k.arrears, 0)} 元` : '无欠费'}
                />
              </div>

              {/* 风险信号 */}
              <div>
                <h4 className="mb-2 text-sm font-medium text-slate-300">
                  风险信号
                  <span className="ml-2 text-xs text-slate-500">共 {signals.length} 条</span>
                </h4>
                {signals.length === 0 ? (
                  <EmptyState text="暂无风险信号" hint="该企业当前未触发任何风险规则。" />
                ) : (
                  <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-3">
                    {signals.map((sig, i) => (
                      <div
                        key={i}
                        className={cx(
                          'rounded-lg border p-3',
                          sig.level === 'RISK'
                            ? 'border-state-danger/30 bg-state-danger/[0.08]'
                            : sig.level === 'WARNING'
                              ? 'border-state-warn/30 bg-state-warn/[0.08]'
                              : 'border-white/10 bg-white/[0.03]',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <Tag tone={RISK_TONE[sig.level] ?? 'muted'}>{sig.type ?? '信号'}</Tag>
                          <span className="text-xs text-slate-300">{sig.text}</span>
                        </div>
                        {sig.basis && (
                          <p className="mt-1.5 border-t border-white/6 pt-1.5 text-[10px] text-slate-500">
                            依据：{sig.basis}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
                <Panel title="在租空间" subtitle={`共 ${(e?.spaces ?? []).length} 间`}>
                  <DataTable<any>
                    columns={[
                      { key: 'space_code', title: '编号', render: (r) => <span className="font-num text-xs">{r.space_code}</span> },
                      { key: 'space_name', title: '名称' },
                      { key: 'area', title: '面积(㎡)', align: 'right', render: (r) => fmt(r.area, 2) },
                      { key: 'rent_price', title: '租金单价', align: 'right', render: (r) => fmt(r.rent_price) },
                      { key: 'lease_end', title: '租期至', render: (r) => <span className="font-num">{r.lease_end ?? '—'}</span> },
                    ]}
                    rows={e?.spaces ?? []}
                    rowKey={(r) => r.id}
                    compact
                    empty="暂无在租空间"
                  />
                </Panel>

                <Panel title="合同" subtitle={`共 ${(e?.contracts ?? []).length} 份`}>
                  <DataTable<any>
                    columns={[
                      { key: 'contract_code', title: '编号', render: (r) => <span className="font-num text-xs">{r.contract_code}</span> },
                      { key: 'monthly_rent', title: '月租金(元)', align: 'right', render: (r) => fmt(r.monthly_rent) },
                      { key: 'leased_area', title: '面积(㎡)', align: 'right', render: (r) => fmt(r.leased_area, 2) },
                      { key: 'end_date', title: '到期日', render: (r) => <span className="font-num">{r.end_date ?? '—'}</span> },
                      {
                        key: 'days_left', title: '剩余', align: 'right',
                        render: (r) => (
                          <span className={Number(r.days_left) <= 90 ? 'text-state-warn' : ''}>
                            {r.days_left ?? '—'} 天
                          </span>
                        ),
                      },
                    ]}
                    rows={e?.contracts ?? []}
                    rowKey={(r) => r.id}
                    compact
                    empty="暂无合同"
                  />
                </Panel>
              </div>

              <Panel title="联系人" subtitle={`共 ${(e?.contacts ?? []).length} 位`}>
                <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-4">
                  {(e?.contacts ?? []).map((c: any) => (
                    <div key={c.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-100">{c.name}</span>
                        {c.is_primary && <Tag tone="info">主要</Tag>}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-400">{c.position ?? '—'}</div>
                      <div className="mt-1 font-num text-[11px] text-slate-500">
                        {c.phone ?? '—'}
                        {c.email && <div className="truncate">{c.email}</div>}
                      </div>
                    </div>
                  ))}
                  {(e?.contacts ?? []).length === 0 && <EmptyState text="暂无联系人" />}
                </div>
              </Panel>

              <Panel title="账单记录" subtitle={`展示最近 ${(e?.bills ?? []).length} 条`}>
                <DataTable<any>
                  columns={[
                    { key: 'bill_code', title: '账单号', render: (r) => <span className="font-num text-xs">{r.bill_code}</span> },
                    { key: 'period', title: '账期', render: (r) => <span className="font-num">{r.period}</span> },
                    { key: 'receivable', title: '应收(元)', align: 'right', render: (r) => fmt(r.receivable) },
                    { key: 'received', title: '实收(元)', align: 'right', render: (r) => fmt(r.received) },
                    {
                      key: 'arrears', title: '欠费(元)', align: 'right',
                      render: (r) => <span className={Number(r.arrears) > 0 ? 'text-state-warn' : ''}>{fmt(r.arrears)}</span>,
                    },
                    { key: 'due_date', title: '到期日', render: (r) => <span className="font-num">{r.due_date}</span> },
                    {
                      key: 'status', title: '状态',
                      render: (r) => (
                        <Tag tone={r.status === 'PAID' ? 'ok' : r.status === 'OVERDUE' ? 'danger' : 'warn'}>
                          {{ PAID: '已收', UNPAID: '未收', PARTIAL: '部分', OVERDUE: '逾期' }[r.status as string] ?? r.status}
                        </Tag>
                      ),
                    },
                    { key: 'overdue_days', title: '逾期', align: 'right', render: (r) => (Number(r.overdue_days) > 0 ? `${r.overdue_days} 天` : '—') },
                  ]}
                  rows={e?.bills ?? []}
                  rowKey={(r) => r.id}
                  compact
                  empty="暂无账单"
                />
              </Panel>
            </div>
          ) : (
            /* ------------------------------------------------- 政策匹配 */
            <div className="space-y-5">
              <div className="rounded-lg border border-brand-500/22 bg-brand-500/[0.07] px-4 py-2.5 text-xs text-brand-200">
                匹配评分（match_score）与匹配等级（match_level）由后端依据企业资质字段与政策申报条件逐条比对得出，
                每条均附「匹配理由」与「缺失数据」，可用于判断是否具备申报条件。
              </div>

              {matches.loading ? (
                <Loading text="正在计算政策匹配…" />
              ) : matches.error ? (
                <ErrorState error={matches.error} onRetry={matches.reload} />
              ) : policyRows.length === 0 ? (
                <EmptyState
                  text="该企业暂无政策匹配结果"
                  hint={`政策库当前收录 ${policyLib.length} 条政策，可尝试在政策库中手工比对。`}
                />
              ) : (
                <div className="space-y-3">
                  {policyRows.map((m) => (
                    <div key={m.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium text-slate-100">
                              {m.policy_name ?? m.policy?.policy_name ?? `政策 #${m.policy_id}`}
                            </span>
                            <Tag tone={
                              m.match_level === 'HIGH' ? 'ok'
                                : m.match_level === 'MEDIUM' ? 'warn' : 'muted'
                            }>
                              {{ HIGH: '高度匹配', MEDIUM: '中度匹配', LOW: '低匹配' }[m.match_level as string] ?? m.match_level}
                            </Tag>
                            {m.status && <Tag tone="muted">{m.status}</Tag>}
                          </div>
                          <p className="mt-1.5 text-xs text-slate-400">
                            {m.match_reason ?? '—'}
                          </p>
                        </div>
                        <div className="w-32 shrink-0 text-right">
                          <div className="font-num text-2xl font-semibold text-brand-300">
                            {fmt(m.match_score, 1)}
                          </div>
                          <div className="text-[10px] text-slate-500">匹配评分</div>
                        </div>
                      </div>

                      <div className="mt-3">
                        <ProgressBar value={Number(m.match_score) || 0} tone="ai" />
                      </div>

                      <div className="mt-3 grid grid-cols-1 gap-2 border-t border-white/6 pt-3 text-[11px] md:grid-cols-2">
                        {m.missing_data && (
                          <div className="text-state-warn">
                            <span className="text-slate-500">缺失数据：</span>
                            {Array.isArray(m.missing_data) ? m.missing_data.join('、') : String(m.missing_data)}
                          </div>
                        )}
                        {m.risk_note && (
                          <div className="text-slate-400">
                            <span className="text-slate-500">风险提示：</span>{m.risk_note}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <Panel title="政策库" subtitle={`共 ${policies.data?.total ?? policyLib.length} 条政策`}>
                <DataTable<any>
                  columns={[
                    { key: 'policy_code', title: '编号', render: (r) => <span className="font-num text-xs">{r.policy_code}</span> },
                    { key: 'policy_name', title: '政策名称' },
                    { key: 'policy_type', title: '类型', render: (r) => r.policy_type ?? '—' },
                    { key: 'issuing_authority', title: '发布机构', render: (r) => r.issuing_authority ?? '—' },
                    { key: 'subsidy_amount', title: '补贴金额(元)', align: 'right', render: (r) => fmt(r.subsidy_amount, 0) },
                    { key: 'deadline', title: '申报截止', render: (r) => <span className="font-num">{r.deadline ?? '—'}</span> },
                  ]}
                  rows={policyLib}
                  rowKey={(r) => r.id}
                  compact
                  empty="政策库为空"
                />
              </Panel>
            </div>
          )}
        </Panel>
      )}
    </div>
  )
}

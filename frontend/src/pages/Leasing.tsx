/**
 * 招商管理 —— 线索漏斗 / 渠道效能 / 停滞线索
 *
 * 漏斗的 stage / step_rate / overall_rate 由后端按线索阶段实时计算，
 * 前端不重复定义阶段顺序与转化率口径。
 */
import { useMemo, useState } from 'react'
import { leasingApi } from '@/api/modules'
import { useAsync, pushToast } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, Field, KpiCard, Loading, ErrorState,
  PageHeader, Panel, ProgressBar, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, funnelOption, pieOption, rankBarOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const wan = (v: any) => `${((Number(v) || 0) / 10000).toFixed(1)} 万`

const STAGE_TONE: Record<string, string> = {
  LEAD: 'info', FOLLOWING: 'info', VISITED: 'brand' as unknown as string,
  NEGOTIATION: 'warn', SIGNED: 'ok', LOST: 'muted',
}

export default function Leasing() {
  const { activeParkId, can } = useAuth()
  const [stage, setStage] = useState('')
  const [keyword, setKeyword] = useState('')
  const [stagnantOnly, setStagnantOnly] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 15

  const funnel = useAsync(
    () => leasingApi.funnel(activeParkId ?? undefined),
    [activeParkId],
  )
  const channels = useAsync(() => leasingApi.channels(), [], {})
  const leads = useAsync(
    () => leasingApi.leads({
      park_id: activeParkId ?? undefined,
      stage: stage || undefined,
      keyword: keyword || undefined,
      is_stagnant: stagnantOnly ? true : undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, stage, keyword, stagnantOnly, page],
  )
  const stagnant = useAsync(
    () => leasingApi.stagnant({ park_id: activeParkId ?? undefined, days: 14 }),
    [activeParkId],
  )

  const f = funnel.data
  const fs_ = f?.summary ?? {}
  const stages: any[] = f?.stages ?? []

  const funnelChart = useMemo(
    () => funnelOption({ data: stages.map((s) => ({ name: s.stage_name ?? s.stage, value: s.count })) }),
    [stages],
  )

  const stepOption = useMemo(
    () =>
      barOption({
        x: stages.map((s) => s.stage_name ?? s.stage),
        series: [
          { name: '本环节转化率(%)', data: stages.map((s) => s.step_rate), color: '#00D4FF' },
          { name: '累计转化率(%)', data: stages.map((s) => s.overall_rate), color: '#7B61FF' },
        ],
      }),
    [stages],
  )

  const parkOption = useMemo(
    () =>
      barOption({
        x: (f?.by_park ?? []).map((p: any) => p.park_name),
        series: [
          { name: '线索数', data: (f?.by_park ?? []).map((p: any) => p.lead_count), color: '#2F80ED' },
          { name: '签约数', data: (f?.by_park ?? []).map((p: any) => p.signed_count), color: '#22C55E' },
          { name: '停滞数', data: (f?.by_park ?? []).map((p: any) => p.stagnant), color: '#EF4444' },
        ],
      }),
    [f],
  )

  const chItems: any[] = channels.data?.items ?? []
  const chRank = useMemo(
    () =>
      rankBarOption({
        names: chItems.map((c) => c.channel_type ?? c.channel_name),
        values: chItems.map((c) => c.lead_count ?? 0),
        color: '#2F80ED',
      }),
    [chItems],
  )

  const leadRows: any[] = leads.data?.items ?? []
  const leadStats = leads.data?.stats ?? {}
  const total = leads.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const stagnantCount = stagnant.data?.items?.length ?? leadStats.stagnant_count ?? 0

  const doFollowup = async (lead: any) => {
    try {
      await leasingApi.followup(lead.id, { content: '由招商台账发起跟进（演示）', next_action: '电话回访' })
      pushToast('ok', `已为 ${lead.company_name} 记录跟进`)
      leads.reload()
    } catch (err: any) {
      pushToast('err', err?.message ?? '跟进记录失败')
    }
  }

  const doMoveStage = async (lead: any) => {
    const next: Record<string, string> = {
      LEAD: 'FOLLOWING', FOLLOWING: 'VISITED', VISITED: 'NEGOTIATION',
      NEGOTIATION: 'SIGNED',
    }
    const target = next[lead.stage]
    if (!target) { pushToast('info', '该线索已处于终态'); return }
    try {
      await leasingApi.moveStage(lead.id, target)
      pushToast('ok', `已推进至 ${target}`)
      leads.reload(); funnel.reload()
    } catch (err: any) {
      pushToast('err', err?.message ?? '推进阶段失败')
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="招商管理"
        desc="线索漏斗、渠道效能与停滞预警，阶段转化率由后端按线索台账实时计算。"
        demo
        extra={<Btn variant="ghost" onClick={() => { funnel.reload(); leads.reload(); channels.reload() }}>刷新</Btn>}
      />

      {/* ------------------------------------------------------------ KPI */}
      {funnel.loading ? (
        <Panel><Loading text="正在汇总招商数据…" /></Panel>
      ) : funnel.error ? (
        <Panel><ErrorState error={funnel.error} onRetry={funnel.reload} /></Panel>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-7">
          <KpiCard label="线索总量" value={fs_.total_leads ?? 0} unit="条" />
          <KpiCard label="活跃线索" value={fs_.active_leads ?? 0} unit="条" tone="brand" />
          <KpiCard label="已签约" value={fs_.signed_leads ?? 0} unit="条" tone="ok" />
          <KpiCard
            label="整体转化率" value={fmt(fs_.conversion_rate, 2)} unit="%"
            tone="ai" hint="签约数 ÷ 线索总数"
          />
          <KpiCard label="需求面积" value={fmt(fs_.total_demand_area, 0)} unit="㎡" />
          <KpiCard label="意向投资额" value={wan(fs_.total_investment)} unit="元" />
          <KpiCard
            label="停滞线索" value={fs_.stagnant_count ?? stagnantCount} unit="条"
            tone={stagnantCount > 0 ? 'warn' : 'ok'} hint="超过 14 天无跟进"
          />
        </div>
      )}

      {/* ------------------------------------------------------- 漏斗区 */}
      {f && (
        <>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Panel title="招商转化漏斗" subtitle="各阶段线索数量（后端按 stage 排序）">
              <Chart height={330} option={funnelChart} empty={stages.length === 0} />
            </Panel>
            <div className="xl:col-span-2">
              <Panel title="阶段转化率" subtitle="本环节转化 = 本环节 ÷ 上一环节；累计 = 本环节 ÷ 首环节">
                <Chart height={330} option={stepOption} empty={stages.length === 0} />
              </Panel>
            </div>
          </div>

          {/* 阶段明细 */}
          <Panel title="漏斗阶段明细" subtitle="数据由 /leasing/funnel 下发">
            <DataTable<any>
              columns={[
                { key: 'stage_name', title: '阶段', render: (r) => r.stage_name ?? r.stage },
                { key: 'count', title: '数量', align: 'right' },
                { key: 'step_rate', title: '本环节转化率', align: 'right', render: (r) => `${fmt(r.step_rate, 2)}%` },
                {
                  key: 'overall_rate', title: '累计转化率', width: 150,
                  render: (r) => <ProgressBar value={Number(r.overall_rate) || 0} showText />,
                },
                { key: 'demand_area', title: '需求面积(㎡)', align: 'right', render: (r) => fmt(r.demand_area, 0) },
              ]}
              rows={stages}
              rowKey={(r) => r.stage}
              compact
            />
          </Panel>

          {(f.by_park ?? []).length > 0 && (
            <Panel title="各园区招商对比" subtitle="线索 / 签约 / 停滞数量">
              <Chart height={280} option={parkOption} />
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------- 渠道效能 */}
      {chItems.length > 0 && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <Panel
              title="渠道效能"
              subtitle={`共 ${channels.data?.total ?? chItems.length} 个渠道；单签约成本由后端按费用 ÷ 签约数计算`}
            >
              <DataTable<any>
                columns={[
                  {
                    key: 'channel_type', title: '渠道类型',
                    render: (r) => (
                      <div>
                        <div className="text-slate-100">{r.channel_type ?? '—'}</div>
                        <div className="font-num text-[11px] text-slate-500">{r.channel_code}</div>
                      </div>
                    ),
                  },
                  { key: 'cost', title: '投入(元)', align: 'right', render: (r) => fmt(r.cost) },
                  { key: 'lead_count', title: '线索', align: 'right' },
                  { key: 'signed_count', title: '签约', align: 'right' },
                  {
                    key: 'conversion_rate', title: '转化率', align: 'right',
                    render: (r) => (
                      <span className={Number(r.conversion_rate) >= 30 ? 'text-state-ok' : ''}>
                        {fmt(r.conversion_rate, 2)}%
                      </span>
                    ),
                  },
                  {
                    key: 'cost_per_sign', title: '单签约成本(元)', align: 'right',
                    render: (r) => (r.cost_per_sign == null
                      ? <span className="text-slate-600">—</span>
                      : <span className={Number(r.cost_per_sign) > 10000 ? 'text-state-warn' : ''}>
                          {fmt(r.cost_per_sign)}
                        </span>),
                  },
                  { key: 'demand_area', title: '需求面积(㎡)', align: 'right', render: (r) => fmt(r.demand_area, 0) },
                ]}
                rows={chItems}
                rowKey={(r) => r.id}
                compact
              />
            </Panel>
          </div>
          <Panel title="渠道线索贡献" subtitle="按线索数降序">
            <Chart height={340} option={chRank} />
          </Panel>
        </div>
      )}

      {/* ------------------------------------------------------- 线索列表 */}
      <Panel
        title="线索台账"
        subtitle={`共 ${total} 条线索`}
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
              className={inputCls} placeholder="企业名称 / 联系人 / 线索编号"
              value={keyword}
              onChange={(ev) => { setKeyword(ev.target.value); setPage(1) }}
            />
          </Field>
          <Field label="阶段">
            <select
              className={inputCls} value={stage}
              onChange={(ev) => { setStage(ev.target.value); setPage(1) }}
            >
              <option value="">全部阶段</option>
              {stages.map((s) => (
                <option key={s.stage} value={s.stage}>{s.stage_name ?? s.stage}</option>
              ))}
            </select>
          </Field>
          <label className="flex cursor-pointer items-center gap-2 pb-2 text-xs text-slate-400">
            <input
              type="checkbox" checked={stagnantOnly}
              onChange={(ev) => { setStagnantOnly(ev.target.checked); setPage(1) }}
              className="accent-brand-500"
            />
            仅看停滞线索
          </label>
          {(stage || keyword || stagnantOnly) && (
            <Btn variant="ghost" onClick={() => { setStage(''); setKeyword(''); setStagnantOnly(false); setPage(1) }}>
              清空筛选
            </Btn>
          )}
        </div>

        <DataTable<any>
          columns={[
            {
              key: 'company_name', title: '企业',
              render: (r) => (
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{r.company_name}</div>
                  <div className="font-num text-[11px] text-slate-500">{r.lead_code} · {r.industry ?? '—'}</div>
                </div>
              ),
            },
            {
              key: 'contact_person', title: '联系人',
              render: (r) => (
                <div className="text-xs">
                  <div>{r.contact_person ?? '—'}</div>
                  <div className="font-num text-[11px] text-slate-500">{r.contact_phone ?? '—'}</div>
                </div>
              ),
            },
            {
              key: 'stage', title: '阶段',
              render: (r) => (
                <Tag tone={STAGE_TONE[r.stage] ?? 'muted'}>{r.stage_name ?? r.stage}</Tag>
              ),
            },
            { key: 'source_name', title: '来源', render: (r) => r.source_name ?? r.source ?? '—' },
            {
              key: 'score', title: '评分', align: 'right',
              render: (r) => {
                const s = Number(r.score)
                if (!r.score) return <span className="text-slate-600">—</span>
                return (
                  <span className={s >= 70 ? 'text-state-ok' : s >= 40 ? 'text-state-warn' : 'text-slate-400'}>
                    {s.toFixed(0)}
                  </span>
                )
              },
            },
            { key: 'demand_area', title: '需求面积(㎡)', align: 'right', render: (r) => fmt(r.demand_area, 0) },
            { key: 'investment_amount', title: '意向投资(元)', align: 'right', render: (r) => fmt(r.investment_amount) },
            {
              key: 'stagnant_days', title: '停滞天数', align: 'right',
              render: (r) => {
                const d = Number(r.stagnant_days) || 0
                if (!r.is_stagnant && d <= 0) return <span className="text-slate-600">—</span>
                return <span className={d >= 14 ? 'text-state-danger' : 'text-state-warn'}>{d} 天</span>
              },
            },
            { key: 'owner_name', title: '负责人', render: (r) => r.owner_name ?? '—' },
            {
              key: 'ops', title: '操作',
              render: (r) => (
                can('leasing', 'EDIT') ? (
                  <div className="flex items-center gap-1.5">
                    <Btn size="sm" variant="ghost" onClick={() => doFollowup(r)}>跟进</Btn>
                    <Btn size="sm" variant="ghost" onClick={() => doMoveStage(r)}>推进</Btn>
                  </div>
                ) : null
              ),
            },
          ]}
          rows={leadRows}
          loading={leads.loading}
          error={leads.error}
          onRetry={leads.reload}
          rowKey={(r) => r.id}
          compact
          empty="没有匹配的线索"
        />
      </Panel>
    </div>
  )
}

/**
 * 财务与收费 —— 应收/实收/欠费账龄/收缴率
 *
 * 所有指标来自 /finance/summary 与 /finance/bills，前端不硬编码业务数字。
 * 「指标口径」（basis）由后端下发并原样展示，保证口径可追溯。
 */
import { useMemo, useState } from 'react'
import { financeApi } from '@/api/modules'
import { useAsync, pushToast } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, Field, KpiCard, Loading,
  PageHeader, Panel, ProgressBar, Tag, inputCls,
} from '@/components/ui'
import { Chart, barOption, lineOption, pieOption, rankBarOption } from '@/components/Charts'

const fmt = (v: any, d = 2) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

const wan = (v: any) => {
  const n = Number(v) || 0
  return `${(n / 10000).toFixed(1)} 万`
}

const RISK_TONE: Record<string, string> = { HIGH: 'danger', MEDIUM: 'warn', LOW: 'ok' }
const BILL_STATUS_TONE: Record<string, string> = {
  PAID: 'ok', PARTIAL: 'warn', UNPAID: 'info', OVERDUE: 'danger', CANCELLED: 'muted',
}
const BILL_STATUS_LABEL: Record<string, string> = {
  PAID: '已收', PARTIAL: '部分收款', UNPAID: '未收', OVERDUE: '逾期',
}

export default function Finance() {
  const { activeParkId, can } = useAuth()
  const [status, setStatus] = useState('')
  const [feeType, setFeeType] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 15

  const summary = useAsync(
    () => financeApi.summary(activeParkId ?? undefined),
    [activeParkId],
  )

  const bills = useAsync(
    () => financeApi.bills({
      park_id: activeParkId ?? undefined,
      status: status || undefined,
      fee_type: feeType || undefined,
      keyword: keyword || undefined,
      page,
      page_size: pageSize,
    }),
    [activeParkId, status, feeType, keyword, page],
  )

  const s = summary.data
  const kpi = s?.kpi ?? {}
  const basis = s?.basis as Record<string, string> | undefined

  const trendOption = useMemo(
    () =>
      lineOption({
        x: (s?.trend ?? []).map((t: any) => String(t.month ?? '').slice(2)),
        series: [
          { name: '应收', data: (s?.trend ?? []).map((t: any) => t.receivable), color: '#2F80ED' },
          { name: '实收', data: (s?.trend ?? []).map((t: any) => t.received), color: '#00D4FF' },
          { name: '欠费', data: (s?.trend ?? []).map((t: any) => t.arrears), color: '#EF4444' },
        ],
        yName: '元',
      }),
    [s],
  )

  const rateOption = useMemo(
    () =>
      lineOption({
        x: (s?.trend ?? []).map((t: any) => String(t.month ?? '').slice(2)),
        series: [{
          name: '收缴率(%)',
          data: (s?.trend ?? []).map((t: any) => t.collection_rate),
          color: '#22C55E', area: true,
        }],
        smooth: false,
      }),
    [s],
  )

  const feeOption = useMemo(
    () =>
      barOption({
        x: (s?.fee_dist ?? []).map((f: any) => f.name),
        series: [
          { name: '应收', data: (s?.fee_dist ?? []).map((f: any) => f.receivable) },
          { name: '实收', data: (s?.fee_dist ?? []).map((f: any) => f.received) },
        ],
      }),
    [s],
  )

  const ageOption = useMemo(
    () =>
      pieOption({
        data: (s?.arrears_age ?? []).map((a: any) => ({ name: a.name, value: a.amount })),
        centerLabel: { title: '欠费总额', value: wan(kpi.total_arrears) },
      }),
    [s, kpi],
  )

  const topOption = useMemo(
    () =>
      rankBarOption({
        names: (s?.top_arrears ?? []).map((t: any) => t.enterprise_name ?? `#${t.enterprise_id}`),
        values: (s?.top_arrears ?? []).map((t: any) => t.arrears),
        color: '#EF4444',
      }),
    [s],
  )

  const billList: any[] = bills.data?.items ?? []
  const total = bills.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / pageSize))

  const doPay = async (bill: any) => {
    const remaining = Number(bill.arrears ?? 0)
    if (remaining <= 0) {
      pushToast('info', '该账单已结清')
      return
    }
    try {
      await financeApi.pay(bill.id, { amount: remaining, pay_method: '银行转账' })
      pushToast('ok', `已登记收款 ${fmt(remaining)} 元`)
      bills.reload()
      summary.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '收款登记失败')
    }
  }

  const doDunning = async (bill: any) => {
    try {
      await financeApi.dunning(bill.id, '短信催缴（演示）')
      pushToast('ok', '催缴已发起（演示环境不实际发送）')
      bills.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '催缴失败')
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="财务与收费"
        desc="应收、实收、欠费账龄与收缴率，全部由后端基于账单台账实时聚合。"
        demo
      />

      {/* ------------------------------------------------------------ KPI */}
      {summary.loading ? (
        <Panel><Loading text="正在汇总财务指标…" /></Panel>
      ) : summary.error ? (
        <Panel><ErrorState error={summary.error} onRetry={summary.reload} /></Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-7">
            <KpiCard label="本月应收" value={wan(kpi.month_receivable)} unit="元" />
            <KpiCard
              label="本月实收" value={wan(kpi.month_received)} unit="元" tone="ok"
              delta={kpi.month_mom} deltaLabel="环比"
            />
            <KpiCard label="累计应收" value={wan(kpi.total_receivable)} unit="元" />
            <KpiCard label="累计实收" value={wan(kpi.total_received)} unit="元" tone="ok" />
            <KpiCard
              label="收缴率" value={fmt(kpi.collection_rate, 2)} unit="%"
              tone={Number(kpi.collection_rate) >= 90 ? 'ok' : 'warn'}
              hint={basis?.collection_rate}
            />
            <KpiCard label="累计欠费" value={wan(kpi.total_arrears)} unit="元" tone="warn"
              hint={basis?.arrears} />
            <KpiCard label="逾期欠费" value={wan(kpi.overdue_arrears)} unit="元" tone="risk"
              hint={`逾期 ${kpi.overdue_count ?? 0} 笔`} />
          </div>

          {basis && (
            <Panel title="指标口径" subtitle="由后端下发，前端不重复维护口径文案">
              <dl className="grid grid-cols-1 gap-x-8 gap-y-1.5 text-xs md:grid-cols-2">
                {Object.entries(basis).map(([k, v]) => (
                  <div key={k} className="flex gap-3 border-b border-white/5 py-1.5">
                    <dt className="w-24 shrink-0 font-num font-medium text-brand-300">{k}</dt>
                    <dd className="text-slate-400">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------ 图表区 */}
      {s && (
        <>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <Panel title="应收 / 实收 / 欠费趋势" subtitle="近 12 个月">
                <Chart height={290} option={trendOption} empty={(s.trend ?? []).length === 0} />
              </Panel>
            </div>
            <Panel title="收费项目构成" subtitle="按 fee_type 归集（元）">
              <Chart height={290} option={feeOption} empty={(s.fee_dist ?? []).length === 0} />
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Panel title="收缴率趋势" subtitle="实收 ÷ 应收 × 100%">
              <Chart height={260} option={rateOption} empty={(s.trend ?? []).length === 0} />
            </Panel>
            <Panel title="欠费账龄分布" subtitle="按账龄区间统计金额">
              <Chart height={260} option={ageOption} empty={(s.arrears_age ?? []).length === 0} />
            </Panel>
            <Panel title="欠费 TOP 10 企业" subtitle="按欠费金额降序">
              <Chart height={260} option={topOption} empty={(s.top_arrears ?? []).length === 0} />
            </Panel>
          </div>

          {(s.top_arrears ?? []).length > 0 && (
            <Panel title="重点欠费企业" subtitle="建议按风险等级分级催缴">
              <DataTable<any>
                columns={[
                  { key: 'enterprise_name', title: '企业名称' },
                  { key: 'industry', title: '行业', render: (r) => r.industry ?? '—' },
                  {
                    key: 'risk_level', title: '风险等级',
                    render: (r) => <Tag tone={RISK_TONE[r.risk_level] ?? 'muted'}>{r.risk_level ?? '—'}</Tag>,
                  },
                  { key: 'arrears', title: '欠费金额(元)', align: 'right', render: (r) => fmt(r.arrears) },
                  { key: 'bill_count', title: '欠费笔数', align: 'right' },
                  {
                    key: 'overdue_days', title: '最长逾期(天)', align: 'right',
                    render: (r) => (
                      <span className={Number(r.overdue_days) > 90 ? 'text-state-danger' : ''}>
                        {r.overdue_days ?? 0}
                      </span>
                    ),
                  },
                ]}
                rows={s.top_arrears}
                rowKey={(r) => r.enterprise_id}
                compact
              />
            </Panel>
          )}
        </>
      )}

      {/* ------------------------------------------------------ 账单列表 */}
      <Panel
        title="应收账单"
        subtitle={`共 ${total} 笔账单`}
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
              className={inputCls} placeholder="账单号 / 企业名称"
              value={keyword}
              onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
            />
          </Field>
          <Field label="收费类型">
            <select
              className={inputCls} value={feeType}
              onChange={(e) => { setFeeType(e.target.value); setPage(1) }}
            >
              <option value="">全部</option>
              <option value="RENT">租金</option>
              <option value="PROPERTY">物业费</option>
              <option value="UTILITY">水电费</option>
            </select>
          </Field>
          <Field label="账单状态">
            <select
              className={inputCls} value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            >
              <option value="">全部</option>
              {Object.entries(BILL_STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </Field>
          {(status || feeType || keyword) && (
            <Btn
              variant="ghost"
              onClick={() => { setStatus(''); setFeeType(''); setKeyword(''); setPage(1) }}
            >
              清空筛选
            </Btn>
          )}
        </div>

        <DataTable<any>
          columns={[
            {
              key: 'bill_code', title: '账单号',
              render: (r) => <span className="font-num text-xs">{r.bill_code}</span>,
            },
            { key: 'enterprise_name', title: '企业名称', render: (r) => r.enterprise_name ?? '—' },
            {
              key: 'fee_type_name', title: '类型',
              render: (r) => <Tag tone="muted">{r.fee_type_name ?? r.fee_type}</Tag>,
            },
            { key: 'period', title: '账期', render: (r) => <span className="font-num">{r.period ?? '—'}</span> },
            { key: 'due_date', title: '到期日', render: (r) => <span className="font-num">{r.due_date ?? '—'}</span> },
            { key: 'receivable', title: '应收(元)', align: 'right', render: (r) => fmt(r.receivable) },
            { key: 'received', title: '实收(元)', align: 'right', render: (r) => fmt(r.received) },
            {
              key: 'arrears', title: '欠费(元)', align: 'right',
              render: (r) => (
                <span className={Number(r.arrears) > 0 ? 'text-state-warn' : 'text-slate-500'}>
                  {fmt(r.arrears)}
                </span>
              ),
            },
            {
              key: 'collection_rate', title: '收缴率', width: 112,
              render: (r) => <ProgressBar value={Number(r.collection_rate) || 0} showText />,
            },
            {
              key: 'status', title: '状态',
              render: (r) => (
                <Tag tone={BILL_STATUS_TONE[r.status] ?? 'muted'}>{r.status_name ?? r.status}</Tag>
              ),
            },
            {
              key: 'overdue_days', title: '逾期', align: 'right',
              render: (r) => {
                const d = Number(r.overdue_days) || 0
                return d > 0
                  ? <span className="text-state-danger">{d} 天</span>
                  : <span className="text-slate-600">—</span>
              },
            },
            { key: 'dunning_count', title: '催缴', align: 'right', render: (r) => r.dunning_count ?? 0 },
            {
              key: 'ops', title: '操作',
              render: (r) => (
                <div className="flex items-center gap-1.5">
                  {can('finance', 'EDIT') && Number(r.arrears) > 0 && (
                    <>
                      <Btn size="sm" variant="ghost" onClick={() => doPay(r)}>收款</Btn>
                      <Btn size="sm" variant="ghost" onClick={() => doDunning(r)}>催缴</Btn>
                    </>
                  )}
                </div>
              ),
            },
          ]}
          rows={billList}
          loading={bills.loading}
          error={bills.error}
          onRetry={bills.reload}
          rowKey={(r) => r.id}
          compact
          empty="没有匹配的账单"
        />
      </Panel>
    </div>
  )
}

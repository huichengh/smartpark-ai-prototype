/**
 * 科技拟态 UI 基础组件
 *
 * 视觉基调（对齐需求文档的色彩规范）：
 *  - 深海军蓝渐变背景 + 玻璃拟态面板（backdrop-blur）
 *  - 主品牌色 #2F80ED，AI 强调色 #7B61FF
 *  - 所有卡片统一 16px/20px 圆角与发光描边
 *
 * 设计约束：本文件只提供「结构 + 视觉」，不内置任何业务假数据。
 * 数据一律由页面从 API 获取后传入，避免出现「前端硬编码指标」。
 */
import type { ReactNode, CSSProperties } from 'react'
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'
import type { ApiException } from '@/api/client'

export const cx = (...parts: (string | false | null | undefined)[]) =>
  parts.filter(Boolean).join(' ')

/**
 * 统一色调词表（全站组件的单一数据源）。
 *
 * 历史坑：KpiCard 之前只接受 'risk'、ProgressBar 只接受 'danger'，
 * 二者语义相同却互不兼容，导致「同一个 tone 变量喂给两个组件」时编译失败。
 * 现在统一为 Tone，danger ≡ risk（同色），info/muted 仅作弱化标签用。
 */
export const TONES = [
  'brand',
  'ai',
  'ok',
  'warn',
  'risk',
  'danger',
  'info',
  'muted',
] as const
export type Tone = (typeof TONES)[number]

// ================================================================ 面板
export function Panel({
  children,
  className = '',
  title,
  subtitle,
  extra,
  icon,
  padded = true,
  style,
}: {
  children?: ReactNode
  className?: string
  title?: ReactNode
  subtitle?: ReactNode
  extra?: ReactNode
  icon?: ReactNode
  padded?: boolean
  style?: CSSProperties
}) {
  return (
    <section
      className={cx(
        'relative rounded-card border border-white/8 bg-panel-grad backdrop-blur-[14px]',
        'shadow-glass transition-shadow duration-300 hover:shadow-glass-hover',
        className,
      )}
      style={style}
    >
      {(title || extra) && (
        <header className="flex items-start justify-between gap-3 border-b border-white/6 px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-2.5">
            {icon && <span className="mt-0.5 text-brand-400">{icon}</span>}
            <div className="min-w-0">
              <h3 className="truncate text-[15px] font-semibold text-slate-100">{title}</h3>
              {subtitle && (
                <p className="mt-0.5 truncate text-xs text-slate-400">{subtitle}</p>
              )}
            </div>
          </div>
          {extra && <div className="shrink-0">{extra}</div>}
        </header>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

// ================================================================ KPI 卡
export function KpiCard({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  hint,
  tone = 'brand',
  icon,
  loading,
}: {
  label: string
  value: ReactNode
  unit?: string
  /** 环比/同比数值；正负号决定配色（涨红跌绿，符合国内业务语境） */
  delta?: number | null
  deltaLabel?: string
  hint?: ReactNode
  tone?: Tone
  icon?: ReactNode
  loading?: boolean
}) {
  const toneRing: Record<string, string> = {
    brand: 'from-brand-500/22 to-transparent',
    ai: 'from-ai/22 to-transparent',
    ok: 'from-state-ok/22 to-transparent',
    warn: 'from-state-warn/22 to-transparent',
    risk: 'from-state-danger/22 to-transparent',
    danger: 'from-state-danger/22 to-transparent',
    info: 'from-brand-500/14 to-transparent',
    muted: 'from-white/6 to-transparent',
  }
  const toneText: Record<string, string> = {
    brand: 'text-brand-400',
    ai: 'text-ai-light',
    ok: 'text-state-ok',
    warn: 'text-state-warn',
    risk: 'text-state-danger',
    danger: 'text-state-danger',
    info: 'text-brand-300',
    muted: 'text-slate-300',
  }

  return (
    <div className="group relative overflow-hidden rounded-card border border-white/8 bg-panel-grad p-4 shadow-glass backdrop-blur-[14px] transition-all duration-300 hover:shadow-glass-hover">
      <div
        className={cx(
          'pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full bg-gradient-to-br blur-2xl',
          toneRing[tone],
        )}
      />
      <div className="relative flex items-start justify-between gap-2">
        <span className="text-xs font-medium tracking-wide text-slate-400">{label}</span>
        {icon && <span className={cx('opacity-70', toneText[tone])}>{icon}</span>}
      </div>
      <div className="relative mt-2 flex items-baseline gap-1">
        {loading ? (
          <span className="inline-block h-8 w-20 animate-shimmer rounded bg-white/8 bg-[length:200%_100%]" />
        ) : (
          <>
            <span className={cx('font-num text-kpi font-semibold', toneText[tone])}>
              {value}
            </span>
            {unit && <span className="text-xs text-slate-400">{unit}</span>}
          </>
        )}
      </div>
      {(delta !== undefined || hint) && (
        <div className="relative mt-2 flex items-center gap-2 text-xs">
          {delta !== undefined && delta !== null && (
            <span
              className={cx(
                'rounded px-1.5 py-0.5 font-num font-medium',
                delta > 0
                  ? 'bg-state-danger/12 text-state-danger'
                  : delta < 0
                    ? 'bg-state-ok/12 text-state-ok'
                    : 'bg-white/8 text-slate-400',
              )}
            >
              {delta > 0 ? '+' : ''}
              {delta}%{deltaLabel ? ` ${deltaLabel}` : ''}
            </span>
          )}
          {hint && <span className="truncate text-slate-500">{hint}</span>}
        </div>
      )}
    </div>
  )
}

// ================================================================ 状态三态
export function Loading({ text = '加载中…', inline }: { text?: string; inline?: boolean }) {
  return (
    <div
      className={cx(
        'flex items-center justify-center gap-2 text-slate-400',
        inline ? 'py-6' : 'py-16',
      )}
    >
      <Loader2 size={16} className="animate-spin" />
      <span className="text-sm">{text}</span>
    </div>
  )
}

export function EmptyState({
  text = '暂无数据',
  hint,
  action,
}: {
  text?: string
  hint?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      <Inbox size={30} className="text-slate-600" />
      <p className="text-sm text-slate-400">{text}</p>
      {hint && <p className="max-w-md text-xs text-slate-500">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/**
 * 错误态：显式区分「字段权限不足 / 数据不足 / 服务异常」，
 * 并把后端的 error.type 与 message 原样展示，便于定位而非掩盖问题。
 */
export function ErrorState({
  error,
  onRetry,
}: {
  error: ApiException | null
  onRetry?: () => void
}) {
  if (!error) return null
  const isPerm = error.code === 403 || error.type === 'FORBIDDEN'
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <AlertTriangle size={28} className={isPerm ? 'text-state-warn' : 'text-state-danger'} />
      <p className="text-sm font-medium text-slate-200">
        {isPerm ? '没有访问权限' : '数据加载失败'}
      </p>
      <p className="max-w-lg text-xs leading-relaxed text-slate-400">{error.message}</p>
      <p className="font-num text-[11px] text-slate-600">
        {error.type}
        {error.code ? ` · ${error.code}` : ''}
        {error.path ? ` · ${error.path}` : ''}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-white/12 bg-white/5 px-3 py-1.5 text-xs text-slate-200 transition hover:border-brand-400/50 hover:bg-brand-500/12"
        >
          <RefreshCw size={13} /> 重新加载
        </button>
      )}
    </div>
  )
}

// ================================================================ 标签 / 徽标
const TONE_MAP: Record<string, string> = {
  ok: 'bg-state-ok/12 text-state-ok border-state-ok/25',
  info: 'bg-brand-500/14 text-brand-300 border-brand-500/30',
  warn: 'bg-state-warn/12 text-state-warn border-state-warn/25',
  risk: 'bg-state-risk/14 text-state-risk border-state-risk/28',
  danger: 'bg-state-danger/14 text-state-danger border-state-danger/28',
  ai: 'bg-ai/16 text-ai-light border-ai/32',
  muted: 'bg-white/6 text-slate-400 border-white/10',
}

export function Tag({
  children,
  tone = 'muted',
  className = '',
}: {
  children: ReactNode
  tone?: keyof typeof TONE_MAP | string
  className?: string
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium',
        TONE_MAP[tone] ?? TONE_MAP.muted,
        className,
      )}
    >
      {children}
    </span>
  )
}

/** 演示数据水印：所有模拟数据必须显式标注（需求文档硬性要求） */
export function DemoBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded border border-state-warn/35 bg-state-warn/10 px-1.5 py-0.5 text-[10px] font-medium text-state-warn',
        className,
      )}
      title="该平台当前运行于演示环境，数据为模拟生成"
    >
      演示数据
    </span>
  )
}

// ================================================================ 进度条
export function ProgressBar({
  value,
  max = 100,
  tone = 'brand',
  height = 6,
  showText,
}: {
  value: number | null | undefined
  max?: number
  tone?: Tone
  height?: number
  showText?: boolean
}) {
  const v = value ?? 0
  const pct = max > 0 ? Math.min(100, Math.max(0, (v / max) * 100)) : 0
  const bg: Record<string, string> = {
    brand: 'bg-brand-grad',
    ok: 'bg-state-ok',
    warn: 'bg-state-warn',
    risk: 'bg-state-danger',
    danger: 'bg-state-danger',
    ai: 'bg-ai-grad',
    info: 'bg-brand-500',
    muted: 'bg-white/30',
  }
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex-1 overflow-hidden rounded-full bg-white/8"
        style={{ height }}
      >
        <div
          className={cx('h-full rounded-full transition-[width] duration-500', bg[tone] ?? bg.brand)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showText && (
        <span className="w-11 shrink-0 text-right font-num text-xs text-slate-300">
          {value === null || value === undefined ? '—' : `${v.toFixed(1)}%`}
        </span>
      )}
    </div>
  )
}

// ================================================================ 表格
export function DataTable<T>({
  columns,
  rows,
  loading,
  error,
  onRetry,
  empty = '暂无数据',
  rowKey,
  onRowClick,
  compact,
}: {
  columns: {
    key: string
    title: ReactNode
    width?: number | string
    align?: 'left' | 'right' | 'center'
    render?: (row: T, index: number) => ReactNode
  }[]
  rows: T[] | null | undefined
  loading?: boolean
  error?: ApiException | null
  onRetry?: () => void
  empty?: ReactNode
  rowKey: (row: T, i: number) => string | number
  onRowClick?: (row: T) => void
  compact?: boolean
}) {
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (!rows || rows.length === 0) return <EmptyState text={typeof empty === 'string' ? empty : undefined} />

  const cellPad = compact ? 'px-3 py-2' : 'px-3.5 py-2.5'
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-white/8">
            {columns.map((c) => (
              <th
                key={c.key}
                style={{ width: c.width }}
                className={cx(
                  'whitespace-nowrap px-3.5 py-2.5 text-left text-xs font-medium text-slate-400',
                  c.align === 'right' && 'text-right',
                  c.align === 'center' && 'text-center',
                )}
              >
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={rowKey(r, i)}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={cx(
                'border-b border-white/5 transition-colors last:border-0',
                onRowClick
                  ? 'cursor-pointer hover:bg-brand-500/[0.07]'
                  : 'hover:bg-white/[0.03]',
              )}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cx(
                    'align-middle text-slate-200',
                    cellPad,
                    c.align === 'right' && 'text-right font-num',
                    c.align === 'center' && 'text-center',
                  )}
                >
                  {c.render
                    ? c.render(r, i)
                    : ((r as Record<string, any>)[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ================================================================ 其他小组件
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = 'md',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode }[]
  size?: 'sm' | 'md'
}) {
  return (
    <div className="inline-flex rounded-lg border border-white/10 bg-white/[0.04] p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            'rounded-md font-medium transition-all',
            size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-[13px]',
            value === o.value
              ? 'bg-brand-500/22 text-brand-300 shadow-[0_0_0_1px_rgba(47,128,237,0.35)]'
              : 'text-slate-400 hover:text-slate-200',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Field({
  label,
  children,
  hint,
}: {
  label: ReactNode
  children: ReactNode
  hint?: ReactNode
}) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-slate-400">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
  )
}

export const inputCls =
  'w-full rounded-lg border border-white/10 bg-white/[0.05] px-3 py-2 text-sm text-slate-100 ' +
  'placeholder:text-slate-500 outline-none transition ' +
  'focus:border-brand-400/60 focus:bg-brand-500/[0.08] focus:ring-2 focus:ring-brand-500/18'

export function Btn({
  children,
  onClick,
  variant = 'default',
  disabled,
  loading,
  size = 'md',
  className = '',
  title,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'default' | 'primary' | 'ai' | 'danger' | 'ghost'
  disabled?: boolean
  loading?: boolean
  size?: 'sm' | 'md'
  className?: string
  title?: string
  type?: 'button' | 'submit'
}) {
  const base =
    'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all ' +
    'disabled:cursor-not-allowed disabled:opacity-45'
  const sizes = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-[13px]'
  const variants: Record<string, string> = {
    default:
      'border border-white/12 bg-white/[0.06] text-slate-200 hover:border-brand-400/45 hover:bg-brand-500/12',
    primary:
      'bg-brand-grad text-white shadow-glow-brand hover:brightness-110 active:brightness-95',
    ai: 'bg-ai-grad text-white shadow-glow-ai hover:brightness-110 active:brightness-95',
    danger:
      'border border-state-danger/35 bg-state-danger/12 text-state-danger hover:bg-state-danger/20',
    ghost: 'text-slate-400 hover:bg-white/6 hover:text-slate-200',
  }
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || loading}
      className={cx(base, sizes, variants[variant], className)}
    >
      {loading && <Loader2 size={13} className="animate-spin" />}
      {children}
    </button>
  )
}

/** 页面标题区 */
export function PageHeader({
  title,
  desc,
  extra,
  demo,
}: {
  title: ReactNode
  desc?: ReactNode
  extra?: ReactNode
  demo?: boolean
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight text-slate-50">{title}</h1>
          {demo && <DemoBadge />}
        </div>
        {desc && <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-slate-400">{desc}</p>}
      </div>
      {extra && <div className="flex items-center gap-2">{extra}</div>}
    </div>
  )
}

/** 迷你统计行（用于面板内嵌摘要） */
export function StatLine({
  items,
}: {
  items: { label: string; value: ReactNode; tone?: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2">
      {items.map((it) => (
        <div key={it.label} className="flex items-baseline gap-1.5">
          <span className="text-xs text-slate-500">{it.label}</span>
          <span
            className={cx(
              'font-num text-sm font-semibold',
              it.tone ? `text-${it.tone}` : 'text-slate-200',
            )}
            style={it.tone ? { color: it.tone } : undefined}
          >
            {it.value}
          </span>
        </div>
      ))}
    </div>
  )
}

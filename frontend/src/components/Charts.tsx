/**
 * ECharts 通用封装
 *
 * 统一深色主题与交互行为，避免每个图表各写一份 option 造成视觉不一致。
 * 颜色取自 tailwind.config.js 的设计 Token，保证图表与 UI 同源。
 */
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { EmptyState, Loading } from './ui'

export const CHART_COLORS = [
  '#2F80ED',
  '#00D4FF',
  '#7B61FF',
  '#22C55E',
  '#FACC15',
  '#F97316',
  '#EF4444',
  '#38BDF8',
  '#A48CFF',
  '#34D399',
]

/** 中文语境下的状态色：涨红跌绿 */
export const RISE = '#EF4444'
export const FALL = '#22C55E'

const BASE: Partial<EChartsOption> = {
  backgroundColor: 'transparent',
  textStyle: { color: '#94A3B8', fontFamily: 'Inter, PingFang SC, Microsoft YaHei' },
  grid: { left: 8, right: 12, top: 28, bottom: 4, containLabel: true },
  tooltip: {
    backgroundColor: 'rgba(13,27,42,0.94)',
    borderColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    textStyle: { color: '#E2E8F0', fontSize: 12 },
    extraCssText: 'backdrop-filter: blur(8px); border-radius: 10px;',
  },
  legend: {
    textStyle: { color: '#94A3B8', fontSize: 11 },
    itemWidth: 10,
    itemHeight: 8,
    icon: 'roundRect',
  },
}

const AXIS = {
  axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
  axisTick: { show: false },
  axisLabel: { color: '#64748B', fontSize: 11 },
  splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)', type: 'dashed' as const } },
}

export function Chart({
  option,
  height = 260,
  loading,
  empty,
  className = '',
  onEvents,
}: {
  option: EChartsOption
  height?: number
  loading?: boolean
  empty?: boolean
  className?: string
  onEvents?: Record<string, (params: any) => void>
}) {
  if (loading) return <Loading inline />
  if (empty) return <EmptyState text="该维度暂无数据" hint="可能当前筛选范围内没有对应记录" />

  return (
    <ReactECharts
      className={className}
      option={{
        ...BASE,
        ...option,
        grid: { ...BASE.grid, ...(option.grid as object) },
      }}
      style={{ height, width: '100%' }}
      opts={{ renderer: 'canvas' }}
      notMerge
      lazyUpdate
      onEvents={onEvents}
    />
  )
}

/** 折线/面积图 */
export function lineOption({
  x,
  series,
  showLegend = true,
  area = false,
  yName,
  smooth = true,
}: {
  x: (string | number)[]
  series: { name: string; data: (number | null)[]; color?: string; area?: boolean }[]
  showLegend?: boolean
  area?: boolean
  yName?: string
  smooth?: boolean
}): EChartsOption {
  return {
    legend: { show: showLegend, top: 0, right: 0 },
    grid: { top: showLegend ? 32 : 16 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: 'rgba(47,128,237,0.4)' } } },
    xAxis: { type: 'category', boundaryGap: false, data: x, ...AXIS },
    yAxis: { type: 'value', name: yName, nameTextStyle: { color: '#64748B', fontSize: 11 }, ...AXIS },
    series: series.map((s, i) => ({
      name: s.name,
      type: 'line',
      smooth,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: x.length <= 14,
      data: s.data,
      itemStyle: { color: s.color ?? CHART_COLORS[i % CHART_COLORS.length] },
      lineStyle: { width: 2, color: s.color ?? CHART_COLORS[i % CHART_COLORS.length] },
      areaStyle:
        area || s.area
          ? {
              opacity: 0.16,
              color: s.color ?? CHART_COLORS[i % CHART_COLORS.length],
            }
          : undefined,
    })),
  }
}

/** 柱状图（支持堆叠） */
export function barOption({
  x,
  series,
  stack,
  horizontal,
  showLegend = true,
}: {
  x: (string | number)[]
  series: { name: string; data: (number | null)[]; color?: string }[]
  stack?: boolean
  horizontal?: boolean
  showLegend?: boolean
}): EChartsOption {
  const cat = { type: 'category' as const, data: x, ...AXIS }
  const val = { type: 'value' as const, ...AXIS }
  return {
    legend: { show: showLegend, top: 0, right: 0 },
    grid: { top: showLegend ? 32 : 16, left: horizontal ? 100 : 8 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? { ...cat, axisLabel: { ...cat.axisLabel, width: 92, overflow: 'truncate' } } : val,
    series: series.map((s, i) => ({
      name: s.name,
      type: 'bar',
      stack: stack ? 'total' : undefined,
      barMaxWidth: 26,
      data: s.data,
      itemStyle: {
        color: s.color ?? CHART_COLORS[i % CHART_COLORS.length],
        borderRadius: stack ? 0 : ([3, 3, 0, 0] as number[]),
      },
    })),
  }
}

/** 饼/环图 */
export function pieOption({
  data,
  donut = true,
  centerLabel,
}: {
  data: { name: string; value: number; color?: string }[]
  donut?: boolean
  centerLabel?: { title: string; value: string | number }
}): EChartsOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} ({d}%)' },
    legend: {
      orient: 'vertical',
      right: 0,
      top: 'middle',
      textStyle: { color: '#94A3B8', fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: donut ? ['52%', '74%'] : '66%',
        center: ['36%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#0A1628', borderWidth: 2 },
        label: { show: false },
        emphasis: {
          label: { show: false },
          scale: true,
          scaleSize: 6,
          itemStyle: { shadowBlur: 14, shadowColor: 'rgba(47,128,237,0.4)' },
        },
        labelLine: { show: false },
        data: data.map((d, i) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: d.color ?? CHART_COLORS[i % CHART_COLORS.length] },
        })),
      },
    ],
    graphic: centerLabel
      ? ([
          {
            type: 'text',
            left: '36%',
            top: '44%',
            style: {
              text: String(centerLabel.value),
              // ECharts 的 text 对齐用 align，不是 CSS 的 textAlign
              align: 'center',
              fill: '#E2E8F0',
              fontSize: 22,
              fontWeight: 600,
            },
          },
          {
            type: 'text',
            left: '36%',
            top: '58%',
            style: {
              text: centerLabel.title,
              align: 'center',
              fill: '#64748B',
              fontSize: 11,
            },
          },
        ] as unknown as EChartsOption['graphic'])
      : undefined,
  }
}

/** 漏斗图（招商管道） */
export function funnelOption({
  data,
}: {
  data: { name: string; value: number; color?: string }[]
}): EChartsOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}<br/>到达 {c} 条' },
    series: [
      {
        type: 'funnel',
        left: '4%',
        right: '4%',
        top: 14,
        bottom: 10,
        minSize: '28%',
        sort: 'descending',
        gap: 2,
        label: { color: '#CBD5E1', fontSize: 11, position: 'inside' },
        itemStyle: { borderColor: 'transparent' },
        data: data.map((d, i) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: d.color ?? CHART_COLORS[i % CHART_COLORS.length], opacity: 0.86 },
        })),
      },
    ],
  }
}

/** 横向条形（排行/分布） */
export function rankBarOption({
  names,
  values,
  color = '#2F80ED',
  max,
}: {
  names: string[]
  values: number[]
  color?: string
  max?: number
}): EChartsOption {
  return {
    grid: { left: 4, right: 34, top: 6, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', max, ...AXIS, axisLabel: { show: false }, splitLine: { show: false } },
    yAxis: {
      type: 'category',
      data: names,
      inverse: true,
      ...AXIS,
      axisLine: { show: false },
      splitLine: { show: false },
      axisLabel: { color: '#94A3B8', fontSize: 11, width: 96, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        data: values,
        barMaxWidth: 14,
        itemStyle: { color, borderRadius: [0, 3, 3, 0] },
        label: { show: true, position: 'right', color: '#94A3B8', fontSize: 11, formatter: '{c}' },
      },
    ],
  }
}

export { ReactECharts }

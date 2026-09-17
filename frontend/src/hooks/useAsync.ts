/**
 * 数据请求 Hook
 *
 * 统一处理「加载中 / 失败 / 演示数据标识」三态。
 * 关键设计：失败时把后端返回的结构化错误（code/type/message）原样暴露给页面，
 * 而不是吞掉或替换成「暂无数据」——用户需要知道是「没数据」还是「接口挂了」。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiException } from '@/api/client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiException | null
  reload: () => void
}

export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  options: { enabled?: boolean } = {},
): AsyncState<T> {
  const enabled = options.enabled !== false
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<ApiException | null>(null)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  // 竞态保护：仅接受最后一次请求的结果，避免快速切换筛选时旧响应覆盖新数据
  const seqRef = useRef(0)

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const seq = ++seqRef.current
    let alive = true
    setLoading(true)
    setError(null)

    fnRef
      .current()
      .then((res) => {
        if (!alive || seq !== seqRef.current) return
        setData(res)
      })
      .catch((e: unknown) => {
        if (!alive || seq !== seqRef.current) return
        setError(
          e instanceof ApiException
            ? e
            : new ApiException({
                code: 0,
                type: 'UNKNOWN',
                message: e instanceof Error ? e.message : String(e),
              }),
        )
      })
      .finally(() => {
        if (!alive || seq !== seqRef.current) return
        setLoading(false)
      })

    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, tick, ...deps])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, loading, error, reload }
}

/** 轻量 toast 队列（无第三方依赖） */
type ToastItem = { id: number; kind: 'ok' | 'err' | 'info'; text: string }
let toastSeq = 0
const toastListeners = new Set<(items: ToastItem[]) => void>()
let toasts: ToastItem[] = []

export function pushToast(kind: ToastItem['kind'], text: string, ms = 3200) {
  const item: ToastItem = { id: ++toastSeq, kind, text }
  toasts = [...toasts, item]
  toastListeners.forEach((l) => l(toasts))
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== item.id)
    toastListeners.forEach((l) => l(toasts))
  }, ms)
}

export function useToasts() {
  const [items, setItems] = useState<ToastItem[]>(toasts)
  useEffect(() => {
    toastListeners.add(setItems)
    return () => {
      toastListeners.delete(setItems)
    }
  }, [])
  return items
}

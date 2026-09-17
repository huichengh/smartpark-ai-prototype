/**
 * API 客户端
 *
 * 约定（与后端 app/main.py 保持一致）：
 *  - 统一前缀 /api
 *  - 成功响应：直接返回业务对象（后端未做 {code,data} 包裹）
 *  - 失败响应：HTTP 4xx/5xx + {success:false, error:{code,type,message}, path, timestamp}
 *
 * 这里对响应做「解包归一」：既兼容当前后端直接返回业务对象的形式，
 * 也兼容未来若引入 {code,data} 包裹的形态，避免前端到处写兼容分支。
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosError,
} from 'axios'

export const TOKEN_KEY = 'smartpark_token'
export const USER_KEY = 'smartpark_user'

export interface ApiError {
  code: number
  type: string
  message: string
  path?: string
  timestamp?: string
}

/** 业务异常：携带后端返回的结构化错误信息，便于页面精确展示 */
export class ApiException extends Error {
  code: number
  type: string
  path?: string
  status?: number

  constructor(e: ApiError, status?: number) {
    super(e.message)
    this.name = 'ApiException'
    this.code = e.code
    this.type = e.type
    this.path = e.path
    this.status = status
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser<T = any>(): T | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function setStoredUser(u: unknown | null) {
  if (u) localStorage.setItem(USER_KEY, JSON.stringify(u))
  else localStorage.removeItem(USER_KEY)
}

/** 未授权时的回调，由 AuthProvider 注册，避免 axios 直接依赖 router */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

/**
 * Query 序列化
 *
 * 后端有 20 个「写操作」端点的参数声明为简单类型（FastAPI 默认解析为 query 参数，
 * 而非 body），因此前端必须把这些参数放到 URL 上。
 * 另外 FastAPI 对数组类 query 参数期望「重复键」形式（permissions=a&permissions=b），
 * 而 axios 默认会序列化成 permissions[]=a，后端解析不到，故这里显式接管。
 */
function serializeParams(params: Record<string, any>): string {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null) return
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)))
    else sp.append(k, String(v))
  })
  return sp.toString()
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
  paramsSerializer: { serialize: (p: any) => serializeParams(p ?? {}) },
})

http.interceptors.request.use((config) => {
  const t = getToken()
  if (t) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${t}`
    // 同时带一份 X-Token：部署到反向代理后面时，网关可能注入/改写 Authorization，
    // 后端会按"多来源候选、取第一个验得通的"来处理，真令牌因此不会被顶掉。
    config.headers['X-Token'] = t
  }
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError<any>) => {
    const status = err.response?.status
    const body = err.response?.data

    // 401：凭证失效，清理并通知上层跳登录
    if (status === 401) {
      setToken(null)
      setStoredUser(null)
      onUnauthorized?.()
    }

    // 后端结构化错误体
    if (body && typeof body === 'object' && body.error) {
      return Promise.reject(
        new ApiException(
          {
            code: body.error.code ?? status ?? 0,
            type: body.error.type ?? 'UNKNOWN',
            message: body.error.message ?? '请求失败',
            path: body.path,
            timestamp: body.timestamp,
          },
          status,
        ),
      )
    }

    // 网络层错误 / 非结构化错误体
    return Promise.reject(
      new ApiException(
        {
          code: status ?? 0,
          type: status ? 'HTTP_ERROR' : 'NETWORK_ERROR',
          message:
            err.message || (status ? `请求失败（HTTP ${status}）` : '无法连接后端服务'),
        },
        status,
      ),
    )
  },
)

/** 解包归一：兼容 {code,data} 包裹与直接返回业务对象两种形态 */
function unwrap<T>(payload: any): T {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    if ('data' in payload && 'code' in payload && Object.keys(payload).length <= 4) {
      return payload.data as T
    }
  }
  return payload as T
}

export async function request<T = any>(
  cfg: AxiosRequestConfig,
): Promise<T> {
  const resp = await http.request(cfg)
  return unwrap<T>(resp.data)
}

export const api = {
  get: <T = any>(url: string, params?: Record<string, any>) =>
    request<T>({ method: 'GET', url, params }),
  /**
   * 注意：后端多数写操作端点的参数是 query 参数而非 body，
   * 调用时请把参数放到第三个入参 params，而不是第二个 data。
   */
  post: <T = any>(url: string, data?: any, params?: Record<string, any>) =>
    request<T>({ method: 'POST', url, data, params }),
  put: <T = any>(url: string, data?: any, params?: Record<string, any>) =>
    request<T>({ method: 'PUT', url, data, params }),
  patch: <T = any>(url: string, data?: any, params?: Record<string, any>) =>
    request<T>({ method: 'PATCH', url, data, params }),
  del: <T = any>(url: string, data?: any, params?: Record<string, any>) =>
    request<T>({ method: 'DELETE', url, data, params }),
  /** 下载文件（报表导出等）。返回 Blob 与从响应头解析出的文件名。 */
  download: async (
    url: string,
    params?: Record<string, any>,
  ): Promise<{ blob: Blob; filename: string }> => {
    const resp = await http.request({
      method: 'GET',
      url,
      params,
      responseType: 'blob',
    })
    return {
      blob: resp.data as Blob,
      filename: parseFilename(resp.headers?.['content-disposition']),
    }
  },
}

/** 解析 Content-Disposition，优先取 RFC 5987 的 filename*（支持中文） */
export function parseFilename(disposition?: string): string {
  if (!disposition) return 'download'
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))
    } catch {
      /* 落回普通 filename */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain?.[1]?.trim() || 'download'
}

/** 触发浏览器下载 */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default http

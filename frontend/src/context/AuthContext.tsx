/**
 * 认证与权限上下文
 *
 * 权限模型与后端 app/core/security.py 对齐：
 *  - 权限点编码形如 `<module>:<action>`（如 space:VIEW、finance:APPROVE）
 *  - 角色携带 data_scope（GROUP / PARK / DEPARTMENT / PROJECT / ENTERPRISE / SELF）
 *  - 页面通过 useAuth().can(module, action) 做按钮级与页面级控制，
 *    与后端 auth.require(module, action) 一一对应，避免「前端能点、后端拒绝」
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { authApi, type SessionUser } from '@/api/modules'
import { setUnauthorizedHandler, setStoredUser, setToken, getToken } from '@/api/client'

interface AuthState {
  user: SessionUser | null
  loading: boolean
  /** 当前可见园区 id 列表；null 表示不限（集团级） */
  visibleParkIds: number[] | null
  /** 当前选中的园区（顶栏切换），null 表示「全部园区」 */
  activeParkId: number | null
  setActiveParkId: (id: number | null) => void
  login: (username: string, password: string) => Promise<SessionUser>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  can: (module: string, action: string) => boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthState | null>(null)

const ACTIVE_PARK_KEY = 'smartpark_active_park'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeParkId, setActiveParkIdState] = useState<number | null>(() => {
    const raw = localStorage.getItem(ACTIVE_PARK_KEY)
    return raw ? Number(raw) : null
  })

  const setActiveParkId = useCallback((id: number | null) => {
    setActiveParkIdState(id)
    if (id === null) localStorage.removeItem(ACTIVE_PARK_KEY)
    else localStorage.setItem(ACTIVE_PARK_KEY, String(id))
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      /* 后端不可用也要完成本地登出 */
    }
    setToken(null)
    setStoredUser(null)
    setUser(null)
    setActiveParkId(null)
  }, [setActiveParkId])

  // 401 时由 axios 拦截器触发，这里做统一登出
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      setToken(null)
      setStoredUser(null)
    })
  }, [])

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await authApi.me()
      setUser(me)
      setStoredUser(me)
    } catch {
      setUser(null)
      setToken(null)
      setStoredUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    const res = await authApi.login(username, password)
    setToken(res.access_token)
    setStoredUser(res.user)
    setUser(res.user)
    return res.user
  }, [])

  const visibleParkIds = useMemo(() => {
    if (!user) return null
    if (user.data_scope === 'GROUP') return null
    return user.visible_park_ids ?? []
  }, [user])

  // 集团级账号若未选园区，则不下发 park_id（后端按全量聚合）
  const can = useCallback(
    (module: string, action: string) => {
      if (!user) return false
      const perms = user.permissions
      if (!perms || perms.length === 0) {
        // 权限点未随登录下发时，退化为「按角色判定」，避免全站按钮不可用
        return (user.roles ?? []).some(
          (r) => r.code === 'SUPER_ADMIN' || r.code === 'GROUP_ADMIN',
        )
      }
      const u = action.toUpperCase()
      return perms.includes(`${module}:${u}`) || perms.includes(`${module.toUpperCase()}:${u}`)
    },
    [user],
  )

  const isAdmin = useMemo(
    () => (user?.roles ?? []).some((r) => r.code === 'SUPER_ADMIN'),
    [user],
  )

  const value: AuthState = {
    user,
    loading,
    visibleParkIds,
    activeParkId,
    setActiveParkId,
    login,
    logout,
    refresh,
    can,
    isAdmin,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}

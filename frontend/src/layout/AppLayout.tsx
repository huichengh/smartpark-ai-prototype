/**
 * 全局框架：左侧导航 + 顶部栏 + 内容区
 *
 * 顶栏的园区切换器把当前园区写入 AuthContext，
 * 各页面统一通过 useParkQuery() 取用，避免每个页面各自维护一份筛选状态。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Search,
  Sparkles,
  UserCircle2,
  X,
} from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { NAV_GROUPS, NAV_ITEMS, findNav } from '@/config/nav'
import { notificationApi, systemApi } from '@/api/modules'
import { cx, DemoBadge } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { useToasts } from '@/hooks/useAsync'

/** 顶栏 · 园区切换 */
function ParkSwitcher() {
  const { user, visibleParkIds, activeParkId, setActiveParkId } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { data } = useAsync(() => systemApi.parks(), [])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const parks = useMemo(() => {
    const list = (data as any)?.items ?? []
    const visible = visibleParkIds ? list.filter((p: any) => visibleParkIds.includes(p.id)) : list
    return visible as { id: number; park_name: string; park_code: string }[]
  }, [data, visibleParkIds])

  const current = parks.find((p) => p.id === activeParkId)

  if (!user) return null
  if (parks.length === 0) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[13px] text-slate-200 transition hover:border-brand-400/45 hover:bg-brand-500/10"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-brand-glow shadow-[0_0_6px_currentColor]" />
        <span className="max-w-[168px] truncate">{current?.park_name ?? '全部园区'}</span>
        <ChevronDown size={13} className={cx('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1.5 min-w-[228px] animate-fade-up overflow-hidden rounded-xl border border-white/10 bg-nav-panel/95 py-1 shadow-glass backdrop-blur-xl">
          <button
            onClick={() => {
              setActiveParkId(null)
              setOpen(false)
            }}
            className={cx(
              'block w-full px-3.5 py-2 text-left text-[13px] transition',
              activeParkId === null
                ? 'bg-brand-500/16 text-brand-300'
                : 'text-slate-300 hover:bg-white/6',
            )}
          >
            全部园区（按权限汇总）
          </button>
          <div className="my-1 h-px bg-white/8" />
          {parks.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                setActiveParkId(p.id)
                setOpen(false)
              }}
              className={cx(
                'block w-full px-3.5 py-2 text-left transition',
                activeParkId === p.id
                  ? 'bg-brand-500/16 text-brand-300'
                  : 'text-slate-300 hover:bg-white/6',
              )}
            >
              <span className="block truncate text-[13px]">{p.park_name}</span>
              <span className="font-num text-[11px] text-slate-500">{p.park_code}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** 顶栏 · 未读通知 */
function NotifyBell() {
  const [count, setCount] = useState(0)
  const nav = useNavigate()

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r: any = await notificationApi.unreadCount()
        if (alive) setCount(r?.total ?? r?.unread ?? 0)
      } catch {
        /* 通知服务不可用不应打断主流程 */
      }
    }
    void load()
    const t = setInterval(load, 60000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <button
      onClick={() => nav('/notification')}
      title={count > 0 ? `${count} 条未读` : '消息通知'}
      className="relative rounded-lg border border-white/10 bg-white/[0.05] p-2 text-slate-300 transition hover:border-brand-400/45 hover:bg-brand-500/10"
    >
      <Bell size={15} />
      {count > 0 && (
        <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-state-danger px-1 font-num text-[10px] font-semibold text-white">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  )
}

/** 顶栏 · 用户菜单 */
function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const nav = useNavigate()

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  if (!user) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1.5 transition hover:border-brand-400/45 hover:bg-brand-500/10"
      >
        <UserCircle2 size={18} className="text-brand-300" />
        <span className="hidden text-[13px] text-slate-200 sm:block">{user.real_name}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-1.5 w-64 animate-fade-up overflow-hidden rounded-xl border border-white/10 bg-nav-panel/95 shadow-glass backdrop-blur-xl">
          <div className="border-b border-white/8 px-4 py-3">
            <p className="text-sm font-medium text-slate-100">{user.real_name}</p>
            <p className="mt-0.5 font-num text-[11px] text-slate-500">{user.username}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              <span className="rounded border border-ai/32 bg-ai/14 px-1.5 py-0.5 text-[10px] text-ai-light">
                {user.role_label ?? '未分配角色'}
              </span>
              <span className="rounded border border-white/12 bg-white/6 px-1.5 py-0.5 text-[10px] text-slate-400">
                范围 {user.data_scope ?? '—'}
              </span>
            </div>
            {user.department && (
              <p className="mt-1.5 text-[11px] text-slate-500">
                {user.department}
                {user.position ? ` · ${user.position}` : ''}
              </p>
            )}
          </div>
          <button
            onClick={async () => {
              await logout()
              nav('/login', { replace: true })
            }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] text-slate-300 transition hover:bg-state-danger/12 hover:text-state-danger"
          >
            <LogOut size={14} /> 退出登录
          </button>
        </div>
      )}
    </div>
  )
}

function Toasts() {
  const items = useToasts()
  if (items.length === 0) return null
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-[60] space-y-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={cx(
            'animate-fade-up rounded-xl border px-4 py-2.5 text-[13px] shadow-glass backdrop-blur-xl',
            t.kind === 'ok' && 'border-state-ok/35 bg-state-ok/12 text-state-ok',
            t.kind === 'err' && 'border-state-danger/35 bg-state-danger/12 text-state-danger',
            t.kind === 'info' && 'border-brand-500/35 bg-brand-500/12 text-brand-300',
          )}
        >
          {t.text}
        </div>
      ))}
    </div>
  )
}

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const loc = useLocation()
  const { can } = useAuth()
  const current = findNav(loc.pathname)

  // 按权限过滤菜单（仅隐藏，真实边界由后端控制）
  const visibleNav = useMemo(
    () => NAV_ITEMS.filter((n) => !n.perm || can(n.perm[0], n.perm[1])),
    [can],
  )

  // 路由切换时收起移动端抽屉
  useEffect(() => setMobileOpen(false), [loc.pathname])

  const sidebar = (
    <aside
      className={cx(
        'flex h-full flex-col border-r border-white/8 bg-nav-deep/85 backdrop-blur-xl transition-[width] duration-300',
        collapsed ? 'w-[68px]' : 'w-[228px]',
      )}
    >
      {/* Logo */}
      <div className="flex h-[58px] shrink-0 items-center gap-2.5 border-b border-white/8 px-4">
        <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-grad shadow-glow-brand">
          <Sparkles size={16} className="text-white" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-[13px] font-semibold tracking-tight text-slate-50">
              园智汇
            </p>
            <p className="truncate text-[10px] text-slate-500">AI 产业园区智慧运营平台</p>
          </div>
        )}
      </div>

      {/* 导航 */}
      <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 py-3.5">
        {NAV_GROUPS.map((g) => {
          const items = visibleNav.filter((n) => n.group === g)
          if (items.length === 0) return null
          return (
            <div key={g}>
              {!collapsed && (
                <p className="mb-1.5 px-2 text-[10px] font-medium tracking-wider text-slate-600">
                  {g}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map((n) => {
                  const Icon = n.icon
                  const active =
                    loc.pathname === n.path || loc.pathname.startsWith(`${n.path}/`)
                  return (
                    <NavLink
                      key={n.path}
                      to={n.path}
                      title={collapsed ? n.label : undefined}
                      className={cx(
                        'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 transition-all',
                        active
                          ? 'bg-brand-500/16 text-brand-300 shadow-[inset_0_0_0_1px_rgba(47,128,237,0.28)]'
                          : 'text-slate-400 hover:bg-white/6 hover:text-slate-200',
                      )}
                    >
                      {active && (
                        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r bg-brand-glow" />
                      )}
                      <Icon size={16} className="shrink-0" />
                      {!collapsed && (
                        <span className="truncate text-[13px] font-medium">{n.label}</span>
                      )}
                    </NavLink>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>

      <button
        onClick={() => setCollapsed((v) => !v)}
        className="hidden h-10 shrink-0 items-center justify-center border-t border-white/8 text-slate-500 transition hover:bg-white/5 hover:text-slate-300 lg:flex"
        title={collapsed ? '展开导航' : '收起导航'}
      >
        <Menu size={15} />
      </button>
    </aside>
  )

  return (
    <div className="flex h-screen overflow-hidden bg-nav-deep text-slate-200">
      {/* 背景装饰：网格 + 光晕 */}
      <div className="pointer-events-none fixed inset-0 bg-grid-fade bg-[size:44px_44px] opacity-40" />
      <div className="pointer-events-none fixed -left-40 top-0 h-[420px] w-[420px] rounded-full bg-brand-500/8 blur-[120px]" />
      <div className="pointer-events-none fixed -right-32 bottom-0 h-[380px] w-[380px] rounded-full bg-ai/8 blur-[120px]" />

      {/* 桌面端侧栏 */}
      <div className="relative z-20 hidden lg:block">{sidebar}</div>

      {/* 移动端抽屉 */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/55 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute left-0 top-0 h-full animate-fade-up">{sidebar}</div>
        </div>
      )}

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        {/* 顶栏 */}
        <header className="flex h-[58px] shrink-0 items-center gap-3 border-b border-white/8 bg-nav-base/70 px-4 backdrop-blur-xl">
          <button
            onClick={() => setMobileOpen(true)}
            className="rounded-lg border border-white/10 bg-white/[0.05] p-2 text-slate-300 lg:hidden"
          >
            <Menu size={15} />
          </button>

          <ParkSwitcher />

          <div className="hidden flex-1 items-center md:flex">
            <div className="relative w-full max-w-[280px]">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
              />
              <input
                placeholder="搜索园区、企业、项目…"
                className="w-full rounded-lg border border-white/10 bg-white/[0.05] py-1.5 pl-8 pr-3 text-[13px] text-slate-200 placeholder:text-slate-500 outline-none transition focus:border-brand-400/50 focus:bg-brand-500/[0.08]"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    const v = (e.target as HTMLInputElement).value.trim()
                    if (v) window.location.href = `/ai?q=${encodeURIComponent(v)}`
                  }
                }}
              />
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <DemoBadge className="hidden sm:inline-flex" />
            {current && (
              <span className="hidden text-[12px] text-slate-500 xl:block">{current.desc}</span>
            )}
            <NotifyBell />
            <UserMenu />
          </div>
        </header>

        {/* 内容区 */}
        <main className="flex-1 overflow-y-auto px-4 py-5 lg:px-6">
          <Outlet />
        </main>
      </div>

      <Toasts />
    </div>
  )
}

export { X }

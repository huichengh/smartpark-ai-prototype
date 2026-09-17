/**
 * 登录页
 *
 * 展示演示账号是为了让评估者能直接进入系统体验不同权限视角，
 * 因此这里的账号列表是「演示环境的一部分」，而非硬编码业务指标。
 */
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Boxes, KeyRound, Loader2, Sparkles, User } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { ApiException } from '@/api/client'
import { cx, inputCls } from '@/components/ui'

const DEMO_ACCOUNTS = [
  { u: 'admin', label: '集团管理员', scope: 'GROUP · 全部园区', desc: '全模块 + 系统管理' },
  { u: 'p1_manager', label: '园区负责人', scope: 'PARK · 园区1', desc: '单园区运营视角' },
  { u: 'tenant1', label: '企业管理员', scope: 'ENTERPRISE', desc: '入驻企业自助视角' },
]

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('Park@2026')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (busy) return
    setBusy(true)
    setErr(null)
    try {
      await login(username.trim(), password)
      nav(loc.state?.from || '/dashboard', { replace: true })
    } catch (e) {
      setErr(
        e instanceof ApiException
          ? e.message
          : '登录失败，请确认后端服务已启动（默认 127.0.0.1:8010）',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-nav-deep px-4">
      {/* 背景装饰 */}
      <div className="pointer-events-none absolute inset-0 bg-grid-fade bg-[size:48px_48px] opacity-50" />
      <div className="pointer-events-none absolute -left-40 top-0 h-[460px] w-[460px] rounded-full bg-brand-500/12 blur-[130px]" />
      <div className="pointer-events-none absolute -right-32 bottom-0 h-[420px] w-[420px] rounded-full bg-ai/12 blur-[130px]" />

      <div className="relative z-10 grid w-full max-w-[980px] gap-8 lg:grid-cols-[1.1fr_1fr]">
        {/* 品牌区 */}
        <div className="hidden flex-col justify-center lg:flex">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-grad shadow-glow-brand">
              <Sparkles size={22} className="text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-50">园智汇</h1>
              <p className="text-[13px] text-slate-400">AI 产业园区智慧运营管理平台</p>
            </div>
          </div>

          <p className="mt-7 max-w-md text-[13px] leading-relaxed text-slate-400">
            面向多园区、多租户场景的一体化运营平台。整合空间资产、招商运营、企业经营、
            合同财务、项目管理与物业运维，由 AI 智能体贯穿数据洞察、风险预警与决策建议，
            高风险动作一律经人工审批。
          </p>

          <div className="mt-9 grid grid-cols-3 gap-4">
            {[
              { k: '20', v: '业务模块' },
              { k: '129', v: 'API 端点' },
              { k: '11', v: 'AI 子智能体' },
            ].map((s) => (
              <div
                key={s.v}
                className="rounded-card border border-white/8 bg-panel-grad p-3.5 backdrop-blur-[14px]"
              >
                <p className="font-num text-kpi-sm font-semibold text-brand-400">{s.k}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{s.v}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 flex items-center gap-2 text-[11px] text-slate-600">
            <Boxes size={13} />
            <span>演示环境 · 全部业务数据为模拟生成，仅供功能演示</span>
          </div>
        </div>

        {/* 表单区 */}
        <div className="rounded-panel border border-white/10 bg-panel-grad p-6 shadow-glass backdrop-blur-[16px]">
          <div className="flex items-center gap-2.5 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-grad">
              <Sparkles size={17} className="text-white" />
            </div>
            <div>
              <p className="text-base font-semibold text-slate-50">园智汇</p>
              <p className="text-[11px] text-slate-500">AI 产业园区智慧运营平台</p>
            </div>
          </div>

          <h2 className="mt-5 text-lg font-semibold text-slate-50 lg:mt-0">账号登录</h2>
          <p className="mt-1 text-xs text-slate-500">请使用平台分配的账号登录</p>

          <form
            className="mt-6 space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-400">用户名</label>
              <div className="relative">
                <User
                  size={15}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                />
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  className={cx(inputCls, 'pl-9')}
                  placeholder="请输入用户名"
                />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-400">密码</label>
              <div className="relative">
                <KeyRound
                  size={15}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  className={cx(inputCls, 'pl-9')}
                  placeholder="请输入密码"
                />
              </div>
            </div>

            {err && (
              <div className="rounded-lg border border-state-danger/35 bg-state-danger/10 px-3 py-2 text-xs leading-relaxed text-state-danger">
                {err}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-grad py-2.5 text-sm font-medium text-white shadow-glow-brand transition hover:brightness-110 active:brightness-95 disabled:opacity-60"
            >
              {busy && <Loader2 size={15} className="animate-spin" />}
              {busy ? '登录中…' : '登 录'}
            </button>
          </form>

          {/* 演示账号快捷入口 */}
          <div className="mt-6 border-t border-white/8 pt-4">
            <p className="mb-2.5 text-[11px] font-medium tracking-wide text-slate-500">
              演示账号（点击填充，密码统一 Park@2026）
            </p>
            <div className="space-y-1.5">
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.u}
                  onClick={() => {
                    setUsername(a.u)
                    setPassword('Park@2026')
                    setErr(null)
                  }}
                  className={cx(
                    'flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition',
                    username === a.u
                      ? 'border-brand-400/50 bg-brand-500/12'
                      : 'border-white/8 bg-white/[0.03] hover:border-brand-400/35 hover:bg-white/[0.06]',
                  )}
                >
                  <div className="min-w-0">
                    <p className="text-[13px] text-slate-200">
                      <span className="font-num">{a.u}</span>
                      <span className="ml-2 text-slate-400">{a.label}</span>
                    </p>
                    <p className="text-[10px] text-slate-500">{a.desc}</p>
                  </div>
                  <span className="shrink-0 font-num text-[10px] text-slate-500">{a.scope}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

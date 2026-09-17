/**
 * 系统管理 —— 组织架构 / 园区模板 / 用户 / 角色权限
 *
 * 设计要点：
 *  - 权限矩阵是 RBAC 的唯一配置入口：模块 × 动作（VIEW/ADD/EDIT/DELETE/IMPORT/EXPORT/APPROVE/AI/CONFIG），
 *    勾选结果直接写入角色权限绑定，并与后端 auth.require(module, action) 对应。
 *  - 园区模板的模块开关决定该类型园区能用哪些业务模块，切换即持久化（多租户可配置能力）。
 *  - 所有枚举标签（模块/动作/数据范围/园区类型…）均由 /system/dict 下发，前端零硬编码字典。
 */
import { useEffect, useMemo, useState } from 'react'
import { systemApi } from '@/api/modules'
import { pushToast, useAsync } from '@/hooks/useAsync'
import { useAuth } from '@/context/AuthContext'
import {
  Btn, DataTable, EmptyState, ErrorState, KpiCard, Loading,
  PageHeader, Panel, Segmented, Tag, Field, inputCls,
} from '@/components/ui'
import {
  Building2, Check, KeyRound, Layers, RefreshCw, Save,
  Shield, ShieldCheck, ToggleLeft, ToggleRight, Users, X,
} from 'lucide-react'

type AnyRow = Record<string, any>

const fmtTime = (s?: string | null) => (s ? String(s).replace('T', ' ').slice(0, 16) : '—')

export default function System() {
  const { can, user } = useAuth()
  const [tab, setTab] = useState<'org' | 'template' | 'user' | 'role'>('org')

  const dict = useAsync(() => systemApi.dict(), [])
  const orgs = useAsync(() => systemApi.organizations(), [], { enabled: tab === 'org' })
  const parks = useAsync(() => systemApi.parks(), [], { enabled: tab === 'org' })
  const templates = useAsync(() => systemApi.templates(), [], { enabled: tab === 'template' })
  const users = useAsync(() => systemApi.users({ page: 1, page_size: 20 }), [], { enabled: tab === 'user' })
  const roles = useAsync(() => systemApi.roles(), [], { enabled: tab === 'role' })
  const perms = useAsync(() => systemApi.permissions(), [], { enabled: tab === 'role' })

  // ---------------------------------------------------------- 角色权限矩阵
  const [roleId, setRoleId] = useState<number | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const roleDetail = useAsync(
    () => systemApi.role(roleId as number),
    [roleId],
    { enabled: tab === 'role' && roleId != null },
  )

  useEffect(() => {
    if (roleDetail.data?.permissions) {
      setChecked(new Set<string>(roleDetail.data.permissions))
    }
  }, [roleDetail.data])

  const canConfig = can('system', 'CONFIG')

  const moduleDefs: AnyRow[] = perms.data?.modules ?? []
  const actionsDef: AnyRow[] = dict.data?.action ?? []
  const moduleLabel = (k: string) =>
    (dict.data?.module ?? []).find((m: AnyRow) => m.key === k)?.label ?? k
  const parkTypeLabel = (k?: string) =>
    (dict.data?.park_type ?? []).find((m: AnyRow) => m.key === k)?.label ?? k ?? '—'
  const scopeLabel = (k?: string) =>
    (dict.data?.data_scope ?? []).find((m: AnyRow) => m.key === k)?.label ?? k ?? '—'

  const dirty = useMemo(() => {
    const orig = new Set<string>(roleDetail.data?.permissions ?? [])
    if (orig.size !== checked.size) return true
    for (const c of checked) if (!orig.has(c)) return true
    return false
  }, [checked, roleDetail.data])

  function togglePerm(code: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  function toggleModuleAll(mod: AnyRow, on: boolean) {
    setChecked((prev) => {
      const next = new Set(prev)
      ;(mod.actions ?? []).forEach((a: AnyRow) => {
        if (on) next.add(a.perm_code)
        else next.delete(a.perm_code)
      })
      return next
    })
  }

  async function savePermissions() {
    if (roleId == null) return
    setSaving(true)
    try {
      await systemApi.setRolePermissions(roleId, Array.from(checked))
      pushToast('ok', '角色权限已保存')
      roleDetail.reload()
      roles.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // ---------------------------------------------------------- 模板模块开关
  const [toggling, setToggling] = useState<string | null>(null)

  async function toggleModule(tpl: AnyRow, moduleKey: string, enabled: boolean) {
    setToggling(`${tpl.id}:${moduleKey}`)
    try {
      await systemApi.toggleModule(tpl.id, moduleKey, enabled)
      pushToast('ok', `${moduleLabel(moduleKey)} 已${enabled ? '启用' : '停用'}`)
      templates.reload()
    } catch (e: any) {
      pushToast('err', e?.message ?? '配置失败')
    } finally {
      setToggling(null)
    }
  }

  // ---------------------------------------------------------- 用户操作
  async function resetPassword(u: AnyRow) {
    const pwd = window.prompt(`为 ${u.real_name ?? u.username} 设置新密码`, 'Park@2026')
    if (pwd === null) return
    if (!pwd.trim()) { pushToast('err', '密码不能为空'); return }
    try {
      await systemApi.resetPassword(u.id, pwd.trim())
      pushToast('ok', `已重置 ${u.username} 的密码`)
    } catch (e: any) {
      pushToast('err', e?.message ?? '重置失败')
    }
  }

  const allModulesForTemplate = dict.data?.module ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="系统管理"
        desc="多租户组织架构、园区模板、用户账号与 RBAC 权限矩阵；所有配置变更均写入日志审计。"
        demo
        extra={
          <Btn variant="ghost" onClick={() => { orgs.reload(); templates.reload(); users.reload(); roles.reload() }}>
            <RefreshCw size={13} /> 刷新
          </Btn>
        }
      />

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: 'org', label: '组织与园区' },
          { value: 'template', label: '园区模板' },
          { value: 'user', label: '用户管理' },
          { value: 'role', label: '角色权限' },
        ]}
      />

      {/* ============================================ 组织与园区 */}
      {tab === 'org' && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              label="组织节点" value={orgs.data?.summary?.org_total ?? 0} unit="个"
              hint={`${orgs.data?.summary?.park_total ?? 0} 个园区`}
            />
            <KpiCard label="园区数量" value={parks.data?.total ?? 0} unit="个" tone="brand" />
            <KpiCard
              label="当前数据范围" value={scopeLabel(user?.data_scope)} tone="ai"
              hint={`可见园区 ${user?.visible_park_ids?.length ?? '全部'}`}
            />
            <KpiCard
              label="租户模式" value="多租户" hint="集团 → 区域公司 → 园区 三级隔离" tone="ok"
            />
          </div>

          <Panel title="组织架构" subtitle="集团 → 区域公司 → 园区（多租户根节点）" padded={false}>
            {orgs.loading ? (
              <Loading />
            ) : orgs.error ? (
              <ErrorState error={orgs.error} onRetry={orgs.reload} />
            ) : (
              <DataTable<AnyRow>
                columns={[
                  {
                    key: 'org_name', title: '组织', width: 220,
                    render: (r) => (
                      <div className="flex items-center gap-2">
                        <Building2 size={13} className="text-brand-300" />
                        <div>
                          <div className="text-[13px] text-slate-100">{r.org_name}</div>
                          <div className="font-num text-[10px] text-slate-500">{r.org_code}</div>
                        </div>
                      </div>
                    ),
                  },
                  { key: 'tenant_key', title: '租户标识', width: 110, render: (r) => <span className="font-num">{r.tenant_key ?? '—'}</span> },
                  { key: 'contact_person', title: '联系人', width: 100, render: (r) => r.contact_person ?? '—' },
                  { key: 'contact_phone', title: '联系电话', width: 130, render: (r) => <span className="font-num">{r.contact_phone ?? '—'}</span> },
                  { key: 'park_count', title: '下属园区', width: 90, align: 'right' },
                  { key: 'address', title: '地址', render: (r) => r.address ?? '—' },
                  {
                    key: 'status', title: '状态', width: 80,
                    render: (r) => <Tag tone={r.status === 'ACTIVE' ? 'ok' : 'muted'}>{r.status ?? '—'}</Tag>,
                  },
                ]}
                rows={orgs.data?.items ?? []}
                rowKey={(r) => r.id}
                compact
              />
            )}
          </Panel>

          <Panel title="园区清单" subtitle="每张园区卡片包含面积、楼宇数与启用的业务模块" padded={false}>
            <div className="grid grid-cols-1 gap-4 p-5 lg:grid-cols-2">
              {(parks.data?.items ?? []).map((p: AnyRow) => (
                <div key={p.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[14px] font-medium text-slate-100">{p.park_name}</span>
                        <Tag tone="info">{p.park_type_label ?? parkTypeLabel(p.park_type)}</Tag>
                      </div>
                      <div className="mt-0.5 font-num text-[10px] text-slate-500">
                        {p.park_code} · 模板：{p.template_name ?? '—'}
                      </div>
                    </div>
                    <Tag tone={p.status === 'ACTIVE' ? 'ok' : 'muted'}>{p.status ?? '—'}</Tag>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                    {([
                      ['总占地', `${p.total_area ?? 0} ㎡`],
                      ['可租面积', `${p.rentable_area ?? 0} ㎡`],
                      ['楼宇数', `${p.building_count ?? 0} 栋`],
                      ['负责人', p.manager_name ?? '—'],
                    ] as [string, any][]).map(([k, v]) => (
                      <div key={k} className="rounded border border-white/8 bg-white/[0.02] p-2">
                        <div className="text-[10px] text-slate-500">{k}</div>
                        <div className="mt-0.5 font-num text-slate-200">{v}</div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-3">
                    <div className="mb-1 text-[10px] text-slate-500">
                      启用模块（{(p.enabled_modules ?? []).length}）
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(p.enabled_modules ?? []).slice(0, 12).map((m: string) => (
                        <span
                          key={m}
                          className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400"
                        >
                          {moduleLabel(m)}
                        </span>
                      ))}
                      {(p.enabled_modules ?? []).length > 12 && (
                        <span className="px-1 text-[10px] text-slate-500">
                          +{(p.enabled_modules ?? []).length - 12}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-2 text-[11px] text-slate-500">
                    {p.province}{p.city}{p.district} · {p.address ?? ''}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      {/* ============================================ 园区模板 */}
      {tab === 'template' && (
        <>
          {templates.loading ? (
            <Panel><Loading text="加载园区模板…" /></Panel>
          ) : templates.error ? (
            <Panel><ErrorState error={templates.error} onRetry={templates.reload} /></Panel>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <KpiCard label="模板数量" value={templates.data?.total ?? 0} unit="套" tone="brand" />
                <KpiCard
                  label="可配置模块" value={allModulesForTemplate.length} unit="个"
                  hint="模板可逐一启停"
                />
                <KpiCard
                  label="系统内置"
                  value={(templates.data?.items ?? []).filter((t: AnyRow) => t.is_system).length}
                  unit="套"
                  hint="内置模板不可删除"
                />
                <KpiCard
                  label="已应用园区"
                  value={(templates.data?.items ?? []).reduce(
                    (a: number, t: AnyRow) => a + (Number(t.park_count) || 0), 0,
                  )}
                  unit="个"
                />
              </div>

              <div className="space-y-4">
                {(templates.data?.items ?? []).map((t: AnyRow) => (
                  <Panel
                    key={t.id}
                    title={t.template_name}
                    subtitle={`${t.template_code} · 园区类型：${t.park_type_label ?? parkTypeLabel(t.park_type)} · 已应用 ${t.park_count ?? 0} 个园区`}
                    icon={<Layers size={14} />}
                    extra={
                      <div className="flex items-center gap-2">
                        {t.is_system && <Tag tone="muted">系统内置</Tag>}
                        <Tag tone="info">{t.module_count ?? 0} 个模块</Tag>
                      </div>
                    }
                  >
                    <p className="text-[12px] leading-relaxed text-slate-400">{t.description}</p>

                    {(t.focus_areas ?? []).length > 0 && (
                      <div className="mt-3">
                        <div className="mb-1 text-[11px] text-slate-500">重点关注领域</div>
                        <div className="flex flex-wrap gap-1.5">
                          {(t.focus_areas ?? []).map((f: string) => (
                            <Tag key={f} tone="ai">{f}</Tag>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 模块开关 —— 多租户可配置能力的核心 */}
                    <div className="mt-4">
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-[11px] text-slate-500">
                          业务模块配置（点击切换，立即持久化）
                        </span>
                        {!canConfig && (
                          <Tag tone="warn">缺少 system:CONFIG 权限，只读</Tag>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-4">
                        {allModulesForTemplate.map((m: AnyRow) => {
                          const on = (t.enabled_modules ?? []).includes(m.key)
                          const busy = toggling === `${t.id}:${m.key}`
                          return (
                            <button
                              key={m.key}
                              disabled={!canConfig || busy}
                              onClick={() => void toggleModule(t, m.key, !on)}
                              className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${
                                on
                                  ? 'border-state-ok/35 bg-state-ok/[0.08]'
                                  : 'border-white/8 bg-white/[0.03] hover:border-white/16'
                              }`}
                            >
                              {on ? (
                                <ToggleRight size={15} className="shrink-0 text-state-ok" />
                              ) : (
                                <ToggleLeft size={15} className="shrink-0 text-slate-500" />
                              )}
                              <span className={`truncate text-[12px] ${on ? 'text-slate-200' : 'text-slate-500'}`}>
                                {m.label}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    </div>

                    {(t.default_space_types ?? []).length > 0 && (
                      <div className="mt-3">
                        <div className="mb-1 text-[11px] text-slate-500">默认空间类型</div>
                        <div className="flex flex-wrap gap-1.5">
                          {(t.default_space_types ?? []).map((s: string) => (
                            <span
                              key={s}
                              className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400"
                            >
                              {(dict.data?.space_type ?? []).find((x: AnyRow) => x.key === s)?.label ?? s}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </Panel>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* ============================================ 用户管理 */}
      {tab === 'user' && (
        <>
          {users.data?.stats && (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <KpiCard label="用户总数" value={users.data.stats.total ?? 0} unit="人" tone="brand" />
              <KpiCard label="启用中" value={users.data.stats.active ?? 0} unit="人" tone="ok" />
              <KpiCard
                label="已停用" value={users.data.stats.disabled ?? 0} unit="人"
                tone={Number(users.data.stats.disabled) > 0 ? 'warn' : 'ok'}
              />
              <KpiCard
                label="角色分布" value={Object.keys(users.data.stats.by_role ?? {}).length} unit="种"
                hint={Object.entries(users.data.stats.by_role ?? {})
                  .slice(0, 3).map(([k, v]) => `${k} ${v}`).join(' · ')}
              />
            </div>
          )}

          <Panel title="用户账号" subtitle="账号的数据范围由角色决定，可额外追加可见园区" padded={false}>
            <DataTable<AnyRow>
              columns={[
                {
                  key: 'real_name', title: '用户', width: 190,
                  render: (r) => (
                    <div className="flex items-center gap-2">
                      <Users size={13} className="text-brand-300" />
                      <div>
                        <div className="text-[13px] text-slate-100">{r.real_name}</div>
                        <div className="font-num text-[10px] text-slate-500">{r.username}</div>
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'role_label', title: '角色', width: 150,
                  render: (r) => (
                    <div className="flex flex-wrap gap-1">
                      {(r.roles ?? []).slice(0, 2).map((role: AnyRow) => (
                        <Tag key={role.role_code} tone="info">{role.role_name}</Tag>
                      ))}
                      {(r.roles ?? []).length > 2 && (
                        <Tag tone="muted">+{(r.roles ?? []).length - 2}</Tag>
                      )}
                      {!(r.roles ?? []).length && <span className="text-slate-500">—</span>}
                    </div>
                  ),
                },
                {
                  key: 'data_scope', title: '数据范围', width: 110,
                  render: (r) => <Tag tone="muted">{scopeLabel(r.data_scope)}</Tag>,
                },
                { key: 'park_name', title: '所属园区', width: 130, render: (r) => r.park_name ?? '全部' },
                { key: 'department', title: '部门', width: 130, render: (r) => r.department ?? '—' },
                { key: 'position', title: '岗位', width: 130, render: (r) => r.position ?? '—' },
                {
                  key: 'status', title: '状态', width: 80,
                  render: (r) => <Tag tone={r.status === 'ACTIVE' ? 'ok' : 'muted'}>{r.status ?? '—'}</Tag>,
                },
                {
                  key: 'last_login_at', title: '最近登录', width: 140,
                  render: (r) => fmtTime(r.last_login_at),
                },
                {
                  key: 'act', title: '操作', width: 120, align: 'right',
                  render: (r) => (
                    <Btn
                      size="sm" variant="ghost"
                      disabled={!can('system', 'EDIT')}
                      onClick={() => void resetPassword(r)}
                    >
                      <KeyRound size={11} /> 重置密码
                    </Btn>
                  ),
                },
              ]}
              rows={users.data?.items ?? []}
              loading={users.loading}
              error={users.error}
              onRetry={users.reload}
              empty="暂无用户"
              rowKey={(r) => r.id}
              compact
            />
          </Panel>

          {users.data?.stats?.by_park && Object.keys(users.data.stats.by_park).length > 0 && (
            <Panel title="按园区分布">
              <div className="flex flex-wrap gap-3">
                {Object.entries(users.data.stats.by_park).map(([k, v]) => (
                  <Tag key={k} tone="muted">{k}：{String(v)} 人</Tag>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}

      {/* ============================================ 角色权限 */}
      {tab === 'role' && (
        <>
          {roles.data?.summary && (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <KpiCard label="角色数量" value={roles.data.summary.role_total ?? 0} unit="个" tone="brand" />
              <KpiCard label="权限点总数" value={roles.data.summary.permission_total ?? 0} unit="个" />
              <KpiCard label="角色权限绑定" value={roles.data.summary.binding_total ?? 0} unit="条" tone="ai" />
              <KpiCard
                label="权限模型" value="RBAC + 数据权限" tone="ok"
                hint="角色 × 模块 × 动作，叠加可见范围"
              />
            </div>
          )}

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[300px_1fr]">
            {/* 角色列表 */}
            <Panel title="角色" subtitle="点击选择以配置权限" padded={false}>
              <div className="max-h-[640px] space-y-1 overflow-y-auto p-3">
                {(roles.data?.items ?? []).map((r: AnyRow) => {
                  const on = roleId === r.id
                  return (
                    <button
                      key={r.id}
                      onClick={() => setRoleId(r.id)}
                      className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                        on
                          ? 'border-brand-400/45 bg-brand-500/[0.12]'
                          : 'border-white/8 bg-white/[0.03] hover:border-brand-400/40'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {r.is_system
                          ? <ShieldCheck size={13} className={on ? 'text-brand-300' : 'text-slate-400'} />
                          : <Shield size={13} className={on ? 'text-brand-300' : 'text-slate-400'} />}
                        <span className="truncate text-[13px] font-medium text-slate-100">
                          {r.role_name}
                        </span>
                        <span className="ml-auto font-num text-[10px] text-slate-500">
                          {r.permission_count}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1 pl-5">
                        <Tag tone="muted">{r.role_category}</Tag>
                        <Tag tone="info">{r.data_scope_label ?? scopeLabel(r.data_scope)}</Tag>
                        <span className="font-num text-[10px] text-slate-500">{r.user_count} 人</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </Panel>

            {/* 权限矩阵 */}
            {roleId == null ? (
              <Panel title="权限矩阵">
                <EmptyState
                  text="请从左侧选择一个角色"
                  hint="选中后可查看并调整该角色在 22 个模块 × 9 种动作上的权限点。"
                />
              </Panel>
            ) : roleDetail.loading ? (
              <Panel title="权限矩阵"><Loading /></Panel>
            ) : roleDetail.error ? (
              <Panel title="权限矩阵"><ErrorState error={roleDetail.error} onRetry={roleDetail.reload} /></Panel>
            ) : (
              <Panel
                title={`${roleDetail.data?.role_name} · 权限矩阵`}
                subtitle={`${roleDetail.data?.role_code} · 数据范围 ${roleDetail.data?.data_scope_label ?? ''} · 已选 ${checked.size} / ${roleDetail.data?.permission_total ?? 0} 个权限点`}
                extra={
                  <div className="flex items-center gap-2">
                    {dirty && <Tag tone="warn">有未保存改动</Tag>}
                    <Btn
                      size="sm" variant="primary"
                      disabled={!canConfig || !dirty}
                      loading={saving}
                      onClick={() => void savePermissions()}
                    >
                      <Save size={12} /> 保存
                    </Btn>
                  </div>
                }
              >
                {!canConfig && (
                  <div className="mb-3 rounded-lg border border-state-warn/25 bg-state-warn/[0.07] p-3 text-xs text-slate-300">
                    当前账号缺少 <b className="font-num">system:CONFIG</b> 权限，权限矩阵为只读。
                  </div>
                )}

                <div className="max-h-[620px] space-y-3 overflow-y-auto pr-1">
                  {moduleDefs.map((mod: AnyRow) => {
                    const codes: string[] = (mod.actions ?? []).map((a: AnyRow) => a.perm_code)
                    const allOn = codes.length > 0 && codes.every((c) => checked.has(c))
                    const someOn = codes.some((c) => checked.has(c))
                    return (
                      <div key={mod.module} className="rounded-lg border border-white/8 bg-white/[0.02] p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-[13px] font-medium text-slate-100">{mod.label}</span>
                            <span className="font-num text-[10px] text-slate-500">{mod.module}</span>
                            <Tag tone={allOn ? 'ok' : someOn ? 'warn' : 'muted'}>
                              {codes.filter((c) => checked.has(c)).length}/{codes.length}
                            </Tag>
                          </div>
                          <button
                            disabled={!canConfig}
                            onClick={() => toggleModuleAll(mod, !allOn)}
                            className="text-[11px] text-brand-300 transition hover:text-brand-200 disabled:opacity-40"
                          >
                            {allOn ? '全不选' : '全选'}
                          </button>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {(mod.actions ?? []).map((a: AnyRow) => {
                            const on = checked.has(a.perm_code)
                            return (
                              <button
                                key={a.perm_code}
                                disabled={!canConfig}
                                title={a.perm_code}
                                onClick={() => togglePerm(a.perm_code)}
                                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition disabled:cursor-not-allowed ${
                                  on
                                    ? 'border-state-ok/40 bg-state-ok/[0.12] text-state-ok'
                                    : 'border-white/10 bg-white/[0.03] text-slate-500 hover:border-white/20'
                                }`}
                              >
                                {on ? <Check size={10} /> : <X size={10} />}
                                {a.label}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>

                <div className="mt-4 border-t border-white/8 pt-3">
                  <div className="mb-2 text-[11px] text-slate-500">
                    持有该角色的用户（{roleDetail.data?.user_count ?? 0}）
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {(roleDetail.data?.users ?? []).slice(0, 24).map((u: AnyRow) => (
                      <Tag key={u.id ?? u.username} tone="muted">
                        {u.real_name ?? u.username}
                      </Tag>
                    ))}
                    {(roleDetail.data?.users ?? []).length === 0 && (
                      <span className="text-[11px] text-slate-500">暂无用户持有该角色</span>
                    )}
                  </div>
                </div>
              </Panel>
            )}
          </div>

          {/* 权限点总览 */}
          {perms.data?.summary && (
            <Panel
              title="权限点总览"
              subtitle={`${perms.data.summary.module_total ?? 0} 个模块 × 9 种动作 = ${perms.data.summary.total ?? 0} 个权限点`}
            >
              <div className="flex flex-wrap gap-3">
                {actionsDef.map((a: AnyRow) => (
                  <Tag key={a.key} tone="muted">{a.label}</Tag>
                ))}
              </div>
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                权限点编码形如 <span className="font-num">模块:动作</span>（如{' '}
                <span className="font-num text-brand-300">finance:APPROVE</span>），
                前端按钮门禁与后端 auth.require(module, action) 使用同一套编码，避免「前端能点、后端拒绝」。
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

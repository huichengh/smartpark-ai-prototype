/**
 * 路由定义
 *
 * 所有页面均为真实页面（非占位），数据来自后端 API。
 * 未登录访问任意受保护路由 -> 跳登录；无权限访问 -> 显示明确的权限提示页。
 */
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { AppLayout } from '@/layout/AppLayout'
import { Loading, ErrorState, Panel } from '@/components/ui'
import { ApiException } from '@/api/client'
import type { ReactNode } from 'react'

import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Twin from '@/pages/Twin'
import Space from '@/pages/Space'
import Leasing from '@/pages/Leasing'
import Enterprise from '@/pages/Enterprise'
import Contracts from '@/pages/Contracts'
import Finance from '@/pages/Finance'
import Projects from '@/pages/Projects'
import ProjectDetail from '@/pages/ProjectDetail'
import Operations from '@/pages/Operations'
import Energy from '@/pages/Energy'
import Safety from '@/pages/Safety'
import Parking from '@/pages/Parking'
import Meeting from '@/pages/Meeting'
import Approval from '@/pages/Approval'
import AiAgent from '@/pages/AiAgent'
import DataCenter from '@/pages/DataCenter'
import Report from '@/pages/Report'
import Notification from '@/pages/Notification'
import Audit from '@/pages/Audit'
import System from '@/pages/System'

/** 登录守卫 */
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-nav-deep">
        <Loading text="正在校验登录状态…" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  return <>{children}</>
}

/** 页面级权限守卫：无权限时给出可读的提示而非白屏 */
function RequirePerm({
  module,
  action = 'VIEW',
  children,
}: {
  module: string
  action?: string
  children: ReactNode
}) {
  const { can, user, loading } = useAuth()
  if (loading) return <Loading />
  if (!can(module, action)) {
    return (
      <Panel title="权限不足">
        <ErrorState
          error={
            new ApiException({
              code: 403,
              type: 'FORBIDDEN',
              message: `当前账号（${user?.role_label ?? '未知角色'}）没有「${module}:${action}」权限，请联系管理员分配。`,
            })
          }
        />
      </Panel>
    )
  }
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/twin" element={<Twin />} />

          <Route
            path="/space"
            element={
              <RequirePerm module="space">
                <Space />
              </RequirePerm>
            }
          />
          <Route
            path="/leasing"
            element={
              <RequirePerm module="leasing">
                <Leasing />
              </RequirePerm>
            }
          />
          <Route
            path="/enterprise"
            element={
              <RequirePerm module="enterprise">
                <Enterprise />
              </RequirePerm>
            }
          />
          <Route
            path="/contracts"
            element={
              <RequirePerm module="contract">
                <Contracts />
              </RequirePerm>
            }
          />
          <Route
            path="/finance"
            element={
              <RequirePerm module="finance">
                <Finance />
              </RequirePerm>
            }
          />
          <Route
            path="/projects"
            element={
              <RequirePerm module="project">
                <Projects />
              </RequirePerm>
            }
          />
          <Route
            path="/projects/:id"
            element={
              <RequirePerm module="project">
                <ProjectDetail />
              </RequirePerm>
            }
          />

          <Route
            path="/operations"
            element={
              // 守卫模块必须与后端接口的 auth.require 一致（工单走 property）。
              // 用 service 会把「物业人员 / 安全人员」挡在门外——他们有 property 却没有 service。
              <RequirePerm module="property">
                <Operations />
              </RequirePerm>
            }
          />
          <Route
            path="/energy"
            element={
              <RequirePerm module="energy">
                <Energy />
              </RequirePerm>
            }
          />
          <Route
            path="/safety"
            element={
              <RequirePerm module="safety">
                <Safety />
              </RequirePerm>
            }
          />
          <Route
            path="/parking"
            element={
              // 后端停车接口要求 parking:VIEW；沿用 service 会让仅有 service 的
              // 角色（如企业员工）进得了页面、却在所有接口上 403。
              <RequirePerm module="parking">
                <Parking />
              </RequirePerm>
            }
          />
          <Route
            path="/meeting"
            element={
              <RequirePerm module="service">
                <Meeting />
              </RequirePerm>
            }
          />

          <Route
            path="/approval"
            element={
              <RequirePerm module="approval">
                <Approval />
              </RequirePerm>
            }
          />
          <Route
            path="/ai"
            element={
              // 权限模块键是 ai，不是 agent（agent 只是审计日志的 module 名）。
              // 写错会让所有角色都看到「权限不足」，AI 中心整体不可用。
              <RequirePerm module="ai">
                <AiAgent />
              </RequirePerm>
            }
          />
          <Route
            path="/data"
            element={
              <RequirePerm module="data">
                <DataCenter />
              </RequirePerm>
            }
          />
          <Route
            path="/report"
            element={
              <RequirePerm module="report">
                <Report />
              </RequirePerm>
            }
          />
          <Route path="/notification" element={<Notification />} />
          <Route
            path="/audit"
            element={
              // 审计有独立模块 audit；用 system 会把只授了 audit 的角色挡在外面。
              <RequirePerm module="audit">
                <Audit />
              </RequirePerm>
            }
          />
          <Route
            path="/system"
            element={
              <RequirePerm module="system">
                <System />
              </RequirePerm>
            }
          />

          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}

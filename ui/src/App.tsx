import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
} from 'react-router-dom'

import { useLogout, useMe } from './api/queries'
import { Spinner } from './components/ui'
import Dashboard from './pages/Dashboard'
import Devices from './pages/Devices'
import Login from './pages/Login'
import { startEventBridge } from './ws'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AuthenticatedLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/devices" element={<Devices />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

function AuthenticatedLayout() {
  const me = useMe()
  const queryClient = useQueryClient()
  const logout = useLogout()

  // WS-мост живёт, пока пользователь авторизован
  useEffect(() => {
    if (me.data === undefined) return
    return startEventBridge(queryClient)
  }, [me.data, queryClient])

  if (me.isPending) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-slate-950">
        <Spinner label="Загрузка…" />
      </div>
    )
  }
  if (me.isError) {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="flex min-h-dvh flex-col bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="size-6" />
            <span className="font-semibold tracking-tight">Easy Breezy</span>
          </div>
          <button
            type="button"
            onClick={() => logout.mutate()}
            className="text-sm text-slate-400 hover:text-slate-200"
          >
            {me.data.username} · выйти
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-4 pb-24">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 border-t border-slate-800 bg-slate-950/95 backdrop-blur">
        <div className="mx-auto flex max-w-3xl">
          <TabLink to="/" label="Дашборд" />
          <TabLink to="/devices" label="Устройства" />
        </div>
      </nav>
    </div>
  )
}

function TabLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex-1 py-3 text-center text-sm font-medium transition-colors ${
          isActive ? 'text-sky-400' : 'text-slate-400 hover:text-slate-200'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

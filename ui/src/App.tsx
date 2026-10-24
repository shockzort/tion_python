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
import Automation from './pages/Automation'
import Charts from './pages/Charts'
import Dashboard from './pages/Dashboard'
import Devices from './pages/Devices'
import Login from './pages/Login'
import Settings from './pages/Settings'
import { startEventBridge } from './ws'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AuthenticatedLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/automation" element={<Automation />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/devices" element={<Devices />} />
          <Route path="/settings" element={<Settings />} />
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
      <header className="sticky top-0 z-10 border-b border-slate-800/70 bg-slate-950/85 pt-[env(safe-area-inset-top)] backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="size-7" />
            <span className="text-lg font-extrabold tracking-tight">Easy Breezy</span>
          </NavLink>
          <div className="flex items-center gap-1 text-sm text-slate-400">
            <span className="hidden sm:inline">{me.data.username}</span>
            <button
              type="button"
              onClick={() => logout.mutate()}
              className="min-h-11 rounded-xl px-3 hover:bg-slate-900 hover:text-slate-200"
            >
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-4 pb-28">
        <Outlet />
      </main>

      <nav
        aria-label="Разделы"
        className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-800/70 bg-slate-950/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md"
      >
        <div className="mx-auto grid max-w-3xl grid-cols-5 px-1">
          <TabLink to="/" label="Дом" icon="home" />
          <TabLink to="/devices" label="Устройства" icon="devices" />
          <TabLink to="/automation" label="Автоматика" icon="automation" />
          <TabLink to="/charts" label="Графики" icon="charts" />
          <TabLink to="/settings" label="Настройки" icon="settings" />
        </div>
      </nav>
    </div>
  )
}

const ICONS: Record<string, string> = {
  home: 'M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
  devices: 'M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5zM8 10h8M8 14h5',
  automation: 'M12 3v3M12 18v3M3 12h3M18 12h3M6.3 6.3l2.1 2.1M15.6 15.6l2.1 2.1M6.3 17.7l2.1-2.1M15.6 8.4l2.1-2.1M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  charts: 'M4 19h16M5 15l4-5 4 3 6-7',
  settings: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 4v6M8 14v6',
}

function TabLink({ to, label, icon }: { to: string; label: string; icon: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex min-h-14 flex-col items-center justify-center gap-1 text-[11px] font-semibold transition-colors ${
          isActive ? 'text-sky-400' : 'text-slate-400 hover:text-slate-200'
        }`
      }
    >
      <svg
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d={ICONS[icon]} />
      </svg>
      {label}
    </NavLink>
  )
}

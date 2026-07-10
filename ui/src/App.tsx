import { useEffect, useState } from 'react'

type Health = {
  status: string
  version: string
  uptime_seconds: number
}

type ServerState =
  | { kind: 'loading' }
  | { kind: 'online'; health: Health }
  | { kind: 'offline' }

function useServerHealth(): ServerState {
  const [state, setState] = useState<ServerState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const probe = async () => {
      try {
        const response = await fetch('/api/system/health')
        if (!response.ok) throw new Error(String(response.status))
        const health = (await response.json()) as Health
        if (!cancelled) setState({ kind: 'online', health })
      } catch {
        if (!cancelled) setState({ kind: 'offline' })
      }
    }
    void probe()
    const timer = setInterval(probe, 10_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return state
}

function StatusBadge({ state }: { state: ServerState }) {
  if (state.kind === 'loading') {
    return <span className="text-slate-400">Проверяем сервер…</span>
  }
  if (state.kind === 'offline') {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-rose-500/10 px-3 py-1 text-sm text-rose-400">
        <span className="size-2 rounded-full bg-rose-400" />
        Сервер недоступен
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1 text-sm text-emerald-400">
      <span className="size-2 rounded-full bg-emerald-400" />
      Сервер онлайн · v{state.health.version}
    </span>
  )
}

export default function App() {
  const server = useServerHealth()

  return (
    <main className="flex min-h-dvh items-center justify-center bg-slate-950 p-6 text-slate-100">
      <div className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/60 p-8 text-center shadow-2xl backdrop-blur">
        <img src="/favicon.svg" alt="" className="mx-auto mb-6 size-16" />
        <h1 className="text-3xl font-semibold tracking-tight">Easy Breezy</h1>
        <p className="mt-2 text-slate-400">
          Локальное управление бризерами Tion — дашборд появится в Фазе 3
        </p>
        <div className="mt-6">
          <StatusBadge state={server} />
        </div>
      </div>
    </main>
  )
}

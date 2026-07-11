import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useAuthStatus, useLogin, useSetup } from '../api/queries'
import { Button, Card, Spinner } from '../components/ui'

export default function Login() {
  const status = useAuthStatus()

  return (
    <div className="flex min-h-dvh items-center justify-center bg-slate-950 p-6 text-slate-100">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <img src="/favicon.svg" alt="" className="mx-auto mb-3 size-14" />
          <h1 className="text-2xl font-semibold tracking-tight">Easy Breezy</h1>
        </div>
        {status.isPending ? (
          <div className="text-center">
            <Spinner label="Проверяем сервер…" />
          </div>
        ) : status.data?.setup_required ? (
          <SetupForm />
        ) : (
          <LoginForm />
        )}
      </div>
    </div>
  )
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'сервер недоступен'
}

function LoginForm() {
  const login = useLogin()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate(
      { username, password },
      { onSuccess: () => navigate('/', { replace: true }) },
    )
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <h2 className="text-lg font-medium">Вход</h2>
        <Field
          label="Логин"
          value={username}
          onChange={setUsername}
          autoComplete="username"
        />
        <Field
          label="Пароль"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        {login.isError && (
          <p className="text-sm text-rose-400">{errorText(login.error)}</p>
        )}
        <Button type="submit" disabled={login.isPending}>
          {login.isPending ? 'Входим…' : 'Войти'}
        </Button>
      </form>
    </Card>
  )
}

function SetupForm() {
  const setup = useSetup()
  const navigate = useNavigate()
  const [token, setToken] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setup.mutate(
      { setup_token: token, username, password },
      { onSuccess: () => navigate('/', { replace: true }) },
    )
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <h2 className="text-lg font-medium">Первичная настройка</h2>
        <p className="text-sm text-slate-400">
          Setup-токен напечатан в логе сервера при старте
          (журнал systemd или консоль <code>make dev</code>).
        </p>
        <Field label="Setup-токен" value={token} onChange={setToken} />
        <Field
          label="Логин администратора"
          value={username}
          onChange={setUsername}
          autoComplete="username"
        />
        <Field
          label="Пароль (не короче 8 символов)"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
        />
        {setup.isError && (
          <p className="text-sm text-rose-400">{errorText(setup.error)}</p>
        )}
        <Button type="submit" disabled={setup.isPending}>
          {setup.isPending ? 'Создаём…' : 'Создать администратора'}
        </Button>
      </form>
    </Card>
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  autoComplete,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  autoComplete?: string
}) {
  return (
    <label className="flex flex-col gap-1 text-sm text-slate-300">
      {label}
      <input
        type={type}
        value={value}
        required
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
      />
    </label>
  )
}

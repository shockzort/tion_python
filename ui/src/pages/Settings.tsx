import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { useChangePassword, useMe } from '../api/queries'
import { Button, Card, Toggle } from '../components/ui'
import {
  currentSubscription,
  disablePush,
  enablePush,
  pushSupported,
} from '../lib/push'

export default function Settings() {
  const me = useMe()
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <p className="text-sm text-slate-400">Пользователь</p>
        <p className="font-medium">{me.data?.username}</p>
      </Card>
      <PushSection />
      <PasswordForm />
    </div>
  )
}

function PushSection() {
  const [enabled, setEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void currentSubscription().then((subscription) =>
      setEnabled(subscription !== null),
    )
  }, [])

  const toggle = async (next: boolean) => {
    setBusy(true)
    setError(null)
    try {
      if (next) {
        await enablePush()
      } else {
        await disablePush()
      }
      setEnabled(next)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'не получилось')
    } finally {
      setBusy(false)
    }
  }

  if (!pushSupported()) {
    return (
      <Card>
        <p className="font-medium">Уведомления</p>
        <p className="mt-1 text-sm text-slate-500">
          Браузер не поддерживает web push (нужен установленный PWA/Chrome).
        </p>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col gap-2">
      <p className="font-medium">Уведомления</p>
      <p className="text-sm text-slate-500">
        Пуш о сбоях: бризер офлайн дольше 10 минут, провал ночного бэкапа.
      </p>
      <Toggle
        label="Присылать на это устройство"
        checked={enabled}
        disabled={busy}
        onChange={(next) => void toggle(next)}
      />
      {error !== null && <p className="text-sm text-rose-400">{error}</p>}
    </Card>
  )
}

function PasswordForm() {
  const changePassword = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [message, setMessage] = useState<
    { tone: 'ok' | 'error'; text: string } | null
  >(null)

  const submit = async () => {
    setMessage(null)
    if (next.length < 8) {
      setMessage({ tone: 'error', text: 'Новый пароль — минимум 8 символов.' })
      return
    }
    if (next !== repeat) {
      setMessage({ tone: 'error', text: 'Пароли не совпадают.' })
      return
    }
    try {
      await changePassword.mutateAsync({
        current_password: current,
        new_password: next,
      })
      setCurrent('')
      setNext('')
      setRepeat('')
      setMessage({
        tone: 'ok',
        text: 'Пароль изменён. Остальные устройства разлогинены.',
      })
    } catch (exc) {
      setMessage({
        tone: 'error',
        text: exc instanceof ApiError ? exc.message : 'Не удалось сменить пароль.',
      })
    }
  }

  const inputClass =
    'rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-sky-500'

  return (
    <Card className="flex flex-col gap-3">
      <p className="font-medium">Смена пароля</p>
      <input
        type="password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        placeholder="Текущий пароль"
        autoComplete="current-password"
        className={inputClass}
      />
      <input
        type="password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        placeholder="Новый пароль (не короче 8 символов)"
        autoComplete="new-password"
        className={inputClass}
      />
      <input
        type="password"
        value={repeat}
        onChange={(event) => setRepeat(event.target.value)}
        placeholder="Новый пароль ещё раз"
        autoComplete="new-password"
        className={inputClass}
      />
      {message !== null && (
        <p
          className={`text-sm ${
            message.tone === 'ok' ? 'text-emerald-400' : 'text-rose-400'
          }`}
        >
          {message.text}
        </p>
      )}
      <Button
        onClick={submit}
        disabled={changePassword.isPending || current === '' || next === ''}
      >
        {changePassword.isPending ? 'Меняем…' : 'Сменить пароль'}
      </Button>
    </Card>
  )
}

// Мастер сопряжения (план §7): инструкция → скан → выбор → имя → пейринг

import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { usePairDevice, useScanAir } from '../api/queries'
import type { FoundBreezer } from '../api/types'
import { pairingProgress } from '../ws'
import { Badge, Button, Card, Spinner } from './ui'

const SCAN_DURATION_S = 15

type Step =
  | { kind: 'intro' }
  | { kind: 'scanning' }
  | { kind: 'found'; items: FoundBreezer[] }
  | { kind: 'name'; candidate: FoundBreezer }
  | { kind: 'pairing'; stage: string }
  | { kind: 'done'; name: string }
  | { kind: 'error'; message: string }

const stageLabels: Record<string, string> = {
  pairing: 'Создаём бонд…',
  registering: 'Регистрируем устройство…',
  done: 'Готово',
}

export default function PairWizard({ onClose }: { onClose: () => void }) {
  const scan = useScanAir()
  const pair = usePairDevice()
  const [step, setStep] = useState<Step>({ kind: 'intro' })
  const [name, setName] = useState('')

  // стадии пейринга приходят по WS (pairing.progress)
  useEffect(() => {
    const listener = (event: Event) => {
      const data = (event as CustomEvent<{ stage: string }>).detail
      setStep((current) =>
        current.kind === 'pairing' ? { ...current, stage: data.stage } : current,
      )
    }
    pairingProgress.addEventListener('progress', listener)
    return () => pairingProgress.removeEventListener('progress', listener)
  }, [])

  const startScan = () => {
    setStep({ kind: 'scanning' })
    scan.mutate(SCAN_DURATION_S, {
      onSuccess: (items) => setStep({ kind: 'found', items }),
      onError: (error) => setStep({ kind: 'error', message: errorText(error) }),
    })
  }

  const startPair = (candidate: FoundBreezer, deviceName: string) => {
    setStep({ kind: 'pairing', stage: 'pairing' })
    pair.mutate(
      { mac: candidate.mac, name: deviceName },
      {
        onSuccess: () => setStep({ kind: 'done', name: deviceName }),
        onError: (error) =>
          setStep({ kind: 'error', message: errorText(error) }),
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-end justify-center bg-black/60 p-4 sm:items-center"
      role="dialog"
      aria-label="Мастер сопряжения"
    >
      <Card className="max-h-[85dvh] w-full max-w-md overflow-y-auto bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Новый бризер</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="закрыть"
            className="text-slate-400 hover:text-slate-200"
          >
            ✕
          </button>
        </div>

        {step.kind === 'intro' && (
          <div className="flex flex-col gap-3 text-sm text-slate-300">
            <p>Переведите бризер в режим сопряжения:</p>
            <ol className="list-decimal space-y-1 pl-5">
              <li>
                зажмите кнопку на корпусе примерно на 5 секунд — до синего
                мигания;
              </li>
              <li>
                надёжнее всего: выключите бризер, затем включите удержанием
                кнопки (если индикация отключена — просто подержите и
                отпустите).
              </li>
            </ol>
            <p className="text-slate-500">
              Бризер, занятый другим приложением, в эфире не виден — закройте
              Tion Remote.
            </p>
            <Button onClick={startScan}>Начать поиск</Button>
          </div>
        )}

        {step.kind === 'scanning' && (
          <div className="py-6 text-center">
            <Spinner label={`Сканируем эфир (~${SCAN_DURATION_S} с)…`} />
          </div>
        )}

        {step.kind === 'found' && (
          <div className="flex flex-col gap-2">
            {step.items.length === 0 ? (
              <>
                <p className="text-sm text-slate-400">
                  Бризеры не найдены. Проверьте режим сопряжения и повторите.
                </p>
                <Button onClick={startScan}>Искать снова</Button>
              </>
            ) : (
              step.items.map((item) => (
                <button
                  key={item.mac}
                  type="button"
                  disabled={item.registered}
                  onClick={() => {
                    setName(item.name)
                    setStep({ kind: 'name', candidate: item })
                  }}
                  className="flex items-center justify-between rounded-xl border border-slate-700 bg-slate-800/60 px-3 py-2 text-left hover:border-sky-600 disabled:opacity-50"
                >
                  <span>
                    <span className="block text-sm">{item.name}</span>
                    <span className="block text-xs text-slate-500">
                      {item.mac}
                      {item.rssi !== null && ` · ${item.rssi} дБм`}
                    </span>
                  </span>
                  {item.registered ? (
                    <Badge tone="muted">уже добавлен</Badge>
                  ) : item.pairing_mode ? (
                    <Badge tone="ok">режим сопряжения</Badge>
                  ) : null}
                </button>
              ))
            )}
          </div>
        )}

        {step.kind === 'name' && (
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              startPair(step.candidate, name)
            }}
          >
            <p className="text-sm text-slate-400">{step.candidate.mac}</p>
            <label className="flex flex-col gap-1 text-sm text-slate-300">
              Название
              <input
                value={name}
                required
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
              />
            </label>
            <Button type="submit">Сопрячь</Button>
          </form>
        )}

        {step.kind === 'pairing' && (
          <div className="py-6 text-center">
            <Spinner label={stageLabels[step.stage] ?? 'Сопрягаем…'} />
          </div>
        )}

        {step.kind === 'done' && (
          <div className="flex flex-col gap-3 py-2 text-center">
            <p className="text-emerald-400">
              «{step.name}» добавлен и подключается.
            </p>
            <Button onClick={onClose}>Готово</Button>
          </div>
        )}

        {step.kind === 'error' && (
          <div className="flex flex-col gap-3 py-2">
            <p className="text-sm text-rose-400">{step.message}</p>
            <Button onClick={startScan}>Повторить поиск</Button>
          </div>
        )}
      </Card>
    </div>
  )
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'сервер недоступен'
}

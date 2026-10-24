// Мастер добавления датчика: тип → поиск или адрес → имя и комната.
// Ничего не знает о конкретных моделях — всё берёт из /api/sensors/providers.

import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import { useAddSensor, useDiscoverSensors, useRooms, useSensorProviders } from '../api/queries'
import type { DiscoveredSensor, SensorProvider } from '../api/types'
import { formatValue, METRIC_INFO, METRIC_ORDER } from '../lib/metrics'
import { Badge, Button, Card, Spinner } from './ui'

type Step =
  | { kind: 'provider' }
  | { kind: 'source'; provider: SensorProvider }
  | { kind: 'details'; provider: SensorProvider; address: string; found: DiscoveredSensor | null }

const TRANSPORT_LABEL: Record<SensorProvider['transport'], string> = {
  mqtt: 'Wi-Fi · MQTT',
  ble: 'Bluetooth',
  cloud: 'Облако',
}

export default function AddSensorWizard({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<Step>({ kind: 'provider' })
  return (
    <div
      className="fixed inset-0 z-20 flex items-end justify-center bg-black/85 p-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-label="Новый датчик"
    >
      <Card className="max-h-[85dvh] w-full max-w-md overflow-y-auto bg-slate-900">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            {step.kind !== 'provider' && (
              <button
                type="button"
                aria-label="назад"
                onClick={() =>
                  setStep(
                    step.kind === 'details' && step.provider.discoverable
                      ? { kind: 'source', provider: step.provider }
                      : { kind: 'provider' },
                  )
                }
                className="text-slate-400 hover:text-slate-200"
              >
                ←
              </button>
            )}
            <h2 className="truncate text-lg font-medium">
              {step.kind === 'provider' ? 'Новый датчик' : step.provider.title}
            </h2>
          </div>
          <button type="button" onClick={onClose} aria-label="закрыть" className="text-slate-400 hover:text-slate-200">
            ✕
          </button>
        </div>
        {step.kind === 'provider' && (
          <ProviderStep
            onPick={(provider) =>
              setStep(
                provider.discoverable
                  ? { kind: 'source', provider }
                  : { kind: 'details', provider, address: '', found: null },
              )
            }
          />
        )}
        {step.kind === 'source' && (
          <DiscoverStep
            provider={step.provider}
            onPick={(found) => setStep({ kind: 'details', provider: step.provider, address: found.address, found })}
            onManual={() => setStep({ kind: 'details', provider: step.provider, address: '', found: null })}
          />
        )}
        {step.kind === 'details' && (
          <DetailsStep provider={step.provider} address={step.address} found={step.found} onDone={onClose} />
        )}
      </Card>
    </div>
  )
}

function ProviderStep({ onPick }: { onPick: (provider: SensorProvider) => void }) {
  const providers = useSensorProviders()
  if (providers.isPending) return <Spinner label="Загружаем типы…" />
  if (providers.isError) return <p className="text-sm text-rose-400">Не удалось загрузить типы датчиков.</p>
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-slate-400">Выберите, как датчик передаёт данные.</p>
      {providers.data.map((provider) => {
        const disabled = !provider.manual || !provider.available
        return (
          <button
            key={provider.kind}
            type="button"
            disabled={disabled}
            onClick={() => onPick(provider)}
            className="flex flex-col gap-1.5 rounded-xl border border-slate-800 p-3 text-left transition-colors enabled:hover:border-sky-500/60 enabled:hover:bg-slate-800/40 disabled:opacity-60"
          >
            <span className="flex items-center justify-between gap-2">
              <span className="font-medium">{provider.title}</span>
              <Badge tone="muted">{TRANSPORT_LABEL[provider.transport]}</Badge>
            </span>
            <span className="text-xs text-slate-400">{provider.description}</span>
            <MetricChips metrics={provider.metrics} />
            {!provider.available && provider.unavailable_reason && (
              <span className="text-xs text-amber-400">{provider.unavailable_reason}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

function DiscoverStep({
  provider,
  onPick,
  onManual,
}: {
  provider: SensorProvider
  onPick: (found: DiscoveredSensor) => void
  onManual: () => void
}) {
  const discover = useDiscoverSensors()
  const { mutate } = discover
  useEffect(() => mutate(provider.kind), [mutate, provider.kind])

  return (
    <div className="flex flex-col gap-3">
      {discover.isPending && (
        <Spinner label={provider.transport === 'ble' ? 'Слушаем эфир ~15 с…' : 'Ищем датчики…'} />
      )}
      {discover.isError && <p role="alert" className="text-sm text-rose-400">{discover.error.message}</p>}
      {discover.isSuccess && discover.data.length === 0 && (
        <p className="text-sm text-slate-400">
          Ничего не найдено. Проверьте питание и настройку датчика, повторите поиск или введите адрес вручную.
        </p>
      )}
      {discover.data?.map((item) => (
        <button
          key={item.source_key}
          type="button"
          disabled={item.registered}
          onClick={() => onPick(item)}
          className="flex flex-col gap-1.5 rounded-xl border border-slate-800 p-3 text-left transition-colors enabled:hover:border-sky-500/60 enabled:hover:bg-slate-800/40 disabled:opacity-60"
        >
          <span className="flex items-center justify-between gap-2">
            <span className="font-mono text-sm">{item.address}</span>
            {item.registered ? (
              <Badge tone="muted">уже добавлен</Badge>
            ) : (
              item.signal_dbm !== null && <Badge tone="ok">{item.signal_dbm} dBm</Badge>
            )}
          </span>
          {item.model && <span className="text-xs text-slate-400">{item.model}</span>}
          <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-300">
            {METRIC_ORDER.filter((metric) => item.metrics[metric] !== undefined).map((metric) => (
              <span key={metric}>
                {METRIC_INFO[metric].short} {formatValue(metric, item.metrics[metric] as number)} {METRIC_INFO[metric].unit}
              </span>
            ))}
          </span>
        </button>
      ))}
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button variant="ghost" disabled={discover.isPending} onClick={() => mutate(provider.kind)} className="flex-1">
          Искать ещё раз
        </Button>
        <Button variant="ghost" onClick={onManual} className="flex-1">
          Ввести вручную
        </Button>
      </div>
    </div>
  )
}

function DetailsStep({
  provider,
  address: initialAddress,
  found,
  onDone,
}: {
  provider: SensorProvider
  address: string
  found: DiscoveredSensor | null
  onDone: () => void
}) {
  const rooms = useRooms()
  const add = useAddSensor()
  const [address, setAddress] = useState(initialAddress)
  const [name, setName] = useState('')
  const [roomId, setRoomId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const roomName = rooms.data?.find((room) => String(room.id) === roomId)?.name
  const submit = async () => {
    setError(null)
    const finalName = name.trim() || (roomName ? `Воздух · ${roomName}` : '')
    if (!finalName || !address.trim()) {
      setError(found ? 'укажите имя датчика' : `укажите имя и ${provider.address_label ?? 'адрес'}`)
      return
    }
    try {
      await add.mutateAsync({
        name: finalName,
        kind: provider.kind,
        address: address.trim(),
        ...(roomId ? { room_id: Number(roomId) } : {}),
      })
      onDone()
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : 'не удалось добавить')
    }
  }

  const field =
    'w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-sky-500'
  return (
    <div className="flex flex-col gap-3">
      {found ? (
        <p className="text-sm text-slate-400">
          Датчик <span className="font-mono text-slate-200">{found.address}</span>
        </p>
      ) : (
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          {provider.address_label ?? 'Адрес'}
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder={provider.address_placeholder ?? ''}
            className={`${field} font-mono`}
          />
        </label>
      )}
      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Комната
        <select value={roomId} onChange={(event) => setRoomId(event.target.value)} className={field}>
          <option value="">Без комнаты</option>
          {rooms.data?.map((room) => (
            <option key={room.id} value={room.id}>
              {room.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Имя
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={roomName ? `Воздух · ${roomName}` : 'Например, Воздух · Спальня'}
          className={field}
        />
      </label>
      <div className="flex flex-col gap-1.5">
        <span className="text-sm text-slate-400">Будет измерять</span>
        <MetricChips metrics={provider.metrics} />
      </div>
      {error !== null && <p role="alert" className="text-sm text-rose-400">{error}</p>}
      <Button onClick={submit} disabled={add.isPending}>
        {add.isPending ? 'Добавляем…' : 'Добавить датчик'}
      </Button>
    </div>
  )
}

export function MetricChips({ metrics }: { metrics: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {METRIC_ORDER.filter((metric) => metrics.includes(metric)).map((metric) => (
        <Badge key={metric} tone="muted">
          {METRIC_INFO[metric].label}
        </Badge>
      ))}
    </span>
  )
}

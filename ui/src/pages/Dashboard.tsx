import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  powerOffAll,
  useDevices,
  useReleaseHold,
  useRooms,
  useRunScenario,
  useScenarios,
  useSendCommand,
  useSensors,
} from '../api/queries'
import DeviceCard from '../components/DeviceCard'
import IntentBar from '../components/IntentBar'
import SensorCard from '../components/SensorCard'
import { Button, Spinner } from '../components/ui'

export default function Dashboard() {
  const devices = useDevices()
  const rooms = useRooms()
  const sensors = useSensors()
  const scenarios = useScenarios()
  const runScenario = useRunScenario()
  const sendCommand = useSendCommand()
  const releaseHold = useReleaseHold()
  const queryClient = useQueryClient()
  const [poweringOff, setPoweringOff] = useState(false)

  if (devices.isPending) {
    return <Spinner label="Загружаем устройства…" />
  }
  if (devices.isError) {
    return <p className="text-rose-400">Не удалось загрузить устройства.</p>
  }
  if (devices.data.length === 0) {
    return (
      <div className="mt-16 text-center text-slate-400">
        <p>Пока нет ни одного бризера.</p>
        <p className="mt-2">
          Добавьте его на вкладке{' '}
          <Link to="/devices" className="text-sky-400 underline">
            Устройства
          </Link>
          .
        </p>
      </div>
    )
  }

  const online = devices.data.filter((d) => d.connection === 'online').length

  const allOff = async () => {
    setPoweringOff(true)
    try {
      await powerOffAll(queryClient, devices.data)
    } finally {
      setPoweringOff(false)
    }
  }

  // комнаты — главный разрез: датчик воздуха и бризеры одной комнаты рядом
  const groups = [
    ...(rooms.data ?? []).map((room) => ({ key: String(room.id), title: room.name, roomId: room.id as number | null })),
    { key: 'none', title: 'Без комнаты', roomId: null },
  ]
    .map((group) => ({
      ...group,
      sensors: (sensors.data ?? []).filter((sensor) => sensor.room_id === group.roomId),
      devices: devices.data.filter((device) => device.room_id === group.roomId),
    }))
    .filter((group) => group.sensors.length > 0 || group.devices.length > 0)

  return (
    <div className="flex flex-col gap-4">
      <IntentBar />

      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-sm text-slate-400">
          <span className={`size-2 rounded-full ${online === devices.data.length ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          На связи {online} из {devices.data.length}
        </span>
        <Button variant="ghost" onClick={allOff} disabled={poweringOff}>
          {poweringOff ? 'Выключаем…' : 'Все выкл'}
        </Button>
      </div>

      {scenarios.data !== undefined && scenarios.data.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {scenarios.data.map((scenario) => {
            const running = runScenario.isPending && runScenario.variables === scenario.id
            return (
              <Button
                key={scenario.id}
                variant="ghost"
                disabled={runScenario.isPending}
                onClick={() => runScenario.mutate(scenario.id)}
              >
                {running ? 'Запускаем…' : scenario.name}
              </Button>
            )
          })}
        </div>
      )}

      {groups.map((group) => (
        <section key={group.key} aria-label={group.title} className="flex flex-col gap-2.5">
          <h2 className="px-1 text-lg font-bold tracking-tight">{group.title}</h2>
          {group.sensors.length > 0 && (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {group.sensors.map((sensor) => (
                <SensorCard key={sensor.id} sensor={sensor} />
              ))}
            </div>
          )}
          {group.devices.length > 0 && (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {group.devices.map((device) => (
                <DeviceCard
                  key={device.uuid}
                  device={device}
                  onCommand={(body) => sendCommand.mutate({ uuid: device.uuid, body })}
                  onReleaseHold={() => releaseHold.mutate(device.uuid)}
                />
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  )
}

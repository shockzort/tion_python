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

  const roomNames = new Map(rooms.data?.map((room) => [room.id, room.name]))
  const online = devices.data.filter((d) => d.connection === 'online').length

  const allOff = async () => {
    setPoweringOff(true)
    try {
      await powerOffAll(queryClient, devices.data)
    } finally {
      setPoweringOff(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <IntentBar />

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          На связи {online} из {devices.data.length}
        </p>
        <Button variant="ghost" onClick={allOff} disabled={poweringOff}>
          {poweringOff ? 'Выключаем…' : 'Все выкл'}
        </Button>
      </div>

      {scenarios.data !== undefined && scenarios.data.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {scenarios.data.map((scenario) => {
            const running =
              runScenario.isPending && runScenario.variables === scenario.id
            return (
              <Button
                key={scenario.id}
                variant="ghost"
                disabled={runScenario.isPending}
                onClick={() => runScenario.mutate(scenario.id)}
              >
                {running ? 'Запускаем…' : `▶ ${scenario.name}`}
              </Button>
            )
          })}
        </div>
      )}

      {sensors.data !== undefined && sensors.data.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {sensors.data.map((sensor) => (
            <SensorCard
              key={sensor.id}
              sensor={sensor}
              roomName={
                sensor.room_id !== null ? roomNames.get(sensor.room_id) : undefined
              }
            />
          ))}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {devices.data.map((device) => (
          <DeviceCard
            key={device.uuid}
            device={device}
            roomName={
              device.room_id !== null ? roomNames.get(device.room_id) : undefined
            }
            onCommand={(body) =>
              sendCommand.mutate({ uuid: device.uuid, body })
            }
            onReleaseHold={() => releaseHold.mutate(device.uuid)}
          />
        ))}
      </div>
    </div>
  )
}

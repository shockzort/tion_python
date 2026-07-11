import { useState } from 'react'

import {
  useAddGroup,
  useAddRoom,
  useDeleteDevice,
  useDeleteGroup,
  useDeleteRoom,
  useDevices,
  useGroups,
  useRooms,
  useSetGroupMembers,
  useUpdateDevice,
} from '../api/queries'
import type { Device, Group } from '../api/types'
import PairWizard from '../components/PairWizard'
import { Badge, Button, Card, Spinner } from '../components/ui'

export default function Devices() {
  const devices = useDevices()
  const [wizardOpen, setWizardOpen] = useState(false)

  if (devices.isPending) {
    return <Spinner label="Загружаем…" />
  }
  if (devices.isError) {
    return <p className="text-rose-400">Не удалось загрузить устройства.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Устройства</h2>
        <Button onClick={() => setWizardOpen(true)}>Добавить бризер</Button>
      </div>

      <div className="flex flex-col gap-3">
        {devices.data.map((device) => (
          <DeviceRow key={device.uuid} device={device} />
        ))}
        {devices.data.length === 0 && (
          <p className="text-sm text-slate-500">
            Нажмите «Добавить бризер», чтобы сопрячь первый.
          </p>
        )}
      </div>

      <RoomsSection />
      <GroupsSection devices={devices.data} />

      {wizardOpen && <PairWizard onClose={() => setWizardOpen(false)} />}
    </div>
  )
}

function DeviceRow({ device }: { device: Device }) {
  const rooms = useRooms()
  const update = useUpdateDevice()
  const remove = useDeleteDevice()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(device.name)

  const saveName = () => {
    const trimmed = name.trim()
    if (trimmed && trimmed !== device.name) {
      update.mutate({ uuid: device.uuid, body: { name: trimmed } })
    }
    setEditing(false)
  }

  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        {editing ? (
          <input
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onBlur={saveName}
            onKeyDown={(event) => event.key === 'Enter' && saveName()}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              setName(device.name)
              setEditing(true)
            }}
            title="Переименовать"
            className="text-left font-medium hover:text-sky-300"
          >
            {device.name} <span className="text-xs text-slate-500">✎</span>
          </button>
        )}
        <Badge tone={device.connection === 'online' ? 'ok' : 'error'}>
          {device.connection === 'online' ? 'на связи' : 'нет связи'}
        </Badge>
      </div>

      <p className="text-xs text-slate-500">{device.mac}</p>

      <div className="flex items-center justify-between gap-2">
        <select
          value={device.room_id ?? ''}
          onChange={(event) => {
            const value = event.target.value
            if (value !== '') {
              update.mutate({
                uuid: device.uuid,
                body: { room_id: Number(value) },
              })
            }
          }}
          aria-label="Комната"
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-300"
        >
          <option value="">Без комнаты</option>
          {rooms.data?.map((room) => (
            <option key={room.id} value={room.id}>
              {room.name}
            </option>
          ))}
        </select>
        <Button
          variant="danger"
          onClick={() => {
            if (confirm(`Удалить «${device.name}»?`)) {
              remove.mutate(device.uuid)
            }
          }}
        >
          Удалить
        </Button>
      </div>
    </Card>
  )
}

function RoomsSection() {
  const rooms = useRooms()
  const addRoom = useAddRoom()
  const deleteRoom = useDeleteRoom()
  const [name, setName] = useState('')

  const add = () => {
    const trimmed = name.trim()
    if (trimmed) {
      addRoom.mutate(trimmed, { onSuccess: () => setName('') })
    }
  }

  return (
    <Card>
      <h3 className="mb-2 font-medium">Комнаты</h3>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {rooms.data?.map((room) => (
          <Badge key={room.id} tone="muted">
            {room.name}
            <button
              type="button"
              aria-label={`удалить комнату ${room.name}`}
              onClick={() => deleteRoom.mutate(room.id)}
              className="ml-0.5 hover:text-slate-200"
            >
              ✕
            </button>
          </Badge>
        ))}
        {rooms.data?.length === 0 && (
          <span className="text-sm text-slate-500">пока пусто</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          value={name}
          placeholder="Например, Спальня"
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && add()}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
        />
        <Button variant="ghost" onClick={add} disabled={!name.trim()}>
          Добавить
        </Button>
      </div>
    </Card>
  )
}

function GroupsSection({ devices }: { devices: Device[] }) {
  const groups = useGroups()
  const addGroup = useAddGroup()
  const deleteGroup = useDeleteGroup()
  const [name, setName] = useState('')

  const add = () => {
    const trimmed = name.trim()
    if (trimmed) {
      addGroup.mutate(trimmed, { onSuccess: () => setName('') })
    }
  }

  return (
    <Card>
      <h3 className="mb-2 font-medium">Группы</h3>
      <div className="flex flex-col gap-3">
        {groups.data?.map((group) => (
          <GroupEditor
            key={group.id}
            group={group}
            devices={devices}
            onDelete={() => deleteGroup.mutate(group.id)}
          />
        ))}
        {groups.data?.length === 0 && (
          <span className="text-sm text-slate-500">пока пусто</span>
        )}
        <div className="flex gap-2">
          <input
            value={name}
            placeholder="Например, Все бризеры"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && add()}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
          />
          <Button variant="ghost" onClick={add} disabled={!name.trim()}>
            Создать
          </Button>
        </div>
      </div>
    </Card>
  )
}

function GroupEditor({
  group,
  devices,
  onDelete,
}: {
  group: Group
  devices: Device[]
  onDelete: () => void
}) {
  const setMembers = useSetGroupMembers()

  const toggleMember = (uuid: string, checked: boolean) => {
    const members = checked
      ? [...group.device_uuids, uuid]
      : group.device_uuids.filter((member) => member !== uuid)
    setMembers.mutate({ id: group.id, device_uuids: members })
  }

  return (
    <div className="rounded-xl border border-slate-800 p-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-sm font-medium">{group.name}</span>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`удалить группу ${group.name}`}
          className="text-xs text-slate-500 hover:text-rose-400"
        >
          удалить
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {devices.map((device) => (
          <label
            key={device.uuid}
            className="flex items-center gap-2 text-sm text-slate-300"
          >
            <input
              type="checkbox"
              checked={group.device_uuids.includes(device.uuid)}
              onChange={(event) =>
                toggleMember(device.uuid, event.target.checked)
              }
              className="accent-sky-500"
            />
            {device.name}
          </label>
        ))}
      </div>
    </div>
  )
}

// WS-мост: события сервера → кэш TanStack Query (план §11: событие → setQueryData)

import type { QueryClient } from '@tanstack/react-query'

import { keys } from './api/queries'
import type { Connection, Device, DeviceState, WsEvent } from './api/types'

/** Прогресс мастера сопряжения — отдельная шина для PairWizard. */
export const pairingProgress = new EventTarget()

const WS_UNAUTHORIZED = 4401
const MAX_BACKOFF_MS = 15_000

export function startEventBridge(queryClient: QueryClient): () => void {
  let socket: WebSocket | null = null
  let stopped = false
  let attempt = 0

  const connect = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(`${protocol}//${location.host}/api/ws`)
    socket.onopen = () => {
      attempt = 0
      // догоняем пропущенное за время реконнекта
      void queryClient.invalidateQueries({ queryKey: keys.devices })
    }
    socket.onmessage = (message: MessageEvent<string>) => {
      try {
        handleEvent(queryClient, JSON.parse(message.data) as WsEvent)
      } catch {
        // битое сообщение не должно ронять мост
      }
    }
    socket.onclose = (event) => {
      if (stopped) return
      if (event.code === WS_UNAUTHORIZED) {
        // сессия истекла — роутер уведёт на логин после сброса me
        void queryClient.resetQueries({ queryKey: keys.me })
        return
      }
      attempt += 1
      setTimeout(connect, Math.min(500 * 2 ** attempt, MAX_BACKOFF_MS))
    }
  }

  connect()
  return () => {
    stopped = true
    socket?.close()
  }
}

function handleEvent(queryClient: QueryClient, event: WsEvent) {
  switch (event.topic) {
    case 'device.state_changed': {
      const uuid = event.data.device_uuid as string
      const state = event.data.state as DeviceState
      patchDevice(queryClient, uuid, (device) => ({
        ...device,
        state,
        state_at: Date.now() / 1000,
      }))
      break
    }
    case 'device.connection_changed': {
      const uuid = event.data.device_uuid as string
      const connection = event.data.connection as Connection
      patchDevice(queryClient, uuid, (device) => ({ ...device, connection }))
      break
    }
    case 'device.list_changed':
      void queryClient.invalidateQueries({ queryKey: keys.devices })
      break
    case 'command.finished':
      if (event.data.status !== 'done') {
        // откат optimistic-обновления: показываем фактическое состояние
        void queryClient.invalidateQueries({ queryKey: keys.devices })
      }
      break
    case 'pairing.progress':
      pairingProgress.dispatchEvent(
        new CustomEvent('progress', { detail: event.data }),
      )
      break
    case 'automation.changed':
      void queryClient.invalidateQueries({ queryKey: keys.scenarios })
      void queryClient.invalidateQueries({ queryKey: keys.schedules })
      void queryClient.invalidateQueries({ queryKey: keys.triggers })
      break
    case 'sensor.updated':
      void queryClient.invalidateQueries({ queryKey: keys.sensors })
      break
  }
}

function patchDevice(
  queryClient: QueryClient,
  uuid: string,
  patch: (device: Device) => Device,
) {
  queryClient.setQueryData<Device[]>(keys.devices, (devices) =>
    devices?.map((device) => (device.uuid === uuid ? patch(device) : device)),
  )
}

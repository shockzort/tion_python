// Подписка на web push: ключ VAPID с сервера → pushManager → регистрация.

import { api } from '../api/client'

function keyToBytes(base64url: string): Uint8Array {
  const padded = base64url + '='.repeat((4 - (base64url.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (char) => char.charCodeAt(0))
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

export async function enablePush(): Promise<void> {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('уведомления запрещены в браузере')
  }
  const { key } = await api<{ key: string }>('/api/push/vapid-key')
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyToBytes(key).buffer as ArrayBuffer,
  })
  const info = subscription.toJSON()
  await api('/api/push/subscriptions', {
    method: 'POST',
    json: { endpoint: info.endpoint, keys: info.keys },
  })
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription()
  if (subscription === null) return
  await api('/api/push/unsubscribe', {
    method: 'POST',
    json: { endpoint: subscription.endpoint },
  })
  await subscription.unsubscribe()
}

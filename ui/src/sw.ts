/// <reference lib="webworker" />
// Service worker PWA: precache app-shell + web push (FR-32).
// injectManifest: vite-plugin-pwa подставляет манифест прекеша при сборке.

import { clientsClaim } from 'workbox-core'
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { createHandlerBoundToURL } from 'workbox-precaching'

declare let self: ServiceWorkerGlobalScope

self.skipWaiting()
clientsClaim()
cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)

// app-shell для клиентских маршрутов; данные всегда с сервера
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('index.html'), {
    denylist: [/^\/api\//, /^\/v1\.0\//, /^\/oauth\//, /^\/ws/],
  }),
)

type PushPayload = { title?: string; body?: string }

self.addEventListener('push', (event) => {
  let payload: PushPayload = {}
  try {
    payload = (event.data?.json() ?? {}) as PushPayload
  } catch {
    payload = { body: event.data?.text() }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title ?? 'Easy Breezy', {
      body: payload.body,
      icon: '/pwa-192.png',
      badge: '/pwa-192.png',
      lang: 'ru',
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((clients) => {
      const open = clients.find((client) => 'focus' in client)
      if (open !== undefined) return open.focus()
      return self.clients.openWindow('/')
    }),
  )
})

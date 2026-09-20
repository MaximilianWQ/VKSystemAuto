/* Service worker дашборда.

   Две задачи: показать оболочку без сети и принять пуш. Кешировать ответы API
   нельзя — оператор увидел бы устаревшую очередь и решил, что всё разобрано. */

const CACHE = 'shell-v1'
const SHELL = ['/', '/index.html', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  const live = url.pathname.startsWith('/api') || url.pathname.startsWith('/ws') ||
    url.pathname.startsWith('/vk')
  if (event.request.method !== 'GET' || live) return

  // Навигация: сеть первой, кеш как запасной вариант при обрыве.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/index.html').then((r) => r || Response.error())),
    )
    return
  }

  event.respondWith(
    caches.match(event.request).then(
      (cached) =>
        cached ||
        fetch(event.request).then((response) => {
          if (response.ok && url.origin === location.origin) {
            const copy = response.clone()
            caches.open(CACHE).then((cache) => cache.put(event.request, copy))
          }
          return response
        }),
    ),
  )
})

self.addEventListener('push', (event) => {
  let payload = { title: 'Новое сообщение', body: '', ticket_id: null }
  try {
    payload = { ...payload, ...(event.data ? event.data.json() : {}) }
  } catch {
    payload.body = event.data ? event.data.text() : ''
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      // Один тег на диалог: десять сообщений подряд не завалят экран.
      tag: payload.ticket_id ? `ticket-${payload.ticket_id}` : 'support',
      renotify: true,
      data: payload,
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const open = clients.find((client) => client.url.includes(location.origin))
      if (open) return open.focus()
      return self.clients.openWindow('/')
    }),
  )
})

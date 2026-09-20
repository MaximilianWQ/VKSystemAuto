/** Подписка на веб-пуши.

Ограничения iOS, из которых растёт всё поведение этого модуля: пуши приходят
только когда приложение добавлено на экран «Домой», разрешение можно запросить
лишь по нажатию, а подписку система периодически сбрасывает — поэтому
переподписываемся при каждом запуске. */

import { api } from './api'

export const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches ||
  (navigator as unknown as { standalone?: boolean }).standalone === true

export const pushSupported = () =>
  'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

function toUint8(base64Url: string): Uint8Array<ArrayBuffer> {
  const padded = base64Url.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
  // Явный ArrayBuffer: applicationServerKey не принимает ArrayBufferLike.
  const bytes = new Uint8Array(new ArrayBuffer(binary.length))
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

export async function currentSubscription() {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

/** Запрашивает разрешение и подписывается. Вызывать только из обработчика клика. */
export async function enablePush(): Promise<'ok' | 'denied' | 'unsupported'> {
  if (!pushSupported()) return 'unsupported'

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return 'denied'

  const { key } = await api.get<{ key: string }>('/api/push/key')
  const registration = await navigator.serviceWorker.ready
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: toUint8(key),
    }))

  await api.post('/api/push/subscribe', subscription.toJSON())
  return 'ok'
}

export async function disablePush() {
  const subscription = await currentSubscription()
  if (!subscription) return
  await api.post('/api/push/unsubscribe', { endpoint: subscription.endpoint })
  await subscription.unsubscribe()
}

/** iOS сбрасывает подписку молча — на каждом запуске отдаём её серверу заново. */
export async function refreshSubscription() {
  try {
    const subscription = await currentSubscription()
    if (subscription) await api.post('/api/push/subscribe', subscription.toJSON())
  } catch {
    // Молча: обновление подписки не должно мешать работе дашборда.
  }
}

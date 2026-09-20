/** Подключение к WebSocket дашборда с переподключением.

Railway рвёт простаивающие соединения, а телефон засыпает, поэтому разрыв здесь
норма, а не исключение: переподключаемся с нарастающей паузой и без шума в консоли. */

import { useEffect, useRef, useState } from 'react'

const FIRST_DELAY = 1000
const MAX_DELAY = 20000

import type { Message } from './api'

export type SocketEvent = {
  type: string
  ticket_id?: number
  user_id?: number
  text?: string
  message?: Message
}

export function useSocket(onEvent: (event: SocketEvent) => void, enabled: boolean) {
  const [connected, setConnected] = useState(false)
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    // Без сессии сервер отвечает 403, и переподключение уходит в цикл —
    // подключаемся только после входа.
    if (!enabled) {
      setConnected(false)
      return
    }

    let socket: WebSocket | null = null
    let timer: number | undefined
    let delay = FIRST_DELAY
    let stopped = false

    const connect = () => {
      if (stopped) return
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${location.host}/ws`)

      socket.onopen = () => {
        delay = FIRST_DELAY
        setConnected(true)
      }
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as SocketEvent
        if (payload.type === 'ping') {
          socket?.send(JSON.stringify({ type: 'pong' }))
          return
        }
        if (payload.type === 'ready' || payload.type === 'pong') return
        handler.current(payload)
      }
      socket.onclose = () => {
        setConnected(false)
        if (stopped) return
        timer = window.setTimeout(connect, delay)
        delay = Math.min(delay * 2, MAX_DELAY)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    // Возврат из фона на телефоне — самый частый момент, когда соединение уже мертво.
    const wake = () => {
      if (document.visibilityState === 'visible' && socket?.readyState !== WebSocket.OPEN) {
        socket?.close()
      }
    }
    document.addEventListener('visibilitychange', wake)

    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', wake)
      window.clearTimeout(timer)
      socket?.close()
    }
  }, [enabled])

  return connected
}

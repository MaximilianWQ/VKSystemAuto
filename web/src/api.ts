/** Тонкая обёртка над fetch: единая обработка 401 и ошибок сервера. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `Ошибка ${status}`)
  }
}

let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers:
      init?.body instanceof FormData
        ? init?.headers
        : { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })

  if (response.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, 'Нужно войти заново')
  }
  if (!response.ok) {
    let detail = ''
    try {
      detail = (await response.json())?.detail ?? ''
    } catch {
      detail = ''
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : '{}' }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  remove: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>(path, { method: 'POST', body: form })
  },
}

export type VkUser = {
  vk_id: number
  name: string
  photo_url: string
  can_write: boolean
}

export type Attachment = {
  type: 'photo' | 'video' | 'doc' | 'audio_message' | 'sticker' | 'geo' | 'unsupported'
  url?: string
  preview?: string
  title?: string
  ext?: string
  size?: number
  duration?: number
  waveform?: number[]
  width?: number
  height?: number
  lat?: number
  lon?: number
  raw_type?: string
}

export type Dialog = {
  id: number
  status: 'open' | 'in_progress' | 'closed'
  unread: number
  preview: string
  preview_attachments: Attachment[]
  waiting_seconds: number
  created_at: string
  last_message_at: string
  rating: number | null
  user: VkUser
}

export type Message = {
  id: number
  direction: 'in' | 'out'
  text: string
  attachments: Attachment[]
  created_at: string
  read_at: string | null
}

export type Thread = {
  ticket: { id: number; status: string; rating: number | null; user: VkUser }
  messages: Message[]
}

export type Stats = {
  day: number
  week: number
  open_now: number
  avg_first_reply_seconds: number | null
  avg_rating: number | null
}

export type PasskeyInfo = {
  id: number
  name: string
  created_at: string
  last_used_at: string | null
}

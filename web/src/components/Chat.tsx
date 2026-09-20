import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Message, type Operator, type Thread } from '../api'
import { clock, dayLabel } from '../format'
import { Attachments } from './Attachments'
import { Avatar, Button, Tag, type Status } from './ui'

function Bubble({ message }: { message: Message }) {
  const outgoing = message.direction === 'out'
  return (
    <div className={`flex ${outgoing ? 'justify-end' : 'justify-start'}`}>
      <div
        className="max-w-[min(620px,86%)] px-3 py-2"
        style={{
          background: outgoing ? 'var(--ink)' : 'var(--surface)',
          color: outgoing ? 'var(--bg)' : 'var(--ink)',
          border: `1px solid ${outgoing ? 'var(--ink)' : 'var(--line)'}`,
          borderRadius: 'var(--radius)',
        }}
      >
        {message.text && (
          <div className="whitespace-pre-wrap break-words text-[14px]">{message.text}</div>
        )}
        <Attachments items={message.attachments} messageId={message.id} />
        <div className="num mt-0.5 text-[11px] text-right" style={{ opacity: 0.55 }}>
          {clock(message.created_at)}
        </div>
      </div>
    </div>
  )
}

function TakeBar({
  ticketId,
  onTaken,
}: {
  ticketId: number
  onTaken: (operator: Operator) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const take = async (tier: 'operator' | 'lead') => {
    setBusy(true)
    setError('')
    try {
      const { operator } = await api.post<{ operator: Operator }>(
        `/api/dialogs/${ticketId}/take`,
        { tier },
      )
      onTaken(operator)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail || e.message : 'Не получилось')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="px-4 py-3 flex flex-wrap items-center gap-2"
      style={{ background: 'var(--wait-bg)', borderBottom: '1px solid var(--line)' }}
    >
      <span className="text-[13px] font-medium" style={{ color: 'var(--wait)' }}>
        Обращение не взято в работу
      </span>
      <span className="text-[12px] flex-1 min-w-[180px]" style={{ color: 'var(--muted)' }}>
        Клиенту уйдёт представление — имя и должность закрепятся за обращением
      </span>
      <Button onClick={() => take('operator')} disabled={busy} variant="primary">
        Взять как оператор
      </Button>
      <Button onClick={() => take('lead')} disabled={busy}>
        Взять как руководитель
      </Button>
      {error && (
        <span className="text-[12px] w-full" style={{ color: 'var(--alarm)' }}>
          {error}
        </span>
      )}
    </div>
  )
}

export function Chat({
  ticketId,
  incoming,
  onChanged,
  onBack,
}: {
  ticketId: number
  /** Сообщение, пришедшее по сокету. Дописывается без перезапроса ленты. */
  incoming: Message | null
  onChanged: () => void
  onBack?: () => void
}) {
  const [thread, setThread] = useState<Thread | null>(null)
  const [draft, setDraft] = useState('')
  const [attachment, setAttachment] = useState<{ token: string; name: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)

  const load = useCallback(async () => {
    const data = await api.get<Thread>(`/api/dialogs/${ticketId}/messages`)
    setThread(data)
    await api.post(`/api/dialogs/${ticketId}/read`)
    onChanged()
  }, [ticketId, onChanged])

  useEffect(() => {
    setThread(null)
    setDraft('')
    setAttachment(null)
    setError('')
    load().catch((e) => setError(e.message))
    composer.current?.focus()
  }, [ticketId, load])

  // Входящее по сокету дописываем на месте: перезапрос ленты даёт рывок
  // и теряет позицию прокрутки.
  useEffect(() => {
    if (!incoming) return
    setThread((current) => {
      if (!current) return current
      if (current.messages.some((m) => m.id === incoming.id)) return current
      return { ...current, messages: [...current.messages, incoming] }
    })
    api.post(`/api/dialogs/${ticketId}/read`).then(onChanged).catch(() => undefined)
  }, [incoming, ticketId, onChanged])

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [thread?.messages.length])

  const append = (message: Message) =>
    setThread((current) =>
      current ? { ...current, messages: [...current.messages, message] } : current,
    )

  const send = async () => {
    const text = draft.trim()
    if (!text && !attachment) return
    setBusy(true)
    setError('')

    // Показываем сразу: ожидание ответа сервера в чате читается как зависание.
    const optimistic: Message = {
      id: -Date.now(),
      direction: 'out',
      text,
      attachments: [],
      created_at: new Date().toISOString(),
      read_at: null,
    }
    append(optimistic)
    setDraft('')
    const sending = attachment
    setAttachment(null)

    try {
      await api.post(`/api/dialogs/${ticketId}/reply`, {
        text,
        attachment: sending?.token ?? null,
      })
      await load()
    } catch (e) {
      // Откатываем временный пузырь и возвращаем текст в поле.
      setThread((current) =>
        current
          ? { ...current, messages: current.messages.filter((m) => m.id !== optimistic.id) }
          : current,
      )
      setDraft(text)
      setAttachment(sending)
      setError(e instanceof ApiError ? e.detail || e.message : 'Не отправилось')
    } finally {
      setBusy(false)
    }
  }

  const attach = async (file: File) => {
    if (!thread) return
    setBusy(true)
    setError('')
    try {
      const { attachment: token } = await api.upload<{ attachment: string }>(
        `/api/uploads?peer_id=${thread.ticket.user.vk_id}`,
        file,
      )
      setAttachment({ token, name: file.name })
    } catch (e) {
      setError(e instanceof ApiError ? e.detail || e.message : 'Файл не загрузился')
    } finally {
      setBusy(false)
    }
  }

  const close = async () => {
    if (!confirm('Закрыть обращение? Клиенту уйдёт сообщение и просьба об оценке.')) return
    setBusy(true)
    try {
      await api.post(`/api/dialogs/${ticketId}/close`)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.detail || e.message : 'Не закрылось')
    } finally {
      setBusy(false)
    }
  }

  if (!thread) {
    return (
      <div className="grid place-items-center h-full text-[13px]" style={{ color: 'var(--muted)' }}>
        {error || 'Загружаем…'}
      </div>
    )
  }

  const { user, status, operator } = thread.ticket
  const closed = status === 'closed'
  let lastDay = ''

  return (
    <div className="flex flex-col h-full min-h-0" style={{ background: 'var(--bg)' }}>
      <header
        className="flex items-center gap-2.5 px-3 py-2.5 safe-t shrink-0"
        style={{ background: 'var(--surface)', borderBottom: '1px solid var(--line)' }}
      >
        {onBack && (
          <button
            onClick={onBack}
            className="md:hidden w-8 h-8 grid place-items-center text-[17px] shrink-0"
            style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}
            aria-label="Назад к очереди"
          >
            ‹
          </button>
        )}
        <Avatar name={user.name} src={user.photo_url} size={32} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[14px] truncate">{user.name}</span>
            <span className="mono shrink-0" style={{ color: 'var(--muted)' }}>
              #{thread.ticket.id}
            </span>
            <Tag status={status as Status} />
          </div>
          <div className="text-[12px] truncate" style={{ color: 'var(--muted)' }}>
            {operator ? `▸ ${operator.signature}` : 'никто не ведёт'}
            {thread.ticket.rating ? ` · оценка ${thread.ticket.rating} из 5` : ''}
          </div>
        </div>
        {!closed && (
          <Button onClick={close} disabled={busy} variant="danger">
            Закрыть
          </Button>
        )}
      </header>

      {!closed && !operator && <TakeBar ticketId={ticketId} onTaken={() => void load()} />}

      <div className="flex-1 min-h-0 scroll px-3 py-4">
        <div className="flex flex-col gap-1.5 max-w-3xl mx-auto">
          {thread.messages.map((message) => {
            const day = dayLabel(message.created_at)
            const divider = day !== lastDay ? day : null
            lastDay = day
            return (
              <div key={message.id} className="contents">
                {divider && (
                  <div
                    className="self-center my-2 px-2 py-[2px] text-[11px] font-medium rounded"
                    style={{ background: 'var(--panel)', color: 'var(--muted)' }}
                  >
                    {divider}
                  </div>
                )}
                <Bubble message={message} />
              </div>
            )
          })}
          <div ref={bottom} />
        </div>
      </div>

      {!user.can_write && (
        <div
          className="px-4 py-2.5 text-[12px] text-center shrink-0"
          style={{ background: 'var(--alarm-bg)', color: 'var(--alarm)' }}
        >
          Пользователь запретил сообщения от сообщества — ответить нельзя
        </div>
      )}

      {!closed && user.can_write && (
        <div
          className="px-3 py-2.5 safe-b shrink-0"
          style={{ background: 'var(--surface)', borderTop: '1px solid var(--line)' }}
        >
          {error && (
            <div className="mb-1.5 text-[12px]" style={{ color: 'var(--alarm)' }}>
              {error}
            </div>
          )}
          {attachment && (
            <div
              className="mb-1.5 flex items-center gap-2 px-2.5 py-1.5 text-[12px]"
              style={{ background: 'var(--panel)', borderRadius: 'var(--radius)' }}
            >
              <span className="truncate flex-1">{attachment.name}</span>
              <button onClick={() => setAttachment(null)} aria-label="Убрать вложение">
                ✕
              </button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <button
              onClick={() => fileInput.current?.click()}
              disabled={busy}
              className="w-9 h-9 shrink-0 grid place-items-center text-[17px] disabled:opacity-40"
              style={{ border: '1px solid var(--line)', borderRadius: 'var(--radius)' }}
              aria-label="Прикрепить файл"
            >
              +
            </button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void attach(file)
                event.target.value = ''
              }}
            />
            <textarea
              ref={composer}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                // Enter отправляет, Shift+Enter переносит строку — как в мессенджере.
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void send()
                }
              }}
              rows={1}
              placeholder="Ответ клиенту · Enter отправит"
              className="flex-1 resize-none outline-none px-2.5 py-2 text-[14px] max-h-40 scroll"
              style={{
                background: 'var(--bg)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius)',
                color: 'var(--ink)',
              }}
            />
            <Button
              onClick={send}
              disabled={busy || (!draft.trim() && !attachment)}
              variant="primary"
            >
              Отправить
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

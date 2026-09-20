import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api, ApiError, type Thread } from '../api'
import { clock, dayLabel } from '../format'
import { Attachments } from './Attachments'
import { Avatar } from './Avatar'

function Bubble({
  outgoing,
  children,
}: {
  outgoing: boolean
  children: React.ReactNode
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 460, damping: 34 }}
      className={`max-w-[min(560px,82%)] px-4 py-3 ${outgoing ? 'self-end' : 'self-start'}`}
      style={{
        background: outgoing ? 'var(--ink)' : 'var(--surface)',
        color: outgoing ? 'var(--bg)' : 'var(--ink)',
        borderRadius: 22,
        borderBottomRightRadius: outgoing ? 8 : 22,
        borderBottomLeftRadius: outgoing ? 22 : 8,
        boxShadow: outgoing ? 'none' : 'var(--shadow)',
      }}
    >
      {children}
    </motion.div>
  )
}

export function Chat({
  ticketId,
  onChanged,
  onBack,
}: {
  ticketId: number
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

  const load = async () => {
    const data = await api.get<Thread>(`/api/dialogs/${ticketId}/messages`)
    setThread(data)
    await api.post(`/api/dialogs/${ticketId}/read`)
    onChanged()
  }

  useEffect(() => {
    setThread(null)
    setDraft('')
    setAttachment(null)
    setError('')
    load().catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thread?.messages.length])

  const send = async () => {
    const text = draft.trim()
    if (!text && !attachment) return
    setBusy(true)
    setError('')
    try {
      await api.post(`/api/dialogs/${ticketId}/reply`, {
        text,
        attachment: attachment?.token ?? null,
      })
      setDraft('')
      setAttachment(null)
      await load()
    } catch (e) {
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
      <div className="grid place-items-center h-full text-[14px]" style={{ color: 'var(--muted)' }}>
        {error || 'Загружаем…'}
      </div>
    )
  }

  const { user, status } = thread.ticket
  const closed = status === 'closed'
  let lastDay = ''

  return (
    <div className="flex flex-col h-full min-h-0">
      <header
        className="flex items-center gap-3 px-4 py-3 border-b hairline safe-top"
        style={{ background: 'var(--bg)' }}
      >
        {onBack && (
          <button
            onClick={onBack}
            className="md:hidden pill w-9 h-9 grid place-items-center text-lg"
            style={{ background: 'var(--surface)', boxShadow: 'var(--shadow)' }}
            aria-label="Назад к списку"
          >
            ‹
          </button>
        )}
        <Avatar name={user.name} src={user.photo_url} size={40} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold truncate text-[15px]">{user.name}</div>
          <div className="text-[12px]" style={{ color: 'var(--muted)' }}>
            Обращение №{thread.ticket.id}
            {closed && ' · закрыто'}
            {thread.ticket.rating && ` · оценка ${thread.ticket.rating}`}
          </div>
        </div>
        {!closed && (
          <button
            onClick={close}
            disabled={busy}
            className="pill px-4 h-9 text-[13px] font-medium transition-transform active:scale-95 disabled:opacity-40"
            style={{ background: 'var(--surface)', boxShadow: 'var(--shadow)' }}
          >
            Закрыть
          </button>
        )}
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto quiet-scroll px-4 py-5">
        <div className="flex flex-col gap-2 max-w-3xl mx-auto">
          <AnimatePresence initial={false}>
            {thread.messages.map((message) => {
              const day = dayLabel(message.created_at)
              const divider = day !== lastDay ? day : null
              lastDay = day
              const outgoing = message.direction === 'out'
              return (
                <div key={message.id} className="contents">
                  {divider && (
                    <div
                      className="self-center my-3 pill px-3 py-1 text-[12px]"
                      style={{ background: 'var(--sunken)', color: 'var(--muted)' }}
                    >
                      {divider}
                    </div>
                  )}
                  <Bubble outgoing={outgoing}>
                    {message.text && (
                      <div className="whitespace-pre-wrap break-words text-[15px]">
                        {message.text}
                      </div>
                    )}
                    <Attachments items={message.attachments} messageId={message.id} />
                    <div
                      className="mt-1 text-[11px] tabular-nums"
                      style={{ opacity: 0.55, textAlign: outgoing ? 'right' : 'left' }}
                    >
                      {clock(message.created_at)}
                    </div>
                  </Bubble>
                </div>
              )
            })}
          </AnimatePresence>
          <div ref={bottom} />
        </div>
      </div>

      {!user.can_write && (
        <div
          className="px-4 py-3 text-[13px] text-center"
          style={{ background: 'var(--sunken)', color: 'var(--muted)' }}
        >
          Пользователь запретил сообщения от сообщества — ответить нельзя
        </div>
      )}

      {!closed && user.can_write && (
        <div className="px-4 pb-4 safe-bottom" style={{ background: 'var(--bg)' }}>
          {error && (
            <div className="mb-2 text-[13px]" style={{ color: '#D8412F' }}>
              {error}
            </div>
          )}
          {attachment && (
            <div
              className="mb-2 flex items-center gap-2 px-3 py-2 text-[13px]"
              style={{ background: 'var(--sunken)', borderRadius: 'var(--radius-inner)' }}
            >
              <span className="truncate flex-1">{attachment.name}</span>
              <button onClick={() => setAttachment(null)} aria-label="Убрать вложение">
                ✕
              </button>
            </div>
          )}
          <div
            className="flex items-end gap-2 p-2"
            style={{
              background: 'var(--surface)',
              borderRadius: 'var(--radius-card)',
              boxShadow: 'var(--shadow)',
            }}
          >
            <button
              onClick={() => fileInput.current?.click()}
              disabled={busy}
              className="pill w-10 h-10 shrink-0 grid place-items-center text-xl disabled:opacity-40"
              style={{ background: 'var(--sunken)' }}
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
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void send()
              }}
              rows={1}
              placeholder="Ответ клиенту"
              className="flex-1 resize-none bg-transparent outline-none py-2 px-1 text-[15px] max-h-32"
              style={{ color: 'var(--ink)' }}
            />
            <button
              onClick={send}
              disabled={busy || (!draft.trim() && !attachment)}
              className="pill w-10 h-10 shrink-0 grid place-items-center text-lg transition-transform active:scale-90 disabled:opacity-30"
              style={{ background: 'var(--ink)', color: 'var(--bg)' }}
              aria-label="Отправить"
            >
              ↑
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

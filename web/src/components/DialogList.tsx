import type { Dialog } from '../api'
import { waiting } from '../format'
import { Avatar, StatusDot, type Status } from './ui'

function previewText(dialog: Dialog): string {
  if (dialog.preview.trim()) return dialog.preview.replace(/\s+/g, ' ')
  const kinds = dialog.preview_attachments.map((item) => item.type)
  if (kinds.includes('photo')) return 'Фото'
  if (kinds.includes('audio_message')) return 'Голосовое'
  if (kinds.includes('video')) return 'Видео'
  if (kinds.includes('doc')) return 'Файл'
  if (kinds.length) return 'Вложение'
  return '—'
}

/** Ждём дольше пятнадцати минут — это уже видно глазом в очереди. */
const URGENT_SECONDS = 15 * 60

export function DialogList({
  dialogs,
  activeId,
  onPick,
  showClosed,
  onToggleClosed,
}: {
  dialogs: Dialog[]
  activeId: number | null
  onPick: (id: number) => void
  showClosed: boolean
  onToggleClosed: (value: boolean) => void
}) {
  const untaken = dialogs.filter((d) => !d.operator && d.status !== 'closed').length

  return (
    <div className="flex flex-col h-full min-h-0" style={{ background: 'var(--panel)' }}>
      <div
        className="px-3 pt-3 pb-2 safe-t shrink-0"
        style={{ borderBottom: '1px solid var(--line)' }}
      >
        <div className="flex items-baseline gap-2 mb-2.5">
          <h1 className="text-[15px] font-semibold">Очередь</h1>
          <span className="num text-[13px]" style={{ color: 'var(--muted)' }}>
            {dialogs.length}
          </span>
          {untaken > 0 && !showClosed && (
            <span
              className="ml-auto num text-[12px] px-1.5 py-[1px] rounded-md font-medium"
              style={{ background: 'var(--wait-bg)', color: 'var(--wait)' }}
              title="Не взято в работу"
            >
              {untaken} без ответа
            </span>
          )}
        </div>

        <div
          className="inline-flex text-[12px] p-[2px] rounded-lg"
          style={{ background: 'var(--bg)', border: '1px solid var(--line)' }}
          role="tablist"
        >
          {[
            { label: 'Активные', value: false },
            { label: 'Закрытые', value: true },
          ].map((tab) => (
            <button
              key={tab.label}
              role="tab"
              aria-selected={showClosed === tab.value}
              onClick={() => onToggleClosed(tab.value)}
              className="px-2.5 py-1 rounded-md font-medium"
              style={
                showClosed === tab.value
                  ? { background: 'var(--surface)', color: 'var(--ink)' }
                  : { color: 'var(--muted)' }
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 scroll">
        {dialogs.length === 0 && (
          <p className="px-4 py-8 text-center text-[13px]" style={{ color: 'var(--muted)' }}>
            {showClosed ? 'Закрытых обращений нет' : 'Очередь пуста'}
          </p>
        )}

        {dialogs.map((dialog) => {
          const active = dialog.id === activeId
          const urgent =
            dialog.status !== 'closed' && dialog.waiting_seconds > URGENT_SECONDS
          return (
            <button
              key={dialog.id}
              onClick={() => onPick(dialog.id)}
              className="w-full text-left px-3 py-2.5 flex gap-2.5 items-start"
              style={{
                background: active ? 'var(--surface)' : 'transparent',
                borderBottom: '1px solid var(--line)',
                borderLeft: `2px solid ${active ? 'var(--ink)' : 'transparent'}`,
              }}
            >
              <Avatar name={dialog.user.name} src={dialog.user.photo_url} size={30} />

              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <StatusDot status={dialog.status as Status} />
                  <span className="font-medium text-[13px] truncate flex-1">
                    {dialog.user.name}
                  </span>
                  <span
                    className="num text-[12px] shrink-0"
                    style={{ color: urgent ? 'var(--wait)' : 'var(--muted)' }}
                  >
                    {waiting(dialog.waiting_seconds)}
                  </span>
                </span>

                <span className="flex items-center gap-2 mt-0.5">
                  <span className="text-[12px] truncate flex-1" style={{ color: 'var(--muted)' }}>
                    {previewText(dialog)}
                  </span>
                  {dialog.unread > 0 && (
                    <span
                      className="num shrink-0 min-w-[17px] h-[17px] px-1 grid place-items-center text-[11px] font-semibold rounded"
                      style={{ background: 'var(--ink)', color: 'var(--bg)' }}
                    >
                      {dialog.unread}
                    </span>
                  )}
                </span>

                <span className="block mt-1 text-[11px] truncate" style={{ color: 'var(--muted)' }}>
                  {dialog.operator
                    ? `▸ ${dialog.operator.signature}`
                    : dialog.status === 'closed'
                      ? '—'
                      : 'не взято в работу'}
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

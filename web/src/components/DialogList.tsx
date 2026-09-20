import { motion } from 'motion/react'
import type { Dialog } from '../api'
import { waiting } from '../format'
import { Avatar } from './Avatar'

function previewText(dialog: Dialog): string {
  if (dialog.preview.trim()) return dialog.preview
  const kinds = dialog.preview_attachments.map((item) => item.type)
  if (kinds.includes('photo')) return 'Фото'
  if (kinds.includes('audio_message')) return 'Голосовое сообщение'
  if (kinds.includes('video')) return 'Видео'
  if (kinds.includes('doc')) return 'Файл'
  if (kinds.length) return 'Вложение'
  return 'Пусто'
}

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
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 pt-4 pb-3 safe-top">
        <h1 className="numeral text-[28px] mb-3">Диалоги</h1>
        <div
          className="inline-flex p-1 pill text-[13px]"
          style={{ background: 'var(--sunken)' }}
          role="tablist"
        >
          {[
            { label: 'Открытые', value: false },
            { label: 'Закрытые', value: true },
          ].map((tab) => (
            <button
              key={tab.label}
              role="tab"
              aria-selected={showClosed === tab.value}
              onClick={() => onToggleClosed(tab.value)}
              className="pill px-4 py-1.5 font-medium transition-colors"
              style={
                showClosed === tab.value
                  ? { background: 'var(--surface)', boxShadow: 'var(--shadow)' }
                  : { color: 'var(--muted)' }
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto quiet-scroll px-3 pb-4">
        {dialogs.length === 0 && (
          <p className="px-3 py-10 text-center text-[14px]" style={{ color: 'var(--muted)' }}>
            {showClosed ? 'Закрытых обращений пока нет' : 'Все обращения разобраны'}
          </p>
        )}

        <div className="flex flex-col gap-1.5">
          {dialogs.map((dialog, index) => {
            const active = dialog.id === activeId
            return (
              <motion.button
                key={dialog.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  type: 'spring',
                  stiffness: 420,
                  damping: 34,
                  delay: Math.min(index * 0.025, 0.3),
                }}
                onClick={() => onPick(dialog.id)}
                className="w-full text-left p-3 flex gap-3 items-center transition-shadow"
                style={{
                  background: active ? 'var(--surface)' : 'transparent',
                  borderRadius: 'var(--radius-inner)',
                  boxShadow: active ? 'var(--shadow-lift)' : 'none',
                }}
              >
                <Avatar name={dialog.user.name} src={dialog.user.photo_url} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="font-semibold text-[15px] truncate flex-1">
                      {dialog.user.name}
                    </span>
                    <span className="text-[12px] shrink-0" style={{ color: 'var(--muted)' }}>
                      {waiting(dialog.waiting_seconds)}
                    </span>
                  </span>
                  <span className="flex items-center gap-2 mt-0.5">
                    <span
                      className="text-[13px] truncate flex-1"
                      style={{ color: 'var(--muted)' }}
                    >
                      {previewText(dialog)}
                    </span>
                    {dialog.unread > 0 && (
                      <span
                        className="pill min-w-[20px] h-5 px-1.5 grid place-items-center text-[11px] font-semibold shrink-0"
                        style={{ background: '#FF6B4A', color: '#fff' }}
                      >
                        {dialog.unread}
                      </span>
                    )}
                  </span>
                </span>
              </motion.button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

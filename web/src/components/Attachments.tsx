import { useState } from 'react'
import type { Attachment } from '../api'
import { fileSize, voiceLength } from '../format'

const source = (messageId: number, index: number) => `/api/attachments/${messageId}/${index}`

function Photo({ messageId, index, onOpen }: { messageId: number; index: number; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="block overflow-hidden"
      style={{ borderRadius: 'var(--radius-inner)' }}
    >
      <img
        src={source(messageId, index)}
        alt="Вложение"
        loading="lazy"
        className="max-h-64 w-auto object-cover"
      />
    </button>
  )
}

function Voice({ item, messageId, index }: { item: Attachment; messageId: number; index: number }) {
  // Форма волны из ВК рисуется столбиками: так голосовое видно как голосовое,
  // а не как безымянный аудиофайл.
  const bars = (item.waveform ?? []).filter((_, i) => i % 3 === 0).slice(0, 40)
  const peak = Math.max(1, ...bars)
  return (
    <div
      className="flex items-center gap-3 p-3 pr-4"
      style={{ background: 'var(--sunken)', borderRadius: 'var(--radius-inner)' }}
    >
      <audio controls preload="none" src={source(messageId, index)} className="h-9" />
      {bars.length > 0 && (
        <div className="hidden sm:flex items-end gap-[2px] h-7" aria-hidden>
          {bars.map((value, i) => (
            <span
              key={i}
              className="w-[2px] rounded-full"
              style={{
                height: `${Math.max(12, (value / peak) * 100)}%`,
                background: 'var(--muted)',
                opacity: 0.55,
              }}
            />
          ))}
        </div>
      )}
      <span className="text-[13px] tabular-nums" style={{ color: 'var(--muted)' }}>
        {voiceLength(item.duration)}
      </span>
    </div>
  )
}

function Doc({ item, messageId, index }: { item: Attachment; messageId: number; index: number }) {
  return (
    <a
      href={source(messageId, index)}
      download
      className="flex items-center gap-3 p-3 pr-4 transition-transform active:scale-[.98]"
      style={{ background: 'var(--sunken)', borderRadius: 'var(--radius-inner)' }}
    >
      <span
        className="grid place-items-center w-10 h-10 pill text-[11px] font-semibold uppercase"
        style={{ background: 'var(--surface)', color: 'var(--muted)' }}
      >
        {(item.ext || 'file').slice(0, 4)}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[14px] font-medium">{item.title || 'Файл'}</span>
        <span className="block text-[12px]" style={{ color: 'var(--muted)' }}>
          {fileSize(item.size) || 'Скачать'}
        </span>
      </span>
    </a>
  )
}

function Video({ item }: { item: Attachment }) {
  // VK API не отдаёт прямой файл видео — только страницу с плеером.
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noreferrer"
      className="block relative overflow-hidden"
      style={{ borderRadius: 'var(--radius-inner)', background: 'var(--sunken)' }}
    >
      {item.preview ? (
        <img src={item.preview} alt="" className="max-h-56 w-auto object-cover" loading="lazy" />
      ) : (
        <div className="px-4 py-6 text-[14px]">{item.title || 'Видео'}</div>
      )}
      <span
        className="absolute inset-0 grid place-items-center text-white text-2xl"
        style={{ background: 'rgba(0,0,0,.28)' }}
      >
        ▶
      </span>
    </a>
  )
}

export function Attachments({
  items,
  messageId,
}: {
  items: Attachment[]
  messageId: number
}) {
  const [lightbox, setLightbox] = useState<string | null>(null)
  if (!items.length) return null

  return (
    <>
      <div className="flex flex-col gap-2 mt-2">
        {items.map((item, index) => {
          if (item.type === 'photo' || item.type === 'sticker') {
            return (
              <Photo
                key={index}
                messageId={messageId}
                index={index}
                onOpen={() => setLightbox(source(messageId, index))}
              />
            )
          }
          if (item.type === 'audio_message')
            return <Voice key={index} item={item} messageId={messageId} index={index} />
          if (item.type === 'video') return <Video key={index} item={item} />
          if (item.type === 'geo')
            return (
              <a
                key={index}
                href={`https://yandex.ru/maps/?pt=${item.lon},${item.lat}&z=16`}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-2 text-[14px]"
                style={{ background: 'var(--sunken)', borderRadius: 'var(--radius-inner)' }}
              >
                📍 {item.title || 'Геопозиция'}
              </a>
            )
          if (item.type === 'doc')
            return <Doc key={index} item={item} messageId={messageId} index={index} />
          return (
            <span key={index} className="text-[13px]" style={{ color: 'var(--muted)' }}>
              Вложение{item.raw_type ? ` «${item.raw_type}»` : ''} — откройте в ВК
            </span>
          )
        })}
      </div>

      {lightbox && (
        <div
          className="fixed inset-0 z-50 grid place-items-center p-6"
          style={{ background: 'rgba(0,0,0,.82)' }}
          onClick={() => setLightbox(null)}
          role="presentation"
        >
          <img src={lightbox} alt="" className="max-w-full max-h-full object-contain" />
        </div>
      )}
    </>
  )
}

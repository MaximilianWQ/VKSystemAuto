/** Мелкие примитивы интерфейса.

   Вынесены отдельно, чтобы плотность и отступы задавались в одном месте:
   в рабочем инструменте разнобой в высоте строк заметнее, чем в витрине. */

import type { ReactNode } from 'react'
import { initials } from '../format'

export type Status = 'open' | 'in_progress' | 'closed'

export const STATUS_LABEL: Record<Status, string> = {
  open: 'ждёт',
  in_progress: 'в работе',
  closed: 'закрыто',
}

const STATUS_COLOR: Record<Status, { dot: string; fg: string; bg: string }> = {
  open: { dot: 'var(--wait)', fg: 'var(--wait)', bg: 'var(--wait-bg)' },
  in_progress: { dot: 'var(--work)', fg: 'var(--work)', bg: 'var(--work-bg)' },
  closed: { dot: 'var(--done)', fg: 'var(--done)', bg: 'var(--done-bg)' },
}

export function StatusDot({ status }: { status: Status }) {
  return (
    <span
      className="inline-block w-[7px] h-[7px] rounded-full shrink-0"
      style={{ background: STATUS_COLOR[status].dot }}
      aria-label={STATUS_LABEL[status]}
    />
  )
}

export function Tag({
  status,
  children,
}: {
  status: Status
  children?: ReactNode
}) {
  const color = STATUS_COLOR[status]
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-[3px] text-[12px] font-medium rounded-md whitespace-nowrap"
      style={{ background: color.bg, color: color.fg }}
    >
      {children ?? STATUS_LABEL[status]}
    </span>
  )
}

export function Button({
  children,
  onClick,
  variant = 'quiet',
  disabled,
  title,
  full,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'quiet' | 'danger'
  disabled?: boolean
  title?: string
  full?: boolean
}) {
  const style =
    variant === 'primary'
      ? { background: 'var(--ink)', color: 'var(--bg)', borderColor: 'var(--ink)' }
      : variant === 'danger'
        ? { background: 'var(--surface)', color: 'var(--alarm)', borderColor: 'var(--line)' }
        : { background: 'var(--surface)', color: 'var(--ink)', borderColor: 'var(--line)' }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`h-8 px-3 text-[13px] font-medium border transition-[background,opacity] disabled:opacity-40 disabled:cursor-not-allowed active:translate-y-[0.5px] ${full ? 'w-full' : ''}`}
      style={{ ...style, borderRadius: 'var(--radius)' }}
    >
      {children}
    </button>
  )
}

export function Avatar({ name, src, size = 30 }: { name: string; src?: string; size?: number }) {
  return (
    <span
      className="shrink-0 overflow-hidden grid place-items-center font-medium select-none rounded-full"
      style={{
        width: size,
        height: size,
        background: 'var(--panel)',
        color: 'var(--muted)',
        fontSize: Math.round(size * 0.36),
        border: '1px solid var(--line)',
      }}
    >
      {src ? <img src={src} alt="" className="w-full h-full object-cover" loading="lazy" /> : initials(name)}
    </span>
  )
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-lg)',
      }}
    >
      {children}
    </div>
  )
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="h-full grid place-items-center px-6 text-center">
      <div>
        <div className="text-[14px] font-medium">{title}</div>
        {hint && (
          <div className="mt-1 text-[13px]" style={{ color: 'var(--muted)' }}>
            {hint}
          </div>
        )}
      </div>
    </div>
  )
}

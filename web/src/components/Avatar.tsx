import { initials } from '../format'

export function Avatar({ name, src, size = 44 }: { name: string; src?: string; size?: number }) {
  return (
    <div
      className="shrink-0 overflow-hidden pill grid place-items-center font-medium select-none"
      style={{
        width: size,
        height: size,
        background: 'var(--sunken)',
        color: 'var(--muted)',
        fontSize: size * 0.34,
      }}
    >
      {src ? (
        <img src={src} alt="" className="w-full h-full object-cover" loading="lazy" />
      ) : (
        initials(name)
      )}
    </div>
  )
}

import type { ReactNode } from 'react'

export type Tab = 'dialogs' | 'faq' | 'stats' | 'settings'

const TABS: { key: Tab; label: string; glyph: string }[] = [
  { key: 'dialogs', label: 'Диалоги', glyph: '💬' },
  { key: 'faq', label: 'Вопросы', glyph: '📖' },
  { key: 'stats', label: 'Статистика', glyph: '📊' },
  { key: 'settings', label: 'Настройки', glyph: '⚙︎' },
]

export function Shell({
  tab,
  onTab,
  connected,
  unread,
  children,
}: {
  tab: Tab
  onTab: (tab: Tab) => void
  connected: boolean
  unread: number
  children: ReactNode
}) {
  return (
    <div className="h-full flex flex-col md:flex-row" style={{ background: 'var(--bg)' }}>
      {/* Боковая панель на десктопе, нижняя — на телефоне. */}
      <nav
        className="hidden md:flex flex-col gap-1 w-56 shrink-0 p-3 border-r hairline safe-top"
      >
        <div className="px-3 py-4 flex items-center gap-2">
          <span className="font-semibold text-[15px]">Поддержка</span>
          <span
            className="w-2 h-2 pill"
            title={connected ? 'Связь есть' : 'Нет связи'}
            style={{ background: connected ? '#6FCF62' : '#D8412F' }}
          />
        </div>
        {TABS.map((item) => (
          <button
            key={item.key}
            onClick={() => onTab(item.key)}
            className="flex items-center gap-3 px-3 py-2.5 text-[14px] font-medium transition-colors"
            style={{
              borderRadius: 14,
              background: tab === item.key ? 'var(--surface)' : 'transparent',
              boxShadow: tab === item.key ? 'var(--shadow)' : 'none',
              color: tab === item.key ? 'var(--ink)' : 'var(--muted)',
            }}
          >
            <span aria-hidden>{item.glyph}</span>
            {item.label}
            {item.key === 'dialogs' && unread > 0 && (
              <span
                className="ml-auto pill min-w-[20px] h-5 px-1.5 grid place-items-center text-[11px] font-semibold"
                style={{ background: '#FF6B4A', color: '#fff' }}
              >
                {unread}
              </span>
            )}
          </button>
        ))}
      </nav>

      <main className="flex-1 min-h-0 min-w-0">{children}</main>

      <nav
        className="md:hidden flex border-t hairline safe-bottom"
        style={{ background: 'var(--surface)' }}
      >
        {TABS.map((item) => (
          <button
            key={item.key}
            onClick={() => onTab(item.key)}
            className="flex-1 py-2.5 flex flex-col items-center gap-0.5 text-[11px] relative"
            style={{ color: tab === item.key ? 'var(--ink)' : 'var(--muted)' }}
          >
            <span className="text-[17px]" aria-hidden>
              {item.glyph}
            </span>
            {item.label}
            {item.key === 'dialogs' && unread > 0 && (
              <span
                className="absolute top-1 right-[28%] pill min-w-[16px] h-4 px-1 grid place-items-center text-[10px] font-semibold"
                style={{ background: '#FF6B4A', color: '#fff' }}
              >
                {unread}
              </span>
            )}
          </button>
        ))}
      </nav>
    </div>
  )
}

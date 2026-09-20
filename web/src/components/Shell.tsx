import type { ReactNode } from 'react'

export type Tab = 'dialogs' | 'faq' | 'stats' | 'settings'

const TABS: { key: Tab; label: string; short: string }[] = [
  { key: 'dialogs', label: 'Очередь', short: 'Очередь' },
  { key: 'faq', label: 'Вопросы', short: 'Вопросы' },
  { key: 'stats', label: 'Статистика', short: 'Отчёт' },
  { key: 'settings', label: 'Настройки', short: 'Ещё' },
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
      <nav
        className="hidden md:flex flex-col w-[180px] shrink-0 px-2 py-2 safe-t"
        style={{ background: 'var(--panel)', borderRight: '1px solid var(--line)' }}
      >
        <div className="px-2 py-2 flex items-center gap-2">
          <span className="text-[13px] font-semibold">Поддержка</span>
          <span
            className="w-[7px] h-[7px] rounded-full"
            title={connected ? 'Связь есть' : 'Нет связи'}
            style={{ background: connected ? 'var(--work)' : 'var(--alarm)' }}
          />
        </div>

        <div className="mt-1 flex flex-col gap-[2px]">
          {TABS.map((item) => (
            <button
              key={item.key}
              onClick={() => onTab(item.key)}
              className="flex items-center gap-2 px-2 h-8 text-[13px] font-medium rounded-lg"
              style={{
                background: tab === item.key ? 'var(--surface)' : 'transparent',
                color: tab === item.key ? 'var(--ink)' : 'var(--muted)',
                border: `1px solid ${tab === item.key ? 'var(--line)' : 'transparent'}`,
              }}
            >
              {item.label}
              {item.key === 'dialogs' && unread > 0 && (
                <span
                  className="num ml-auto min-w-[17px] h-[17px] px-1 grid place-items-center text-[11px] font-semibold rounded"
                  style={{ background: 'var(--ink)', color: 'var(--bg)' }}
                >
                  {unread}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="mt-auto px-2 pb-1 text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>
          <div className="flex items-center gap-1.5">
            <kbd>↑</kbd>
            <kbd>↓</kbd>
            <span>по очереди</span>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <kbd>Esc</kbd>
            <span>к очереди</span>
          </div>
        </div>
      </nav>

      <main className="flex-1 min-h-0 min-w-0">{children}</main>

      <nav
        className="md:hidden flex safe-b shrink-0"
        style={{ background: 'var(--panel)', borderTop: '1px solid var(--line)' }}
      >
        {TABS.map((item) => (
          <button
            key={item.key}
            onClick={() => onTab(item.key)}
            className="flex-1 py-2 text-[11px] font-medium relative"
            style={{ color: tab === item.key ? 'var(--ink)' : 'var(--muted)' }}
          >
            {item.short}
            {item.key === 'dialogs' && unread > 0 && (
              <span
                className="num absolute top-1 right-[22%] min-w-[15px] h-[15px] px-1 grid place-items-center text-[10px] font-semibold rounded"
                style={{ background: 'var(--ink)', color: 'var(--bg)' }}
              >
                {unread}
              </span>
            )}
            {tab === item.key && (
              <span
                className="absolute left-1/2 -translate-x-1/2 bottom-0 w-6 h-[2px]"
                style={{ background: 'var(--ink)' }}
              />
            )}
          </button>
        ))}
      </nav>
    </div>
  )
}

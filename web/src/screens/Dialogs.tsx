import { useEffect, useState } from 'react'
import { api, type Dialog, type Message } from '../api'
import { Chat } from '../components/Chat'
import { DialogList } from '../components/DialogList'
import { Empty } from '../components/ui'

export function Dialogs({
  dialogs,
  incoming,
  activeId,
  onPick,
  reload,
  showClosed,
  onToggleClosed,
}: {
  dialogs: Dialog[]
  incoming: { ticketId: number; message: Message } | null
  activeId: number | null
  onPick: (id: number | null) => void
  reload: () => void
  showClosed: boolean
  onToggleClosed: (value: boolean) => void
}) {
  // На телефоне очередь и переписка — разные экраны, на десктопе видны разом.
  const [narrow, setNarrow] = useState(() => window.innerWidth < 900)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 900)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (activeId && !dialogs.some((dialog) => dialog.id === activeId)) onPick(null)
  }, [dialogs, activeId, onPick])

  const forChat = incoming && incoming.ticketId === activeId ? incoming.message : null

  const list = (
    <DialogList
      dialogs={dialogs}
      activeId={activeId}
      onPick={onPick}
      showClosed={showClosed}
      onToggleClosed={onToggleClosed}
    />
  )

  if (narrow) {
    return activeId ? (
      <Chat ticketId={activeId} incoming={forChat} onChanged={reload} onBack={() => onPick(null)} />
    ) : (
      list
    )
  }

  return (
    <div className="h-full flex min-h-0">
      <div className="w-[320px] shrink-0 min-h-0" style={{ borderRight: '1px solid var(--line)' }}>
        {list}
      </div>
      <div className="flex-1 min-w-0 min-h-0">
        {activeId ? (
          <Chat ticketId={activeId} incoming={forChat} onChanged={reload} />
        ) : (
          <Empty
            title="Выберите обращение"
            hint="Стрелки ↑ ↓ переключают, Esc возвращает к очереди"
          />
        )}
      </div>
    </div>
  )
}

export async function fetchDialogs(showClosed: boolean): Promise<Dialog[]> {
  return api.get<Dialog[]>(`/api/dialogs?status=${showClosed ? 'closed' : 'open'}`)
}

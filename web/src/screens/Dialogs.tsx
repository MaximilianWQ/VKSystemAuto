import { useCallback, useEffect, useState } from 'react'
import { api, type Dialog } from '../api'
import { Chat } from '../components/Chat'
import { DialogList } from '../components/DialogList'

export function Dialogs({
  dialogs,
  reload,
  showClosed,
  onToggleClosed,
}: {
  dialogs: Dialog[]
  reload: () => void
  showClosed: boolean
  onToggleClosed: (value: boolean) => void
}) {
  const [activeId, setActiveId] = useState<number | null>(null)

  // На телефоне список и переписка — разные экраны, на десктопе видны разом.
  const [narrow, setNarrow] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (activeId && !dialogs.some((dialog) => dialog.id === activeId)) setActiveId(null)
  }, [dialogs, activeId])

  const pick = useCallback((id: number) => setActiveId(id), [])

  const list = (
    <DialogList
      dialogs={dialogs}
      activeId={activeId}
      onPick={pick}
      showClosed={showClosed}
      onToggleClosed={onToggleClosed}
    />
  )

  if (narrow) {
    return activeId ? (
      <Chat ticketId={activeId} onChanged={reload} onBack={() => setActiveId(null)} />
    ) : (
      list
    )
  }

  return (
    <div className="h-full flex min-h-0">
      <div className="w-[360px] shrink-0 border-r hairline min-h-0">{list}</div>
      <div className="flex-1 min-w-0 min-h-0">
        {activeId ? (
          <Chat ticketId={activeId} onChanged={reload} />
        ) : (
          <div
            className="h-full grid place-items-center text-[14px]"
            style={{ color: 'var(--muted)' }}
          >
            Выберите диалог слева
          </div>
        )}
      </div>
    </div>
  )
}

export async function fetchDialogs(showClosed: boolean): Promise<Dialog[]> {
  return api.get<Dialog[]>(`/api/dialogs?status=${showClosed ? 'closed' : 'open'}`)
}

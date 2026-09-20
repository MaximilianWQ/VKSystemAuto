import { useCallback, useEffect, useState } from 'react'
import { api, setUnauthorizedHandler, type Dialog, type Message } from './api'
import { refreshSubscription } from './push'
import { useSocket } from './useSocket'
import { Shell, type Tab } from './components/Shell'
import { Dialogs, fetchDialogs } from './screens/Dialogs'
import { Faq } from './screens/Faq'
import { Login } from './screens/Login'
import { Settings } from './screens/Settings'
import { Setup } from './screens/Setup'
import { Stats } from './screens/Stats'

type Auth = 'unknown' | 'in' | 'out'
type Incoming = { ticketId: number; message: Message }

export default function App() {
  const setupToken = new URLSearchParams(location.search).get('token')
  const isSetup = location.pathname === '/setup' && !!setupToken

  const [auth, setAuth] = useState<Auth>('unknown')
  const [tab, setTab] = useState<Tab>('dialogs')
  const [dialogs, setDialogs] = useState<Dialog[]>([])
  const [showClosed, setShowClosed] = useState(false)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [incoming, setIncoming] = useState<Incoming | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth('out'))
  }, [])

  useEffect(() => {
    if (isSetup) return
    api
      .get('/api/auth/me')
      .then(() => setAuth('in'))
      .catch(() => setAuth('out'))
  }, [isSetup])

  const reload = useCallback(() => {
    if (auth !== 'in') return
    fetchDialogs(showClosed)
      .then(setDialogs)
      .catch(() => undefined)
  }, [auth, showClosed])

  useEffect(reload, [reload])

  const connected = useSocket(
    useCallback(
      (event) => {
        // Сообщение прокидываем в открытый чат, чтобы оно появилось сразу.
        if (event.type === 'message' && event.message && event.ticket_id) {
          setIncoming({ ticketId: event.ticket_id, message: event.message })
        }
        reload()
      },
      [reload],
    ),
    auth === 'in',
  )

  useEffect(() => {
    if (auth === 'in') void refreshSubscription()
  }, [auth])

  // Стрелки листают очередь, Esc закрывает переписку.
  useEffect(() => {
    if (auth !== 'in' || tab !== 'dialogs') return
    const onKey = (event: KeyboardEvent) => {
      const typing = ['INPUT', 'TEXTAREA'].includes(
        (event.target as HTMLElement)?.tagName ?? '',
      )
      if (event.key === 'Escape' && !typing) {
        setActiveId(null)
        return
      }
      if (typing || (event.key !== 'ArrowDown' && event.key !== 'ArrowUp')) return
      event.preventDefault()
      const index = dialogs.findIndex((dialog) => dialog.id === activeId)
      const next = event.key === 'ArrowDown' ? index + 1 : index - 1
      const target = dialogs[next < 0 ? 0 : Math.min(next, dialogs.length - 1)]
      if (target) setActiveId(target.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [auth, tab, dialogs, activeId])

  const enter = () => {
    history.replaceState(null, '', '/')
    setAuth('in')
  }

  if (isSetup) return <Setup token={setupToken} onDone={enter} />
  if (auth === 'unknown') return <div className="h-full" style={{ background: 'var(--bg)' }} />
  if (auth === 'out') return <Login onDone={enter} />

  const unread = dialogs.reduce((sum, dialog) => sum + dialog.unread, 0)

  return (
    <Shell tab={tab} onTab={setTab} connected={connected} unread={unread}>
      {tab === 'dialogs' && (
        <Dialogs
          dialogs={dialogs}
          incoming={incoming}
          activeId={activeId}
          onPick={setActiveId}
          reload={reload}
          showClosed={showClosed}
          onToggleClosed={setShowClosed}
        />
      )}
      {tab === 'faq' && <Faq />}
      {tab === 'stats' && <Stats />}
      {tab === 'settings' && <Settings onLoggedOut={() => setAuth('out')} />}
    </Shell>
  )
}

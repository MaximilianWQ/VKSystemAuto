import { useCallback, useEffect, useState } from 'react'
import { api, setUnauthorizedHandler, type Dialog } from './api'
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

export default function App() {
  const setupToken = new URLSearchParams(location.search).get('token')
  const isSetup = location.pathname === '/setup' && !!setupToken

  const [auth, setAuth] = useState<Auth>('unknown')
  const [tab, setTab] = useState<Tab>('dialogs')
  const [dialogs, setDialogs] = useState<Dialog[]>([])
  const [showClosed, setShowClosed] = useState(false)

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth('out'))
  }, [])

  // Проверяем сессию одним запросом, который и так нужен настройкам.
  useEffect(() => {
    if (isSetup) return
    api
      .get('/api/auth/me')
      .then(() => setAuth('in'))
      .catch(() => setAuth('out'))
  }, [isSetup])

  const reload = useCallback(() => {
    if (auth !== 'in') return
    fetchDialogs(showClosed).then(setDialogs).catch(() => undefined)
  }, [auth, showClosed])

  useEffect(reload, [reload])

  // Один хук на всё приложение: второй вызов открыл бы второе соединение.
  const connected = useSocket(
    useCallback(() => {
      reload()
    }, [reload]),
    auth === 'in',
  )

  useEffect(() => {
    if (auth === 'in') void refreshSubscription()
  }, [auth])

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

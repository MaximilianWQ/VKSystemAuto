import { useEffect, useState } from 'react'
import { api, type PasskeyInfo } from '../api'
import { logout } from '../auth'
import { currentSubscription, disablePush, enablePush, isStandalone, pushSupported } from '../push'
import { Button, Panel } from '../components/ui'

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-3" style={{ borderTop: '1px solid var(--line)' }}>
      {children}
    </div>
  )
}

function Head({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-3 text-[13px] font-semibold">{children}</div>
}

export function Settings({ onLoggedOut }: { onLoggedOut: () => void }) {
  const [keys, setKeys] = useState<PasskeyInfo[]>([])
  const [pushOn, setPushOn] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const standalone = isStandalone()
  const canPush = pushSupported() && standalone

  useEffect(() => {
    api.get<{ keys: PasskeyInfo[] }>('/api/auth/me').then((data) => setKeys(data.keys))
    currentSubscription().then((subscription) => setPushOn(!!subscription))
  }, [])

  const togglePush = async () => {
    setBusy(true)
    setNote('')
    try {
      if (pushOn) {
        await disablePush()
        setPushOn(false)
      } else {
        const result = await enablePush()
        if (result === 'ok') setPushOn(true)
        if (result === 'denied') setNote('Разрешение на уведомления не выдано')
        if (result === 'unsupported') setNote('Браузер не поддерживает пуши')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full scroll px-4 py-4 safe-t">
      <h1 className="text-[15px] font-semibold mb-3">Настройки</h1>

      <div className="max-w-xl flex flex-col gap-2.5">
        <Panel>
          <Head>Уведомления</Head>
          {!standalone ? (
            /* На iOS пуши приходят только установленному приложению, поэтому
               вместо бесполезного переключателя показываем, что сделать. */
            <Row>
              <div className="text-[13px] font-medium">Сначала установите приложение</div>
              <p className="mt-1 text-[12px] leading-relaxed" style={{ color: 'var(--muted)' }}>
                В Safari нажмите «Поделиться» → «На экран Домой», затем откройте дашборд
                с домашнего экрана. Пуши работают только так — это ограничение iOS,
                а не наша настройка.
              </p>
            </Row>
          ) : (
            <Row>
              <label className="flex items-center gap-2.5 text-[13px]">
                <input
                  type="checkbox"
                  checked={pushOn}
                  disabled={busy || !canPush}
                  onChange={togglePush}
                  className="w-4 h-4"
                />
                Присылать пуш о новых сообщениях
              </label>
              {note && (
                <p className="mt-2 text-[12px]" style={{ color: 'var(--alarm)' }}>
                  {note}
                </p>
              )}
            </Row>
          )}
        </Panel>

        <Panel>
          <Head>Ключи входа</Head>
          {keys.map((key) => (
            <Row key={key.id}>
              <div className="flex items-baseline gap-3">
                <span className="text-[13px] flex-1">{key.name}</span>
                <span className="num text-[12px]" style={{ color: 'var(--muted)' }}>
                  {key.last_used_at
                    ? `вход ${new Date(key.last_used_at).toLocaleDateString('ru-RU')}`
                    : 'не использовался'}
                </span>
              </div>
            </Row>
          ))}
          <Row>
            <p className="text-[12px] leading-relaxed" style={{ color: 'var(--muted)' }}>
              Ключ живёт на устройстве. Чтобы войти с другого телефона или компьютера,
              напишите боту слово «дашборд» — придёт одноразовая ссылка, и там появится
              отдельный ключ.
            </p>
          </Row>
        </Panel>

        <div>
          <Button
            onClick={async () => {
              await logout()
              onLoggedOut()
            }}
            variant="danger"
          >
            Выйти
          </Button>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { api, type PasskeyInfo } from '../api'
import { logout } from '../auth'
import { currentSubscription, disablePush, enablePush, isStandalone, pushSupported } from '../push'

function Row({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-3.5 border-b hairline last:border-0">{children}</div>
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
    <div className="h-full overflow-y-auto quiet-scroll px-4 py-5 safe-top">
      <h1 className="numeral text-[28px] mb-5">Настройки</h1>

      <div className="max-w-2xl flex flex-col gap-4">
        <section className="card overflow-hidden">
          <Row>
            <div className="font-semibold text-[15px]">Уведомления</div>
          </Row>

          {!standalone ? (
            /* На iOS пуши приходят только установленному приложению, поэтому
               вместо бесполезного переключателя показываем, что сделать. */
            <Row>
              <p className="text-[14px] mb-1">Сначала установите приложение</p>
              <p className="text-[13px]" style={{ color: 'var(--muted)' }}>
                В Safari нажмите «Поделиться» → «На экран Домой», затем откройте
                дашборд с домашнего экрана. Пуши работают только так — это
                ограничение iOS, не наша настройка.
              </p>
            </Row>
          ) : (
            <Row>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={pushOn}
                  disabled={busy || !canPush}
                  onChange={togglePush}
                  className="w-5 h-5"
                />
                <span className="text-[15px]">Присылать пуш о новых сообщениях</span>
              </label>
              {note && (
                <p className="mt-2 text-[13px]" style={{ color: '#D8412F' }}>
                  {note}
                </p>
              )}
            </Row>
          )}
        </section>

        <section className="card overflow-hidden">
          <Row>
            <div className="font-semibold text-[15px]">Ключи входа</div>
          </Row>
          {keys.map((key) => (
            <Row key={key.id}>
              <div className="flex items-baseline gap-3">
                <span className="text-[15px] flex-1">{key.name}</span>
                <span className="text-[12px]" style={{ color: 'var(--muted)' }}>
                  {key.last_used_at
                    ? `вход ${new Date(key.last_used_at).toLocaleDateString('ru-RU')}`
                    : 'не использовался'}
                </span>
              </div>
            </Row>
          ))}
          <Row>
            <p className="text-[13px]" style={{ color: 'var(--muted)' }}>
              Чтобы добавить ключ на другом устройстве, напишите боту слово «дашборд» —
              он пришлёт одноразовую ссылку.
            </p>
          </Row>
        </section>

        <button
          onClick={async () => {
            await logout()
            onLoggedOut()
          }}
          className="card px-4 py-3.5 text-left text-[15px] font-medium"
          style={{ color: '#D8412F' }}
        >
          Выйти
        </button>
      </div>
    </div>
  )
}

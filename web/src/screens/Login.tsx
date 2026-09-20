import { useEffect, useState } from 'react'
import { ApiError } from '../api'
import { loginWithPasskey, passkeySupported } from '../auth'
import { Button, Panel } from '../components/ui'

export function Login({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const supported = passkeySupported()

  const enter = async () => {
    setBusy(true)
    setError('')
    setHint('')
    try {
      await loginWithPasskey()
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setHint(
          'На этом сервере ещё нет ни одного ключа. Напишите боту сообщества слово «дашборд» — придёт ссылка на регистрацию.',
        )
      } else if (e instanceof DOMException && e.name === 'NotAllowedError') {
        setError('Вход отменён')
      } else if (e instanceof ApiError && e.status === 400) {
        setHint(
          'Ключ не подошёл. Если вы входите с нового устройства, ключа на нём ещё нет — напишите боту «дашборд» и зарегистрируйте новый.',
        )
      } else {
        setError(e instanceof Error ? e.message : 'Не получилось войти')
      }
    } finally {
      setBusy(false)
    }
  }

  // Вход — единственное действие на экране, поэтому предлагаем его сразу.
  useEffect(() => {
    if (!supported) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && !busy) void enter()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, supported])

  return (
    <div className="h-full grid place-items-center px-4" style={{ background: 'var(--bg)' }}>
      <Panel className="w-full max-w-[360px] p-6">
        <h1 className="text-[16px] font-semibold">Поддержка</h1>
        <p className="mt-1 text-[13px]" style={{ color: 'var(--muted)' }}>
          Вход по ключу устройства. Паролей нет.
        </p>

        <div className="mt-5">
          {!supported ? (
            <p className="text-[13px]" style={{ color: 'var(--alarm)' }}>
              Этот браузер не поддерживает passkey. Откройте дашборд в Safari или Chrome.
            </p>
          ) : (
            <Button onClick={enter} disabled={busy} variant="primary" full>
              {busy ? 'Проверяем…' : 'Войти по passkey'}
            </Button>
          )}
        </div>

        {hint && (
          <p
            className="mt-4 text-[12px] px-3 py-2.5 leading-relaxed"
            style={{ background: 'var(--panel)', borderRadius: 'var(--radius)' }}
          >
            {hint}
          </p>
        )}
        {error && (
          <p className="mt-3 text-[12px]" style={{ color: 'var(--alarm)' }}>
            {error}
          </p>
        )}
      </Panel>
    </div>
  )
}

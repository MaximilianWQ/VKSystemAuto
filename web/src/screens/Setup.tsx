import { useState } from 'react'
import { ApiError } from '../api'
import { passkeySupported, registerPasskey } from '../auth'
import { Button, Panel } from '../components/ui'

const defaultName = () => {
  const agent = navigator.userAgent
  if (/iPhone/.test(agent)) return 'iPhone'
  if (/iPad/.test(agent)) return 'iPad'
  if (/Android/.test(agent)) return 'Телефон'
  if (/Macintosh/.test(agent)) return 'Mac'
  if (/Windows/.test(agent)) return 'Windows'
  return 'Устройство'
}

export function Setup({ token, onDone }: { token: string; onDone: () => void }) {
  const [name, setName] = useState(defaultName)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const create = async () => {
    setBusy(true)
    setError('')
    try {
      await registerPasskey(token, name.trim() || defaultName())
      onDone()
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setError('Ссылка уже использована или истекла. Напишите боту «дашборд» ещё раз.')
      } else if (e instanceof DOMException && e.name === 'NotAllowedError') {
        setError('Создание ключа отменено')
      } else {
        setError(e instanceof Error ? e.message : 'Не получилось создать ключ')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full grid place-items-center px-4" style={{ background: 'var(--bg)' }}>
      <Panel className="w-full max-w-[360px] p-6">
        <h1 className="text-[16px] font-semibold">Новый ключ</h1>
        <p className="mt-1 text-[13px]" style={{ color: 'var(--muted)' }}>
          Ключ останется на этом устройстве. Ссылка работает один раз.
        </p>

        <label className="block mt-5 mb-1.5 text-[12px]" style={{ color: 'var(--muted)' }}>
          Название устройства
        </label>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !busy) void create()
          }}
          className="w-full h-9 px-3 outline-none text-[14px]"
          style={{
            background: 'var(--bg)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius)',
            color: 'var(--ink)',
          }}
        />

        <div className="mt-4">
          {!passkeySupported() ? (
            <p className="text-[13px]" style={{ color: 'var(--alarm)' }}>
              Этот браузер не поддерживает passkey.
            </p>
          ) : (
            <Button onClick={create} disabled={busy} variant="primary" full>
              {busy ? 'Создаём…' : 'Создать ключ и войти'}
            </Button>
          )}
        </div>

        {error && (
          <p className="mt-3 text-[12px]" style={{ color: 'var(--alarm)' }}>
            {error}
          </p>
        )}
      </Panel>
    </div>
  )
}

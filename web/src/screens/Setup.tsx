import { useState } from 'react'
import { motion } from 'motion/react'
import { ApiError } from '../api'
import { passkeySupported, registerPasskey } from '../auth'

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
    <div className="h-full grid place-items-center p-6" style={{ background: 'var(--bg)' }}>
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 340, damping: 30 }}
        className="card w-full max-w-sm p-8"
      >
        <div
          className="mx-auto mb-6 w-16 h-16 pill grid place-items-center text-2xl"
          style={{ background: 'linear-gradient(145deg,#B9A7FF,#8EC5FF)' }}
          aria-hidden
        >
          ✳︎
        </div>
        <h1 className="numeral text-[24px] mb-2 text-center">Новый ключ</h1>
        <p className="text-[14px] mb-6 text-center" style={{ color: 'var(--muted)' }}>
          Ключ останется на этом устройстве. Ссылка работает один раз.
        </p>

        <label className="block text-[13px] mb-2" style={{ color: 'var(--muted)' }}>
          Название устройства
        </label>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="w-full h-11 px-4 mb-5 outline-none text-[15px]"
          style={{
            background: 'var(--sunken)',
            borderRadius: 'var(--radius-inner)',
            color: 'var(--ink)',
          }}
        />

        {!passkeySupported() ? (
          <p className="text-[14px] text-center" style={{ color: '#D8412F' }}>
            Этот браузер не поддерживает passkey.
          </p>
        ) : (
          <button
            onClick={create}
            disabled={busy}
            className="w-full pill h-12 font-medium text-[15px] transition-transform active:scale-[.97] disabled:opacity-50"
            style={{ background: 'var(--ink)', color: 'var(--bg)' }}
          >
            {busy ? 'Создаём…' : 'Создать ключ и войти'}
          </button>
        )}

        {error && (
          <p className="mt-4 text-[13px] text-center" style={{ color: '#D8412F' }}>
            {error}
          </p>
        )}
      </motion.div>
    </div>
  )
}

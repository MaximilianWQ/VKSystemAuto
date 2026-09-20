import { useState } from 'react'
import { motion } from 'motion/react'
import { ApiError } from '../api'
import { loginWithPasskey, passkeySupported } from '../auth'

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
        setHint('Напишите боту сообщества слово «дашборд» — он пришлёт ссылку для входа.')
      } else if (e instanceof DOMException && e.name === 'NotAllowedError') {
        setError('Вход отменён')
      } else {
        setError(e instanceof Error ? e.message : 'Не получилось войти')
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
        className="card w-full max-w-sm p-8 text-center"
      >
        <div
          className="mx-auto mb-6 w-16 h-16 pill grid place-items-center text-2xl"
          style={{ background: 'linear-gradient(145deg,#6FCF62,#C8F169)' }}
          aria-hidden
        >
          🔑
        </div>
        <h1 className="numeral text-[26px] mb-2">Поддержка</h1>
        <p className="text-[14px] mb-7" style={{ color: 'var(--muted)' }}>
          Вход по ключу устройства. Паролей нет.
        </p>

        {!supported ? (
          <p className="text-[14px]" style={{ color: '#D8412F' }}>
            Этот браузер не поддерживает passkey. Откройте дашборд в Safari или Chrome.
          </p>
        ) : (
          <button
            onClick={enter}
            disabled={busy}
            className="w-full pill h-12 font-medium text-[15px] transition-transform active:scale-[.97] disabled:opacity-50"
            style={{ background: 'var(--ink)', color: 'var(--bg)' }}
          >
            {busy ? 'Проверяем…' : 'Войти по passkey'}
          </button>
        )}

        {hint && (
          <p
            className="mt-5 text-[13px] px-4 py-3 text-left"
            style={{ background: 'var(--sunken)', borderRadius: 'var(--radius-inner)' }}
          >
            {hint}
          </p>
        )}
        {error && (
          <p className="mt-4 text-[13px]" style={{ color: '#D8412F' }}>
            {error}
          </p>
        )}
      </motion.div>
    </div>
  )
}

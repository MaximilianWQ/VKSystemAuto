import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { api, ApiError } from '../api'

type Topic = {
  id: number
  title: string
  answer: string
  position: number
  is_active: boolean
}

const MAX_TITLE = 200

function Editor({
  initial,
  busy,
  onSave,
  onCancel,
}: {
  initial: { title: string; answer: string }
  busy: boolean
  onSave: (value: { title: string; answer: string }) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(initial.title)
  const [answer, setAnswer] = useState(initial.answer)
  const tooLong = title.length > MAX_TITLE

  return (
    <div className="flex flex-col gap-3">
      <div>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Тема — то, что увидит клиент на кнопке"
          className="w-full h-11 px-4 outline-none text-[15px]"
          style={{
            background: 'var(--sunken)',
            borderRadius: 'var(--radius-inner)',
            color: 'var(--ink)',
          }}
        />
        <div
          className="mt-1 text-[12px] text-right tabular-nums"
          style={{ color: tooLong ? '#D8412F' : 'var(--muted)' }}
        >
          {title.length} / {MAX_TITLE}
        </div>
      </div>
      <textarea
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder="Ответ, который бот пришлёт в сообщении"
        rows={4}
        className="w-full p-4 outline-none resize-y text-[15px]"
        style={{
          background: 'var(--sunken)',
          borderRadius: 'var(--radius-inner)',
          color: 'var(--ink)',
        }}
      />
      <div className="flex gap-2">
        <button
          onClick={() => onSave({ title: title.trim(), answer: answer.trim() })}
          disabled={busy || tooLong || !title.trim() || !answer.trim()}
          className="pill px-5 h-10 text-[14px] font-medium transition-transform active:scale-95 disabled:opacity-40"
          style={{ background: 'var(--ink)', color: 'var(--bg)' }}
        >
          Сохранить
        </button>
        <button
          onClick={onCancel}
          className="pill px-5 h-10 text-[14px]"
          style={{ background: 'var(--sunken)' }}
        >
          Отмена
        </button>
      </div>
    </div>
  )
}

export function Faq() {
  const [topics, setTopics] = useState<Topic[]>([])
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = () => api.get<Topic[]>('/api/faq').then(setTopics)

  useEffect(() => {
    load().catch((e) => setError(e.message))
  }, [])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await action()
      await load()
      setEditing(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.detail || e.message : 'Не получилось')
    } finally {
      setBusy(false)
    }
  }

  const move = (index: number, delta: number) => {
    const next = [...topics]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    setTopics(next)
    void run(() => api.post('/api/faq/reorder', { ids: next.map((t) => t.id) }))
  }

  return (
    <div className="h-full overflow-y-auto quiet-scroll px-4 py-5 safe-top">
      <div className="max-w-2xl">
        <h1 className="numeral text-[28px] mb-2">Частые вопросы</h1>
        <p className="text-[14px] mb-5" style={{ color: 'var(--muted)' }}>
          Первые восемь включённых тем бот показывает кнопками. Порядок здесь —
          порядок в боте.
        </p>

        {error && (
          <p className="mb-4 text-[13px]" style={{ color: '#D8412F' }}>
            {error}
          </p>
        )}

        <div className="flex flex-col gap-2.5">
          <AnimatePresence initial={false}>
            {topics.map((topic, index) => (
              <motion.div
                key={topic.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                className="card p-4"
                style={{ opacity: topic.is_active ? 1 : 0.55 }}
              >
                {editing === topic.id ? (
                  <Editor
                    initial={{ title: topic.title, answer: topic.answer }}
                    busy={busy}
                    onCancel={() => setEditing(null)}
                    onSave={(value) => run(() => api.patch(`/api/faq/${topic.id}`, value))}
                  />
                ) : (
                  <>
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold text-[15px]">{topic.title}</div>
                        <div
                          className="mt-1 text-[14px] whitespace-pre-wrap"
                          style={{ color: 'var(--muted)' }}
                        >
                          {topic.answer}
                        </div>
                      </div>
                      <div className="flex flex-col gap-1 shrink-0">
                        <button
                          onClick={() => move(index, -1)}
                          disabled={index === 0 || busy}
                          className="pill w-7 h-7 grid place-items-center text-[13px] disabled:opacity-25"
                          style={{ background: 'var(--sunken)' }}
                          aria-label="Выше"
                        >
                          ↑
                        </button>
                        <button
                          onClick={() => move(index, 1)}
                          disabled={index === topics.length - 1 || busy}
                          className="pill w-7 h-7 grid place-items-center text-[13px] disabled:opacity-25"
                          style={{ background: 'var(--sunken)' }}
                          aria-label="Ниже"
                        >
                          ↓
                        </button>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 mt-3">
                      <button
                        onClick={() => setEditing(topic.id)}
                        className="pill px-4 h-8 text-[13px]"
                        style={{ background: 'var(--sunken)' }}
                      >
                        Изменить
                      </button>
                      <button
                        onClick={() =>
                          run(() =>
                            api.patch(`/api/faq/${topic.id}`, { is_active: !topic.is_active }),
                          )
                        }
                        disabled={busy}
                        className="pill px-4 h-8 text-[13px]"
                        style={{ background: 'var(--sunken)' }}
                      >
                        {topic.is_active ? 'Скрыть от клиентов' : 'Показать клиентам'}
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Удалить тему «${topic.title}»?`)) {
                            void run(() => api.remove(`/api/faq/${topic.id}`))
                          }
                        }}
                        disabled={busy}
                        className="pill px-4 h-8 text-[13px]"
                        style={{ background: 'var(--sunken)', color: '#D8412F' }}
                      >
                        Удалить
                      </button>
                    </div>
                  </>
                )}
              </motion.div>
            ))}
          </AnimatePresence>

          {editing === 'new' ? (
            <div className="card p-4">
              <Editor
                initial={{ title: '', answer: '' }}
                busy={busy}
                onCancel={() => setEditing(null)}
                onSave={(value) => run(() => api.post('/api/faq', value))}
              />
            </div>
          ) : (
            <button
              onClick={() => setEditing('new')}
              className="card p-4 text-left text-[15px] font-medium"
            >
              + Добавить тему
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

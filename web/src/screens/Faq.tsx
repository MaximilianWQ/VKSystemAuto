import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Panel } from '../components/ui'

type Topic = {
  id: number
  title: string
  answer: string
  position: number
  is_active: boolean
}

const MAX_TITLE = 200
/** Столько тем помещается в клавиатуру ВК — дальше кнопки обрезаются. */
const VISIBLE_IN_BOT = 8

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
    <div className="flex flex-col gap-2">
      <div>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Тема — текст на кнопке у клиента"
          className="w-full h-9 px-3 outline-none text-[14px]"
          style={{
            background: 'var(--bg)',
            border: `1px solid ${tooLong ? 'var(--alarm)' : 'var(--line)'}`,
            borderRadius: 'var(--radius)',
            color: 'var(--ink)',
          }}
        />
        <div
          className="num mt-1 text-[11px] text-right"
          style={{ color: tooLong ? 'var(--alarm)' : 'var(--muted)' }}
        >
          {title.length} / {MAX_TITLE}
        </div>
      </div>
      <textarea
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder="Ответ, который бот пришлёт сообщением"
        rows={4}
        className="w-full p-3 outline-none resize-y text-[14px] scroll"
        style={{
          background: 'var(--bg)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius)',
          color: 'var(--ink)',
        }}
      />
      <div className="flex gap-2">
        <Button
          onClick={() => onSave({ title: title.trim(), answer: answer.trim() })}
          disabled={busy || tooLong || !title.trim() || !answer.trim()}
          variant="primary"
        >
          Сохранить
        </Button>
        <Button onClick={onCancel}>Отмена</Button>
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

  let activeSeen = 0

  return (
    <div className="h-full scroll px-4 py-4 safe-t">
      <div className="max-w-2xl">
        <h1 className="text-[15px] font-semibold">Частые вопросы</h1>
        <p className="mt-1 mb-3 text-[12px]" style={{ color: 'var(--muted)' }}>
          Первые {VISIBLE_IN_BOT} включённых тем бот показывает кнопками. Порядок здесь —
          порядок в боте.
        </p>

        {error && (
          <p className="mb-3 text-[12px]" style={{ color: 'var(--alarm)' }}>
            {error}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {topics.map((topic, index) => {
            if (topic.is_active) activeSeen += 1
            const beyondBot = topic.is_active && activeSeen > VISIBLE_IN_BOT
            return (
              <Panel key={topic.id} className="px-4 py-3">
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
                      <div className="min-w-0 flex-1" style={{ opacity: topic.is_active ? 1 : 0.5 }}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-[14px]">{topic.title}</span>
                          {!topic.is_active && (
                            <span
                              className="text-[11px] px-1.5 py-[1px] rounded"
                              style={{ background: 'var(--done-bg)', color: 'var(--done)' }}
                            >
                              скрыта
                            </span>
                          )}
                          {beyondBot && (
                            <span
                              className="text-[11px] px-1.5 py-[1px] rounded"
                              style={{ background: 'var(--wait-bg)', color: 'var(--wait)' }}
                              title="Не поместится в клавиатуру ВК"
                            >
                              вне кнопок
                            </span>
                          )}
                        </div>
                        <div
                          className="mt-1 text-[13px] whitespace-pre-wrap"
                          style={{ color: 'var(--muted)' }}
                        >
                          {topic.answer}
                        </div>
                      </div>

                      <div className="flex flex-col gap-1 shrink-0">
                        <button
                          onClick={() => move(index, -1)}
                          disabled={index === 0 || busy}
                          className="w-7 h-6 grid place-items-center text-[12px] disabled:opacity-25"
                          style={{ border: '1px solid var(--line)', borderRadius: 6 }}
                          aria-label="Выше"
                        >
                          ↑
                        </button>
                        <button
                          onClick={() => move(index, 1)}
                          disabled={index === topics.length - 1 || busy}
                          className="w-7 h-6 grid place-items-center text-[12px] disabled:opacity-25"
                          style={{ border: '1px solid var(--line)', borderRadius: 6 }}
                          aria-label="Ниже"
                        >
                          ↓
                        </button>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-2 mt-3">
                      <Button onClick={() => setEditing(topic.id)}>Изменить</Button>
                      <Button
                        onClick={() =>
                          run(() =>
                            api.patch(`/api/faq/${topic.id}`, { is_active: !topic.is_active }),
                          )
                        }
                        disabled={busy}
                      >
                        {topic.is_active ? 'Скрыть' : 'Показать'}
                      </Button>
                      <Button
                        onClick={() => {
                          if (confirm(`Удалить тему «${topic.title}»?`)) {
                            void run(() => api.remove(`/api/faq/${topic.id}`))
                          }
                        }}
                        disabled={busy}
                        variant="danger"
                      >
                        Удалить
                      </Button>
                    </div>
                  </>
                )}
              </Panel>
            )
          })}

          {editing === 'new' ? (
            <Panel className="px-4 py-3">
              <Editor
                initial={{ title: '', answer: '' }}
                busy={busy}
                onCancel={() => setEditing(null)}
                onSave={(value) => run(() => api.post('/api/faq', value))}
              />
            </Panel>
          ) : (
            <div>
              <Button onClick={() => setEditing('new')} variant="primary">
                + Добавить тему
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

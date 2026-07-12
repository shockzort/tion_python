import { useState, type FormEvent } from 'react'

import { useExecuteIntent } from '../api/queries'

/** Строка текстовых команд (FR-30): фундамент локального голоса. */
export default function IntentBar() {
  const executeIntent = useExecuteIntent()
  const [text, setText] = useState('')
  const [reply, setReply] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const phrase = text.trim()
    if (phrase === '' || executeIntent.isPending) return
    try {
      const result = await executeIntent.mutateAsync(phrase)
      setReply(result.reply)
      if (result.executed) setText('')
    } catch {
      setReply('Сервер не ответил — попробуйте ещё раз.')
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-1">
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Скажите бризеру: «включи в спальне на тройку»"
          aria-label="текстовая команда"
          className="flex-1 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none placeholder:text-slate-600 focus:border-sky-500"
        />
        <button
          type="submit"
          disabled={executeIntent.isPending || text.trim() === ''}
          className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {executeIntent.isPending ? '…' : '→'}
        </button>
      </div>
      {reply !== null && (
        <p className="px-1 text-sm text-slate-400" role="status">
          {reply}
        </p>
      )}
    </form>
  )
}

import { useRef, useState } from 'react'

import { useCommandStatus, useResetFilter } from '../api/queries'
import type { Device } from '../api/types'
import { Button } from './ui'

export default function FilterReset({ device }: { device: Device }) {
  const reset = useResetFilter()
  const [commandId, setCommandId] = useState<number | null>(null)
  const command = useCommandStatus(commandId)
  const requestKey = useRef<string | null>(null)
  const result = command.data ?? reset.data
  const pending = reset.isPending ||
    (commandId !== null && (!command.data || ['pending', 'running'].includes(command.data.status)))
  const reason = !device.filter_reset_supported
    ? 'Сброс станет доступен после проверки на этом бризере при замене фильтров.'
    : device.connection !== 'online' ? 'Для смены фильтров дождитесь связи с бризером.' : null

  const run = async () => {
    if (!confirm(`Фильтры в «${device.name}» заменены? Сбросить их ресурс в бризере?`)) return
    if (result && !['pending', 'running'].includes(result.status)) requestKey.current = null
    requestKey.current ??= `ui:${crypto.randomUUID()}`
    setCommandId(null)
    try {
      const response = await reset.mutateAsync({ uuid: device.uuid, key: requestKey.current })
      if (['pending', 'running'].includes(response.status)) setCommandId(response.command_id)
    } catch {
      // Ключ сохраняется: повтор после потери HTTP-ответа вернёт прежний итог.
    }
  }

  if (device.model !== 's4') return null
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <Button variant="ghost" onClick={run} disabled={reason !== null || pending} title={reason ?? undefined}>
        {pending ? 'Сбрасываем…' : 'Смена фильтров'}
      </Button>
      {reason && <p className="max-w-sm text-xs text-slate-500">{reason}</p>}
      {reset.isError && <p role="alert" className="text-xs text-rose-400">{reset.error.message}</p>}
      {command.isError && <p role="alert" className="text-xs text-amber-400">Не удалось прочитать итог. Ожидаем связь; повторный сброс не отправляется.</p>}
      {!pending && result?.status === 'done' && <p role="status" className="text-xs text-emerald-400">Ресурс фильтров обновлён</p>}
      {!pending && result && result.status !== 'done' && <p role="alert" className="text-xs text-rose-400">{result.error ?? 'Сброс не подтверждён'}</p>}
    </div>
  )
}

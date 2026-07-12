// useState с зеркалом в localStorage — UI-мелочи per-устройство (ключи eb:*)

import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'

/** Как useState, но значение переживает перезагрузку страницы (JSON).
 *  Битые данные или недоступный localStorage — молча initial. */
export function usePersistentState<T>(
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // квота или приватный режим — работаем без персистентности
    }
  }, [key, value])

  return [value, setValue]
}

// Мелкие примитивы интерфейса (Tailwind, тёмная тема)

import type { ButtonHTMLAttributes, ReactNode } from 'react'

type ButtonVariant = 'primary' | 'ghost' | 'danger'

const buttonStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-sky-600 text-white hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-400',
  ghost:
    'bg-slate-800 text-slate-200 hover:bg-slate-700 disabled:text-slate-500',
  danger: 'bg-rose-600/80 text-white hover:bg-rose-500 disabled:bg-slate-700',
}

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type="button"
      className={`rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${buttonStyles[variant]} ${className}`}
      {...props}
    />
  )
}

export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-2xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}
    >
      {children}
    </section>
  )
}

type BadgeTone = 'ok' | 'warn' | 'error' | 'muted'

const badgeStyles: Record<BadgeTone, string> = {
  ok: 'bg-emerald-500/10 text-emerald-400',
  warn: 'bg-amber-500/10 text-amber-400',
  error: 'bg-rose-500/10 text-rose-400',
  muted: 'bg-slate-700/40 text-slate-400',
}

export function Badge({
  tone,
  children,
}: {
  tone: BadgeTone
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs ${badgeStyles[tone]}`}
    >
      {children}
    </span>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-400">
      <span
        role="status"
        aria-label={label ?? 'загрузка'}
        className="size-4 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400"
      />
      {label}
    </span>
  )
}

/** Переключатель-строка: подпись слева, свитч справа.

Обёртка — div, не label: label пересылает клик по всей строке (включая
текст и пустое место) вложенной кнопке, из-за чего промах пальцем мимо
соседнего контрола дёргал свитч (полевой баг: выключение бризера при
захвате ползунка скорости). Кликабелен только сам свитч.
*/
export function Toggle({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 py-1 text-sm ${
        disabled ? 'text-slate-500' : 'text-slate-200'
      }`}
    >
      {label}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 rounded-full transition-colors disabled:cursor-not-allowed ${
          checked ? 'bg-sky-600' : 'bg-slate-700'
        }`}
      >
        <span
          className={`absolute top-0.5 size-5 rounded-full bg-white transition-all ${
            checked ? 'left-[22px]' : 'left-0.5'
          }`}
        />
      </button>
    </div>
  )
}

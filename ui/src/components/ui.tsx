// Мелкие примитивы интерфейса (Tailwind, тёмная тема)

import type { ButtonHTMLAttributes, ReactNode } from 'react'

type ButtonVariant = 'primary' | 'ghost' | 'danger'

const buttonStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-sky-400 text-slate-950 hover:bg-sky-300 disabled:bg-slate-700 disabled:text-slate-400',
  ghost:
    'border border-slate-800 bg-slate-950/60 text-slate-200 hover:border-slate-700 hover:bg-slate-800 disabled:text-slate-500',
  danger:
    'border border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-500',
}

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${buttonStyles[variant]} ${className}`}
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
      className={`rounded-2xl border border-slate-800 bg-slate-900 p-4 ${className}`}
    >
      {children}
    </section>
  )
}

type BadgeTone = 'ok' | 'warn' | 'error' | 'muted'

const badgeStyles: Record<BadgeTone, string> = {
  ok: 'bg-emerald-500/10 text-emerald-300',
  warn: 'bg-amber-500/10 text-amber-300',
  error: 'bg-rose-500/10 text-rose-300',
  muted: 'border border-slate-800 bg-slate-950/60 text-slate-300',
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
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${badgeStyles[tone]}`}
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
        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          checked ? 'bg-sky-400' : 'bg-slate-700'
        }`}
      >
        <span
          className={`absolute top-0.5 size-6 rounded-full transition-all ${
            checked ? 'left-[22px] bg-slate-950' : 'left-0.5 bg-slate-300'
          }`}
        />
      </button>
    </div>
  )
}

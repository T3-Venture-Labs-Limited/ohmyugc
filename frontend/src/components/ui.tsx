import { useQueryClient } from '@tanstack/react-query'
import { clsx, type ClassValue } from 'clsx'
import { AlertTriangle, Camera, Check, Loader2, X } from 'lucide-react'
import {
  type ButtonHTMLAttributes,
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { twMerge } from 'tailwind-merge'
import { api, type Json, money } from '../api'

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))

// ── buttons ──────────────────────────────────────────────────────────────────

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'secondary' | 'primary' | 'sage' | 'butter' | 'danger' | 'ghost'
  size?: 'md' | 'sm'
  busy?: boolean
  icon?: ReactNode
  cost?: number | null | 'unknown'
  iconOnly?: boolean
}

export function Button({ variant = 'secondary', size = 'md', busy, icon, cost, iconOnly, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={cn('btn', variant !== 'secondary' && `btn-${variant}`, size === 'sm' && 'btn-sm', iconOnly && 'btn-icon', className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Loader2 size={16} className="spin" aria-hidden /> : icon}
      {children}
      {cost !== undefined && cost !== null && <span className="cost">{cost === 'unknown' ? 'price unknown' : money(cost)}</span>}
    </button>
  )
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch" onClick={() => onChange(!checked)} />
}

// ── fields ───────────────────────────────────────────────────────────────────

export function Field({ label, help, error, children, className }: { label: string; help?: ReactNode; error?: string; children: (id: string) => ReactNode; className?: string }) {
  const id = useId()
  return (
    <div className={className}>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      {children(id)}
      {error ? <p className="help" style={{ color: 'var(--color-bad)' }} role="alert">{error}</p> : help ? <p className="help">{help}</p> : null}
    </div>
  )
}

// ── dialog ───────────────────────────────────────────────────────────────────

export function Dialog({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement
    const first = ref.current?.querySelector<HTMLElement>('textarea, input, select, button:not([data-close])')
    ;(first ?? ref.current)?.focus()
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && ref.current) {
        const items = [...ref.current.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((n) => !n.hasAttribute('disabled'))
        if (!items.length) return
        const [a, b] = [items[0], items[items.length - 1]]
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); b.focus() }
        else if (!e.shiftKey && document.activeElement === b) { e.preventDefault(); a.focus() }
      }
    }
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('keydown', key)
      ;(opener.current as HTMLElement | null)?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[60] grid place-items-center p-3 sm:p-6" style={{ background: 'rgb(23 32 25 / 0.5)' }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className={cn('card max-h-[92dvh] w-full overflow-auto p-5 sm:p-6', wide ? 'max-w-3xl' : 'max-w-lg')}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 id={titleId}>{title}</h2>
          <Button variant="ghost" size="sm" iconOnly aria-label="Close" data-close onClick={onClose} icon={<X size={18} />} />
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** A button that asks twice before doing something destructive. */
export function ConfirmButton({ label, confirmLabel = 'Yes, delete', onConfirm, size = 'sm', icon, iconOnly, busy }: { label: string; confirmLabel?: string; onConfirm: () => void; size?: 'sm' | 'md'; icon?: ReactNode; iconOnly?: boolean; busy?: boolean }) {
  const [asking, setAsking] = useState(false)
  useEffect(() => {
    if (!asking) return
    const t = setTimeout(() => setAsking(false), 5000)
    return () => clearTimeout(t)
  }, [asking])
  if (!asking) return <Button variant="danger" size={size} icon={icon} iconOnly={iconOnly} aria-label={iconOnly ? label : undefined} onClick={() => setAsking(true)} busy={busy}>{iconOnly ? null : label}</Button>
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Button variant="danger" size={size} onClick={() => { setAsking(false); onConfirm() }}>{confirmLabel}</Button>
      <Button variant="ghost" size={size} onClick={() => setAsking(false)}>Keep it</Button>
    </span>
  )
}

// ── media ────────────────────────────────────────────────────────────────────

export function Phone({ src, video, ratio = '9 / 16', empty, className, poster, label }: { src?: string | null; video?: boolean; ratio?: string; empty?: ReactNode; className?: string; poster?: string | null; label?: string }) {
  return (
    <div className={cn('phone', className)} style={{ aspectRatio: ratio.replace(':', ' / ') }}>
      {src ? (
        video ? (
          <video src={src} poster={poster ?? undefined} controls playsInline preload="metadata" aria-label={label} />
        ) : (
          <img src={src} alt={label ?? ''} loading="lazy" />
        )
      ) : (
        <div className="phone-empty h-full w-full">
          <span className="grid gap-1.5 justify-items-center">
            <Camera size={22} aria-hidden />
            {empty ?? 'No picture yet'}
          </span>
        </div>
      )}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <div className="flex items-start gap-2 rounded-[12px] border-2 border-bad bg-[#f7d4d0] p-3 text-[14.5px] font-medium text-bad" role="alert">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

export function Note({ children, tone = 'butter', icon }: { children: ReactNode; tone?: 'butter' | 'sage' | 'lilac' | 'clay'; icon?: ReactNode }) {
  const bg = { butter: 'bg-butter', sage: 'bg-sage', lilac: 'bg-lilac', clay: 'bg-clay-soft' }[tone]
  return (
    <div className={cn('flex items-start gap-2.5 rounded-[12px] border-2 border-ink p-3 text-[14.5px] font-medium leading-snug', bg)}>
      {icon}
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card-flat grid justify-items-center gap-3 p-8 text-center">
      <h3>{title}</h3>
      {children && <p className="max-w-md text-ink-soft">{children}</p>}
      {action}
    </div>
  )
}

export function StatusChip({ status, stage }: { status: string; stage?: string }) {
  const map: Record<string, { cls: string; text: string }> = {
    none: { cls: 'chip', text: 'Not made yet' },
    queued: { cls: 'chip chip-lilac', text: 'Queued' },
    waiting: { cls: 'chip chip-butter', text: 'Waiting for rate limit' },
    running: { cls: 'chip chip-clay', text: 'Making it' },
    checking: { cls: 'chip chip-lilac', text: 'Checking product' },
    done: { cls: 'chip chip-sage', text: 'Ready' },
    failed: { cls: 'chip chip-bad', text: 'Failed' },
    canceled: { cls: 'chip', text: 'Canceled' },
  }
  const m = map[status] ?? map.none
  const live = status === 'running' || status === 'checking' || status === 'waiting' || status === 'queued'
  return (
    <span className={m.cls} title={stage}>
      {live ? <span className="live-dot" aria-hidden /> : status === 'done' ? <Check size={14} aria-hidden /> : null}
      {m.text}
    </span>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-ink-soft" role="status">
      <Loader2 className="spin" size={20} aria-hidden /> {label}…
    </div>
  )
}

export function CostLine({ total, prefix }: { total?: { amount: number; partial?: boolean } | null; prefix?: string }) {
  if (!total) return null
  return (
    <span className="mono">
      {prefix} {money(total.amount)}
      {total.partial ? ' + unknown' : ''}
    </span>
  )
}

// ── the floating console ─────────────────────────────────────────────────────

const ConsoleCtx = createContext<HTMLElement | null>(null)
export const ConsoleProvider = ConsoleCtx.Provider

export function Console({ info, children }: { info?: ReactNode; children?: ReactNode }) {
  const root = useContext(ConsoleCtx)
  if (!root) return null
  return createPortal(
    <div className="console" role="region" aria-label="Actions for this step">
      {info && <div className="console-info">{info}</div>}
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>,
    root,
  )
}

// ── jobs ─────────────────────────────────────────────────────────────────────

/** Follow background jobs: a toast while they run, then success or the plain error. */
export function useJobWatch() {
  const qc = useQueryClient()
  return useCallback(
    (jobId: string | string[], opts: { label: string; invalidate?: unknown[][]; onDone?: (job: Json) => void }) => {
      const ids = Array.isArray(jobId) ? jobId : [jobId]
      if (!ids.length) return
      const toastId = toast.loading(`${opts.label}…`)
      const poll = async () => {
        try {
          const jobs = await Promise.all(ids.map((id) => api.job(id)))
          const live = jobs.some((j) => j.status === 'queued' || j.status === 'running')
          for (const key of opts.invalidate ?? []) void qc.invalidateQueries({ queryKey: key })
          if (live) {
            const running = jobs.find((j) => j.status === 'running') ?? jobs[0]
            toast.loading(`${opts.label}: ${running.stage || 'working'}…`, { id: toastId })
            setTimeout(poll, 1200)
            return
          }
          const failed = jobs.find((j) => j.status === 'failed')
          if (failed) toast.error(failed.error || 'That did not work.', { id: toastId, duration: 9000 })
          else if (jobs[0].result?.status === 'skipped') toast.message(jobs[0].result.message, { id: toastId, duration: 10000 })
          else toast.success(`${opts.label}: done`, { id: toastId })
          opts.onDone?.(jobs[0])
        } catch (e) {
          toast.error((e as Error).message, { id: toastId })
        }
      }
      void poll()
    },
    [qc],
  )
}

export function useAction() {
  const [busy, setBusy] = useState<string | null>(null)
  const run = useCallback(async <T,>(key: string, fn: () => Promise<T>, onOk?: (r: T) => void): Promise<T | undefined> => {
    setBusy(key)
    try {
      const r = await fn()
      onOk?.(r)
      return r
    } catch (e) {
      toast.error((e as Error).message, { duration: 8000 })
      return undefined
    } finally {
      setBusy((b) => (b === key ? null : b))
    }
  }, [])
  return { busy, run }
}

export const fmtSeconds = (s: number) => `${s.toFixed(1)} s`

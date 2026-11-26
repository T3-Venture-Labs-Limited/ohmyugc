import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { api, type Json, money } from '../api'
import { Note, Spinner, cn } from '../components/ui'
import { BriefStage } from './stages/Brief'
import { ClipsStage } from './stages/Clips'
import { ExportStage } from './stages/Export'
import { ScriptStage } from './stages/Script'
import { StoryboardStage } from './stages/Storyboard'

export const STAGES = [
  { id: 'brief', label: 'Brief' },
  { id: 'script', label: 'Script' },
  { id: 'storyboard', label: 'Storyboard' },
  { id: 'clips', label: 'Clips' },
  { id: 'export', label: 'Export' },
] as const

export type Workspace = {
  project: Json
  shots: Json[]
  variants: Json[]
  script: Json
  jobs: Json[]
  progress: Json[]
  warnings: string[]
  unit_blocks: string[][]
  variant_progress: Record<string, Json[]>
  exports: Json[]
}
export type StageProps = { ws: Workspace; refresh: () => Promise<unknown>; id: string }

export function useWorkspace(id: string) {
  return useQuery({
    queryKey: ['ws', id],
    queryFn: () => api.workspace(id) as Promise<Workspace>,
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === 'queued' || j.status === 'running') ? 1500 : false),
  })
}

/** What is missing before a stage can do its work (never hides later work, only explains). */
export function missingFor(stage: string, ws: Workspace): { text: string; to: string }[] {
  const p = ws.project
  const out: { text: string; to: string }[] = []
  if (stage === 'brief') return out
  if (stage === 'script') {
    if (!p.brand) out.push({ text: 'Choose a brand', to: 'brief' })
    if (!p.product) out.push({ text: 'Choose a product', to: 'brief' })
    return out
  }
  if (!p.script?.trim()) out.push({ text: 'Write or paste the script', to: 'script' })
  if (stage === 'storyboard') return out
  if (ws.shots.length === 0) out.push({ text: 'Draft the storyboard', to: 'storyboard' })
  else if (ws.shots.some((s) => !s.approved)) out.push({ text: `Approve every shot (${ws.shots.filter((s) => !s.approved).length} left)`, to: 'storyboard' })
  if (stage === 'clips') return out
  const clipUnits = ws.progress.filter((u) => u.status !== 'none' || true)
  if (clipUnits.some((u) => u.status !== 'done')) out.push({ text: `Make every clip (${clipUnits.filter((u) => u.status !== 'done').length} left)`, to: 'clips' })
  return out
}

export function Missing({ stage, ws }: { stage: string; ws: Workspace }) {
  const items = missingFor(stage, ws)
  if (items.length === 0) return null
  const first = stage === 'script' ? 'Before the script' : stage === 'storyboard' ? 'Before the storyboard' : stage === 'clips' ? 'Before clips' : 'Before exporting'
  return (
    <Note tone="butter">
      <b>{first}:</b>{' '}
      {items.map((m, i) => (
        <span key={m.text}>{i > 0 && ', '}<Link className="font-bold underline" to={`../${m.to}`} relative="path">{m.text}</Link></span>
      ))}
      .
    </Note>
  )
}

function stageDone(stage: string, ws: Workspace): boolean {
  const p = ws.project
  if (stage === 'brief') return !!(p.brand && p.product && p.actor)
  if (stage === 'script') return !!p.script?.trim()
  if (stage === 'storyboard') return ws.shots.length > 0 && ws.shots.every((s) => s.approved)
  if (stage === 'clips') return ws.progress.length > 0 && ws.progress.every((u) => u.status === 'done')
  return false
}

export function ProjectPage() {
  const { id = '', stage } = useParams()
  const qc = useQueryClient()
  const ws = useWorkspace(id)
  const refresh = () => qc.invalidateQueries({ queryKey: ['ws', id] })
  if (!stage) return ws.data ? <Navigate to={ws.data.project.stage} replace /> : <Spinner />
  if (ws.isError) return <Note tone="clay">{(ws.error as Error).message} <Link className="font-bold underline" to="/">Back to your ads</Link></Note>
  if (!ws.data) return <Spinner />
  const p = ws.data.project
  const budget = p.budget_status
  const props: StageProps = { ws: ws.data, refresh, id }
  return (
    <div className="grid gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-x-6">
        <div className="w-full min-w-0 sm:flex-1">
          <label className="sr-only" htmlFor="ad-name">Ad name</label>
          <input
            id="ad-name"
            maxLength={120}
            key={p.name}
            className="display w-full max-w-[640px] rounded-[10px] border-2 border-transparent bg-transparent px-2 py-1 text-[clamp(26px,4.4vw,38px)] hover:border-ink/20 focus:border-ink"
            defaultValue={p.name}
            onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== p.name) api.updateProject(id, { name: v }).then(refresh).catch((er: Error) => toast.error(er.message)) }}
          />
          <p className="px-2 text-[14.5px] text-ink-soft">{[p.brand?.name, p.product?.name, p.actor?.name && `with ${p.actor.name}`].filter(Boolean).join(' · ') || 'Pick a brand, product and actor in the Brief.'}</p>
        </div>
        <div className="card-flat flex w-fit shrink-0 items-center gap-3 px-4 py-2" aria-label="Spend and budget">
          <div>
            <p className="text-[13px] text-ink-mute">Spent on this ad</p>
            <p className="mono text-[18px] font-medium">{money(budget.spent)}{budget.budget != null && <span className="text-ink-mute"> / {money(budget.budget)}</span>}</p>
          </div>
          {budget.budget != null && <div className="h-2 w-20 overflow-hidden rounded-full border-2 border-ink bg-white" role="img" aria-label={`${Math.round(Math.min(100, (budget.spent / Math.max(budget.budget, 0.01)) * 100))}% of the budget used`}><div className="h-full bg-clay" style={{ width: `${Math.min(100, (budget.spent / Math.max(budget.budget, 0.01)) * 100)}%` }} /></div>}
        </div>
      </div>
      <nav aria-label="Steps" className="scrollbar-none -mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
        <ol className="flex min-w-max gap-2">
          {STAGES.map((s, i) => (
            <li key={s.id}>
              <Link to={`/ads/${id}/${s.id}`} className={cn('stage-pill', stageDone(s.id, ws.data) && stage !== s.id && 'done')} aria-current={stage === s.id ? 'step' : undefined}>
                <span className="n">{stageDone(s.id, ws.data) && stage !== s.id ? <Check size={14} aria-label="done" /> : i + 1}</span>
                {s.label}
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      {stage === 'brief' && <BriefStage {...props} />}
      {stage === 'script' && <ScriptStage {...props} />}
      {stage === 'storyboard' && <StoryboardStage {...props} />}
      {stage === 'clips' && <ClipsStage {...props} />}
      {stage === 'export' && <ExportStage {...props} />}
      {!STAGES.some((s) => s.id === stage) && <Navigate to="brief" replace />}
    </div>
  )
}

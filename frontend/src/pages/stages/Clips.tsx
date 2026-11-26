import { ArrowRight, Clapperboard, Film, Play, RefreshCw, Scissors, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { api, type Json, money } from '../../api'
import { Button, Console, Dialog, Field, Note, Phone, StatusChip, fmtSeconds, useAction, useJobWatch } from '../../components/ui'
import { Missing, type StageProps } from '../Project'

function driftLines(drift: Json | null): string[] {
  if (!drift || drift.status !== 'flagged') return []
  return (drift.failing ?? []).map((f: Json) => `At ${f.t.toFixed(1)} s: ${(f.issues ?? []).map((i: Json) => i.text).join('; ') || 'the product does not match your photo'}`)
}

function UnitCard({ unit, ws, id, refresh, estimate }: { unit: Json; ws: StageProps['ws']; id: string; refresh: () => Promise<unknown>; estimate: Json | undefined }) {
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [dialog, setDialog] = useState<null | 'take' | 'trim'>(null)
  const [note, setNote] = useState('')
  const [quality, setQuality] = useState<'draft' | 'final'>('draft')
  const [preview, setPreview] = useState<string | null>(null)
  const [keep, setKeep] = useState(false)
  const [trim, setTrim] = useState<{ start: string; end: string }>({ start: '0', end: '' })
  const shots: Json[] = ws.shots.filter((s) => unit.shot_ids.includes(s.id))
  const lead = shots[0]
  const p = ws.project
  if (!lead) return null
  const takes: Json[] = lead.takes ?? []
  const chosen = takes.find((t) => t.id === lead.chosen_take)
  const shown = takes.find((t) => t.id === preview) ?? chosen
  const lines = driftLines(chosen?.drift ?? null)
  const live = unit.status === 'queued' || unit.status === 'running' || unit.status === 'waiting' || unit.status === 'checking'
  const unitEst = estimate?.units?.find((u: Json) => u.shot_id === lead.id)
  const render = (q: 'draft' | 'final') => run(`render-${q}`, () => api.render(id, { quality: q, shot_ids: [lead.id] }), (r) => watch(r.job_ids, { label: `Clip for shot ${unit.position}`, invalidate: [['ws', id]] }))
  return (
    <li className="card grid gap-4 p-4 sm:grid-cols-[190px_minmax(0,1fr)]" aria-label={`Clip for shot ${unit.position}`}>
      <div className="grid content-start gap-2">
        <Phone ratio={p.aspect} src={shown?.url} video={!!shown} poster={lead.frame_url} empty={lead.frame_url ? undefined : 'Not made yet'} label={`Clip for shot ${unit.position}`} />
        {!shown && lead.frame_url && <img src={lead.frame_url} alt="" className="hidden" />}
        {shown && <p className="mono text-[13px] text-ink-mute">{shown.quality} · {fmtSeconds(shown.duration ?? 0)}{shown.has_audio ? ' · sound' : ''}</p>}
      </div>
      <div className="grid min-w-0 content-start gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3>{shots.length > 1 ? `Shots ${shots[0].position + 1}–${shots[shots.length - 1].position + 1}` : `Shot ${unit.position}`}</h3>
          <StatusChip status={unit.status} stage={unit.stage} />
        </div>
        {shots.map((s) => <p key={s.id} className="text-[14.5px] text-ink-soft">{s.line ? `“${s.line}”` : <i className="not-italic text-ink-mute">No spoken line</i>}</p>)}
        {live && <p className="text-[14px] font-semibold" role="status">{unit.stage || 'Working'}{unit.elapsed != null ? ` · ${Math.round(unit.elapsed)} s` : ''}</p>}
        {unit.status === 'failed' && (
          <div className="rounded-[12px] border-2 border-bad bg-[#f7d4d0] p-3 text-[14.5px] font-medium text-bad" role="alert">
            {unit.error}
            <div className="mt-2"><Button size="sm" icon={<RefreshCw size={15} />} busy={busy === 'render-draft'} onClick={() => void render('draft')}>Retry</Button></div>
          </div>
        )}
        {lines.length > 0 && !keep && (
          <div className="rounded-[12px] border-2 border-clay bg-clay-soft p-3 text-[14px]" role="alert">
            <b>The product looks wrong in this clip.</b>
            <ul className="mt-1 list-disc pl-5">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" icon={<RefreshCw size={15} />} aria-label={`New take for shot ${unit.position}`} onClick={() => setDialog('take')}>New take</Button>
              <Button size="sm" variant="butter" aria-label={`Use real product shot for shot ${unit.position}`} onClick={() => void run('swap', () => api.realProduct(lead.id), () => { toast.success('Now a real-product shot.'); void refresh() })}>Use real product shot</Button>
              <Button size="sm" variant="ghost" aria-label={`Keep shot ${unit.position} anyway`} onClick={() => setKeep(true)}>Keep anyway</Button>
            </div>
          </div>
        )}
        {chosen?.drift?.status === 'passed' && <p className="text-[13.5px] font-semibold text-ok">Product matches your photo in every checked frame.</p>}
        {chosen?.drift?.status === 'not_checked' && <p className="text-[13.5px] text-ink-mute">Product check skipped: {chosen.drift.reason}</p>}
        {takes.length > 0 && (
          <div>
            <p className="label">Takes</p>
            <ul className="flex flex-wrap gap-2">
              {takes.map((t, i) => (
                <li key={t.id} className="flex items-center gap-1 rounded-[10px] border-2 border-ink px-2 py-1 text-[13.5px]">
                  <span className="mono">#{i + 1} {t.quality}</span>
                  <Button size="sm" variant="ghost" iconOnly aria-label={`Preview take ${i + 1}`} icon={<Play size={14} />} onClick={() => setPreview(t.id)} />
                  {t.id === lead.chosen_take ? <span className="chip chip-sage">In use</span> : <Button size="sm" onClick={() => void run('choose', () => api.chooseTake(lead.id, t.id), () => { setPreview(null); void refresh() })}>Use</Button>}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {unit.status === 'none' && <Button size="sm" variant="primary" icon={<Film size={15} />} cost={unitEst?.estimate} busy={busy === 'render-draft'} onClick={() => void render('draft')}>Make draft clip</Button>}
          {lead.type !== 'real_product' && takes.length > 0 && <Button size="sm" icon={<RefreshCw size={15} />} disabled={live} aria-label={`Make a new take of shot ${unit.position}`} onClick={() => setDialog('take')}>New take</Button>}
          {chosen && lead.type !== 'real_product' && <Button size="sm" icon={<Scissors size={15} />} aria-label={`Trim shot ${unit.position}`} onClick={() => { setTrim({ start: String(chosen.trim_start ?? 0), end: chosen.trim_end != null ? String(chosen.trim_end) : '' }); setDialog('trim') }}>Trim</Button>}
          {lead.type !== 'real_product' && <Button size="sm" variant="butter" disabled={live} aria-label={`Swap shot ${unit.position} for a real product shot`} onClick={() => void run('swap', () => api.realProduct(lead.id), () => { toast.success('Now a real-product shot.'); void refresh() })}>Use real product shot</Button>}
          {takes.length > 1 && <Button size="sm" variant="danger" icon={<Trash2 size={15} />} aria-label={`Clear other takes of shot ${unit.position}`} onClick={() => void run('clear', () => api.clearTakes(lead.id), () => void refresh())}>Clear other takes</Button>}
        </div>
      </div>
      <Dialog open={dialog === 'take'} onClose={() => setDialog(null)} title={`New take for shot ${unit.position}`}>
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); setDialog(null); void run('take', () => api.newTake(lead.id, quality, note), (r) => { setNote(''); watch(r.job_id, { label: `New take, shot ${unit.position}`, invalidate: [['ws', id]] }) }) }}>
          <p className="text-ink-soft">Same picture, a fresh generation. Earlier takes stay until you clear them.</p>
          <Field label="Quality">
            {(fid) => <select id={fid} className="input" value={quality} onChange={(e) => setQuality(e.target.value as 'draft' | 'final')}><option value="draft">Draft (cheapest)</option><option value="final">Final ({p.final_resolution})</option></select>}
          </Field>
          <Field label="Extra direction (optional)">{(fid) => <textarea id={fid} className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Keep the bottle label facing the camera" />}</Field>
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button variant="primary" type="submit" cost={unitEst?.estimate}>Make it</Button></div>
        </form>
      </Dialog>
      <Dialog open={dialog === 'trim'} onClose={() => setDialog(null)} title={`Trim shot ${unit.position}`}>
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (!chosen) return; setDialog(null); void run('trim', () => api.trim(lead.id, chosen.id, Number(trim.start || 0), trim.end === '' ? null : Number(trim.end)), () => void refresh()) }}>
          <p className="text-ink-soft">The clip is {fmtSeconds(chosen?.duration ?? 0)} long. Keep at least half a second.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Start at (seconds)">{(fid) => <input id={fid} className="input" inputMode="decimal" value={trim.start} onChange={(e) => setTrim({ ...trim, start: e.target.value })} />}</Field>
            <Field label="End at (seconds)" help="Empty keeps the rest.">{(fid) => <input id={fid} className="input" inputMode="decimal" value={trim.end} onChange={(e) => setTrim({ ...trim, end: e.target.value })} />}</Field>
          </div>
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button variant="primary" type="submit">Save trim</Button></div>
        </form>
      </Dialog>
    </li>
  )
}

export function ClipsStage({ ws, refresh, id }: StageProps) {
  const navigate = useNavigate()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const p = ws.project
  const key = [id, ws.shots.length, ws.shots.map((s) => `${s.type}${s.frame}${s.approved}`).join('').length, p.models?.image_to_video, p.final_resolution, p.voice_mode]
  const draft = useQuery({ queryKey: ['clip-est', 'draft', ...key], queryFn: () => api.clipEstimate(id, 'draft'), enabled: ws.shots.length > 0 })
  const final = useQuery({ queryKey: ['clip-est', 'final', ...key], queryFn: () => api.clipEstimate(id, 'final'), enabled: ws.shots.length > 0 })
  const progress = ws.progress
  const ready = progress.length > 0 && progress.every((u) => u.status === 'done')
  const live = progress.filter((u) => ['queued', 'running', 'waiting', 'checking'].includes(u.status)).length
  const approved = ws.shots.length > 0 && ws.shots.every((s) => s.approved)
  const done = progress.filter((u) => u.status === 'done').length
  const go = (q: 'draft' | 'final') => run(`render-${q}`, () => api.render(id, { quality: q }), (r) => watch(r.job_ids, { label: `Making ${r.count} ${q} clips`, invalidate: [['ws', id]] }))
  const e = (q: Json | undefined) => (q?.available ? q.total.amount : undefined)
  return (
    <div className="grid gap-6">
      <Missing stage="clips" ws={ws} />
      <div className="card p-4">
        <h2>Clips</h2>
        <p className="text-[14.5px] text-ink-soft">Make a cheap draft of every shot first, check it, then make final quality. Shots you approved are the first frames. Real-product shots are made on your computer for free.</p>
      </div>
      {ws.warnings.map((w) => <Note key={w} tone="butter">{w}</Note>)}
      {(draft.data && !draft.data.available) && <Note tone="clay">{draft.data.message}</Note>}
      {draft.data?.available && (
        <details className="card-flat p-3">
          <summary className="cursor-pointer font-bold">What a render costs, line by line</summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {([['Draft', draft.data], ['Final', final.data]] as [string, Json | undefined][]).map(([label, d]) => d && (
              <div key={label}>
                <h3 className="mb-1 text-[16px]">{label}: {d.available ? money(d.total.amount) : ''}{d.total?.partial ? ' + unknown' : ''}</h3>
                <ul className="grid gap-1 text-[14px]">
                  {d.units?.map((u: Json) => <li key={u.shot_id}><b>Shot {u.position}</b>: {u.kind === 'local' ? 'made on your computer, free' : u.lines.map((l: Json) => `${l.label} ${l.estimate == null ? 'price unknown' : money(l.estimate)}`).join(' + ')}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}
      <ul className="grid gap-5">
        {progress.map((u) => <UnitCard key={u.shot_id} unit={u} ws={ws} id={id} refresh={refresh} estimate={draft.data} />)}
        {progress.length === 0 && <li><Note tone="butter">Nothing to render yet. Approve the shots in the storyboard first.</Note></li>}
      </ul>
      <Console info={live ? <><span className="live-dot" aria-hidden /> <b>{live}</b> clip{live === 1 ? '' : 's'} in progress, {done} of {progress.length} ready</> : <>{done} of {progress.length} clips ready.</>}>
        <Button icon={<Clapperboard size={16} />} cost={e(draft.data)} busy={busy === 'render-draft'} disabled={!approved || progress.length === 0 || draft.data?.available === false} onClick={() => void go('draft')}>Render draft</Button>
        <Button icon={<Film size={16} />} cost={e(final.data)} busy={busy === 'render-final'} disabled={!approved || progress.length === 0 || final.data?.available === false} onClick={() => void go('final')}>Render final</Button>
        <Button variant="primary" icon={<ArrowRight size={17} />} disabled={!ready} onClick={() => navigate('../export', { relative: 'path' })}>Next: Export</Button>
      </Console>
    </div>
  )
}

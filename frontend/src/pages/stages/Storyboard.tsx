import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowRight, ArrowUp, Check, Copy, History, ImagePlus, Link2, Link2Off, Plus, RefreshCw, Sparkles, Trash2, Type, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, type Json, money } from '../../api'
import { Button, ConfirmButton, Console, Dialog, Field, Note, Phone, useAction, useJobWatch } from '../../components/ui'
import { Missing, type StageProps } from '../Project'

const PURPOSES = ['hook', 'problem', 'demo', 'proof', 'offer', 'cta', 'other']
const TYPES: [string, string][] = [['talking', 'Talking to camera'], ['product_in_hand', 'Product in hand'], ['cutaway', 'Cutaway (b-roll)'], ['real_product', 'Real product shot']]
const MOTIONS: [string, string][] = [['push_in', 'Slow push in'], ['pan', 'Pan'], ['parallax', 'Parallax'], ['rotate_in', 'Rotate in']]
const BACKGROUNDS: [string, string][] = [['blur', 'Blurred shot'], ['brand', 'Brand colour'], ['image', 'My image']]

function driftText(d: Json | null): string {
  if (!d) return ''
  if (d.status === 'passed') return 'Matches your product photo'
  if (d.status === 'not_checked') return d.reason ?? 'Not checked'
  return (d.issues ?? []).map((i: Json) => i.text).join('; ') || 'The product does not match your photo'
}

function ShotCard({ shot, index, total, ws, id, refresh, frameEach, busyShot }: { shot: Json; index: number; total: number; ws: Workspace; id: string; refresh: () => Promise<unknown>; frameEach: number | null; busyShot: boolean }) {
  const watch = useJobWatch()
  const { run } = useAction()
  const [dialog, setDialog] = useState<null | 'regen' | 'history' | 'end'>(null)
  const [note, setNote] = useState('')
  const upload = useRef<HTMLInputElement>(null)
  const endUpload = useRef<HTMLInputElement>(null)
  const p = ws.project
  const isReal = shot.type === 'real_product'
  const nextShot = ws.shots[index + 1]
  const inBlock = shot.block != null
  const blockWithNext = inBlock && nextShot?.block === shot.block
  const patch = (values: Json) => run(`patch-${Object.keys(values)[0]}`, () => api.updateShot(shot.id, values), () => void refresh())
  const text = (key: string) => ({
    key: `${key}-${shot[key]}`, defaultValue: shot[key] ?? '',
    onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => { if (e.target.value !== (shot[key] ?? '')) void patch({ [key]: e.target.value }) },
  })
  const job = shot.job
  const making = job && (job.status === 'queued' || job.status === 'running')
  const failed = job && job.status === 'failed' && job.kind === 'frame'
  const reorder = (delta: number) => {
    const ids = ws.shots.map((s) => s.id)
    ;[ids[index], ids[index + delta]] = [ids[index + delta], ids[index]]
    void run('reorder', () => api.reorder(id, ids), () => void refresh())
  }
  const drift = shot.frame_drift
  return (
    <li className="card grid gap-4 p-4 sm:grid-cols-[168px_minmax(0,1fr)]" aria-label={`Shot ${index + 1}`}>
      <div className="grid content-start gap-2">
        <div className="relative">
          <Phone ratio={p.aspect} src={shot.frame_url} empty={isReal ? 'Preview made free from your photo' : 'No picture yet'} label={`Frame for shot ${index + 1}`} />
          {making && (
            <div className="absolute inset-0 grid place-items-center rounded-[14px] bg-ink/60 p-2 text-center text-[13px] font-bold text-white" role="status">
              <span><span className="live-dot mb-1" aria-hidden /><br />{job.stage || 'Working'}</span>
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {shot.approved ? <span className="chip chip-sage"><Check size={13} aria-hidden /> Approved</span> : <span className="chip">Not approved</span>}
          {shot.stale && <span className="chip chip-butter">Out of date</span>}
          {inBlock && <span className="chip chip-lilac">Block {shot.block}</span>}
        </div>
        {drift && drift.status === 'flagged' && (
          <div className="rounded-[10px] border-2 border-clay bg-clay-soft p-2 text-[13px] font-medium" role="alert">
            <b>Product check:</b> {driftText(drift)}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Button size="sm" onClick={() => void run('regen-drift', () => api.shotFrame(shot.id, ''), (r) => watch(r.job_id, { label: 'Making a new picture', invalidate: [['ws', id]] }))}>Regenerate</Button>
              <Button size="sm" variant="butter" onClick={() => void run('swap', () => api.realProduct(shot.id), () => { toast.success('Now a real-product shot.'); void refresh() })}>Use real product</Button>
            </div>
          </div>
        )}
        {drift && drift.status === 'passed' && <p className="text-[13px] font-semibold text-ok"><Check size={13} className="inline" aria-hidden /> Matches your photo</p>}
        {drift && drift.status === 'not_checked' && <p className="text-[13px] text-ink-mute">Product check skipped: {drift.reason}</p>}
        {failed && <p className="text-[13px] font-semibold text-bad" role="alert">{job.error}</p>}
      </div>

      <div className="grid min-w-0 content-start gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3>Shot {index + 1}</h3>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" iconOnly aria-label={`Move shot ${index + 1} up`} icon={<ArrowUp size={16} />} disabled={index === 0} onClick={() => reorder(-1)} />
            <Button size="sm" iconOnly aria-label={`Move shot ${index + 1} down`} icon={<ArrowDown size={16} />} disabled={index === total - 1} onClick={() => reorder(1)} />
            <Button size="sm" iconOnly aria-label={`Duplicate shot ${index + 1}`} icon={<Copy size={15} />} onClick={() => void run('dup', () => api.duplicateShot(shot.id), () => void refresh())} />
            <ConfirmButton label={`Delete shot ${index + 1}`} icon={<Trash2 size={15} />} iconOnly onConfirm={() => void run('del', () => api.deleteShot(shot.id), () => void refresh())} />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Purpose">{(fid) => <select id={fid} className="input" value={shot.purpose} onChange={(e) => void patch({ purpose: e.target.value })}>{PURPOSES.map((x) => <option key={x}>{x}</option>)}</select>}</Field>
          <Field label="Type">{(fid) => <select id={fid} className="input" value={shot.type} onChange={(e) => void patch({ type: e.target.value })}>{TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
          <Field label="Seconds">{(fid) => <input id={fid} className="input" type="number" min={1} max={30} step={0.5} {...text('duration')} />}</Field>
        </div>
        <Field label="Spoken line" help={shot.line ? undefined : 'No line: this shot is silent.'}>{(fid) => <textarea id={fid} className="input min-h-[72px]" {...text('line')} />}</Field>
        <Field label="Text on screen (optional)">{(fid) => <input id={fid} className="input" maxLength={80} {...text('onscreen')} />}</Field>
        {isReal ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Motion">{(fid) => <select id={fid} className="input" value={shot.motion} onChange={(e) => void patch({ motion: e.target.value })}>{MOTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
            <Field label="Background">{(fid) => <select id={fid} className="input" value={shot.background} onChange={(e) => void patch({ background: e.target.value })}>{BACKGROUNDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
          </div>
        ) : (
          <details className="rounded-[12px] border-2 border-ink/20 p-3">
            <summary className="cursor-pointer font-bold">Camera and scene</summary>
            <div className="mt-3 grid gap-3">
              <Field label="Camera and framing">{(fid) => <textarea id={fid} className="input min-h-[60px]" {...text('framing')} />}</Field>
              <Field label="Setting">{(fid) => <input id={fid} className="input" {...text('setting')} />}</Field>
              <Field label="What happens">{(fid) => <textarea id={fid} className="input min-h-[72px]" {...text('action')} />}</Field>
            </div>
          </details>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {shot.approved
            ? <Button size="sm" onClick={() => void run('unapprove', () => api.approve(shot.id, false), () => void refresh())}>Unapprove</Button>
            : <Button size="sm" variant="primary" icon={<Check size={15} />} disabled={!isReal && !shot.frame} onClick={() => void run('approve', () => api.approve(shot.id, true), () => void refresh())}>Approve shot {index + 1}</Button>}
          <Button size="sm" icon={<RefreshCw size={15} />} cost={isReal ? 0 : frameEach} busy={!!making || busyShot} onClick={() => setDialog('regen')}>{shot.frame ? 'New picture' : 'Make picture'}</Button>
          <input ref={upload} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" aria-label={`Upload a picture for shot ${index + 1}`} onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('upload', () => api.uploadFrame(shot.id, f), () => { toast.success('Picture replaced.'); void refresh() }) }} />
          <Button size="sm" icon={<Upload size={15} />} onClick={() => upload.current?.click()}>Use my own picture</Button>
          {shot.history.length > 1 && <Button size="sm" icon={<History size={15} />} onClick={() => setDialog('history')}>Earlier pictures ({shot.history.length - 1})</Button>}
          {!isReal && <Button size="sm" icon={<ImagePlus size={15} />} onClick={() => setDialog('end')}>{shot.end_frame ? 'End picture set' : 'End picture'}</Button>}
        </div>
        {blockWithNext && <Button size="sm" icon={<Link2Off size={15} />} onClick={() => void run('ungroup', () => api.ungroup(id, shot.block), () => void refresh())}>Split block {shot.block}</Button>}
        {!blockWithNext && nextShot && !isReal && nextShot.type !== 'real_product' && !nextShot.text_card && (
          <Button size="sm" icon={<Link2 size={15} />} onClick={() => void run('group', () => api.group(id, [shot.id, nextShot.id]), () => void refresh())}>Make one clip with shot {index + 2}</Button>
        )}
      </div>

      <Dialog open={dialog === 'regen'} onClose={() => setDialog(null)} title={shot.frame ? `New picture for shot ${index + 1}` : `Picture for shot ${index + 1}`}>
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); setDialog(null); void run('regen', () => api.shotFrame(shot.id, note), (r) => { setNote(''); watch(r.job_id, { label: `Picture for shot ${index + 1}`, invalidate: [['ws', id]] }) }) }}>
          <p className="text-ink-soft">{isReal ? 'Real-product pictures are made free from your photo.' : 'The earlier picture stays in the history, so you can switch back.'}</p>
          {!isReal && <Field label="Extra direction (optional)">{(fid) => <textarea id={fid} className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Hold the bottle closer to the camera" />}</Field>}
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDialog(null)}>Cancel</Button><Button variant="primary" type="submit" cost={isReal ? 0 : frameEach}>Make picture</Button></div>
        </form>
      </Dialog>
      <Dialog open={dialog === 'history'} onClose={() => setDialog(null)} title={`Pictures for shot ${index + 1}`} wide>
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {shot.history.map((h: Json, i: number) => (
            <li key={h.id} className="grid gap-1.5">
              <Phone ratio={p.aspect} src={h.url} label={`Picture ${shot.history.length - i}`} />
              {h.current ? <span className="chip chip-sage justify-center">In use</span> : <Button size="sm" onClick={() => void run('use', () => api.useFrame(shot.id, h.id), () => { setDialog(null); void refresh() })}>Use this one</Button>}
              {h.note && <p className="text-[12.5px] text-ink-mute">“{h.note}”</p>}
            </li>
          ))}
        </ul>
      </Dialog>
      <Dialog open={dialog === 'end'} onClose={() => setDialog(null)} title={`End picture for shot ${index + 1}`}>
        <div className="grid gap-3">
          <p className="text-ink-soft">The clip ends on this picture (models that support it). Leave it empty to let the model decide.</p>
          {shot.end_frame_url && <div className="w-[120px]"><Phone ratio={p.aspect} src={shot.end_frame_url} label="End picture" /></div>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!nextShot?.frame} onClick={() => void run('end-next', () => api.endFrame(shot.id, 'next'), () => { setDialog(null); void refresh() })}>Use the next shot’s picture</Button>
            <input ref={endUpload} className="sr-only" type="file" accept="image/*" aria-label="Upload an end picture" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('end-up', () => api.uploadFrame(shot.id, f, 'end'), () => { setDialog(null); void refresh() }) }} />
            <Button icon={<Upload size={15} />} onClick={() => endUpload.current?.click()}>Upload one</Button>
            <Button icon={<Sparkles size={15} />} cost={frameEach} onClick={() => void run('end-gen', () => api.shotFrame(shot.id, 'Final moment of this shot', 'end'), (r) => { setDialog(null); watch(r.job_id, { label: 'End picture', invalidate: [['ws', id]] }) })}>Make one</Button>
            {shot.end_frame && <Button variant="danger" onClick={() => void run('end-none', () => api.endFrame(shot.id, 'none'), () => { setDialog(null); void refresh() })}>Remove it</Button>}
          </div>
        </div>
      </Dialog>
    </li>
  )
}

type Workspace = StageProps['ws']

function TextCard({ shot, index, total, id, refresh, ws }: { shot: Json; index: number; total: number; id: string; refresh: () => Promise<unknown>; ws: Workspace }) {
  const { run } = useAction()
  const reorder = (delta: number) => {
    const ids = ws.shots.map((s) => s.id)
    ;[ids[index], ids[index + delta]] = [ids[index + delta], ids[index]]
    void run('reorder', () => api.reorder(id, ids), () => void refresh())
  }
  return (
    <li className="card-flat grid gap-3 bg-lilac/50 p-4 sm:grid-cols-[minmax(0,1fr)_120px_auto] sm:items-end" aria-label={`Text card ${index + 1}`}>
      <Field label={`Text card (position ${index + 1})`}>{(fid) => <input id={fid} className="input" defaultValue={shot.onscreen} key={shot.onscreen} onBlur={(e) => { if (e.target.value !== shot.onscreen) void run('card', () => api.updateShot(shot.id, { onscreen: e.target.value }), () => void refresh()) }} />}</Field>
      <Field label="Seconds">{(fid) => <input id={fid} className="input" type="number" min={1} step={0.5} defaultValue={shot.duration} onBlur={(e) => { if (Number(e.target.value) !== shot.duration) void run('dur', () => api.updateShot(shot.id, { duration: Number(e.target.value) }), () => void refresh()) }} />}</Field>
      <div className="flex gap-1.5">
        <Button size="sm" iconOnly aria-label="Move text card up" icon={<ArrowUp size={16} />} disabled={index === 0} onClick={() => reorder(-1)} />
        <Button size="sm" iconOnly aria-label="Move text card down" icon={<ArrowDown size={16} />} disabled={index === total - 1} onClick={() => reorder(1)} />
        <ConfirmButton label="Delete text card" icon={<Trash2 size={15} />} iconOnly onConfirm={() => void run('del', () => api.deleteShot(shot.id), () => void refresh())} />
      </div>
    </li>
  )
}

export function StoryboardStage({ ws, refresh, id }: StageProps) {
  const p = ws.project
  const navigate = useNavigate()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [redraft, setRedraft] = useState(false)
  const [cardText, setCardText] = useState('')
  const [addCard, setAddCard] = useState(false)
  const shots = ws.shots
  const key = [id, shots.length, shots.map((s) => `${s.frame_basis}${s.frame}${s.type}`).join('|').length, p.actor_id, p.models?.image_edit, p.models?.image_to_video, p.voice_mode]
  const est = useQuery({ queryKey: ['sb-estimate', ...key], queryFn: () => api.sbEstimate(id) })
  const draftEst = useQuery({ queryKey: ['clip-est', 'draft', ...key], queryFn: () => api.clipEstimate(id, 'draft'), enabled: shots.length > 0 })
  const finalEst = useQuery({ queryKey: ['clip-est', 'final', ...key], queryFn: () => api.clipEstimate(id, 'final'), enabled: shots.length > 0 })
  const actors = useQuery({ queryKey: ['actors'], queryFn: api.actors })
  const frames = est.data?.frames
  const draft = est.data?.draft
  const needFrames = frames?.available ? frames.shots : 0
  const allApproved = shots.length > 0 && shots.every((s) => s.approved)
  const working = ws.jobs.some((j) => (j.status === 'queued' || j.status === 'running') && (j.kind === 'frame' || j.kind === 'draft_storyboard'))
  const hasScript = !!p.script?.trim()
  const startDraft = (replace: boolean) => run('draft', () => api.draft(id, replace), (r) => watch(r.job_id, { label: 'Drafting the storyboard', invalidate: [['ws', id]] }))
  return (
    <div className="grid gap-6">
      <Missing stage="storyboard" ws={ws} />
      <div className="card flex flex-wrap items-end gap-4 p-4">
        <div className="min-w-[200px] flex-1">
          <h2>Storyboard</h2>
          <p className="text-[14.5px] text-ink-soft">Each shot gets a picture. The picture you approve becomes the first frame of its video clip.</p>
        </div>
        <Field label="Actor" className="w-full sm:w-[220px]">
          {(fid) => (
            <select id={fid} className="input" value={p.actor_id && !p.actor_removed ? p.actor_id : ''} onChange={(e) => void run('actor', () => api.changeActor(id, e.target.value || null), () => { toast.message('Actor changed. Shots with a person need new pictures and approval.'); void refresh() })}>
              <option value="">No actor</option>
              {(actors.data?.actors ?? []).map((a: Json) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
        </Field>
        {shots.length === 0
          ? <Button variant="primary" icon={<Sparkles size={17} />} disabled={!hasScript || (draft && !draft.available)} cost={draft?.available ? draft.total.amount : undefined} busy={busy === 'draft' || working} onClick={() => void startDraft(false)}>Draft the storyboard</Button>
          : <Button icon={<RefreshCw size={16} />} cost={draft?.available ? draft.total.amount : undefined} disabled={draft && !draft.available} onClick={() => setRedraft(true)}>Redraft</Button>}
      </div>
      {draft && !draft.available && <Note tone="clay">{draft.message}</Note>}
      {shots.length === 0 && !working && <Note tone="sage">Draft turns your script into shots: who is on screen, what happens, and which words are said. Every word of the script lands in exactly one shot.</Note>}
      {ws.warnings.map((w) => <Note key={w} tone="butter">{w}</Note>)}

      <ol className="grid gap-5">
        {shots.map((s, i) => (
          <div key={s.id} className="grid gap-3">
            {s.text_card ? <TextCard shot={s} index={i} total={shots.length} id={id} refresh={refresh} ws={ws} /> : <ShotCard shot={s} index={i} total={shots.length} ws={ws} id={id} refresh={refresh} frameEach={frames?.available ? frames.each : null} busyShot={false} />}
            <div className="flex justify-center gap-2">
              <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => void run('add', () => api.addShot(id, { type: 'cutaway' }, s.id), () => void refresh())}>Add a shot here</Button>
              <Button size="sm" variant="ghost" icon={<Type size={14} />} onClick={() => { setAddCard(true); sessionStorage.setItem('card-after', s.id) }}>Add a text card here</Button>
            </div>
          </div>
        ))}
      </ol>

      <Dialog open={redraft} onClose={() => setRedraft(false)} title="Redraft the storyboard?">
        <p className="mb-4 text-ink-soft">This replaces every shot, picture and approval with a fresh draft from the script. Pictures you already paid for stay in your history only if you keep this storyboard.</p>
        <div className="flex justify-end gap-2"><Button variant="primary" onClick={() => setRedraft(false)}>Keep my storyboard</Button><Button variant="danger" cost={draft?.available ? draft.total.amount : undefined} onClick={() => { setRedraft(false); void startDraft(true) }}>Redraft</Button></div>
      </Dialog>
      <Dialog open={addCard} onClose={() => setAddCard(false)} title="Add a text card">
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (cardText.trim()) { setAddCard(false); void run('card', () => api.addCard(id, cardText, sessionStorage.getItem('card-after') ?? undefined), () => { setCardText(''); void refresh() }) } }}>
          <p className="text-ink-soft">A full-screen card of plain text between shots, drawn by the app so the letters are always exact.</p>
          <Field label="Text">{(fid) => <input id={fid} className="input" value={cardText} onChange={(e) => setCardText(e.target.value)} placeholder="Day 1 vs day 21" />}</Field>
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setAddCard(false)}>Cancel</Button><Button variant="primary" type="submit" disabled={!cardText.trim()}>Add card</Button></div>
        </form>
      </Dialog>

      <Console info={shots.length === 0 ? <>No shots yet.</> : (
        <span className="mono">
          Pictures {needFrames ? money(frames.total.amount) : 'done'} · Draft clips {draftEst.data?.available ? money(draftEst.data.total.amount) : '…'} · Final clips {finalEst.data?.available ? money(finalEst.data.total.amount) : '…'}
          {draftEst.data?.total?.partial ? ' + unknown' : ''}
        </span>
      )}>
        <Button icon={<Sparkles size={16} />} disabled={shots.length === 0 || needFrames === 0 || !frames?.available} cost={needFrames ? frames.total.amount : undefined} busy={busy === 'frames'} onClick={() => run('frames', () => api.frames(id), (r) => watch(r.job_ids, { label: `Making ${r.count} pictures`, invalidate: [['ws', id]] }))}>{needFrames ? `Make ${needFrames} picture${needFrames === 1 ? '' : 's'}` : 'Pictures made'}</Button>
        <Button icon={<Check size={16} />} disabled={shots.length === 0 || allApproved} busy={busy === 'approve-all'} onClick={() => run('approve-all', () => api.approveAll(id), () => { toast.success('Everything approved.'); void refresh() })}>Approve all</Button>
        <Button variant="primary" icon={<ArrowRight size={17} />} disabled={!allApproved} onClick={() => navigate('../clips', { relative: 'path' })}>Next: Clips</Button>
      </Console>
    </div>
  )
}

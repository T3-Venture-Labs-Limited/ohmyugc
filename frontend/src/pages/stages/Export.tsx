import { useQuery } from '@tanstack/react-query'
import { Download, Film, Music, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, type Json } from '../../api'
import { Button, Console, Field, Note, Phone, StatusChip, Switch, fmtSeconds, useAction, useJobWatch } from '../../components/ui'
import { Missing, type StageProps } from '../Project'

export function ExportStage({ ws, refresh, id }: StageProps) {
  const p = ws.project
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const music = useRef<HTMLInputElement>(null)
  const bg = useRef<HTMLInputElement>(null)
  const styles = useQuery({ queryKey: ['caption-styles'], queryFn: api.captionStyles })
  const ready = ws.progress.length > 0 && ws.progress.every((u) => u.status === 'done')
  const planKey = [id, ws.progress.map((u) => u.take?.id).join(), p.crossfade, p.end_card?.on, p.end_card?.seconds]
  const plan = useQuery({ queryKey: ['plan', ...planKey], queryFn: () => api.plan(id), enabled: ready })
  const card = p.end_card ?? {}
  const [quality, setQuality] = useState<'draft' | 'final'>('final')
  const hooks = ws.variants
  const keptHooks = hooks.filter((h) => h.kept)
  const exporting = ws.jobs.find((j) => (j.kind === 'assemble' || j.kind === 'export_all') && (j.status === 'queued' || j.status === 'running'))
  const last: Json | undefined = ws.exports?.[0]
  const files: Json[] = last ? (last.kind === 'export_all' ? last.result.files : [{ name: 'main', ...last.result }]) : []
  const patch = (values: Json) => run('patch', () => api.updateProject(id, values), () => void refresh())
  const patchCard = (values: Json) => patch({ end_card: { ...card, ...values } })
  const total = plan.data?.duration ?? 0
  const vp = ws.variant_progress ?? {}
  const hookReady = (hid: string) => (vp[hid] ?? []).length > 0 && vp[hid].every((u) => u.status === 'done')
  const missingHooks = keptHooks.filter((h) => !hookReady(h.id))
  return (
    <div className="grid gap-6">
      <Missing stage="export" ws={ws} />
      <section className="card grid gap-3 p-5" aria-labelledby="timeline">
        <h2 id="timeline">Your ad{plan.data ? `, ${fmtSeconds(total)}` : ''}</h2>
        {plan.data ? (
          <div className="flex h-12 w-full overflow-hidden rounded-[12px] border-2 border-ink" role="img" aria-label={`Timeline: ${plan.data.segments.length} shots${plan.data.end_card ? ' and an end card' : ''}`}>
            {plan.data.segments.map((s: Json, i: number) => (
              <div key={i} style={{ width: `${(s.length / total) * 100}%` }} className={`grid place-items-center border-r-2 border-ink text-[13px] font-bold ${s.kind === 'card' ? 'bg-lilac' : 'bg-sage'}`}>{i + 1}</div>
            ))}
            {plan.data.end_card && <div style={{ width: `${(plan.data.end_card.length / total) * 100}%` }} className="grid place-items-center bg-butter text-[13px] font-bold">End</div>}
          </div>
        ) : <p className="text-ink-soft">{ready ? 'Working out the timeline…' : 'Make every clip first, then the timeline appears here.'}</p>}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card grid gap-4 p-5" aria-labelledby="captions">
          <h2 id="captions">Captions and sound</h2>
          <div className="flex items-center justify-between gap-3"><span className="font-bold">Word-by-word captions</span><Switch checked={!!p.caption_on} label="Captions" onChange={(v) => void patch({ caption_on: v })} /></div>
          {p.caption_on ? (
            <Field label="Caption style">
              {(fid) => <select id={fid} className="input" value={p.caption_style} onChange={(e) => void patch({ caption_style: e.target.value })}>{(styles.data?.styles ?? []).map((s: Json) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
            </Field>
          ) : null}
          <div>
            <span className="label">Music (optional)</span>
            <input ref={music} className="sr-only" type="file" accept="audio/*" aria-label="Music file" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('music', () => api.projectMusic(id, f), () => { toast.success('Music added.'); void refresh() }) }} />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" icon={<Music size={15} />} onClick={() => music.current?.click()} busy={busy === 'music'}>{p.music ? 'Replace music' : 'Add music'}</Button>
              {p.music && <Button size="sm" variant="danger" onClick={() => void patch({ music: null })}>Remove</Button>}
            </div>
            {p.music_url && <audio src={p.music_url} controls className="mt-2 h-10 w-full" aria-label="Music preview" />}
            {p.music && <Field label={`Music level (${Math.round(p.music_volume * 100)}%)`} help="It drops automatically while someone is speaking.">{(fid) => <input id={fid} type="range" min={5} max={60} value={Math.round(p.music_volume * 100)} className="w-full accent-clay" onChange={(e) => void patch({ music_volume: Number(e.target.value) / 100 })} />}</Field>}
          </div>
          <Field label="Between shots">
            {(fid) => <select id={fid} className="input" value={p.crossfade} onChange={(e) => void patch({ crossfade: Number(e.target.value) })}><option value={0}>Hard cuts</option><option value={0.15}>Quick crossfade</option><option value={0.3}>Soft crossfade</option></select>}
          </Field>
        </section>

        <section className="card grid gap-4 p-5" aria-labelledby="end">
          <div className="flex items-center justify-between gap-3"><h2 id="end">End card</h2><Switch checked={!!card.on} label="End card" onChange={(v) => void patchCard({ on: v })} /></div>
          {card.on ? (
            <>
              <p className="text-[14.5px] text-ink-soft">Your real product photo, with the name and call to action drawn as exact text.</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Call to action">{(fid) => <input id={fid} className="input" key={card.cta} defaultValue={card.cta ?? ''} onBlur={(e) => { if (e.target.value !== (card.cta ?? '')) void patchCard({ cta: e.target.value }) }} placeholder="Shop now" />}</Field>
                <Field label="Offer">{(fid) => <input id={fid} className="input" key={card.offer} defaultValue={card.offer ?? ''} onBlur={(e) => { if (e.target.value !== (card.offer ?? '')) void patchCard({ offer: e.target.value }) }} placeholder="20% off this week" />}</Field>
                <Field label="Seconds">{(fid) => <input id={fid} className="input" type="number" min={1.5} max={5} step={0.5} key={card.seconds} defaultValue={card.seconds ?? 3} onBlur={(e) => { if (Number(e.target.value) !== card.seconds) void patchCard({ seconds: Number(e.target.value) }) }} />}</Field>
                <Field label="Background">
                  {(fid) => <select id={fid} className="input" value={card.background ?? 'blur'} onChange={(e) => void patchCard({ background: e.target.value })}><option value="blur">Blurred shot</option><option value="brand">Solid colour</option><option value="image">My image</option></select>}
                </Field>
                <Field label="Button colour">{(fid) => <input id={fid} className="input h-11 p-1" type="color" value={card.button_color ?? '#ffe14d'} onChange={(e) => void patchCard({ button_color: e.target.value })} />}</Field>
                <Field label="Solid background colour">{(fid) => <input id={fid} className="input h-11 p-1" type="color" value={card.color ?? '#14151a'} onChange={(e) => void patchCard({ color: e.target.value })} />}</Field>
              </div>
              {(card.background === 'image') && (
                <div>
                  <input ref={bg} className="sr-only" type="file" accept="image/*" aria-label="Background image" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('bg', () => api.projectBackground(id, f), () => void refresh()) }} />
                  <Button size="sm" icon={<Upload size={15} />} onClick={() => bg.current?.click()}>{card.background_image ? 'Replace image' : 'Upload an image'}</Button>
                </div>
              )}
            </>
          ) : <p className="text-[14.5px] text-ink-soft">No end card. The ad ends on the last shot.</p>}
        </section>
      </div>

      <section className="card grid gap-3 p-5" aria-labelledby="hooks">
        <h2 id="hooks">Hook variants</h2>
        {hooks.length === 0 ? <p className="text-ink-soft">No hooks yet. Add some in the Script step to export several openings of the same ad.</p> : (
          <>
            <p className="text-[14.5px] text-ink-soft">Each kept hook becomes its own video that shares the rest of the ad. Only its first shot is made again.</p>
            <div className="flex flex-wrap items-center gap-2"><span className="label mb-0">Quality for hook clips</span>
              <div className="seg" role="radiogroup" aria-label="Quality for hook clips">{(['draft', 'final'] as const).map((q) => <button key={q} type="button" role="radio" aria-checked={quality === q} onClick={() => setQuality(q)}>{q === 'draft' ? 'Draft' : `Final (${p.final_resolution})`}</button>)}</div></div>
            <ul className="grid gap-2">
              {hooks.map((h) => (
                <li key={h.id} className="card-flat flex flex-wrap items-center gap-3 p-3">
                  <Switch checked={!!h.kept} label={`Export ${h.name}`} onChange={(v) => void api.updateHook(h.id, { kept: v }).then(refresh)} />
                  <div className="min-w-0 flex-1"><b>{h.name}</b><p className="truncate text-[14px] text-ink-soft">{h.hook}</p></div>
                  <StatusChip status={hookReady(h.id) ? 'done' : (vp[h.id] ?? []).some((u) => u.status === 'running' || u.status === 'queued') ? 'running' : 'none'} />
                  <Button size="sm" disabled={!ready || !h.kept} busy={busy === `hook-${h.id}`} onClick={() => void run(`hook-${h.id}`, () => api.render(id, { quality, variant_id: h.id }), (r) => watch(r.job_ids, { label: `Clip for ${h.name}`, invalidate: [['ws', id]] }))}>{hookReady(h.id) ? 'Make again' : 'Make hook clip'}</Button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {exporting && <Note tone="lilac"><span className="live-dot mr-2" aria-hidden />Exporting: <b>{exporting.stage || 'working'}</b></Note>}
      {files.length > 0 && !exporting && (
        <section className="card grid gap-4 p-5" aria-labelledby="done">
          <h2 id="done">Your export</h2>
          <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {files.map((f) => (
              <li key={f.path} className="grid gap-2">
                <Phone ratio={p.aspect} src={f.url} video label={`${f.name} export`} />
                <p className="mono break-all text-[12.5px] text-ink-mute">{f.path}</p>
                <div className="flex flex-wrap gap-2">
                  <a className="btn btn-sm btn-sage" href={`/api/projects/${id}/download/${f.media}?name=${encodeURIComponent(f.name === 'main' ? p.name : `${p.name} ${f.name}`)}`}><Download size={15} aria-hidden /> Download MP4</a>
                  {f.srt && <a className="btn btn-sm" href={`/api/projects/${id}/download/${f.srt}?name=${encodeURIComponent(p.name)}`}><Download size={15} aria-hidden /> Captions (.srt)</a>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Console info={ready ? <>Exporting is free: it runs on your computer.{missingHooks.length ? <> {missingHooks.length} kept hook{missingHooks.length === 1 ? ' has' : 's have'} no clip yet.</> : null}</> : <>Make every clip to export.</>}>
        <Button variant="primary" icon={<Film size={17} />} disabled={!ready || !!exporting} busy={busy === 'export'} onClick={() => run('export', () => api.assemble(id), (r) => watch(r.job_id, { label: 'Exporting your ad', invalidate: [['ws', id]] }))}>Export the ad</Button>
        {keptHooks.length > 0 && <Button icon={<Film size={16} />} disabled={!ready || !!exporting || missingHooks.length > 0} onClick={() => run('export-all', () => api.exportAll(id), (r) => watch(r.job_id, { label: `Exporting ${keptHooks.length + 1} videos`, invalidate: [['ws', id]] }))}>Export with {keptHooks.length} hook{keptHooks.length === 1 ? '' : 's'}</Button>}
      </Console>
    </div>
  )
}

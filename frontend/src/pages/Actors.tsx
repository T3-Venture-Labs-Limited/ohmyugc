import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Mic, Plus, Sparkles, Trash2, Upload, UserPlus } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, type Json, money } from '../api'
import { Button, ConfirmButton, Dialog, Empty, ErrorNote, Field, Note, Phone, Segmented, Spinner, useAction, useJobWatch } from '../components/ui'

const VOICE_PROVIDERS = [
  { value: '', label: 'Use the voice model chosen in Settings' },
  { value: 'elevenlabs', label: 'ElevenLabs' },
  { value: 'fish', label: 'Fish Audio' },
]

function NewActor({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [mode, setMode] = useState<'generate' | 'upload'>('generate')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [count, setCount] = useState(4)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const estimate = useQuery({ queryKey: ['actor-estimate', count], queryFn: () => api.actorEstimate(count), enabled: mode === 'generate' })
  const input = useRef<HTMLInputElement>(null)
  const reminder = 'You are responsible for having the right to use this person’s likeness, and for labelling AI-generated ads where platforms require it.'
  const go = () => {
    setError('')
    if (mode === 'upload') {
      if (!file) return setError('Choose a photo of the person.')
      void run('create', () => api.actorPhoto(name, description, file), (a) => { toast.success('Actor added.'); void qc.invalidateQueries({ queryKey: ['actors'] }); onCreated(a.id); onClose() })
    } else {
      if (!description.trim()) return setError('Describe the actor first, for example: woman in her late 20s, natural makeup, casual knit sweater.')
      void run('create', () => api.actorGenerate({ name, description, count }), (r) => {
        void qc.invalidateQueries({ queryKey: ['actors'] })
        watch(r.job_id, { label: `Making ${count} portraits`, invalidate: [['actors']], onDone: () => onCreated(r.actor.id) })
        onClose()
      })
    }
  }
  return (
    <Dialog open onClose={onClose} title="New actor" wide>
      <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); go() }}>
        <Segmented label="How to make the actor" value={mode} onChange={setMode} options={[{ value: 'generate', label: 'Describe them' }, { value: 'upload', label: 'Upload a photo' }]} />
        <Field label="Name" help="Only you see this.">{(id) => <input id={id} className="input" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Maya" />}</Field>
        {mode === 'generate' ? (
          <>
            <Field label="What they look like" help="Age range, look, style and setting. Phone-selfie realism works best.">{(id) => <textarea id={id} className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="woman in her late 20s, natural makeup, casual knit sweater, bright kitchen" />}</Field>
            <Field label="How many to try">{(id) => <select id={id} className="input sm:max-w-[160px]" value={count} onChange={(e) => setCount(Number(e.target.value))}>{[2, 4, 6, 8].map((n) => <option key={n}>{n}</option>)}</select>}</Field>
            <p className="mono text-[14px]">{estimate.data?.available ? `About ${money(estimate.data.total.amount)} with ${estimate.data.model}` : estimate.data?.message ?? ''}</p>
          </>
        ) : (
          <>
            <Field label="Description (optional)" help="Helps keep the person looking the same across shots.">{(id) => <input id={id} className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="man in his 30s with a beard" />}</Field>
            <div>
              <span className="label">Photo</span>
              <input ref={input} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Photo of the person" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <Button icon={<Upload size={16} />} onClick={() => input.current?.click()}>{file ? file.name : 'Choose a photo'}</Button>
            </div>
            <Note tone="butter">{reminder}</Note>
          </>
        )}
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" busy={busy === 'create'} cost={mode === 'generate' && estimate.data?.available ? estimate.data.total.amount : undefined}>{mode === 'generate' ? 'Make portraits' : 'Add actor'}</Button>
        </div>
      </form>
    </Dialog>
  )
}

function VoicePicker({ actor, onSaved }: { actor: Json; onSaved: () => void }) {
  const { busy, run } = useAction()
  const [provider, setProvider] = useState<string>(actor.voice_provider ?? '')
  const [voice, setVoice] = useState<string>(actor.voice_id ?? '')
  const [search, setSearch] = useState('')
  const voices = useQuery({ queryKey: ['voices', provider, search], queryFn: () => api.voices(provider, search), enabled: !!provider, retry: false })
  const sample = useRef<HTMLInputElement>(null)
  const watch = useJobWatch()
  return (
    <section aria-labelledby="voice" className="grid gap-3">
      <h3 id="voice">Voice</h3>
      <p className="text-ink-soft">Used for voiceover and talking avatars. Pick the voice provider you have a key for, then a voice.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Voice provider">{(id) => <select id={id} className="input" value={provider} onChange={(e) => { setProvider(e.target.value); setVoice('') }}>{VOICE_PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}</select>}</Field>
        <Field label="Voice id" help="Choose from the list, or paste an id.">{(id) => <input id={id} className="input mono" value={voice} onChange={(e) => setVoice(e.target.value)} placeholder="voice id" />}</Field>
      </div>
      {provider && (
        <div className="grid gap-2">
          {provider === 'fish' && <Field label="Search Fish voices">{(id) => <input id={id} className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="warm female narrator" />}</Field>}
          {voices.isError && <ErrorNote>{(voices.error as Error).message}</ErrorNote>}
          <ul className="grid max-h-56 gap-1.5 overflow-auto pr-1" aria-label="Voices">
            {(voices.data?.voices ?? []).map((v: Json) => (
              <li key={v.id} className="flex flex-wrap items-center gap-2 rounded-[10px] border-2 border-ink/20 px-3 py-2">
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setVoice(v.id)} aria-pressed={voice === v.id}>
                  <b>{v.name}</b> {voice === v.id && <Check size={14} className="inline" aria-label="selected" />}
                  <span className="block truncate text-[13px] text-ink-mute">{v.description}</span>
                </button>
                {v.preview_url && <audio src={v.preview_url} controls preload="none" className="h-9 max-w-[200px]" aria-label={`Preview ${v.name}`} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" busy={busy === 'voice'} onClick={() => run('voice', () => api.updateActor(actor.id, { voice_provider: provider, voice_id: voice }), () => { toast.success('Voice saved.'); onSaved() })}>Save voice</Button>
        <Button icon={<Mic size={16} />} disabled={!voice} onClick={() => run('sample', () => api.actorVoiceGenerate(actor.id), (r) => watch(r.job_id, { label: 'Recording a voice sample', invalidate: [['actors']], onDone: onSaved }))}>Make a voice sample</Button>
        <input ref={sample} className="sr-only" type="file" accept="audio/*" aria-label="Upload a voice sample" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('upload', () => api.actorVoiceUpload(actor.id, f), () => { toast.success('Voice sample saved.'); onSaved() }) }} />
        <Button icon={<Upload size={16} />} onClick={() => sample.current?.click()}>Upload a voice sample</Button>
      </div>
      <p className="help">A voice sample lets video models that accept one (like Seedance 2.5) keep the same voice in every talking shot.</p>
      {actor.voice_sample_url && <audio src={actor.voice_sample_url} controls className="h-10 w-full max-w-sm" aria-label="Voice sample" />}
    </section>
  )
}

function ActorDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient()
  const watch = useJobWatch()
  const { run } = useAction()
  const actor = useQuery({ queryKey: ['actor', id], queryFn: () => api.actor(id), refetchInterval: 3000 })
  const [name, setName] = useState<string | null>(null)
  const [description, setDescription] = useState<string | null>(null)
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['actor', id] }); void qc.invalidateQueries({ queryKey: ['actors'] }) }
  const a = actor.data
  if (!a) return <Dialog open onClose={onClose} title="Actor"><Spinner /></Dialog>
  return (
    <Dialog open onClose={onClose} title={a.name} wide>
      <div className="grid gap-6">
        <section aria-labelledby="refs" className="grid gap-2">
          <h3 id="refs">Pictures used for this actor</h3>
          <p className="text-ink-soft">The first picture is the main portrait. All of them are given to the image model whenever this actor appears.</p>
          {a.ref_urls.length === 0 && <Note tone="butter">No portrait chosen yet. Pick one of the candidates below.</Note>}
          <ul className="flex flex-wrap gap-3">
            {a.ref_urls.map((u: string, i: number) => <li key={u} className="grid w-[110px] gap-1"><Phone ratio="3:4" src={u} label={i === 0 ? 'Main portrait' : `Reference ${i + 1}`} />{i === 0 ? <span className="chip chip-sage justify-center">Main portrait</span> : <span className="chip justify-center">Reference</span>}</li>)}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={<Sparkles size={15} />} disabled={a.refs.length === 0} onClick={() => run('ref', () => api.actorReference(id, 'Side profile, head and shoulders'), (r) => watch(r.job_id, { label: 'Making a side view', invalidate: [['actor', id]] }))}>Add a side view</Button>
            {a.description && <Button size="sm" icon={<Plus size={15} />} onClick={() => run('more', () => api.actorMore(id, 4), (r) => watch(r.job_id, { label: 'Making 4 more portraits', invalidate: [['actor', id]] }))}>4 more candidates</Button>}
          </div>
        </section>
        {a.candidate_urls.length > 0 && (
          <section aria-labelledby="cands" className="grid gap-2">
            <h3 id="cands">Candidates</h3>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {a.candidate_urls.map((c: Json, i: number) => (
                <li key={`${c.media}-${i}`} className="grid gap-1.5">
                  <Phone ratio="3:4" src={c.url} label={`Candidate ${i + 1}`} />
                  <Button size="sm" variant="sage" onClick={() => run('acc', () => api.actorAccept(id, c.media, a.refs.length === 0 || c.kind === 'portrait'), refresh)}>{a.refs.length === 0 || c.kind === 'portrait' ? 'Use as main' : 'Use as reference'}</Button>
                  <Button size="sm" variant="ghost" onClick={() => run('dis', () => api.actorDiscard(id, c.media), refresh)}>Discard</Button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section aria-labelledby="details" className="grid gap-3 sm:grid-cols-2">
          <h3 id="details" className="sm:col-span-2">Details</h3>
          <Field label="Name">{(fid) => <input id={fid} className="input" maxLength={120} value={name ?? a.name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Description">{(fid) => <input id={fid} className="input" value={description ?? a.description} onChange={(e) => setDescription(e.target.value)} />}</Field>
          <div className="sm:col-span-2"><Button disabled={name === null && description === null} onClick={() => run('save', () => api.updateActor(id, { name: name ?? a.name, description: description ?? a.description }), () => { setName(null); setDescription(null); toast.success('Saved.'); refresh() })}>Save details</Button></div>
        </section>
        <VoicePicker actor={a} onSaved={refresh} />
        <Note tone="butter">{a.likeness_reminder}</Note>
        <div className="flex justify-between gap-2">
          <ConfirmButton label="Delete actor" confirmLabel="Yes, delete the actor" onConfirm={() => run('del', () => api.deleteActor(id), () => { toast.success('Actor deleted. Ads that used them keep their pictures and clips.'); refresh(); onClose() })} />
          <Button variant="primary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </Dialog>
  )
}

export function ActorsPage() {
  const actors = useQuery({ queryKey: ['actors'], queryFn: api.actors, refetchInterval: 4000 })
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const list: Json[] = actors.data?.actors ?? []
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>Actors</h1>
          <p className="mt-1 max-w-2xl text-ink-soft">The people in your ads. Make one from a description or a photo, give them a voice, and reuse them in every ad.</p>
        </div>
        <Button variant="primary" icon={<UserPlus size={18} />} onClick={() => setCreating(true)}>New actor</Button>
      </div>
      {actors.isLoading ? <Spinner /> : list.length === 0 ? (
        <Empty title="No actors yet" action={<Button variant="primary" onClick={() => setCreating(true)}>Make your first actor</Button>}>Describe a person and pick the portrait you like best, or upload a photo.</Empty>
      ) : (
        <ul className="grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-5">
          {list.map((a) => (
            <li key={a.id} className="card flex flex-col gap-2 p-3">
              <button type="button" className="rounded-[16px] text-left" onClick={() => setOpen(a.id)} aria-label={`Open ${a.name}`}><Phone ratio="3:4" src={a.portrait_url} empty="Choosing portrait…" label={a.name} /></button>
              <b className="break-words">{a.name}</b>
              <p className="text-[13.5px] text-ink-mute">{a.voice_id ? `Voice: ${a.voice_provider || 'auto'}` : 'No voice yet'}</p>
              <div className="mt-auto flex flex-wrap gap-2"><Button size="sm" className="flex-1" onClick={() => setOpen(a.id)}>Open</Button>
                <ConfirmButton label={`Delete ${a.name}`} icon={<Trash2 size={14} />} iconOnly onConfirm={() => api.deleteActor(a.id).then(() => actors.refetch()).catch((e: Error) => toast.error(e.message))} /></div>
            </li>
          ))}
        </ul>
      )}
      {creating && <NewActor onClose={() => setCreating(false)} onCreated={(id) => setOpen(id)} />}
      {open && <ActorDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

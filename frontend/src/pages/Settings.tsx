import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useLocation } from 'react-router'
import { toast } from 'sonner'
import { api, type Json } from '../api'
import { Button, Field, Note, Spinner, useAction } from '../components/ui'

const PROVIDERS: { id: string; name: string; key: string; what: string; url: string }[] = [
  { id: 'replicate', name: 'Replicate', key: 'replicate_api_key', what: 'Images, video, avatars, lip sync, background removal.', url: 'https://replicate.com/account/api-tokens' },
  { id: 'fal', name: 'fal', key: 'fal_api_key', what: 'Images, video, avatars, lip sync, background removal.', url: 'https://fal.ai/dashboard/keys' },
  { id: 'openrouter', name: 'OpenRouter', key: 'openrouter_api_key', what: 'Writing, the product check, and image and video models. One key can run most of an ad.', url: 'https://openrouter.ai/keys' },
  { id: 'elevenlabs', name: 'ElevenLabs', key: 'elevenlabs_api_key', what: 'Voices for voiceover and talking avatars.', url: 'https://elevenlabs.io/app/settings/api-keys' },
  { id: 'fish', name: 'Fish Audio', key: 'fish_api_key', what: 'Voices for voiceover and talking avatars.', url: 'https://fish.audio/go-api/' },
]

const TASKS: [string, string][] = [
  ['llm', 'Writing and storyboards'], ['vision_check', 'Product check'], ['image_edit', 'Storyboard frames'], ['image_generation', 'Actor portraits'],
  ['image_to_video', 'Video clips'], ['speech', 'Voices'], ['talking_avatar', 'Talking avatars'], ['background_removal', 'Product cutouts'],
]

function KeyRow({ p, state }: { p: (typeof PROVIDERS)[number]; state: Json }) {
  const qc = useQueryClient()
  const { busy, run } = useAction()
  const [value, setValue] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['settings'] })
  const set = state?.set
  return (
    <li className="card-flat grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3>{p.name}</h3>
          {set ? <span className="chip chip-sage"><Check size={14} aria-hidden /> Connected {state.masked}{state.source === 'environment' ? ' (from environment)' : ''}</span> : <span className="chip">No key yet</span>}
        </div>
        <p className="mt-1 text-[14.5px] text-ink-soft">{p.what}{' '}
          <a className="inline-flex items-center gap-1 font-bold underline" href={p.url} target="_blank" rel="noreferrer">Get a key<ExternalLink size={13} aria-hidden /></a>
        </p>
        <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (value.trim()) void run(`save-${p.id}`, () => api.saveSettings({ [p.key]: value }), () => { setValue(''); toast.success(`${p.name} key saved.`); void refresh() }) }}>
          <label className="sr-only" htmlFor={`key-${p.id}`}>{p.name} API key</label>
          <input id={`key-${p.id}`} className="input min-w-[220px] flex-1 sm:max-w-sm" type="password" autoComplete="off" spellCheck={false} placeholder={set ? 'Paste a new key to replace it' : 'Paste your API key'} value={value} onChange={(e) => setValue(e.target.value)} />
          <Button type="submit" variant="primary" disabled={!value.trim()} busy={busy === `save-${p.id}`}>Save key</Button>
        </form>
      </div>
      <div className="flex flex-wrap gap-2 sm:flex-col">
        <Button size="sm" disabled={!set} busy={busy === `test-${p.id}`} onClick={() => run(`test-${p.id}`, () => api.testKey(p.id), (r) => (r.ok ? toast.success(`${p.name}: connected.`) : toast.error(r.message, { duration: 9000 })))}>Test</Button>
        <Button size="sm" variant="danger" disabled={!set || state.source === 'environment'} busy={busy === `clear-${p.id}`} onClick={() => run(`clear-${p.id}`, () => api.saveSettings({ [p.key]: '' }), () => { toast.success(`${p.name} key removed.`); void refresh() })}>Remove</Button>
      </div>
    </li>
  )
}

export function SettingsPage() {
  const qc = useQueryClient()
  const location = useLocation()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const models = useQuery({ queryKey: ['models', 'connected'], queryFn: () => api.models(undefined, true) })
  const doctor = useQuery({ queryKey: ['doctor'], queryFn: () => api.doctor() })
  const { busy, run } = useAction()
  const [draft, setDraft] = useState<Json>({})
  if (settings.isLoading || !settings.data) return <Spinner />
  const s = settings.data.settings
  const connected: string[] = settings.data.connected
  const defaults: Record<string, string> = settings.data.defaults
  const value = (k: string) => (k in draft ? draft[k] : s[k].value)
  const dirty = Object.keys(draft).length > 0
  const discovery = models.data?.discovery ?? {}
  const list: Json[] = models.data?.models ?? []
  const problems: Json[] = models.data?.problems ?? []
  return (
    <div className="grid gap-8">
      <div>
        <h1>Settings</h1>
        <p className="mt-1 max-w-2xl text-ink-soft">Your keys stay on this computer. oh-my-ugc never shows a full key again after you save it.</p>
      </div>
      {connected.length === 0 && (
        <Note tone="butter">
          <b>Start here.</b> Add a key, then choose the model each step should use under Models. An OpenRouter key alone can serve writing, the product check, images and video. Add Replicate or fal for talking avatars and cutouts, and ElevenLabs or Fish Audio for voices.
          {location.state?.firstRun ? '' : ''}
        </Note>
      )}
      <section aria-labelledby="keys" className="grid gap-3">
        <h2 id="keys">Provider keys</h2>
        <ul className="grid gap-3">{PROVIDERS.map((p) => <KeyRow key={p.id} p={p} state={s[p.key]} />)}</ul>
      </section>

      <section aria-labelledby="models" className="grid gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="models">Models</h2>
            <p className="text-ink-soft">Nothing is chosen for you: everyone prefers different models and prices. Pick the model each step should use. You can still pick another per ad in its Brief.</p>
          </div>
          <Button size="sm" icon={<RefreshCw size={15} />} busy={busy === 'refresh'} disabled={connected.length === 0} onClick={() => run('refresh', api.refreshModels, () => { toast.success('Model list refreshed.'); void qc.invalidateQueries({ queryKey: ['models'] }) })}>Find new models</Button>
        </div>
        <div className="card-flat grid gap-4 p-4 sm:grid-cols-2">
          {TASKS.map(([task, label]) => {
            const options = list.filter((m) => m.task === task && m.usable)
            return (
              <Field key={task} label={label} help={options.length === 0 ? models.data?.requirements?.[task] : defaults[task] ? undefined : 'Not chosen yet. This step will not run until you choose.'}>
                {(id) => (
                  <select id={id} className="input" disabled={options.length === 0} value={defaults[task] ?? ''} onChange={(e) => run(`default-${task}`, () => api.setDefaults({ [task]: e.target.value }), () => { void qc.invalidateQueries({ queryKey: ['settings'] }) })}>
                    <option value="">Choose a model…</option>
                    {options.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.provider}){m.discovered ? ' · discovered' : ''}</option>)}
                  </select>
                )}
              </Field>
            )
          })}
        </div>
        <p className="help">
          {Object.entries(discovery as Json).filter(([, d]) => d.count || d.error).map(([p, d]) => `${p}: ${d.count} discovered${d.error ? ` (${d.error})` : ''}`).join(' · ') || 'No discovered models yet.'}
        </p>
        {problems.length > 0 && <Note tone="clay">Some of your own model files could not be read: {problems.map((p) => `${p.file.split('/').pop()} (${p.reason})`).join('; ')}</Note>}
      </section>

      <section aria-labelledby="defaults" className="grid gap-3">
        <h2 id="defaults">Defaults</h2>
        <div className="card-flat grid gap-4 p-4 sm:grid-cols-3">
          <Field label="Jobs at once per provider" help="How many requests run in parallel.">{(id) => <input id={id} className="input" type="number" min={1} max={16} value={value('concurrency')} onChange={(e) => setDraft({ ...draft, concurrency: e.target.value })} />}</Field>
          <Field label="Budget for new ads ($)" help="Leave empty for no limit.">{(id) => <input id={id} className="input" inputMode="decimal" placeholder="No limit" value={value('default_budget')} onChange={(e) => setDraft({ ...draft, default_budget: e.target.value })} />}</Field>
          <Field label="Caption style for new ads">{(id) => <input id={id} className="input" value={value('caption_style')} onChange={(e) => setDraft({ ...draft, caption_style: e.target.value })} />}</Field>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" disabled={!dirty} busy={busy === 'save'} onClick={() => run('save', () => api.saveSettings(draft), () => { setDraft({}); toast.success('Saved.'); void qc.invalidateQueries({ queryKey: ['settings'] }) })}>Save defaults</Button>
          {dirty && <Button variant="ghost" onClick={() => setDraft({})}>Discard changes</Button>}
        </div>
      </section>

      <section aria-labelledby="health" className="grid gap-3">
        <h2 id="health">Setup check</h2>
        <ul className="card-flat divide-y-2 divide-ink/10">
          {(doctor.data?.checks ?? []).filter((c: Json) => !c.name.startsWith('key_')).map((c: Json) => (
            <li key={c.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3">
              <span className={c.ok ? 'chip chip-sage' : c.required ? 'chip chip-bad' : 'chip chip-butter'}>{c.ok ? 'OK' : c.required ? 'Fix this' : 'Note'}</span>
              <b>{c.label}</b>
              <span className="min-w-0 break-words text-[14.5px] text-ink-soft">{c.detail}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

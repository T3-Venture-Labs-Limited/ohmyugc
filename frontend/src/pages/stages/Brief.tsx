import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, type Json } from '../../api'
import { Button, Console, Field, Note, Phone, Segmented, cn } from '../../components/ui'
import type { StageProps } from '../Project'

const FORMATS = [
  ['talking_head', 'Talking head', 'One person talks to camera and holds up the product.'],
  ['problem_solution', 'Problem and solution', 'Show the frustration, then the product as the fix.'],
  ['unboxing', 'Unboxing', 'First impressions while opening and trying it.'],
  ['demo_voiceover', 'Demo with voiceover', 'The product in use while a voice explains.'],
  ['testimonial', 'Testimonial', 'A customer story: before, after, honest and specific.'],
] as const

const VOICE_MODES = [
  ['voiceover', 'Voiceover', 'A voice you pick speaks each line over silent video. Same voice in every shot. The safe choice.'],
  ['native', 'The video model speaks', 'The model says the line itself, in sync. The voice can differ between shots unless the model takes a voice sample.'],
  ['avatar', 'Talking avatar', 'A voice speaks each line and an avatar model animates the picture to match. Needs Replicate or fal.'],
] as const

const MODEL_STEPS: [string, string][] = [
  ['llm', 'Writing and storyboard'], ['image_edit', 'Storyboard frames'], ['image_to_video', 'Video clips'], ['speech', 'Voices'],
  ['talking_avatar', 'Talking avatars'], ['lipsync', 'Lip sync (optional, avatar mode)'], ['vision_check', 'Product check'], ['background_removal', 'Cutouts'], ['image_generation', 'Actor portraits'],
]

export function BriefStage({ ws, refresh, id }: StageProps) {
  const p = ws.project
  const navigate = useNavigate()
  const brands = useQuery({ queryKey: ['brands'], queryFn: api.brands })
  const products = useQuery({ queryKey: ['products', p.brand_id], queryFn: () => api.products(p.brand_id), enabled: !!p.brand_id })
  const actors = useQuery({ queryKey: ['actors'], queryFn: api.actors })
  const models = useQuery({ queryKey: ['models', 'connected'], queryFn: () => api.models(undefined, true) })
  const styles = useQuery({ queryKey: ['caption-styles'], queryFn: api.captionStyles })
  const patch = (values: Json) => api.updateProject(id, values).then(refresh).catch((e: Error) => toast.error(e.message))
  const commitText = (key: string) => (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const v = e.target.value
    if (v !== (p[key] ?? '')) void patch({ [key]: v })
  }
  const resolved: Json = p.resolved_models ?? {}
  const brandList: Json[] = brands.data?.brands ?? []
  const productList: Json[] = products.data?.products ?? []
  const actorList: Json[] = actors.data?.actors ?? []
  const missing = [!p.brand_id && 'a brand', !p.product_id && 'a product', !p.actor_id && 'an actor'].filter(Boolean) as string[]
  const noKeys = models.data && !(models.data.models ?? []).some((m: Json) => m.usable)
  return (
    <div className="grid gap-6">
      {noKeys && <Note tone="clay">No provider is connected yet, so nothing can be generated. <Link className="font-bold underline" to="/settings">Add a key in Settings</Link>.</Note>}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="grid gap-6">
          <section className="card grid gap-4 p-5" aria-labelledby="who">
            <h2 id="who">What the ad is about</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Brand" help={<Link className="font-bold underline" to="/brands">Add or edit brands</Link>}>
                {(fid) => (
                  <select id={fid} className="input" value={p.brand_id ?? ''} onChange={(e) => void patch({ brand_id: e.target.value || null, product_id: null })}>
                    <option value="">Choose a brand</option>
                    {brandList.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                )}
              </Field>
              <Field label="Product" help={p.brand_id && productList.length === 0 ? <>This brand has no products. <Link className="font-bold underline" to="/brands">Add one</Link>.</> : undefined}>
                {(fid) => (
                  <select id={fid} className="input" disabled={!p.brand_id} value={p.product_id ?? ''} onChange={(e) => void patch({ product_id: e.target.value || null })}>
                    <option value="">{p.brand_id ? 'Choose a product' : 'Choose a brand first'}</option>
                    {productList.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </select>
                )}
              </Field>
              <Field label="Actor" help={<>{p.actor_removed ? 'This actor was deleted; your pictures and clips are kept. ' : ''}<Link className="font-bold underline" to="/actors">Make or edit actors</Link></>} className="sm:col-span-2">
                {(fid) => (
                  <select id={fid} className="input" value={p.actor_id && !p.actor_removed ? p.actor_id : ''} onChange={(e) => void patch({ actor_id: e.target.value || null })}>
                    <option value="">Choose an actor</option>
                    {actorList.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                )}
              </Field>
            </div>
            <Field label="Anything the writer should know (optional)" help="Angle, season, audience, a moment you want shown.">
              {(fid) => <textarea id={fid} className="input" key={p.brief} defaultValue={p.brief} onBlur={commitText('brief')} placeholder="Morning routine angle. Mention it works under makeup." />}
            </Field>
          </section>

          <section className="card grid gap-5 p-5" aria-labelledby="format">
            <h2 id="format">Format and length</h2>
            <fieldset>
              <legend className="label">Format</legend>
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Format">
                {FORMATS.map(([value, title, text]) => (
                  <button key={value} type="button" role="radio" aria-checked={p.format === value} onClick={() => void patch({ format: value })}
                    className={cn('rounded-[14px] border-2 border-ink p-3 text-left', p.format === value ? 'bg-butter shadow-[3px_3px_0_var(--color-ink)]' : 'bg-card hover:bg-ink/5')}>
                    <b className="block">{title}</b><span className="text-[14px] text-ink-soft">{text}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Length (seconds)" help={`About ${Math.round(p.target_seconds * 2.5)} spoken words`}>
                {(fid) => <input id={fid} className="input" type="number" min={5} max={120} key={p.target_seconds} defaultValue={p.target_seconds} onBlur={(e) => { const v = Number(e.target.value); if (v && v !== p.target_seconds) void patch({ target_seconds: v }) }} />}
              </Field>
              <Field label="Platform">
                {(fid) => (
                  <select id={fid} className="input" value={p.platform} onChange={(e) => void patch({ platform: e.target.value })}>
                    {[['tiktok', 'TikTok'], ['reels', 'Instagram Reels'], ['shorts', 'YouTube Shorts'], ['meta', 'Meta ads'], ['other', 'Other']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                )}
              </Field>
              <div>
                <span className="label" id="aspect-label">Shape</span>
                <Segmented label="Shape" value={p.aspect} onChange={(v) => void patch({ aspect: v })} options={[{ value: '9:16', label: '9:16' }, { value: '1:1', label: '1:1' }, { value: '4:5', label: '4:5' }, { value: '16:9', label: '16:9' }]} />
              </div>
            </div>
          </section>

          <section className="card grid gap-4 p-5" aria-labelledby="voice">
            <h2 id="voice">How the ad talks</h2>
            <div className="grid gap-2" role="radiogroup" aria-label="Voice mode">
              {VOICE_MODES.map(([value, title, text]) => (
                <button key={value} type="button" role="radio" aria-checked={p.voice_mode === value} onClick={() => void patch({ voice_mode: value })}
                  className={cn('rounded-[14px] border-2 border-ink p-3 text-left', p.voice_mode === value ? 'bg-butter shadow-[3px_3px_0_var(--color-ink)]' : 'bg-card hover:bg-ink/5')}>
                  <b className="block">{title}</b><span className="text-[14px] text-ink-soft">{text}</span>
                </button>
              ))}
            </div>
            {p.voice_mode !== 'native' && p.actor && !p.actor.voice_id && <Note tone="butter">{p.actor.name} has no voice yet. <Link className="font-bold underline" to="/actors">Pick one</Link> before making clips.</Note>}
            {p.voice_mode === 'avatar' && resolved.talking_avatar?.requirement && <Note tone="clay">{resolved.talking_avatar.requirement} Talking avatar mode needs it.</Note>}
          </section>

          <section className="card grid gap-4 p-5" aria-labelledby="quality">
            <h2 id="quality">Quality, captions and budget</h2>
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <span className="label">Final quality</span>
                <Segmented label="Final quality" value={p.final_resolution} onChange={(v) => void patch({ final_resolution: v })} options={[{ value: '480p', label: '480p' }, { value: '720p', label: '720p' }, { value: '1080p', label: '1080p' }]} />
                <p className="help">Drafts are always the cheapest setting.</p>
              </div>
              <Field label="Caption style">
                {(fid) => (
                  <select id={fid} className="input" value={p.caption_style} onChange={(e) => void patch({ caption_style: e.target.value })}>
                    {(styles.data?.styles ?? [{ id: p.caption_style, name: p.caption_style }]).map((s: Json) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                )}
              </Field>
              <Field label="Budget for this ad ($)" help="Steps that would go over stop first. Empty means no limit.">
                {(fid) => <input id={fid} className="input" inputMode="decimal" key={String(p.budget)} defaultValue={p.budget ?? ''} placeholder="No limit" onBlur={(e) => { const v = e.target.value.trim(); if (v !== String(p.budget ?? '')) void patch({ budget: v === '' ? null : Number(v) }) }} />}
              </Field>
            </div>
          </section>

          <section className="card grid gap-3 p-5" aria-labelledby="models">
            <h2 id="models">Models for this ad</h2>
            <p className="text-ink-soft">Each step uses the model you chose in Settings. Choose a different one here for this ad only.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              {MODEL_STEPS.map(([task, label]) => {
                const options = (models.data?.models ?? []).filter((m: Json) => m.task === task && m.usable)
                const current = resolved[task]
                return (
                  <Field key={task} label={label} help={current?.name ? `Using ${current.name}${current.chosen ? ' (chosen for this ad)' : ' (from Settings)'}` : task === 'lipsync' ? undefined : current?.requirement}>
                    {(fid) => (
                      <select id={fid} className="input" disabled={options.length === 0} value={p.models?.[task] ?? ''} onChange={(e) => void patch({ models: { ...p.models, [task]: e.target.value } })}>
                        <option value="">{task === 'lipsync' ? 'Not used' : 'Use the Settings choice'}</option>
                        {options.map((m: Json) => <option key={m.id} value={m.id}>{m.name} ({m.provider}){m.discovered ? ' · discovered' : ''}</option>)}
                      </select>
                    )}
                  </Field>
                )
              })}
            </div>
          </section>
        </div>
        <aside className="grid content-start gap-4" aria-label="Selected product and actor">
          <div className="card p-4">
            <p className="label">Product</p>
            <Phone ratio="3:4" src={p.product?.primary_url} empty="Choose a product" label={p.product?.name ?? ''} />
            {p.product && <p className="mt-2 text-[14.5px]"><b>{p.product.name}</b><br /><span className="text-ink-soft">{p.product.label_text ? `Label: ${p.product.label_text}` : 'No label text yet'}</span></p>}
          </div>
          <div className="card p-4">
            <p className="label">Actor</p>
            <Phone ratio="3:4" src={p.actor?.portrait_url} empty="Choose an actor" label={p.actor?.name ?? ''} />
            {p.actor && <p className="mt-2 text-[14.5px]"><b>{p.actor.name}</b><br /><span className="text-ink-soft">{p.actor.voice_id ? `Voice: ${p.actor.voice_provider || 'automatic'}` : 'No voice yet'}</span></p>}
          </div>
        </aside>
      </div>
      <Console info={missing.length ? <>Still to choose: <b>{missing.join(', ')}</b></> : <>Brief is ready. Next, the words.</>}>
        <Button variant="primary" icon={<ArrowRight size={17} />} onClick={() => navigate('../script', { relative: 'path' })} disabled={!p.brand_id || !p.product_id}>Next: Script</Button>
      </Console>
    </div>
  )
}

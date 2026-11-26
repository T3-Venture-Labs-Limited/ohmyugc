import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, money } from '../../api'
import { Button, Console, Dialog, Field, Note, Switch, useAction, useJobWatch } from '../../components/ui'
import { Missing, type StageProps } from '../Project'

export function ScriptStage({ ws, refresh, id }: StageProps) {
  const p = ws.project
  const navigate = useNavigate()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [text, setText] = useState<string>(p.script)
  const [prompt, setPrompt] = useState('')
  const [newHook, setNewHook] = useState('')
  const [ask, setAsk] = useState(false)
  const [replaceAsk, setReplaceAsk] = useState(false)
  const dirty = text !== p.script
  const estimate = useQuery({ queryKey: ['script-estimate', id, p.models?.llm], queryFn: () => api.scriptEstimate(id) })
  useEffect(() => { setText(p.script) }, [p.script])
  const words = text.split(/\s+/).filter(Boolean).length
  const seconds = words / 2.5
  const analysis = ws.script
  const hasStoryboard = ws.shots.length > 0
  const hits: string[] = dirty ? [] : analysis.claim_hits
  const missingMentions: string[] = dirty ? [] : analysis.missing_mentions
  const unitCost = estimate.data?.available ? estimate.data.total.amount : null
  const save = async (after?: () => void) => {
    await run('save', () => api.saveScript(id, text), async () => { await refresh(); toast.success('Script saved.'); after?.() })
  }
  const saveAndGo = () => {
    if (dirty && hasStoryboard) return setAsk(true)
    void save(() => navigate('../storyboard', { relative: 'path' }))
  }
  const writeNow = () => run('write', () => api.writeScript(id, prompt), (r) => watch(r.job_id, { label: 'Writing the script', invalidate: [['ws', id]] }))
  const hooks = ws.variants
  return (
    <div className="grid gap-6">
      <Missing stage="script" ws={ws} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className="card grid gap-3 p-5" aria-labelledby="words">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="words">The words</h2>
            <p className="mono text-[14px] text-ink-soft" aria-live="polite">{words} words · about {seconds.toFixed(0)} s · aim for {analysis.target_words}</p>
          </div>
          <label className="sr-only" htmlFor="script-text">Script</label>
          <textarea id="script-text" className="input min-h-[300px] text-[17px] leading-relaxed" value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste your own script, or let AI write one from the brand and product. Only the spoken words, no stage directions." />
          <div className="flex flex-wrap gap-2">
            {hits.map((h) => <span key={h} className="chip chip-bad">Says “{h}”, which the brand never claims</span>)}
            {missingMentions.map((m) => <span key={m} className="chip chip-butter">Doesn’t mention: {m}</span>)}
            {!dirty && text.trim() && hits.length === 0 && missingMentions.length === 0 && <span className="chip chip-sage">Covers the brand’s points</span>}
          </div>
          {Math.abs(words - analysis.target_words) > analysis.target_words * 0.35 && words > 0 && <p className="help">That is far from the {p.target_seconds}-second target. You can change the length in the Brief or just keep it.</p>}
        </section>

        <div className="grid content-start gap-6">
          <section className="card grid gap-3 p-5" aria-labelledby="ai">
            <h2 id="ai">Write it with AI</h2>
            {estimate.data && !estimate.data.available ? <Note tone="butter">{estimate.data.message}</Note> : (
              <>
                <p className="text-[14.5px] text-ink-soft">Uses {estimate.data?.model ?? 'your language model'} with the brand’s tone, must-mention points and claims to avoid.</p>
                <Field label="Direction (optional)">{(fid) => <input id={fid} className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Open with a question. Mention it works under makeup." />}</Field>
                <Button variant="primary" icon={<Sparkles size={17} />} cost={unitCost} busy={busy === 'write'} disabled={!p.brand_id || !p.product_id} onClick={() => (p.script.trim() ? setReplaceAsk(true) : writeNow())}>Write the script</Button>
                {(!p.brand_id || !p.product_id) && <p className="help">Choose a brand and product in the Brief first.</p>}
              </>
            )}
          </section>

          <section className="card grid gap-3 p-5" aria-labelledby="hooks">
            <h2 id="hooks">Hook variants</h2>
            <p className="text-[14.5px] text-ink-soft">Other ways to open the same ad, to test which stops the scroll. Each one is exported as its own video; the rest of the ad is shared.</p>
            <ul className="grid gap-2">
              {hooks.map((h) => (
                <li key={h.id} className="card-flat grid gap-2 p-3">
                  <label className="sr-only" htmlFor={`hook-${h.id}`}>{h.name}</label>
                  <textarea id={`hook-${h.id}`} className="input min-h-[64px]" defaultValue={h.hook} key={h.hook} onBlur={(e) => { if (e.target.value !== h.hook) void api.updateHook(h.id, { hook: e.target.value }).then(refresh).catch((er: Error) => toast.error(er.message)) }} />
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-[14px] font-bold"><Switch checked={!!h.kept} label={`Keep ${h.name}`} onChange={(v) => void api.updateHook(h.id, { kept: v }).then(refresh)} />{h.kept ? 'Kept' : 'Not used'}</span>
                    <Button size="sm" variant="danger" iconOnly aria-label={`Delete ${h.name}`} icon={<Trash2 size={15} />} onClick={() => void api.deleteHook(h.id).then(refresh)} />
                  </div>
                </li>
              ))}
              {hooks.length === 0 && <li className="text-ink-mute">No hooks yet.</li>}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (newHook.trim()) void run('add-hook', () => api.addHook(id, newHook), () => { setNewHook(''); void refresh() }) }}>
              <label className="sr-only" htmlFor="new-hook">New hook</label>
              <input id="new-hook" className="input" value={newHook} onChange={(e) => setNewHook(e.target.value)} placeholder="Write your own opening line" />
              <Button type="submit" iconOnly aria-label="Add hook" icon={<Plus size={18} />} disabled={!newHook.trim()} />
            </form>
            <Button icon={<Sparkles size={16} />} disabled={!p.script?.trim() || dirty || (estimate.data && !estimate.data.available)} cost={unitCost} busy={busy === 'hooks'} onClick={() => run('hooks', () => api.generateHooks(id, 3), (r) => watch(r.job_id, { label: 'Writing 3 hooks', invalidate: [['ws', id]] }))}>Write 3 hooks</Button>
            {dirty && <p className="help">Save the script first; hooks are written to fit it.</p>}
          </section>
        </div>
      </div>

      <Dialog open={replaceAsk} onClose={() => setReplaceAsk(false)} title="Replace your script?">
        <p className="mb-4 text-ink-soft">The AI writes a new script and replaces the one you have now.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setReplaceAsk(false)}>Keep mine</Button>
          <Button variant="primary" cost={unitCost} onClick={() => { setReplaceAsk(false); void writeNow() }}>Write a new one</Button>
        </div>
      </Dialog>

      <Dialog open={ask} onClose={() => setAsk(false)} title="You changed the script">
        <p className="mb-4 text-ink-soft">This ad already has a storyboard. Keep it as it is, or draft a new one from the new script (that replaces the frames and approvals you made).</p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="primary" onClick={() => { setAsk(false); void save(() => navigate('../storyboard', { relative: 'path' })) }}>Keep the storyboard</Button>
          <Button variant="danger" onClick={() => { setAsk(false); void save(async () => { await run('redraft', () => api.draft(id, true), (r) => watch(r.job_id, { label: 'Drafting the storyboard', invalidate: [['ws', id]] })); navigate('../storyboard', { relative: 'path' }) }) }}>Redraft the storyboard</Button>
          <Button variant="ghost" onClick={() => setAsk(false)}>Cancel</Button>
        </div>
      </Dialog>

      <Console info={dirty ? <><b>Unsaved changes</b> to the script.</> : words ? <>{words} words, about {seconds.toFixed(0)} seconds. {analysis.claim_hits.length ? <b>Check the claims above.</b> : null}</> : <>Write or paste the script to continue.</>}>
        <Button disabled={!dirty} busy={busy === 'save'} onClick={() => void save()}>Save script</Button>
        <Button variant="primary" icon={<ArrowRight size={17} />} disabled={!text.trim()} onClick={saveAndGo}>Next: Storyboard</Button>
      </Console>
    </div>
  )
}

export const _unused = money

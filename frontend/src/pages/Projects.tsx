import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, type Json, money } from '../api'
import { Button, ConfirmButton, Dialog, Empty, Field, Phone, Spinner } from '../components/ui'

const STAGE_NAMES: Record<string, string> = { brief: 'Brief', script: 'Script', storyboard: 'Storyboard', clips: 'Clips', export: 'Export' }

export function ProjectsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects, refetchInterval: 4000 })
  const brands = useQuery({ queryKey: ['brands'], queryFn: api.brands })
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [brandId, setBrandId] = useState('')
  const create = useMutation({
    mutationFn: () => api.createProject({ name: name.trim() || 'Untitled ad', brand_id: brandId || null }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/ads/${p.id}/brief`)
    },
    onError: (e: Error) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
    onError: (e: Error) => toast.error(e.message),
  })
  const copy = useMutation({
    mutationFn: (id: string) => api.duplicateProject(id),
    onSuccess: () => { toast.success('Copied.'); return qc.invalidateQueries({ queryKey: ['projects'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const list: Json[] = projects.data?.projects ?? []
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>Your ads</h1>
          <p className="mt-1 max-w-xl text-ink-soft">Product photos and a script in, a UGC ad out. You only pay your model providers, and you see each cost before it happens.</p>
        </div>
        <Button variant="primary" icon={<Plus size={18} />} onClick={() => setCreating(true)}>New ad</Button>
      </div>
      {projects.isLoading ? (
        <Spinner />
      ) : list.length === 0 ? (
        <Empty title="No ads yet" action={<Button variant="primary" icon={<Plus size={18} />} onClick={() => setCreating(true)}>Make your first ad</Button>}>
          Start with a brand and a product photo. oh-my-ugc drafts the storyboard, makes a preview picture of every shot, and only renders video once you approve.
        </Empty>
      ) : (
        <ul className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((p) => (
            <li key={p.id} className="card flex flex-col gap-3 p-4">
              <div className="flex gap-4">
                <Link to={`/ads/${p.id}/${p.stage}`} className="w-[88px] shrink-0 rounded-[16px]" aria-label={`Open ${p.name}`}>
                  <Phone ratio={p.aspect} src={p.product?.primary_url} label={p.product?.name ?? ''} empty="No product" />
                </Link>
                <div className="min-w-0 flex-1">
                  <h3 className="break-words"><Link to={`/ads/${p.id}/${p.stage}`} className="hover:underline">{p.name}</Link></h3>
                  <p className="mt-1 text-[14.5px] text-ink-soft">
                    {[p.brand?.name, p.product?.name].filter(Boolean).join(' · ') || 'No brand or product yet'}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="chip chip-butter">{STAGE_NAMES[p.stage] ?? p.stage}</span>
                    <span className="chip chip-mono">{p.shot_count} shots</span>
                    <span className="chip chip-mono">{money(p.spend.total)}{p.budget != null ? ` / ${money(p.budget)}` : ''}</span>
                    {p.active_jobs > 0 && <span className="chip chip-clay"><span className="live-dot" aria-hidden /> Working</span>}
                  </div>
                </div>
              </div>
              <div className="mt-auto flex flex-wrap gap-2">
                <Link to={`/ads/${p.id}/${p.stage}`} className="btn btn-sm btn-sage">Open</Link>
                <Button size="sm" icon={<Copy size={15} />} onClick={() => copy.mutate(p.id)} aria-label={`Duplicate ${p.name}`}>Copy</Button>
                <ConfirmButton label={`Delete ${p.name}`} icon={<Trash2 size={15} />} iconOnly onConfirm={() => remove.mutate(p.id)} />
              </div>
            </li>
          ))}
        </ul>
      )}
      <Dialog open={creating} onClose={() => setCreating(false)} title="New ad">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
          <Field label="Name" help="Only you see this.">{(id) => <input id={id} className="input" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Serum morning routine" autoFocus />}</Field>
          <Field label="Brand" help={(brands.data?.brands ?? []).length ? 'You can change this later.' : 'No brands yet. You can add one in the Brief step.'}>
            {(id) => (
              <select id={id} className="input" value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                <option value="">Choose later</option>
                {(brands.data?.brands ?? []).map((b: Json) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button variant="primary" type="submit" busy={create.isPending}>Create ad</Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}

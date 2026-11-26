import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Pencil, Plus, Scissors, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { api, type Json } from '../api'
import { Button, ConfirmButton, Dialog, Empty, ErrorNote, Field, Note, Phone, Spinner, useAction, useJobWatch } from '../components/ui'

const BRAND_FIELDS: { key: string; label: string; help?: string; area?: boolean; placeholder?: string }[] = [
  { key: 'name', label: 'Brand name', placeholder: 'Acme' },
  { key: 'description', label: 'What the brand is', area: true, placeholder: 'A small skincare brand for people with sensitive skin.' },
  { key: 'voice_tone', label: 'Voice and tone', placeholder: 'Warm, plain-spoken, a little funny' },
  { key: 'audience', label: 'Who it is for', placeholder: 'Women 25 to 40 who are tired of complicated routines' },
  { key: 'must_mention', label: 'Must mention', area: true, help: 'One point per line. Every script will cover these.' },
  { key: 'avoid_claims', label: 'Never claim', area: true, help: 'One phrase per line. Scripts are checked for these and warn you.' },
  { key: 'offer', label: 'Current offer', placeholder: '20% off this week' },
  { key: 'cta', label: 'Call to action', placeholder: 'Shop now' },
  { key: 'website', label: 'Website', placeholder: 'acme.example' },
]

function BrandDialog({ brand, onClose }: { brand: Json | null; onClose: () => void }) {
  const qc = useQueryClient()
  const { busy, run } = useAction()
  const [v, setV] = useState<Json>(brand ?? {})
  const logo = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const save = () => {
    if (!(v.name ?? '').trim()) return setError('Give the brand a name.')
    setError('')
    void run('save', () => (brand ? api.updateBrand(brand.id, v) : api.createBrand(v)), () => {
      toast.success(brand ? 'Brand saved.' : 'Brand created.')
      void qc.invalidateQueries({ queryKey: ['brands'] })
      onClose()
    })
  }
  return (
    <Dialog open onClose={onClose} title={brand ? `Edit ${brand.name}` : 'New brand'} wide>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save() }}>
        {BRAND_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} help={f.help} className={f.area || f.key === 'name' ? 'sm:col-span-2' : ''}>
            {(id) => f.area ? <textarea id={id} className="input" value={v[f.key] ?? ''} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} placeholder={f.placeholder} /> : <input id={id} className="input" maxLength={f.key === 'name' ? 120 : undefined} value={v[f.key] ?? ''} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} placeholder={f.placeholder} />}
          </Field>
        ))}
        {brand && (
          <div className="sm:col-span-2">
            <span className="label">Logo (optional)</span>
            <div className="flex items-center gap-3">
              {brand.logo_url && <img src={brand.logo_url} alt="Brand logo" className="h-12 w-auto max-w-[140px] rounded-md border-2 border-ink bg-white object-contain p-1" />}
              <input ref={logo} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Upload logo" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('logo', () => api.brandLogo(brand.id, f), (b) => { setV(b); void qc.invalidateQueries({ queryKey: ['brands'] }) }) }} />
              <Button size="sm" icon={<Upload size={15} />} busy={busy === 'logo'} onClick={() => logo.current?.click()}>{brand.logo_url ? 'Replace logo' : 'Upload logo'}</Button>
            </div>
          </div>
        )}
        {error && <div className="sm:col-span-2"><ErrorNote>{error}</ErrorNote></div>}
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" busy={busy === 'save'}>{brand ? 'Save brand' : 'Create brand'}</Button>
        </div>
      </form>
    </Dialog>
  )
}

function ProductCreate({ brand, onClose }: { brand: Json; onClose: () => void }) {
  const qc = useQueryClient()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [name, setName] = useState('')
  const [facts, setFacts] = useState('')
  const [label, setLabel] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const previews = files.map((f) => URL.createObjectURL(f))
  const save = () => {
    if (!name.trim()) return setError('Give the product a name.')
    if (files.length === 0) return setError('Add at least one photo of the product.')
    setError('')
    void run('create', () => api.createProduct(brand.id, { name, facts, label_text: label }, files), (p) => {
      toast.success('Product added.')
      void qc.invalidateQueries({ queryKey: ['brands'] })
      void qc.invalidateQueries({ queryKey: ['brand', brand.id] })
      if (p.cutout_job) watch(p.cutout_job, { label: 'Cutting out the product', invalidate: [['brand', brand.id]] })
      onClose()
    })
  }
  return (
    <Dialog open onClose={onClose} title={`Add a product to ${brand.name}`} wide>
      <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save() }}>
        <div>
          <span className="label">Photos</span>
          <p className="help mb-2">One to eight clear photos of the real product: front, back, in use. JPEG, PNG or WebP, up to 20 MB each. The first one is the main photo.</p>
          <div className="flex flex-wrap gap-3">
            {previews.map((src, i) => <div key={src} className="w-[84px]"><Phone ratio="3:4" src={src} label={`Photo ${i + 1}`} /></div>)}
            <button type="button" className="btn grid h-[112px] w-[84px] place-items-center gap-1 p-2 text-[13px]" onClick={() => input.current?.click()} aria-label="Choose photos"><ImagePlus size={22} />Add photos</button>
            <input ref={input} className="sr-only" type="file" multiple accept="image/png,image/jpeg,image/webp" aria-label="Product photos" onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, 8))} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Product name">{(id) => <input id={id} className="input" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="LUMA Vitamin C Serum" />}</Field>
          <Field label="Exact text on the label" help="Used to check every generated picture. Copy it exactly.">{(id) => <input id={id} className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="LUMA Vitamin C Serum 30 ml" />}</Field>
          <Field label="Facts and benefits" className="sm:col-span-2" help="Only facts you give here are used in scripts.">{(id) => <textarea id={id} className="input" value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="30 ml. Light texture. Brightens skin in a few weeks." />}</Field>
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" busy={busy === 'create'}>Add product</Button>
        </div>
      </form>
    </Dialog>
  )
}

function ProductEdit({ product, onClose }: { product: Json; onClose: () => void }) {
  const qc = useQueryClient()
  const watch = useJobWatch()
  const { busy, run } = useAction()
  const [v, setV] = useState({ name: product.name, facts: product.facts, label_text: product.label_text })
  const add = useRef<HTMLInputElement>(null)
  const cut = useRef<HTMLInputElement>(null)
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['brands'] }); void qc.invalidateQueries({ queryKey: ['brand', product.brand_id] }); void qc.invalidateQueries({ queryKey: ['product', product.id] }) }
  const fresh = useQuery({ queryKey: ['product', product.id], queryFn: () => api.brand(product.brand_id).then((b) => (b.products as Json[]).find((p) => p.id === product.id) ?? product), initialData: product, refetchInterval: 3000 })
  const p = fresh.data
  return (
    <Dialog open onClose={onClose} title={`Edit ${product.name}`} wide>
      <div className="grid gap-5">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void run('save', () => api.updateProduct(product.id, v), () => { toast.success('Product saved.'); refresh() }) }}>
          <Field label="Product name">{(id) => <input id={id} className="input" maxLength={120} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
          <Field label="Exact text on the label">{(id) => <input id={id} className="input" value={v.label_text} onChange={(e) => setV({ ...v, label_text: e.target.value })} />}</Field>
          <Field label="Facts and benefits" className="sm:col-span-2">{(id) => <textarea id={id} className="input" value={v.facts} onChange={(e) => setV({ ...v, facts: e.target.value })} />}</Field>
          <div className="sm:col-span-2"><Button variant="primary" type="submit" busy={busy === 'save'}>Save product</Button></div>
        </form>
        <section aria-labelledby="photos" className="grid gap-2">
          <h3 id="photos">Photos</h3>
          <ul className="flex flex-wrap gap-3">
            {p.photos.map((m: string, i: number) => (
              <li key={m} className="grid w-[96px] gap-1.5">
                <Phone ratio="3:4" src={p.photo_urls[i]} label={`Photo ${i + 1}`} />
                {m === p.primary_photo ? <span className="chip chip-sage justify-center">Main photo</span> : <Button size="sm" onClick={() => run(`primary-${m}`, () => api.updateProduct(product.id, { primary_photo: m }), refresh)}>Make main</Button>}
                {p.photos.length > 1 && <Button size="sm" variant="danger" onClick={() => run(`rm-${m}`, () => api.removeProductPhoto(product.id, m), refresh)}>Remove</Button>}
              </li>
            ))}
            {p.photos.length < 8 && (
              <li><button type="button" className="btn grid h-[128px] w-[96px] place-items-center gap-1 p-2 text-[13px]" aria-label="Add more photos" onClick={() => add.current?.click()}><ImagePlus size={22} />Add photos</button>
                <input ref={add} className="sr-only" type="file" multiple accept="image/png,image/jpeg,image/webp" aria-label="More product photos" onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) void run('photos', () => api.addProductPhotos(product.id, f), refresh) }} /></li>
            )}
          </ul>
        </section>
        <section aria-labelledby="cutout" className="grid gap-2">
          <h3 id="cutout">Cutout</h3>
          <p className="text-ink-soft">The product with its background removed. Real-product shots and the end card use it, so the label stays exact.</p>
          <div className="flex flex-wrap items-center gap-4">
            <div className="w-[96px] rounded-[16px]" style={{ background: 'repeating-conic-gradient(#e6e1d4 0% 25%, #fff 0% 50%) 50% / 16px 16px' }}>
              {p.cutout_url ? <img src={p.cutout_url} alt="Product cutout" className="aspect-[3/4] w-full rounded-[14px] border-2 border-ink object-contain" /> : <div className="phone-empty aspect-[3/4] rounded-[14px] border-2 border-ink">No cutout</div>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button icon={<Scissors size={16} />} onClick={() => run('cutout', () => api.cutout(product.id), (r) => watch(r.job_id, { label: 'Cutting out the product', invalidate: [['product', product.id]] }))}>{p.cutout ? 'Make it again' : 'Make cutout'}</Button>
              <input ref={cut} className="sr-only" type="file" accept="image/png" aria-label="Upload your own cutout" onChange={(e) => { const f = e.target.files?.[0]; if (f) void run('cutup', () => api.uploadCutout(product.id, f), () => { toast.success('Cutout saved.'); refresh(); void fresh.refetch() }) }} />
              <Button icon={<Upload size={16} />} onClick={() => cut.current?.click()}>Upload my own PNG</Button>
            </div>
          </div>
        </section>
        <div className="flex justify-between gap-2">
          <ConfirmButton label="Delete product" confirmLabel="Yes, delete it" onConfirm={() => run('del', () => api.deleteProduct(product.id), () => { refresh(); onClose() })} />
          <Button variant="primary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </Dialog>
  )
}

function BrandCard({ brand, onEdit }: { brand: Json; onEdit: () => void }) {
  const qc = useQueryClient()
  const detail = useQuery({ queryKey: ['brand', brand.id], queryFn: () => api.brand(brand.id), refetchInterval: 4000 })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Json | null>(null)
  const products: Json[] = detail.data?.products ?? []
  return (
    <li className="card grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {brand.logo_url && <img src={brand.logo_url} alt="" className="h-11 w-11 rounded-[10px] border-2 border-ink bg-white object-contain p-1" />}
          <div className="min-w-0">
            <h2 className="break-words">{brand.name}</h2>
            <p className="text-[14.5px] text-ink-soft">{[brand.voice_tone, brand.cta && `CTA: ${brand.cta}`, brand.offer].filter(Boolean).join(' · ') || 'No tone or offer yet'}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<Pencil size={15} />} onClick={onEdit}>Edit brand</Button>
          <ConfirmButton label={`Delete ${brand.name}`} icon={<Trash2 size={15} />} iconOnly onConfirm={() => api.deleteBrand(brand.id).then(() => qc.invalidateQueries({ queryKey: ['brands'] })).catch((e: Error) => toast.error(e.message))} />
        </div>
      </div>
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {products.map((p) => (
          <li key={p.id} className="card-flat grid gap-2 p-3">
            <Phone ratio="3:4" src={p.primary_url} label={p.name} />
            <div className="min-w-0"><b className="break-words">{p.name}</b><p className="text-[13.5px] text-ink-mute">{p.photos.length} photo{p.photos.length === 1 ? '' : 's'} · {p.cutout ? 'cutout ready' : 'no cutout'}</p></div>
            <Button size="sm" icon={<Pencil size={14} />} onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}>Edit</Button>
          </li>
        ))}
        <li>
          <button type="button" className="card-flat grid h-full min-h-[160px] w-full place-items-center gap-1 border-dashed p-3 font-bold hover:bg-butter/50" onClick={() => setAdding(true)} aria-label={`Add a product to ${brand.name}`}><Plus size={24} />Add product</button>
        </li>
      </ul>
      {adding && <ProductCreate brand={brand} onClose={() => setAdding(false)} />}
      {editing && <ProductEdit product={editing} onClose={() => setEditing(null)} />}
    </li>
  )
}

export function BrandsPage() {
  const brands = useQuery({ queryKey: ['brands'], queryFn: api.brands })
  const [editing, setEditing] = useState<Json | 'new' | null>(null)
  const list: Json[] = brands.data?.brands ?? []
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>Brands and products</h1>
          <p className="mt-1 max-w-2xl text-ink-soft">What the AI needs to know about a company, and the real photos of what it sells. Products come only from photos you upload.</p>
        </div>
        <Button variant="primary" icon={<Plus size={18} />} onClick={() => setEditing('new')}>New brand</Button>
      </div>
      {brands.isLoading ? <Spinner /> : list.length === 0 ? (
        <Empty title="No brands yet" action={<Button variant="primary" onClick={() => setEditing('new')}>Add your first brand</Button>}>A brand is a name plus how it talks, who it is for, and what it must or must not say.</Empty>
      ) : (
        <ul className="grid gap-6">{list.map((b) => <BrandCard key={b.id} brand={b} onEdit={() => setEditing(b)} />)}</ul>
      )}
      {editing && <BrandDialog brand={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      <Note tone="sage">Your product photos are the source of truth. Generated pictures are checked against them, and label close-ups use the original photo.</Note>
    </div>
  )
}

// A thin client for the oh-my-ugc API. Errors carry the server's plain sentence.
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = Record<string, any>

async function request<T = Json>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  let body = init.body
  if (body && !(body instanceof FormData) && typeof body !== 'string') {
    body = JSON.stringify(body)
    headers['Content-Type'] = 'application/json'
  }
  let response: Response
  try {
    response = await fetch(path, { ...init, headers, body })
  } catch {
    throw new ApiError('Could not reach oh-my-ugc. Is it still running?', 0)
  }
  const text = await response.text()
  let data: Json = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { error: text.slice(0, 200) }
  }
  if (!response.ok) throw new ApiError(data.error || data.detail?.[0]?.msg || `Something went wrong (${response.status}).`, response.status)
  return data as T
}

const get = <T = Json>(path: string) => request<T>(path)
const send = <T = Json>(method: string, path: string, body?: unknown) =>
  request<T>(path, { method, body: body === undefined ? undefined : (body as BodyInit) })
const upload = <T = Json>(path: string, fields: Record<string, string | Blob | Blob[] | undefined>, files: Record<string, File | File[]> = {}) => {
  const form = new FormData()
  for (const [k, v] of Object.entries(fields)) if (v !== undefined) form.append(k, v as string)
  for (const [k, v] of Object.entries(files)) for (const f of Array.isArray(v) ? v : [v]) form.append(k, f)
  return request<T>(path, { method: 'POST', body: form })
}
const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const out = s.toString()
  return out ? `?${out}` : ''
}

export const api = {
  health: () => get('/api/health'),
  doctor: (verify = false) => get(`/api/doctor${q({ verify })}`),
  settings: () => get('/api/settings'),
  saveSettings: (values: Json) => send('PUT', '/api/settings', { values }),
  testKey: (provider: string) => send('POST', `/api/settings/test/${provider}`),
  voices: (provider: string, search = '') => get(`/api/voices/${provider}${q({ search })}`),
  captionStyles: () => get('/api/caption-styles'),
  models: (task?: string, connected = false) => get(`/api/models${q({ task, connected })}`),
  refreshModels: () => send('POST', '/api/models/refresh'),
  setDefaults: (values: Json) => send('PUT', '/api/models/defaults', { values }),

  brands: () => get('/api/brands'),
  brand: (id: string) => get(`/api/brands/${id}`),
  createBrand: (values: Json) => send('POST', '/api/brands', { values }),
  updateBrand: (id: string, values: Json) => send('PATCH', `/api/brands/${id}`, { values }),
  deleteBrand: (id: string) => send('DELETE', `/api/brands/${id}`),
  brandLogo: (id: string, file: File) => upload(`/api/brands/${id}/logo`, {}, { file }),
  products: (brandId?: string) => get(`/api/products${q({ brand_id: brandId })}`),
  createProduct: (brandId: string, f: { name: string; facts: string; label_text: string }, photos: File[]) =>
    upload(`/api/brands/${brandId}/products`, f, { photos }),
  updateProduct: (id: string, values: Json) => send('PATCH', `/api/products/${id}`, { values }),
  addProductPhotos: (id: string, photos: File[]) => upload(`/api/products/${id}/photos`, {}, { photos }),
  removeProductPhoto: (id: string, media: string) => send('DELETE', `/api/products/${id}/photos/${media}`),
  cutout: (id: string) => send('POST', `/api/products/${id}/cutout`),
  uploadCutout: (id: string, file: File) => upload(`/api/products/${id}/cutout/upload`, {}, { file }),
  deleteProduct: (id: string) => send('DELETE', `/api/products/${id}`),

  actors: () => get('/api/actors'),
  actor: (id: string) => get(`/api/actors/${id}`),
  actorPhoto: (name: string, description: string, file: File) => upload('/api/actors/photo', { name, description }, { file }),
  actorEstimate: (count: number) => get(`/api/actors/estimate${q({ count })}`),
  actorGenerate: (body: Json) => send('POST', '/api/actors/generate', body),
  actorMore: (id: string, count = 4) => send('POST', `/api/actors/${id}/candidates${q({ count })}`),
  actorReference: (id: string, view: string) => send('POST', `/api/actors/${id}/reference`, { values: { view } }),
  actorAccept: (id: string, media: string, main: boolean) => send('POST', `/api/actors/${id}/accept`, { values: { media, main } }),
  actorDiscard: (id: string, media: string) => send('POST', `/api/actors/${id}/discard`, { values: { media } }),
  updateActor: (id: string, values: Json) => send('PATCH', `/api/actors/${id}`, { values }),
  actorVoiceUpload: (id: string, file: File) => upload(`/api/actors/${id}/voice-sample`, {}, { file }),
  actorVoiceGenerate: (id: string) => send('POST', `/api/actors/${id}/voice-sample/generate`),
  deleteActor: (id: string) => send('DELETE', `/api/actors/${id}`),

  projects: () => get('/api/projects'),
  project: (id: string) => get(`/api/projects/${id}`),
  createProject: (values: Json) => send('POST', '/api/projects', { values }),
  updateProject: (id: string, values: Json) => send('PATCH', `/api/projects/${id}`, { values }),
  deleteProject: (id: string) => send('DELETE', `/api/projects/${id}`),
  duplicateProject: (id: string) => send('POST', `/api/projects/${id}/duplicate`),
  workspace: (id: string) => get(`/api/projects/${id}/workspace`),
  projectMusic: (id: string, file: File) => upload(`/api/projects/${id}/music`, {}, { file }),
  projectBackground: (id: string, file: File) => upload(`/api/projects/${id}/background`, {}, { file }),

  saveScript: (id: string, script: string) => send('PUT', `/api/projects/${id}/script`, { script }),
  scriptEstimate: (id: string) => get(`/api/projects/${id}/script/estimate`),
  writeScript: (id: string, prompt: string) => send('POST', `/api/projects/${id}/script/write`, { prompt }),
  generateHooks: (id: string, count: number) => send('POST', `/api/projects/${id}/hooks/generate`, { count }),
  addHook: (id: string, hook: string) => send('POST', `/api/projects/${id}/hooks`, { values: { hook } }),
  updateHook: (id: string, values: Json) => send('PATCH', `/api/hooks/${id}`, { values }),
  deleteHook: (id: string) => send('DELETE', `/api/hooks/${id}`),

  sbEstimate: (id: string) => get(`/api/projects/${id}/storyboard/estimate`),
  draft: (id: string, replace: boolean) => send('POST', `/api/projects/${id}/storyboard/draft${q({ replace })}`),
  frames: (id: string, all = false) => send('POST', `/api/projects/${id}/storyboard/frames${q({ all })}`),
  approveAll: (id: string) => send('POST', `/api/projects/${id}/storyboard/approve-all`),
  reorder: (id: string, ids: string[]) => send('POST', `/api/projects/${id}/storyboard/reorder`, { ids }),
  changeActor: (id: string, actorId: string | null) => send('POST', `/api/projects/${id}/storyboard/actor`, { values: { actor_id: actorId } }),
  addShot: (id: string, values: Json, after?: string) => send('POST', `/api/projects/${id}/shots${q({ after })}`, { values }),
  addCard: (id: string, text: string, after?: string) => send('POST', `/api/projects/${id}/text-cards${q({ after })}`, { values: { text } }),
  group: (id: string, ids: string[]) => send('POST', `/api/projects/${id}/blocks`, { ids }),
  ungroup: (id: string, block: number) => send('DELETE', `/api/projects/${id}/blocks/${block}`),
  updateShot: (id: string, values: Json) => send('PATCH', `/api/shots/${id}`, { values }),
  deleteShot: (id: string) => send('DELETE', `/api/shots/${id}`),
  duplicateShot: (id: string) => send('POST', `/api/shots/${id}/duplicate`),
  approve: (id: string, approved: boolean) => send('POST', `/api/shots/${id}/approve${q({ approved })}`),
  shotFrame: (id: string, note: string, target = 'frame') => send('POST', `/api/shots/${id}/frame${q({ target })}`, { note }),
  uploadFrame: (id: string, file: File, target = 'frame') => upload(`/api/shots/${id}/frame/upload${q({ target })}`, {}, { file }),
  useFrame: (id: string, frameId: string) => send('POST', `/api/shots/${id}/frame/use/${frameId}`),
  endFrame: (id: string, source: string) => send('POST', `/api/shots/${id}/end-frame${q({ source })}`),

  clipEstimate: (id: string, quality: string) => get(`/api/projects/${id}/clips/estimate${q({ quality })}`),
  render: (id: string, body: Json) => send('POST', `/api/projects/${id}/clips/render`, body),
  newTake: (shotId: string, quality: string, note: string) => send('POST', `/api/shots/${shotId}/take`, { quality, note }),
  chooseTake: (shotId: string, takeId: string) => send('POST', `/api/shots/${shotId}/take/${takeId}/choose`),
  trim: (shotId: string, takeId: string, start: number, end: number | null) => send('POST', `/api/shots/${shotId}/trim`, { take_id: takeId, start, end }),
  realProduct: (shotId: string) => send('POST', `/api/shots/${shotId}/real-product`),
  clearTakes: (shotId: string) => send('POST', `/api/shots/${shotId}/clear-takes`),

  plan: (id: string) => get(`/api/projects/${id}/plan`),
  assemble: (id: string, variantId?: string, captions?: boolean) => send('POST', `/api/projects/${id}/assemble${q({ variant_id: variantId, captions })}`),
  exportAll: (id: string) => send('POST', `/api/projects/${id}/export`),
  job: (id: string) => get(`/api/jobs/${id}`),
  jobs: (projectId?: string) => get(`/api/jobs${q({ project_id: projectId })}`),
  cancelJob: (id: string) => send('POST', `/api/jobs/${id}/cancel`),
  spend: (projectId?: string) => get(`/api/spend${q({ project_id: projectId })}`),
}

export const money = (n: number | null | undefined) => (n == null ? '—' : n < 0.1 && n > 0 ? `$${n.toFixed(3)}` : `$${n.toFixed(2)}`)
export const mediaUrl = (url?: string | null) => url || undefined

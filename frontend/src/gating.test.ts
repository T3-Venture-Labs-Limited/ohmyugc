import { describe, expect, it } from 'vitest'
import { missingFor, type Workspace } from './pages/Project'

const base = (over: Partial<Workspace['project']> = {}, shots: Workspace['shots'] = [], progress: Workspace['progress'] = []): Workspace => ({
  project: { brand: { id: 'b' }, product: { id: 'p' }, actor: { id: 'a' }, script: 'Words.', ...over },
  shots, variants: [], script: {}, jobs: [], progress, warnings: [], unit_blocks: [], variant_progress: {}, exports: [],
})

describe('stage gating', () => {
  it('the brief never needs anything', () => {
    expect(missingFor('brief', base({ brand: null, product: null }))).toEqual([])
  })

  it('the script needs a brand and a product', () => {
    expect(missingFor('script', base({ brand: null, product: null })).map((m) => m.text)).toEqual(['Choose a brand', 'Choose a product'])
    expect(missingFor('script', base())).toEqual([])
  })

  it('the storyboard needs a script and points back to it', () => {
    const missing = missingFor('storyboard', base({ script: '  ' }))
    expect(missing).toEqual([{ text: 'Write or paste the script', to: 'script' }])
  })

  it('clips need a drafted and fully approved storyboard', () => {
    expect(missingFor('clips', base()).map((m) => m.text)).toEqual(['Draft the storyboard'])
    const shots = [{ id: '1', approved: 1 }, { id: '2', approved: 0 }, { id: '3', approved: 0 }]
    expect(missingFor('clips', base({}, shots)).map((m) => m.text)).toEqual(['Approve every shot (2 left)'])
    expect(missingFor('clips', base({}, shots.map((s) => ({ ...s, approved: 1 }))))).toEqual([])
  })

  it('export needs every clip made', () => {
    const shots = [{ id: '1', approved: 1 }]
    const out = missingFor('export', base({}, shots, [{ status: 'done' }, { status: 'running' }]))
    expect(out.map((m) => m.text)).toEqual(['Make every clip (1 left)'])
    expect(missingFor('export', base({}, shots, [{ status: 'done' }]))).toEqual([])
  })
})

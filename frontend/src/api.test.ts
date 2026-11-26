import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, money } from './api'

const reply = (status: number, body: unknown) => vi.fn().mockImplementation(async () => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }))

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('returns parsed JSON on success', async () => {
    vi.stubGlobal('fetch', reply(200, { projects: [] }))
    expect(await api.projects()).toEqual({ projects: [] })
  })

  it('throws the server’s plain sentence', async () => {
    vi.stubGlobal('fetch', reply(402, { error: 'Your Replicate account is out of credit.' }))
    await expect(api.projects()).rejects.toThrow('Your Replicate account is out of credit.')
    await expect(api.projects()).rejects.toBeInstanceOf(ApiError)
  })

  it('explains an unreachable server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.health()).rejects.toThrow('Could not reach oh-my-ugc')
  })

  it('sends JSON bodies and never leaks keys into URLs', async () => {
    const fetchMock = reply(200, {})
    vi.stubGlobal('fetch', fetchMock)
    await api.saveSettings({ replicate_api_key: 'r8_secret' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/settings')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ values: { replicate_api_key: 'r8_secret' } })
    expect(init.headers['Content-Type']).toBe('application/json')
  })

  it('uploads files as multipart', async () => {
    const fetchMock = reply(200, {})
    vi.stubGlobal('fetch', fetchMock)
    await api.createProduct('b1', { name: 'Serum', facts: '', label_text: 'LUMA' }, [new File(['x'], 'a.png', { type: 'image/png' })])
    const init = fetchMock.mock.calls[0][1]
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('name')).toBe('Serum')
    expect((init.body as FormData).getAll('photos')).toHaveLength(1)
  })

  it('encodes query parameters and skips empty ones', async () => {
    const fetchMock = reply(200, {})
    vi.stubGlobal('fetch', fetchMock)
    await api.draft('p1', true)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1/storyboard/draft?replace=true')
    await api.models(undefined, false)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/models?connected=false')
  })

  it('formats money', () => {
    expect(money(0.04)).toBe('$0.040')
    expect(money(1.5)).toBe('$1.50')
    expect(money(0)).toBe('$0.00')
    expect(money(null)).toBe('—')
  })
})

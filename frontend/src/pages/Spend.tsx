import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, type Json, money } from '../api'
import { Empty, Spinner } from '../components/ui'

export function SpendPage() {
  const spend = useQuery({ queryKey: ['spend'], queryFn: () => api.spend() })
  if (spend.isLoading || !spend.data) return <Spinner />
  const total = spend.data.spend
  const ledger: Json[] = spend.data.ledger
  return (
    <div className="grid gap-6">
      <div>
        <h1>Spend</h1>
        <p className="mt-1 max-w-2xl text-ink-soft">Every paid call, with the amount the provider billed when it says so. Amounts marked “est.” are our estimate.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="card p-4"><p className="text-ink-soft">All time</p><p className="display mt-1 text-[34px]">{money(total.total)}</p><p className="text-[14px] text-ink-mute">{total.calls} calls{total.includes_estimates ? ', some estimated' : ''}</p></div>
        <div className="card p-4 sm:col-span-2">
          <p className="text-ink-soft">By provider</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {Object.entries(total.by_provider as Json).map(([p, v]) => <li key={p} className="chip chip-mono">{p} {money(v as number)}</li>)}
            {Object.keys(total.by_provider).length === 0 && <li className="text-ink-mute">Nothing spent yet.</li>}
          </ul>
        </div>
      </div>
      <section aria-labelledby="by-ad" className="grid gap-3">
        <h2 id="by-ad">By ad</h2>
        {(spend.data.by_project ?? []).length === 0 ? <Empty title="No ads yet" /> : (
          <ul className="card-flat divide-y-2 divide-ink/10">
            {(spend.data.by_project as Json[]).map((p) => <li key={p.id} className="flex items-center justify-between gap-3 p-3"><Link className="font-bold hover:underline" to={`/ads/${p.id}/export`}>{p.name}</Link><span className="mono">{money(p.spend)}</span></li>)}
          </ul>
        )}
      </section>
      <section aria-labelledby="ledger" className="grid gap-3">
        <h2 id="ledger">Recent calls</h2>
        <div className="card-flat overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[14.5px]">
            <thead><tr className="border-b-2 border-ink text-ink-soft"><th className="p-3 font-bold">When</th><th className="p-3 font-bold">Step</th><th className="p-3 font-bold">Model</th><th className="p-3 text-right font-bold">Cost</th></tr></thead>
            <tbody>
              {ledger.map((r) => (
                <tr key={r.id} className="border-b border-ink/10">
                  <td className="p-3 mono">{new Date(r.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                  <td className="p-3">{r.step}{r.status !== 'ok' && <span className="chip chip-bad ml-2">failed</span>}</td>
                  <td className="p-3 text-ink-soft">{r.model}</td>
                  <td className="p-3 text-right mono">{money(r.actual ?? r.estimated)}{r.actual == null && r.status === 'ok' ? ' est.' : ''}</td>
                </tr>
              ))}
              {ledger.length === 0 && <tr><td className="p-4 text-ink-mute" colSpan={4}>No calls yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

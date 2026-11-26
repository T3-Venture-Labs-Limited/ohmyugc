import './index.css'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router'
import { Toaster } from 'sonner'
import { api } from './api'
import { ConsoleProvider, cn } from './components/ui'
import { ActorsPage } from './pages/Actors'
import { BrandsPage } from './pages/Brands'
import { ProjectPage } from './pages/Project'
import { ProjectsPage } from './pages/Projects'
import { SettingsPage } from './pages/Settings'
import { SpendPage } from './pages/Spend'

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } } })

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('display inline-flex items-center gap-1 text-[24px] leading-none', className)}>
      <span>oh-my-</span>
      <span className="inline-block -rotate-3 rounded-[8px] border-2 border-ink bg-clay px-1.5 pb-[3px] pt-[1px] text-white">ugc</span>
    </span>
  )
}

function Header() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const missing = settings.data && settings.data.connected.length === 0
  const tab = ({ isActive }: { isActive: boolean }) =>
    cn('flex min-h-[44px] items-center rounded-[10px] px-3 text-[15px] font-bold transition-colors', isActive ? 'bg-ink text-shelf' : 'text-ink-soft hover:bg-ink/10 hover:text-ink')
  return (
    <header className="sticky top-0 z-40 border-b-2 border-ink bg-shelf/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 sm:px-6">
        <Link to="/" aria-label="oh-my-ugc home" className="rounded-[10px]">
          <Wordmark />
        </Link>
        <nav aria-label="Main" className="scrollbar-none -mx-1 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          <NavLink to="/" end className={tab}>Ads</NavLink>
          <NavLink to="/brands" className={tab}>Brands</NavLink>
          <NavLink to="/actors" className={tab}>Actors</NavLink>
          <NavLink to="/spend" className={tab}>Spend</NavLink>
          <NavLink to="/settings" className={tab}>
            Settings
            {missing && <span className="ml-1.5 inline-block h-2.5 w-2.5 rounded-full bg-clay" aria-label="Needs a key" />}
          </NavLink>
        </nav>
      </div>
    </header>
  )
}

/** First run: with no provider key nothing can be made, so send people to Settings once. */
function FirstRun({ children }: { children: React.ReactNode }) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const location = useLocation()
  const [seen] = useState(() => sessionStorage.getItem('omu-first-run') === '1')
  if (settings.data && settings.data.connected.length === 0 && location.pathname === '/' && !seen) {
    sessionStorage.setItem('omu-first-run', '1')
    return <Navigate to="/settings" replace state={{ firstRun: true }} />
  }
  return <>{children}</>
}

function Shell() {
  const [root, setRoot] = useState<HTMLElement | null>(null)
  return (
    <ConsoleProvider value={root}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-ink focus:px-3 focus:py-2 focus:text-shelf">Skip to content</a>
      <Header />
      <main id="main" className="mx-auto max-w-[1240px] px-4 pb-44 pt-6 sm:px-6 sm:pt-8">
        <FirstRun>
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/brands" element={<BrandsPage />} />
            <Route path="/actors" element={<ActorsPage />} />
            <Route path="/spend" element={<SpendPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/ads/:id" element={<ProjectPage />} />
            <Route path="/ads/:id/:stage" element={<ProjectPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </FirstRun>
      </main>
      <div id="console-root" ref={setRoot} />
    </ConsoleProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell />
        <Toaster position="top-center" offset={64} toastOptions={{ style: { border: '2px solid #172019', borderRadius: 14, fontFamily: 'var(--font-sans)', fontWeight: 600 } }} />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)

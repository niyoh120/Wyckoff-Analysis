import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './app.css'
import { AuthGuard } from '@/components/auth-guard'
import { AppLayout } from '@/routes/layout'
import { LoginPage } from '@/routes/login'
import { ChatPage } from '@/routes/chat'
import { PortfolioPage } from '@/routes/portfolio'
import { TrackingPage } from '@/routes/tracking'
import { SettingsPage } from '@/routes/settings'
import { AnalysisPage } from '@/routes/analysis'
import { TailBuyPage } from '@/routes/tail-buy'
import { ExportPage } from '@/routes/export'
import { ChangelogPage } from '@/routes/changelog'
import { HomePage } from '@/routes/home'
import { ScreenerPage } from '@/routes/screener'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AuthGuard />}>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/tracking" element={<TrackingPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/screener" element={<ScreenerPage />} />
              <Route path="/tail-buy" element={<TailBuyPage />} />
              <Route path="/export" element={<ExportPage />} />
              <Route path="/home" element={<HomePage />} />
              <Route path="/changelog" element={<ChangelogPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)

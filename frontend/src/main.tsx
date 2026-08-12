import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './i18n' // Initialize i18n
import App from './App.tsx'
import { setMobileServerUrl } from './api/client'
import { Capacitor } from '@capacitor/core'

// Capacitor launches the bundled UI at /mobile. A QR/deep link may provide
// the server origin once; persist it before React/AuthProvider makes its first
// request so authentication and every existing API call use the same backend.
if (Capacitor.isNativePlatform() && window.location.pathname !== '/mobile') {
  window.history.replaceState({}, '', `/mobile${window.location.search}${window.location.hash}`)
}

if (window.location.pathname === '/mobile') {
  const server = new URLSearchParams(window.location.search).get('server')
  if (server) setMobileServerUrl(server)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

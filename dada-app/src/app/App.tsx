import { RouterProvider } from 'react-router-dom'

import { NetworkStatus } from '../components/system/NetworkStatus'
import { AppErrorBoundary } from './AppErrorBoundary'
import { AppProviders } from './AppProviders'
import { router } from './router'

export function App() {
  return (
    <AppErrorBoundary>
      <AppProviders>
        <NetworkStatus />
        <RouterProvider router={router} />
      </AppProviders>
    </AppErrorBoundary>
  )
}

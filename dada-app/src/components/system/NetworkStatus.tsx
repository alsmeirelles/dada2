import { useEffect, useState } from 'react'

export function NetworkStatus() {
  const [online, setOnline] = useState(navigator.onLine)

  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])

  if (online) return null
  return (
    <div className="network-banner" role="status" aria-live="polite">
      You are offline. Unsaved annotations remain in this tab and will sync after reconnecting.
    </div>
  )
}

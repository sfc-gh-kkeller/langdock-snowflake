// Tiny API + router helpers

export async function api(path, opts = {}) {
  const r = await fetch(path, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (r.status === 401) {
    if (location.pathname !== '/login') navigate('/login')
    throw new Error('not signed in')
  }
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text()
  if (!r.ok) throw new Error(data?.detail || data || r.statusText)
  return data
}

// Streams Server-Sent Events from a POST request
export async function streamPost(path, body, onEvent, signal) {
  const r = await fetch(path, {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i)
      buf = buf.slice(i + 2)
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data:')) {
          try { onEvent(JSON.parse(line.slice(5))) } catch { /* ignore partial */ }
        }
      }
    }
  }
}

// Router: history API, subscribers re-render on change
const listeners = new Set()
export function navigate(to) {
  if (to !== location.pathname + location.search) history.pushState({}, '', to)
  listeners.forEach((l) => l())
}
export function onRoute(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
window.addEventListener('popstate', () => listeners.forEach((l) => l()))

// Opens an OAuth connect popup; resolves when /oauth-done posts back
export function connectPopup(integrationId) {
  return new Promise((resolve) => {
    const w = window.open(`/api/integrations/${integrationId}/connect`, 'icedock_oauth', 'width=520,height=700')
    const onMsg = (e) => {
      if (e.origin !== location.origin || e.data?.type !== 'ldc-oauth') return
      window.removeEventListener('message', onMsg)
      clearInterval(t)
      resolve(e.data)
    }
    window.addEventListener('message', onMsg)
    const t = setInterval(() => {
      if (w && w.closed) { clearInterval(t); window.removeEventListener('message', onMsg); resolve({ status: 'closed' }) }
    }, 800)
  })
}

export function timeAgo(ts) {
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(ts * 1000).toLocaleDateString()
}

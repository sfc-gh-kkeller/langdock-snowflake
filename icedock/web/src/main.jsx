import { render } from 'preact'
import { useEffect, useState } from 'preact/hooks'
import { api, navigate, onRoute } from './api.js'
import { Toasts } from './components/ui.jsx'
import { Sidebar } from './components/Sidebar.jsx'
import { Login } from './pages/Login.jsx'
import { ChatPage } from './pages/Chat.jsx'
import { AgentsPage, AgentEditor } from './pages/Agents.jsx'
import { IntegrationsPage } from './pages/Integrations.jsx'
import { SettingsPage } from './pages/Settings.jsx'
import './styles.css'

function OAuthDone() {
  const p = new URLSearchParams(location.search)
  useEffect(() => {
    if (window.opener) {
      window.opener.postMessage({ type: 'ldc-oauth', status: p.get('status'), iid: p.get('iid'), message: p.get('message') }, location.origin)
      setTimeout(() => window.close(), 300)
    } else {
      // Opened in the same tab (popup blocked): go back to the integrations page
      setTimeout(() => navigate('/integrations'), 800)
    }
  }, [])
  return <div class="center-page"><h2>{p.get('status') === 'error' ? 'Connection failed' : 'Connected'}</h2><p class="muted">You can close this window.</p></div>
}

function App() {
  const [, force] = useState(0)
  const [me, setMe] = useState(undefined)
  const [toasts, setToasts] = useState([])
  const [chatsVersion, setChatsVersion] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => onRoute(() => force((n) => n + 1)), [])
  const path = location.pathname

  useEffect(() => {
    if (path === '/login' || path === '/oauth-done') return
    api('/api/me').then(setMe).catch(() => setMe(null))
  }, [path === '/login'])

  if (path === '/oauth-done') return <OAuthDone />
  if (path === '/login' || me === null) return <Login />
  if (me === undefined) return <div class="center-page"><div class="spinner" /></div>

  const refreshChats = () => setChatsVersion((v) => v + 1)
  let page
  let m
  // Stable key: the first message rewrites the URL to /chat/<id> mid-stream without remounting
  if ((m = path.match(/^\/chat\/([\w]+)/))) page = <ChatPage key="chat" chatId={m[1]} me={me} refreshChats={refreshChats} />
  else if (path === '/' || path === '/chat') page = <ChatPage key="chat" search={location.search} me={me} refreshChats={refreshChats} />
  else if (path === '/agents') page = <AgentsPage me={me} />
  else if ((m = path.match(/^\/agents\/(new|[\w]+)\/edit$/))) page = <AgentEditor id={m[1]} me={me} />
  else if (path.startsWith('/integrations')) page = <IntegrationsPage me={me} />
  else if (path.startsWith('/settings')) page = <SettingsPage me={me} tab={path.split('/')[2] || 'general'} />
  else { navigate('/'); return null }

  return (
    <div class={`layout ${collapsed ? 'collapsed' : ''}`}>
      <Sidebar me={me} path={path} version={chatsVersion} collapsed={collapsed} setCollapsed={setCollapsed} />
      <main class="main">{page}</main>
      <Toasts list={toasts} setList={setToasts} />
    </div>
  )
}

render(<App />, document.getElementById('app'))

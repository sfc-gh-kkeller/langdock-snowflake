import { useEffect, useState } from 'preact/hooks'
import { api, navigate } from '../api.js'
import { Icon, Menu, toast } from './ui.jsx'

function groupChats(chats) {
  const now = Date.now() / 1000
  const groups = { Pinned: [], Today: [], 'Previous 7 days': [], Older: [] }
  for (const c of chats) {
    if (c.pinned) groups.Pinned.push(c)
    else if (now - c.updated_at < 86400) groups.Today.push(c)
    else if (now - c.updated_at < 7 * 86400) groups['Previous 7 days'].push(c)
    else groups.Older.push(c)
  }
  return Object.entries(groups).filter(([, v]) => v.length)
}

export function Sidebar({ me, path, version, collapsed, setCollapsed }) {
  const [chats, setChats] = useState([])
  const [q, setQ] = useState('')
  const [menu, setMenu] = useState(null)
  const [userMenu, setUserMenu] = useState(false)
  const [renaming, setRenaming] = useState(null)

  const load = () => api(`/api/chats?q=${encodeURIComponent(q)}`).then(setChats).catch(() => {})
  useEffect(() => { load() }, [version, q])

  const link = (to, icon, label) => (
    <a href={to} class={`nav-item ${path === to || (to !== '/' && path.startsWith(to)) ? 'active' : ''}`}
      onClick={(e) => { e.preventDefault(); navigate(to) }}>
      <Icon name={icon} /> <span>{label}</span>
    </a>
  )

  const rename = async (c, title) => {
    setRenaming(null)
    if (title && title !== c.title) { await api(`/api/chats/${c.id}`, { method: 'PATCH', body: { title } }); load() }
  }

  if (collapsed) {
    return (
      <aside class="sidebar mini">
        <button class="icon-btn" onClick={() => setCollapsed(false)} title="Expand"><Icon name="sidebar" /></button>
        <button class="icon-btn" onClick={() => navigate('/')} title="New chat"><Icon name="plus" /></button>
        <button class="icon-btn" onClick={() => navigate('/agents')} title="Agents"><Icon name="bot" /></button>
        <button class="icon-btn" onClick={() => navigate('/integrations')} title="Integrations"><Icon name="plug" /></button>
      </aside>
    )
  }

  return (
    <aside class="sidebar">
      <div class="brand">
        <div class="logo">I</div>
        <div class="ws">
          <div class="ws-name">{me.workspace}</div>
          <div class="ws-sub">Icedock · local</div>
        </div>
        <button class="icon-btn" onClick={() => setCollapsed(true)} title="Collapse"><Icon name="sidebar" /></button>
      </div>
      <button class="btn new-chat" onClick={() => navigate('/?n=' + Date.now())}><Icon name="plus" /> New chat</button>
      <nav class="nav">
        {link('/', 'chat', 'Chat')}
        {link('/agents', 'bot', 'Agents')}
        {link('/integrations', 'plug', 'Integrations')}
        {link('/settings', 'settings', 'Settings')}
      </nav>
      <div class="search">
        <Icon name="search" size={14} />
        <input placeholder="Search chats" value={q} onInput={(e) => setQ(e.target.value)} />
      </div>
      <div class="chat-list">
        {groupChats(chats).map(([g, list]) => (
          <div class="chat-group">
            <div class="group-label">{g}</div>
            {list.map((c) => (
              <div class={`chat-item ${path === `/chat/${c.id}` ? 'active' : ''}`}>
                {renaming === c.id ? (
                  <input class="rename" autoFocus value={c.title}
                    onBlur={(e) => rename(c, e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setRenaming(null) }} />
                ) : (
                  <a href={`/chat/${c.id}`} onClick={(e) => { e.preventDefault(); navigate(`/chat/${c.id}`) }}>
                    {c.agent_emoji && <span class="emoji">{c.agent_emoji}</span>}{c.title}
                  </a>
                )}
                <button class="icon-btn tiny" onClick={() => setMenu(menu === c.id ? null : c.id)} aria-label="Chat options"><Icon name="dots" size={14} /></button>
                {menu === c.id && (
                  <Menu onClose={() => setMenu(null)} items={[
                    { label: 'Rename', icon: 'edit', onClick: () => setRenaming(c.id) },
                    { label: c.pinned ? 'Unpin' : 'Pin', icon: 'pin', onClick: async () => { await api(`/api/chats/${c.id}`, { method: 'PATCH', body: { pinned: !c.pinned } }); load() } },
                    { label: 'Delete', icon: 'trash', danger: true, onClick: async () => {
                      await api(`/api/chats/${c.id}`, { method: 'DELETE' }); toast('Chat deleted')
                      if (path === `/chat/${c.id}`) navigate('/'); load()
                    } },
                  ]} />
                )}
              </div>
            ))}
          </div>
        ))}
        {!chats.length && <div class="muted small pad">No chats yet</div>}
      </div>
      <div class="user-box" onClick={() => setUserMenu(!userMenu)}>
        <div class="avatar">{(me.name || me.email || '?').slice(0, 1).toUpperCase()}</div>
        <div class="user-meta">
          <div class="user-name">{me.name}</div>
          <div class="user-mail">{me.email}</div>
        </div>
        {userMenu && (
          <Menu onClose={() => setUserMenu(false)} items={[
            { label: 'Account & identity', icon: 'shield', onClick: () => navigate('/settings/account') },
            { label: 'Sign out', icon: 'logout', onClick: async () => { await api('/auth/logout', { method: 'POST' }); navigate('/login') } },
          ]} />
        )}
      </div>
    </aside>
  )
}

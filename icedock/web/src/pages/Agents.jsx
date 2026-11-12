import { useEffect, useState } from 'preact/hooks'
import { api, navigate, timeAgo } from '../api.js'
import { Icon, IntegrationIcon, Menu, Toggle, toast } from '../components/ui.jsx'

const EMOJIS = ['🤖', '📊', '🔎', '💼', '📈', '🧠', '📝', '⚖️', '🛡️', '❄️', '💬', '🏦']

export function AgentsPage({ me }) {
  const [agents, setAgents] = useState([])
  const [tab, setTab] = useState('all')
  const [q, setQ] = useState('')
  const [menu, setMenu] = useState(null)
  const load = () => api('/api/agents').then(setAgents)
  useEffect(() => { load() }, [])
  const list = agents.filter((a) => (tab === 'all' || (tab === 'mine' ? a.can_edit : a.visibility === 'workspace'))
    && a.name.toLowerCase().includes(q.toLowerCase()))
  return (
    <div class="page">
      <div class="page-head">
        <div>
          <h1>Agents</h1>
          <p class="muted">Custom assistants with instructions, a model and tools from your integrations.</p>
        </div>
        <button class="btn primary" onClick={() => navigate('/agents/new/edit')}><Icon name="plus" /> Create agent</button>
      </div>
      <div class="toolbar">
        <div class="tabs">
          {[['all', 'All'], ['mine', 'Created by me'], ['workspace', 'Shared with workspace']].map(([k, l]) => (
            <button class={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        <div class="search inline"><Icon name="search" size={14} /><input placeholder="Search agents" value={q} onInput={(e) => setQ(e.target.value)} /></div>
      </div>
      <div class="grid">
        {list.map((a) => (
          <div class="card agent-card" onClick={() => navigate(`/?agent=${a.id}`)}>
            <div class="card-top">
              <div class="agent-emoji">{a.emoji}</div>
              {a.can_edit && (
                <div class="dropdown" onClick={(e) => e.stopPropagation()}>
                  <button class="icon-btn tiny" onClick={() => setMenu(menu === a.id ? null : a.id)} aria-label="Agent options"><Icon name="dots" /></button>
                  {menu === a.id && <Menu onClose={() => setMenu(null)} items={[
                    { label: 'Edit', icon: 'edit', onClick: () => navigate(`/agents/${a.id}/edit`) },
                    { label: 'Delete', icon: 'trash', danger: true, onClick: async () => { await api(`/api/agents/${a.id}`, { method: 'DELETE' }); toast('Agent deleted'); load() } },
                  ]} />}
                </div>
              )}
            </div>
            <h3>{a.name}</h3>
            <p class="muted small clamp">{a.description || 'No description'}</p>
            <div class="card-foot">
              <span class="badge">{a.visibility === 'workspace' ? 'Workspace' : 'Private'}</span>
              {a.preselect.length > 0 && <span class="badge warn" title="Tool calls run with the owner's connection">Owner connection</span>}
              <span class="muted small">{a.owner} · {timeAgo(a.updated_at)}</span>
            </div>
          </div>
        ))}
        {!list.length && <div class="empty-state"><Icon name="bot" size={28} /><p>No agents yet. Create one to package instructions and tools for your team.</p></div>}
      </div>
    </div>
  )
}

export function AgentEditor({ id }) {
  const isNew = id === 'new'
  const [a, setA] = useState({ name: '', emoji: '🤖', description: '', instructions: '', model: '', starters: [''], actions: {}, preselect: [], visibility: 'private' })
  const [integrations, setIntegrations] = useState([])
  const [models, setModels] = useState([])
  const [tab, setTab] = useState('configure')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api('/api/integrations').then(setIntegrations)
    api('/api/settings').then((s) => setModels(s.models))
    if (!isNew) api(`/api/agents/${id}`).then((x) => setA({ ...x, starters: x.starters.length ? x.starters : [''] }))
  }, [id])

  const set = (k, v) => setA((x) => ({ ...x, [k]: v }))
  const toggleTool = (iid, tool, on) => {
    const cur = new Set(a.actions[iid] || [])
    on ? cur.add(tool) : cur.delete(tool)
    const actions = { ...a.actions, [iid]: [...cur] }
    if (!cur.size) delete actions[iid]
    set('actions', actions)
    if (!cur.size) set('preselect', a.preselect.filter((x) => x !== iid))
  }

  const save = async () => {
    if (!a.name.trim()) return toast('Give the agent a name', 'error')
    setSaving(true)
    const body = { ...a, starters: a.starters.filter((s) => s.trim()) }
    try {
      const saved = await api(isNew ? '/api/agents' : `/api/agents/${id}`, { method: isNew ? 'POST' : 'PUT', body })
      toast('Agent saved', 'success')
      navigate(`/?agent=${saved.id}`)
    } catch (e) { toast(e.message, 'error') } finally { setSaving(false) }
  }

  return (
    <div class="page editor">
      <div class="page-head">
        <div class="row">
          <button class="icon-btn" onClick={() => navigate('/agents')} aria-label="Back"><Icon name="chevron" class="rot90" /></button>
          <h1>{isNew ? 'Create agent' : `Edit ${a.name}`}</h1>
        </div>
        <div class="row">
          <select value={a.visibility} onChange={(e) => set('visibility', e.target.value)}>
            <option value="private">Only me</option>
            <option value="workspace">Share with workspace</option>
          </select>
          <button class="btn primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
      <div class="tabs">
        <button class={`tab ${tab === 'configure' ? 'active' : ''}`} onClick={() => setTab('configure')}>Configure</button>
        <button class={`tab ${tab === 'actions' ? 'active' : ''}`} onClick={() => setTab('actions')}>Actions {Object.keys(a.actions).length ? `(${Object.values(a.actions).flat().length})` : ''}</button>
      </div>
      {tab === 'configure' ? (
        <div class="form">
          <div class="field">
            <label>Icon & name</label>
            <div class="row">
              <select class="emoji-select" value={a.emoji} onChange={(e) => set('emoji', e.target.value)}>{EMOJIS.map((e) => <option>{e}</option>)}</select>
              <input class="grow" value={a.name} placeholder="e.g. Fund Research" onInput={(e) => set('name', e.target.value)} />
            </div>
          </div>
          <div class="field"><label>Description</label><input value={a.description} placeholder="What does this agent do?" onInput={(e) => set('description', e.target.value)} /></div>
          <div class="field">
            <label>Instructions</label>
            <textarea rows={8} value={a.instructions} placeholder="You are a fund research assistant. Always use the research tool for fund questions…" onInput={(e) => set('instructions', e.target.value)} />
          </div>
          <div class="field">
            <label>Model</label>
            <select value={a.model} onChange={(e) => set('model', e.target.value)}>
              <option value="">Workspace default (user can change)</option>
              {models.map((m) => <option value={m}>{m}</option>)}
            </select>
          </div>
          <div class="field">
            <label>Conversation starters</label>
            {a.starters.map((s, i) => (
              <div class="row">
                <input class="grow" value={s} onInput={(e) => { const st = a.starters.slice(); st[i] = e.target.value; set('starters', st) }} />
                <button class="icon-btn" onClick={() => set('starters', a.starters.filter((_, j) => j !== i))} aria-label="Remove"><Icon name="x" /></button>
              </div>
            ))}
            <button class="btn ghost sm" onClick={() => set('starters', [...a.starters, ''])}><Icon name="plus" size={14} /> Add starter</button>
          </div>
        </div>
      ) : (
        <div class="form">
          <p class="muted">Pick tools from your integrations. By default, each user runs tools with <b>their own</b> connection. Pre-selecting your connection makes everyone using this agent act as you.</p>
          {integrations.map((i) => (
            <div class="card integ-block">
              <div class="row">
                <IntegrationIcon icon={i.icon} />
                <div class="grow"><b>{i.name}</b><div class="muted small">{i.tools.length} tools · {i.connected ? 'connected' : 'not connected'}</div></div>
                {i.auth_type === 'oauth_manual' && (a.actions[i.id] || []).length > 0 && (
                  <Toggle label="Pre-select my connection" checked={a.preselect.includes(i.id)}
                    onChange={(on) => {
                      if (on && !i.connected) return toast('Connect this integration first', 'error')
                      set('preselect', on ? [...a.preselect, i.id] : a.preselect.filter((x) => x !== i.id))
                    }} />
                )}
              </div>
              {a.preselect.includes(i.id) && <div class="warn-box">Everyone using this agent will query {i.name} with your identity and permissions.</div>}
              <div class="tool-list">
                {i.tools.map((t) => (
                  <label class="tool-row">
                    <input type="checkbox" checked={(a.actions[i.id] || []).includes(t.name)} onChange={(e) => toggleTool(i.id, t.name, e.target.checked)} />
                    <div><code>{t.name}</code><div class="muted small">{t.description}</div></div>
                  </label>
                ))}
                {!i.tools.length && <div class="muted small">Connect the integration to discover its tools.</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

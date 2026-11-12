import { useEffect, useState } from 'preact/hooks'
import { api, connectPopup } from '../api.js'
import { Icon, IntegrationIcon, Modal, Toggle, toast } from '../components/ui.jsx'

const EMPTY = { name: '', description: '', icon: 'plug', url: '', auth_type: 'oauth_manual', auth_url: '', token_url: '', client_id: '', client_secret: '', scope: '', send_resource: false, headers: {}, shared: true }

function IntegrationForm({ initial, me, onSaved, onClose }) {
  const [f, setF] = useState(() => ({ ...EMPTY, ...initial, client_secret: initial?.id ? null : '' }))
  const [headers, setHeaders] = useState(() => Object.entries(initial?.headers || {}).map(([k, v]) => ({ k, v })))
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const save = async () => {
    const body = { ...f, headers: Object.fromEntries(headers.filter((h) => h.k.trim()).map((h) => [h.k.trim(), h.v])) }
    try {
      const r = await api(initial?.id ? `/api/integrations/${initial.id}` : '/api/integrations', { method: initial?.id ? 'PUT' : 'POST', body })
      toast('Integration saved', 'success'); onSaved(r)
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={initial?.id ? `Edit ${initial.name}` : 'Add MCP server'} onClose={onClose} wide>
      <div class="form">
        <div class="field"><label>Name</label><input value={f.name} onInput={(e) => set('name', e.target.value)} placeholder="Snowflake Research" /></div>
        <div class="field"><label>Description</label><input value={f.description} onInput={(e) => set('description', e.target.value)} /></div>
        <div class="field"><label>Server URL</label><input value={f.url} onInput={(e) => set('url', e.target.value)} placeholder="https://<account>.snowflakecomputing.com/api/v2/databases/<db>/schemas/<schema>/mcp-servers/<name>" /></div>
        <div class="field"><label>Icon</label>
          <select value={f.icon} onChange={(e) => set('icon', e.target.value)}><option value="plug">Generic</option><option value="snowflake">Snowflake</option></select>
        </div>
        <div class="field">
          <label>Authentication</label>
          <div class="seg">
            {[['none', 'None'], ['bearer', 'API key / Bearer'], ['oauth_manual', 'OAuth 2.0 Manual']].map(([k, l]) => (
              <button class={f.auth_type === k ? 'active' : ''} onClick={() => set('auth_type', k)}>{l}</button>
            ))}
          </div>
        </div>
        {f.auth_type === 'bearer' && (
          <div class="field"><label>Token (shared by all users)</label>
            <input type="password" value={f.client_secret ?? ''} placeholder={initial?.has_secret ? '•••••• (unchanged)' : ''} onInput={(e) => set('client_secret', e.target.value)} />
            <div class="warn-box">A shared key means every user calls the server with the same identity.</div>
          </div>
        )}
        {f.auth_type === 'oauth_manual' && (
          <>
            <div class="two">
              <div class="field"><label>Authorization URL</label><input value={f.auth_url} onInput={(e) => set('auth_url', e.target.value)} placeholder="https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize" /></div>
              <div class="field"><label>Token URL</label><input value={f.token_url} onInput={(e) => set('token_url', e.target.value)} placeholder=".../oauth2/v2.0/token" /></div>
            </div>
            <div class="two">
              <div class="field"><label>Client ID</label><input value={f.client_id} onInput={(e) => set('client_id', e.target.value)} /></div>
              <div class="field"><label>Client secret</label><input type="password" value={f.client_secret ?? ''} placeholder={initial?.has_secret ? '•••••• (unchanged)' : 'optional for public clients'} onInput={(e) => set('client_secret', e.target.value)} /></div>
            </div>
            <div class="field"><label>Scope</label><input value={f.scope} onInput={(e) => set('scope', e.target.value)} placeholder="api://<snowflake-app-id>/session:role:MCP_USER offline_access" /></div>
            <Toggle label="Send resource parameter (RFC 8707) — turn off for Entra ID" checked={f.send_resource} onChange={(v) => set('send_resource', v)} />
            <div class="muted small">Redirect URI to register: <code>{location.origin}/api/integrations/callback</code></div>
          </>
        )}
        <div class="field">
          <label>Custom headers</label>
          {headers.map((h, i) => (
            <div class="row">
              <input placeholder="Header" value={h.k} onInput={(e) => { const c = headers.slice(); c[i] = { ...h, k: e.target.value }; setHeaders(c) }} />
              <input class="grow" placeholder="Value" value={h.v} onInput={(e) => { const c = headers.slice(); c[i] = { ...h, v: e.target.value }; setHeaders(c) }} />
              <button class="icon-btn" onClick={() => setHeaders(headers.filter((_, j) => j !== i))} aria-label="Remove header"><Icon name="x" /></button>
            </div>
          ))}
          <button class="btn ghost sm" onClick={() => setHeaders([...headers, { k: '', v: '' }])}><Icon name="plus" size={14} /> Add header</button>
        </div>
        {me.is_admin && <Toggle label="Share with workspace (each member connects their own account)" checked={f.shared} onChange={(v) => set('shared', v)} />}
        <div class="modal-actions"><button class="btn" onClick={onClose}>Cancel</button><button class="btn primary" onClick={save}>Save</button></div>
      </div>
    </Modal>
  )
}

function ToolTester({ integ, onClose }) {
  const [tool, setTool] = useState(integ.tools[0]?.name || '')
  const [args, setArgs] = useState('{}')
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(false)
  const schema = integ.tools.find((t) => t.name === tool)?.inputSchema
  const run = async () => {
    setBusy(true); setOut(null)
    try { setOut(await api(`/api/integrations/${integ.id}/tools/test`, { method: 'POST', body: { tool, arguments: JSON.parse(args || '{}') } })) }
    catch (e) { setOut({ text: e.message, is_error: true }) } finally { setBusy(false) }
  }
  return (
    <Modal title={`Test ${integ.name}`} onClose={onClose} wide>
      <div class="form">
        <div class="field"><label>Tool</label><select value={tool} onChange={(e) => setTool(e.target.value)}>{integ.tools.map((t) => <option>{t.name}</option>)}</select></div>
        <details><summary class="muted small">Input schema</summary><pre>{JSON.stringify(schema, null, 2)}</pre></details>
        <div class="field"><label>Arguments (JSON)</label><textarea rows={4} class="mono" value={args} onInput={(e) => setArgs(e.target.value)} /></div>
        <button class="btn primary" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run tool'}</button>
        {out && <pre class={out.is_error ? 'error-box' : ''}>{out.ms ? `${out.ms} ms\n\n` : ''}{out.text}</pre>}
      </div>
    </Modal>
  )
}

export function IntegrationsPage({ me }) {
  const [list, setList] = useState([])
  const [editing, setEditing] = useState(null)
  const [testing, setTesting] = useState(null)
  const [busy, setBusy] = useState(null)
  const load = () => api('/api/integrations').then(setList)
  useEffect(() => { load() }, [])

  const connect = async (i) => {
    const r = await connectPopup(i.id)
    if (r.status === 'ok') toast(`Connected ${i.name}`, 'success')
    else if (r.status === 'warn') toast('Connected, but tool discovery failed', 'error')
    else if (r.status !== 'closed') toast(`Connection failed: ${r.message || ''}`, 'error')
    load()
  }
  const refresh = async (i) => {
    setBusy(i.id)
    try { const t = await api(`/api/integrations/${i.id}/tools/refresh`, { method: 'POST' }); toast(`${t.length} tools found`, 'success'); load() }
    catch (e) { toast(e.message, 'error') } finally { setBusy(null) }
  }

  return (
    <div class="page">
      <div class="page-head">
        <div><h1>Integrations</h1><p class="muted">Connect MCP servers. With OAuth, every member signs in with their own account so tools run under their identity.</p></div>
        <button class="btn primary" onClick={() => setEditing({})}><Icon name="plus" /> Add MCP server</button>
      </div>
      <div class="grid">
        {list.map((i) => (
          <div class="card integ-card">
            <div class="card-top">
              <IntegrationIcon icon={i.icon} size={36} />
              <span class={`badge ${i.connected ? 'ok' : ''}`}>{i.auth_type === 'oauth_manual' ? (i.connected ? 'Connected' : 'Not connected') : i.auth_type === 'bearer' ? 'Shared key' : 'No auth'}</span>
            </div>
            <h3>{i.name}</h3>
            <p class="muted small clamp">{i.description || i.url}</p>
            <div class="muted small">{i.tools.length} tools{i.shared ? ' · shared with workspace' : ' · private'}</div>
            {i.tools.length > 0 && <div class="tags">{i.tools.slice(0, 4).map((t) => <code>{t.name}</code>)}</div>}
            <div class="card-actions">
              {i.auth_type === 'oauth_manual' && (i.connected
                ? <button class="btn sm" onClick={async () => { await api(`/api/integrations/${i.id}/disconnect`, { method: 'POST' }); toast('Disconnected'); load() }}>Disconnect</button>
                : <button class="btn primary sm" onClick={() => connect(i)}><Icon name="link" size={14} /> Connect</button>)}
              {i.connected && <button class="btn sm" onClick={() => refresh(i)} disabled={busy === i.id}><Icon name="refresh" size={14} /> {busy === i.id ? 'Loading' : 'Tools'}</button>}
              {i.connected && i.tools.length > 0 && <button class="btn sm" onClick={() => setTesting(i)}>Test</button>}
              {i.can_edit && <button class="icon-btn" onClick={() => setEditing(i)} aria-label="Edit"><Icon name="edit" /></button>}
              {i.can_edit && <button class="icon-btn" onClick={async () => { if (confirm(`Delete ${i.name}?`)) { await api(`/api/integrations/${i.id}`, { method: 'DELETE' }); load() } }} aria-label="Delete"><Icon name="trash" /></button>}
            </div>
          </div>
        ))}
        {!list.length && <div class="empty-state"><Icon name="plug" size={28} /><p>No integrations yet.</p></div>}
      </div>
      {editing && <IntegrationForm initial={editing} me={me} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
      {testing && <ToolTester integ={testing} onClose={() => setTesting(null)} />}
    </div>
  )
}

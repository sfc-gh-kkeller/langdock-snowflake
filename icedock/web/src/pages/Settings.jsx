import { useEffect, useState } from 'preact/hooks'
import { api, navigate, timeAgo } from '../api.js'
import { toast } from '../components/ui.jsx'

function General({ me }) {
  const [s, setS] = useState(null)
  const [models, setModels] = useState('')
  useEffect(() => { api('/api/settings').then((x) => { setS(x); setModels(x.models.join('\n')) }) }, [])
  if (!s) return null
  const save = async () => {
    try { setS(await api('/api/settings', { method: 'PUT', body: { ...s, models: models.split('\n') } })); toast('Settings saved', 'success') }
    catch (e) { toast(e.message, 'error') }
  }
  return (
    <div class="form">
      <div class="field"><label>Workspace name</label><input disabled={!me.is_admin} value={s.workspace_name} onInput={(e) => setS({ ...s, workspace_name: e.target.value })} /></div>
      <div class="field"><label>Available models (Snowflake Cortex model names, one per line)</label>
        <textarea rows={6} class="mono" disabled={!me.is_admin} value={models} onInput={(e) => setModels(e.target.value)} /></div>
      <div class="field"><label>Default model</label>
        <select disabled={!me.is_admin} value={s.default_model} onChange={(e) => setS({ ...s, default_model: e.target.value })}>
          {models.split('\n').filter(Boolean).map((m) => <option>{m}</option>)}
        </select></div>
      {me.is_admin ? <button class="btn primary" onClick={save}>Save</button> : <p class="muted small">Only admins can change workspace settings.</p>}
    </div>
  )
}

function Members({ me }) {
  const [list, setList] = useState([])
  const load = () => api('/api/members').then(setList)
  useEffect(() => { load() }, [])
  return (
    <table class="table">
      <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th></tr></thead>
      <tbody>{list.map((u) => (
        <tr><td>{u.name}</td><td>{u.email}</td>
          <td>{me.is_admin && u.id !== me.id
            ? <select value={u.is_admin ? 'admin' : 'member'} onChange={async (e) => { await api(`/api/members/${u.id}`, { method: 'PUT', body: { is_admin: e.target.value === 'admin' } }); load() }}>
                <option value="member">Member</option><option value="admin">Admin</option></select>
            : (u.is_admin ? 'Admin' : 'Member')}</td>
          <td>{timeAgo(u.created_at)}</td></tr>))}
      </tbody>
    </table>
  )
}

function Audit() {
  const [rows, setRows] = useState([])
  useEffect(() => { api('/api/audit').then(setRows).catch((e) => toast(e.message, 'error')) }, [])
  return (
    <table class="table">
      <thead><tr><th>Time</th><th>User</th><th>Event</th><th>Detail</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr><td class="nowrap">{new Date(r.ts * 1000).toLocaleString()}</td><td>{r.email}</td><td><code>{r.event}</code></td>
          <td class="small mono">{JSON.stringify(r.detail)}</td></tr>))}</tbody>
    </table>
  )
}

function Account({ me }) {
  const sf = me.snowflake || {}
  return (
    <div class="form">
      <div class="kv"><span>Name</span><b>{me.name}</b></div>
      <div class="kv"><span>Email (UPN)</span><b>{me.email}</b></div>
      <div class="kv"><span>Workspace role</span><b>{me.is_admin ? 'Admin' : 'Member'}</b></div>
      <h3>Snowflake session token</h3>
      <div class="kv"><span>Account</span><code>{sf.account}</code></div>
      <div class="kv"><span>Token user</span><code>{sf.upn}</code></div>
      <div class="kv"><span>Scope</span><code>{sf.scp}</code></div>
      <div class="kv"><span>Audience</span><code>{sf.aud}</code></div>
      <div class="kv"><span>Expires</span><b>{sf.exp ? new Date(sf.exp * 1000).toLocaleTimeString() : '—'}</b> <span class="muted small">(refreshed automatically)</span></div>
    </div>
  )
}

export function SettingsPage({ me, tab }) {
  const tabs = [['general', 'General'], ['members', 'Members'], ['account', 'Account'], ...(me.is_admin ? [['audit', 'Audit log']] : [])]
  return (
    <div class="page">
      <div class="page-head"><div><h1>Settings</h1></div></div>
      <div class="tabs">{tabs.map(([k, l]) => <button class={`tab ${tab === k ? 'active' : ''}`} onClick={() => navigate(`/settings/${k}`)}>{l}</button>)}</div>
      {tab === 'general' && <General me={me} />}
      {tab === 'members' && <Members me={me} />}
      {tab === 'account' && <Account me={me} />}
      {tab === 'audit' && me.is_admin && <Audit />}
    </div>
  )
}

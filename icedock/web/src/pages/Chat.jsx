import { useEffect, useRef, useState } from 'preact/hooks'
import { api, connectPopup, navigate, streamPost } from '../api.js'
import { Icon, IntegrationIcon, Markdown, toast } from '../components/ui.jsx'

function ToolCard({ t }) {
  const [open, setOpen] = useState(false)
  const running = t.output === undefined
  return (
    <div class={`tool-card ${running ? 'running' : ''}`}>
      <button class="tool-head" onClick={() => setOpen(!open)}>
        {running ? <span class="spinner sm" /> : <Icon name="check" size={14} class="ok" />}
        <span class="tool-title">{running ? 'Using' : 'Used'} <b>{t.tool}</b></span>
        <span class="tool-integ">{t.integration}</span>
        {t.acting_as && <span class="tool-as" title="Identity used for this call">as {t.acting_as}</span>}
        <Icon name="chevron" size={14} class={open ? 'rot' : ''} />
      </button>
      {open && (
        <div class="tool-body">
          <div class="label">Input</div>
          <pre>{JSON.stringify(t.args, null, 2)}</pre>
          {!running && <><div class="label">Output</div><pre>{t.output}</pre></>}
        </div>
      )}
    </div>
  )
}

function AssistantMessage({ m, last, onRegenerate, onConnect, streaming }) {
  return (
    <div class="msg assistant">
      <div class="msg-avatar">{m.agentEmoji || <Icon name="chat" size={14} />}</div>
      <div class="msg-body">
        {(m.tool_calls || []).map((t) => <ToolCard t={t} />)}
        {m.content ? <Markdown text={m.content} /> : streaming && !(m.tool_calls || []).length && <div class="typing"><span /><span /><span /></div>}
        {m.connect && (
          <div class="connect-card">
            <IntegrationIcon icon="snowflake" size={32} />
            <div>
              <b>Connect {m.connect.integration}</b>
              <div class="muted small">This answer needs a tool that runs with your own account. Sign in once to continue.</div>
            </div>
            <button class="btn primary" onClick={() => onConnect(m.connect)}>Connect</button>
          </div>
        )}
        {m.error && <div class="error-box">{m.error}</div>}
        {!streaming && m.content && (
          <div class="msg-actions">
            <button class="icon-btn tiny" title="Copy" onClick={() => { navigator.clipboard.writeText(m.content); toast('Copied') }}><Icon name="copy" size={14} /></button>
            {last && <button class="icon-btn tiny" title="Regenerate" onClick={onRegenerate}><Icon name="refresh" size={14} /></button>}
          </div>
        )}
      </div>
    </div>
  )
}

export function ChatPage({ chatId, me, refreshChats, search = '' }) {
  const [chat, setChat] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [agent, setAgent] = useState(null)
  const [integrations, setIntegrations] = useState([])
  const [enabled, setEnabled] = useState([])
  const [toolsOpen, setToolsOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const abort = useRef(null)
  const scroller = useRef(null)
  const ta = useRef(null)
  const params = new URLSearchParams(search)
  const agentParam = params.get('agent')

  useEffect(() => {
    api('/api/settings').then((s) => { setModels(s.models); setModel((m) => m || s.default_model) })
    api('/api/integrations').then((list) => {
      setIntegrations(list)
      const saved = JSON.parse(localStorage.getItem('ldc_enabled_integrations') || 'null')
      setEnabled(saved ?? list.filter((i) => i.tools.length).map((i) => i.id))
    })
  }, [])

  useEffect(() => {
    if (chatId && chat?.id === chatId) return
    if (!chatId) {
      setChat(null); setMessages([]); setInput('')
      if (agentParam) api(`/api/agents/${agentParam}`).then((a) => { setAgent(a); if (a.model) setModel(a.model) }).catch(() => setAgent(null))
      else setAgent(null)
      setTimeout(() => ta.current?.focus(), 0)
      return
    }
    api(`/api/chats/${chatId}`).then((c) => {
      setChat(c); setMessages(c.messages); setAgent(c.agent); setModel(c.model)
    }).catch((e) => { toast(e.message, 'error'); navigate('/') })
  }, [chatId, search])

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }) }, [messages])

  const toggleIntegration = (id) => {
    const next = enabled.includes(id) ? enabled.filter((x) => x !== id) : [...enabled, id]
    setEnabled(next); localStorage.setItem('ldc_enabled_integrations', JSON.stringify(next))
  }

  const run = async (content, { regenerate = false } = {}) => {
    let c = chat
    if (!c) {
      c = await api('/api/chats', { method: 'POST', body: { agent_id: agent?.id || null, model } })
      setChat({ ...c, agent })
      history.replaceState({}, '', `/chat/${c.id}`)
    }
    const draft = { role: 'assistant', content: '', tool_calls: [], agentEmoji: agent?.emoji }
    setMessages((ms) => {
      let base = ms
      if (regenerate) { const i = base.map((x) => x.role).lastIndexOf('assistant'); if (i >= 0) base = base.slice(0, i) }
      else base = [...base, { role: 'user', content }]
      return [...base, draft]
    })
    const update = (fn) => setMessages((ms) => { const copy = ms.slice(); copy[copy.length - 1] = fn({ ...copy[copy.length - 1] }); return copy })
    setStreaming(true)
    abort.current = new AbortController()
    try {
      await streamPost(`/api/chats/${c.id}/messages`, { content, integrations: enabled, regenerate }, (ev) => {
        if (ev.type === 'token') update((m) => ({ ...m, content: m.content + ev.text }))
        else if (ev.type === 'assistant_partial' && ev.content) update((m) => ({ ...m, content: m.content + '\n\n' }))
        else if (ev.type === 'tool_start') update((m) => ({ ...m, tool_calls: [...m.tool_calls, { id: ev.id, tool: ev.tool, integration: ev.integration, args: ev.args }] }))
        else if (ev.type === 'tool_end') update((m) => ({ ...m, tool_calls: m.tool_calls.map((t) => (t.id === ev.id ? { ...t, output: ev.output, acting_as: ev.acting_as } : t)) }))
        else if (ev.type === 'connect_required') update((m) => ({ ...m, connect: ev }))
        else if (ev.type === 'error') update((m) => ({ ...m, error: ev.message }))
      }, abort.current.signal)
    } catch (e) {
      if (e.name !== 'AbortError') update((m) => ({ ...m, error: e.message }))
    } finally {
      setStreaming(false)
      refreshChats()
      api(`/api/chats/${c.id}`).then((fresh) => setChat((cur) => ({ ...cur, title: fresh.title }))).catch(() => {})
    }
  }

  const send = () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    run(text)
  }

  const onConnect = async (info) => {
    const r = await connectPopup(info.integration_id)
    if (r.status === 'ok' || r.status === 'warn') {
      toast(`Connected ${info.integration}`, 'success')
      setIntegrations(await api('/api/integrations'))
      run('', { regenerate: true })
    } else toast('Connection was not completed', 'error')
  }

  const changeModel = async (m) => {
    setModel(m); setModelOpen(false)
    if (chat) await api(`/api/chats/${chat.id}`, { method: 'PATCH', body: { model: m } })
  }

  const empty = !messages.length
  const lastAssistant = messages.map((m) => m.role).lastIndexOf('assistant')
  const usable = integrations.filter((i) => i.tools.length || i.auth_type === 'oauth_manual')

  const composer = (
    <div class="composer">
      <textarea ref={ta} rows={1} value={input} placeholder={agent ? `Message ${agent.name}` : 'Ask anything'}
        onInput={(e) => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 220) + 'px' }}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
      <div class="composer-bar">
        <div class="composer-left">
          <div class="dropdown">
            <button class="chip" onClick={() => setModelOpen(!modelOpen)} disabled={!!agent?.model}>
              <Icon name="snowflake" size={13} /> {model || 'Model'} {!agent?.model && <Icon name="chevron" size={12} />}
            </button>
            {modelOpen && (
              <div class="menu up" onMouseLeave={() => setModelOpen(false)}>
                <div class="menu-label">Models (Snowflake Cortex)</div>
                {models.map((m) => <button class="menu-item" onClick={() => changeModel(m)}>{m === model && <Icon name="check" size={14} />} {m}</button>)}
              </div>
            )}
          </div>
          {!agent && (
            <div class="dropdown">
              <button class={`chip ${enabled.length ? 'on' : ''}`} onClick={() => setToolsOpen(!toolsOpen)}>
                <Icon name="wrench" size={13} /> Tools {enabled.length ? `(${enabled.length})` : ''}
              </button>
              {toolsOpen && (
                <div class="menu up wide" onMouseLeave={() => setToolsOpen(false)}>
                  <div class="menu-label">Integrations</div>
                  {usable.map((i) => (
                    <label class="menu-item check">
                      <input type="checkbox" checked={enabled.includes(i.id)} onChange={() => toggleIntegration(i.id)} />
                      <IntegrationIcon icon={i.icon} size={20} /> <span class="grow">{i.name}</span>
                      <span class={`dot ${i.connected ? 'green' : 'grey'}`} title={i.connected ? 'Connected' : 'Not connected'} />
                    </label>
                  ))}
                  {!usable.length && <div class="muted small pad">No integrations yet</div>}
                  <button class="menu-item" onClick={() => navigate('/integrations')}><Icon name="plus" size={14} /> Manage integrations</button>
                </div>
              )}
            </div>
          )}
        </div>
        {streaming
          ? <button class="send stop" onClick={() => abort.current?.abort()} aria-label="Stop"><Icon name="stop" /></button>
          : <button class="send" onClick={send} disabled={!input.trim()} aria-label="Send"><Icon name="send" /></button>}
      </div>
    </div>
  )

  if (empty) {
    return (
      <div class="chat empty">
        <div class="hero">
          {agent ? (
            <>
              <div class="agent-emoji big">{agent.emoji}</div>
              <h1>{agent.name}</h1>
              <p class="muted">{agent.description}</p>
            </>
          ) : <h1>Hi {me.name?.split(' ')[0]}, how can I help?</h1>}
          {composer}
          <div class="starters">
            {(agent?.starters?.length ? agent.starters : ['Which funds and AUM can I see?', 'Summarise the latest research notes', 'Who am I in Snowflake (user and role)?'])
              .filter(Boolean).map((s) => <button class="starter" onClick={() => run(s)}>{s}</button>)}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div class="chat">
      <div class="chat-header">
        <div class="chat-title">{agent && <span class="emoji">{agent.emoji}</span>}{chat?.title || 'New chat'}</div>
        {agent && <span class="badge">Agent · {agent.name}</span>}
      </div>
      <div class="messages" ref={scroller}>
        <div class="messages-inner">
          {messages.map((m, i) => m.role === 'user'
            ? <div class="msg user"><div class="bubble">{m.content}</div></div>
            : <AssistantMessage m={{ ...m, agentEmoji: m.agentEmoji || agent?.emoji }} last={i === lastAssistant}
                streaming={streaming && i === messages.length - 1}
                onRegenerate={() => run('', { regenerate: true })} onConnect={onConnect} />)}
        </div>
      </div>
      <div class="composer-wrap">{composer}<div class="disclaimer">Answers are generated by Snowflake Cortex as {me.email}. Check important information.</div></div>
    </div>
  )
}

import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

const P = {
  chat: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  plus: 'M12 5v14M5 12h14',
  bot: 'M12 8V4H8M4 12a8 8 0 0 1 16 0v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM9 13v2M15 13v2',
  plug: 'M12 22v-5M9 8V2M15 8V2M18 8v5a6 6 0 0 1-12 0V8z',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  send: 'M12 19V5M5 12l7-7 7 7',
  stop: 'M7 7h10v10H7z',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  refresh: 'M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5',
  trash: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z',
  pin: 'M12 17v5M9 3h6l-1 6 4 4H6l4-4z',
  dots: 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
  check: 'M20 6 9 17l-5-5',
  x: 'M18 6 6 18M6 6l12 12',
  chevron: 'm6 9 6 6 6-6',
  wrench: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  sidebar: 'M3 3h18v18H3zM9 3v18',
  snowflake: 'M12 2v20M4.9 4.9l14.2 14.2M2 12h20M4.9 19.1 19.1 4.9M9 3l3 3 3-3M9 21l3-3 3 3M3 9l3 3-3 3M21 9l-3 3 3 3',
  link: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
}

export function Icon({ name, size = 16, class: cls = '' }) {
  return (
    <svg class={`icon ${cls}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d={P[name] || P.plug} />
    </svg>
  )
}

export function Markdown({ text }) {
  const html = DOMPurify.sanitize(marked.parse(text || ''))
  return <div class="md" dangerouslySetInnerHTML={{ __html: html }} />
}

export function Modal({ title, onClose, children, wide }) {
  return (
    <div class="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div class={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div class="modal-head">
          <h3>{title}</h3>
          <button class="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div class="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function Toggle({ checked, onChange, label }) {
  return (
    <label class="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span class="track"><span class="thumb" /></span>
      {label && <span>{label}</span>}
    </label>
  )
}

export function Menu({ items, onClose }) {
  return (
    <div class="menu" onMouseLeave={onClose}>
      {items.map((it) => (
        <button class={`menu-item ${it.danger ? 'danger' : ''}`} onClick={() => { onClose(); it.onClick() }}>
          {it.icon && <Icon name={it.icon} size={14} />} {it.label}
        </button>
      ))}
    </div>
  )
}

const toasts = { set: null }
export function toast(msg, kind = 'info') { toasts.set?.((t) => [...t, { id: Math.random(), msg, kind }]) }
export function Toasts({ list, setList }) {
  toasts.set = setList
  return (
    <div class="toasts">
      {list.map((t) => (
        <div class={`toast ${t.kind}`} onClick={() => setList((l) => l.filter((x) => x.id !== t.id))}
          ref={() => setTimeout(() => setList((l) => l.filter((x) => x.id !== t.id)), 4500)}>{t.msg}</div>
      ))}
    </div>
  )
}

export function IntegrationIcon({ icon, size = 28 }) {
  return (
    <span class={`integ-icon ${icon === 'snowflake' ? 'snow' : ''}`} style={{ width: size, height: size }}>
      <Icon name={icon === 'snowflake' ? 'snowflake' : 'plug'} size={size * 0.55} />
    </span>
  )
}

// Blurs identifying values in the Icedock UI before taking README screenshots.
// Usage: paste into the page (or run via the browser tool) before capturing.
(() => {
  const re = /seclab42|kevin\.keller|secfieldkeller|b3b06c45|818a03b1|370236f4|KELLER/i
  const blur = (el) => { el.style.filter = 'blur(5px)'; el.style.userSelect = 'none' }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const hits = []
  while (walker.nextNode()) if (re.test(walker.currentNode.nodeValue)) hits.push(walker.currentNode)
  for (const t of hits) {
    const parts = t.nodeValue.split(/(\S*(?:seclab42|kevin\.keller|secfieldkeller|b3b06c45|818a03b1|370236f4|KELLER)\S*)/i)
    const frag = document.createDocumentFragment()
    for (const p of parts) {
      if (!p) continue
      if (re.test(p)) { const s = document.createElement('span'); s.textContent = p; blur(s); s.style.display = 'inline-block'; frag.append(s) }
      else frag.append(p)
    }
    t.replaceWith(frag)
  }
  document.querySelectorAll('input, textarea').forEach((i) => { if (re.test(i.value)) blur(i) })
  return hits.length
})()

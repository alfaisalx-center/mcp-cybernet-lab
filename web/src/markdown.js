// Tiny, dependency-free Markdown → HTML for the catalogue view. Escapes HTML first, then handles
// headings, fenced code, lists, tables (pipe), bold, inline code and links. Not a full parser —
// enough for the docs we render.
function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
}

export function md(src) {
  const lines = (src || '').split('\n')
  const out = []
  let i = 0
  let inList = false
  const closeList = () => { if (inList) { out.push('</ul>'); inList = false } }

  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      closeList()
      const buf = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) { buf.push(esc(lines[i])); i++ }
      i++
      out.push('<pre class="code"><code>' + buf.join('\n') + '</code></pre>')
      continue
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue }
    if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push('<li>' + inline(line.replace(/^\s*[-*]\s+/, '')) + '</li>'); i++; continue
    }
    // pipe table
    if (line.includes('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      closeList()
      const cell = (r) => r.split('|').map((x) => x.trim()).filter((x, j, a) => !(j === 0 && !x) && !(j === a.length - 1 && !x))
      const head = cell(line)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].includes('|')) { rows.push(cell(lines[i])); i++ }
      out.push('<table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'
        + rows.map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>')
      continue
    }
    if (line.trim() === '') { closeList(); i++; continue }
    closeList()
    out.push('<p>' + inline(line) + '</p>')
    i++
  }
  closeList()
  return out.join('\n')
}

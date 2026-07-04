/* Minimal markdown-to-HTML for executor final messages. Escapes everything
   first; only emits tags this renderer itself creates, so it is XSS-safe. */

function esc(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

function inline(text: string): string {
  let html = esc(text)
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>")
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
  html = html.replace(
    /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" rel="noopener" target="_blank">$1</a>',
  )
  return html
}

export function renderMarkdown(source: string): string {
  const lines = String(source || "").split("\n")
  const out: string[] = []
  let inCode = false
  let codeLines: string[] = []
  let listType: "ul" | "ol" | null = null
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${inline(paragraph.join(" "))}</p>`)
      paragraph = []
    }
  }
  const flushList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }

  for (const raw of lines) {
    if (raw.trimStart().startsWith("```")) {
      if (inCode) {
        out.push(`<pre><code>${esc(codeLines.join("\n"))}</code></pre>`)
        codeLines = []
        inCode = false
      } else {
        flushParagraph()
        flushList()
        inCode = true
      }
      continue
    }
    if (inCode) {
      codeLines.push(raw)
      continue
    }
    const line = raw.trimEnd()
    const heading = /^(#{1,6})\s+(.*)$/.exec(line.trim())
    const bullet = /^[-*]\s+(.*)$/.exec(line.trim())
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line.trim())

    if (!line.trim()) {
      flushParagraph()
      flushList()
      continue
    }
    if (heading) {
      flushParagraph()
      flushList()
      const level = Math.min(heading[1].length, 3)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
    } else if (bullet) {
      flushParagraph()
      if (listType !== "ul") {
        flushList()
        out.push("<ul>")
        listType = "ul"
      }
      out.push(`<li>${inline(bullet[1])}</li>`)
    } else if (numbered) {
      flushParagraph()
      if (listType !== "ol") {
        flushList()
        out.push("<ol>")
        listType = "ol"
      }
      out.push(`<li>${inline(numbered[1])}</li>`)
    } else {
      flushList()
      paragraph.push(line.trim())
    }
  }
  if (inCode) out.push(`<pre><code>${esc(codeLines.join("\n"))}</code></pre>`)
  flushParagraph()
  flushList()
  return out.join("\n")
}

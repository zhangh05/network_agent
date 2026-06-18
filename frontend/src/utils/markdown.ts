/**
 * Lightweight Markdown-to-HTML renderer for LLM chat messages.
 *
 * Handles: code blocks (```), inline code (`), tables, headers,
 * bold/italic, lists, blockquotes, horizontal rules, links.
 *
 * No external dependencies. Token-budget friendly (~3KB).
 */

// ── Helper: escape HTML (except what we intentionally render) ──

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function normalizeMarkdown(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .replace(/&lt;br\s*\/?&gt;/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{4,}/g, '\n\n\n');
}

function renderSoftBreakLines(lines: string[]): string {
  return renderInline(escapeHtml(lines.join('\n'))).replace(/\n/g, '<br />');
}

// ── Inline formatting ──

function renderInline(raw: string): string {
  let text = raw;

  // Inline code (must run before bold/italic)
  text = text.replace(/`([^`]+)`/g, (_: string, c: string) =>
    `<code>${escapeHtml(c)}</code>`
  );

  // Bold + italic combined
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  text = text.replace(/___(.+?)___/g, '<strong><em>$1</em></strong>');

  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__(.+?)__/g, '<strong>$1</strong>');

  // Italic
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
  text = text.replace(/_(.+?)_/g, '<em>$1</em>');

  // Strikethrough
  text = text.replace(/~~(.+?)~~/g, '<s>$1</s>');

  // Links [text](url)
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );

  return text;
}

// ── Table rendering ──

function renderTable(lines: string[]): string | null {
  if (lines.length < 2) return null;

  const headerLine = lines[0];
  const separatorLine = lines[1];

  // Check if it's a table (header with |, separator with |---|---|)
  if (!headerLine.includes('|') || !separatorLine.match(/^\|?[\s:-]+\|[\s|:-]+\|?$/)) {
    return null;
  }

  const bodyLines = lines.slice(2).filter(l => l.includes('|'));

  const parseRow = (line: string): string[] =>
    line.split('|')
      .map(c => c.trim())
      .filter(c => c !== '');

  const headers = parseRow(headerLine);
  const alignments: string[] = parseRow(separatorLine).map(a =>
    a.startsWith(':') && a.endsWith(':') ? 'center' :
    a.endsWith(':') ? 'right' :
    'left'
  );

  const thead = `<thead><tr>${headers
    .map((h, i) => `<th style="text-align:${alignments[i] || 'left'}">${renderInline(escapeHtml(h))}</th>`)
    .join('')}</tr></thead>`;

  const tbody = bodyLines.length
    ? `<tbody>${bodyLines.map(line => {
        const cells = parseRow(line);
        return `<tr>${headers.map((_, i) => {
          const cell = cells[i] ?? '';
          return `<td style="text-align:${alignments[i] || 'left'}">${renderInline(escapeHtml(cell))}</td>`;
        }).join('')}</tr>`;
      }).join('')}</tbody>`
    : '';

  return `<table>${thead}${tbody}</table>`;
}

// ── Main renderer ──

export function renderMarkdown(text: string): string {
  if (!text) return '';

  const lines = normalizeMarkdown(text).split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // ── Code blocks (fenced) ──
    if (line.trimStart().startsWith('```')) {
      const lang = line.trimStart().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      const codeText = escapeHtml(codeLines.join('\n'));
      const langLabel = lang ? `<span class="code-lang">${escapeHtml(lang)}</span>` : '';
      out.push(`<pre class="code-block">${langLabel}<code>${codeText || ' '}</code></pre>`);
      continue;
    }

    // ── Headers (trim leading whitespace, # or ## or ###) ──
    const trimmed = line.trimStart();
    const headerMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headerMatch) {
      const level = Math.min(headerMatch[1].length + 1, 6);
      out.push(`<h${level}>${renderInline(escapeHtml(headerMatch[2].trim()))}</h${level}>`);
      i++;
      continue;
    }

    // ── Horizontal rule ──
    if (/^(---|\*\*\*|___)\s*$/.test(line.trim())) {
      out.push('<hr />');
      i++;
      continue;
    }

    // ── Blockquote ──
    if (line.startsWith('>')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].startsWith('>')) {
        quoteLines.push(lines[i].slice(1).trimStart());
        i++;
      }
      out.push(`<blockquote><p>${renderSoftBreakLines(quoteLines)}</p></blockquote>`);
      continue;
    }

    // ── Table detection (multi-line) ──
    const remaining = lines.slice(i);
    const tableResult = renderTable(remaining);
    if (tableResult) {
      out.push(tableResult);
      // Skip all consumed table lines (header + sep + body lines without | separator)
      i += 2; // header + separator
      while (i < lines.length && lines[i].includes('|')) i++;
      continue;
    }
    // Orphan | line without valid table — render as paragraph
    if (line.startsWith('|') && !tableResult) {
      out.push(`<p>${renderInline(escapeHtml(line.trim()))}</p>`);
      i++;
      continue;
    }

    // ── Unordered list ──
    if (/^[\s]*[-*+]\s+/.test(line)) {
      out.push('<ul>');
      while (i < lines.length && /^[\s]*[-*+]\s+/.test(lines[i])) {
        const item = lines[i].replace(/^[\s]*[-*+]\s+/, '');
        out.push(`<li>${renderInline(escapeHtml(item))}</li>`);
        i++;
      }
      out.push('</ul>');
      continue;
    }

    // ── Ordered list (only if starts at 1, or there are ≥2 consecutive numbered lines) ──
    const orderedMatch = line.match(/^(\d+)\.\s+/);
    if (orderedMatch) {
      // Peek ahead to see if this is part of a real list (≥2 consecutive items)
      let listCount = 0;
      let peek = i;
      while (peek < lines.length && /^\d+\.\s+/.test(lines[peek])) {
        listCount++;
        peek++;
      }
      if (listCount >= 2 || orderedMatch[1] === '1') {
        out.push('<ol>');
        while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
          const item = lines[i].replace(/^\d+\.\s+/, '');
          out.push(`<li>${renderInline(escapeHtml(item))}</li>`);
          i++;
        }
        out.push('</ol>');
        continue;
      }
      // Single numbered line (not a real list) — render as paragraph and advance
      out.push(`<p>${renderInline(escapeHtml(line.trim()))}</p>`);
      i++;
      continue;
    }

    // ── Empty line → soft break (skip consecutive blanks) ──
    if (line.trim() === '') {
      i++;
      continue;
    }

    // ── Regular paragraph ──
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' &&
           !lines[i].startsWith('```') && !lines[i].startsWith('#') &&
           !lines[i].startsWith('>') && !lines[i].startsWith('|') &&
           !/^[\s]*[-*+]\s+/.test(lines[i]) && !/^\d+\.\s+/.test(lines[i]) &&
           !/^(---|\*\*\*|___)\s*$/.test(lines[i].trim())) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length) {
      out.push(`<p>${renderSoftBreakLines(paraLines)}</p>`);
    }
  }

  return out.join('\n');
}

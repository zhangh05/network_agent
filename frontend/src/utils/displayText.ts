import { renderMarkdown } from './markdown';

export function sanitizeAssistantText(text: string): string {
  const raw = text ?? "";
  if (
    /I'm Network Agent,\s*your AI assistant for network operations/i.test(raw) ||
    /What would you like to do today\?/i.test(raw)
  ) {
    return [
      "当前可处理：配置翻译、知识库检索、制品查看和评审流转。",
      "拓扑、巡检和 CMDB 仍在规划中，未上线的能力不会假装可用。",
    ].join("\n");
  }
  return _stripThinkTags(raw)
    .replace(/^\s*(reasoning|思考过程)\s*[:：][\s\S]*?(?=\n\s*(answer|回答|结论)\s*[:：]|\s*$)/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Strip <think>...</think> blocks with proper nesting support. */
function _stripThinkTags(text: string): string {
  let depth = 0;
  let start = -1;
  const parts: string[] = [];
  let lastEnd = 0;

  const re = /<\/?think\b[^>]*>/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const tag = m[0].toLowerCase();
    if (tag.startsWith('</')) {
      if (depth > 0) {
        depth--;
        if (depth === 0) {
          parts.push(text.slice(lastEnd, start));
          lastEnd = m.index + tag.length;
        }
      }
    } else {
      if (depth === 0) {
        start = m.index;
      }
      depth++;
    }
  }
  parts.push(text.slice(lastEnd));
  return parts.join('');
}

/** Render assistant message text as safe HTML (Markdown → styled HTML). */
export function renderAssistantHtml(text: string): string {
  const cleaned = sanitizeAssistantText(text);
  if (!cleaned) return '';
  return renderMarkdown(cleaned);
}

export function shortId(id: string | undefined | null, fallback = "—"): string {
  if (!id) return fallback;
  if (id.length <= 14) return id;
  return `${id.slice(0, 8)}…${id.slice(-4)}`;
}

export function formatCompactDate(value: string | undefined | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

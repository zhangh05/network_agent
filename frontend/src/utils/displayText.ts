export function sanitizeAssistantText(text: string): string {
  return (text ?? "")
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, "")
    .replace(/<reasoning\b[^>]*>[\s\S]*?<\/reasoning>/gi, "")
    .replace(/^\s*(reasoning|思考过程)\s*[:：][\s\S]*?(?=\n\s*(answer|回答|结论)\s*[:：]|\s*$)/gim, "")
    .replace(/<\/?(think|reasoning)\b[^>]*>/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
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

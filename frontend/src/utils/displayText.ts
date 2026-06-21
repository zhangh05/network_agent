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

// ───────────────────── Tool display helpers ─────────────────────

/**
 * Shared tool label mapping — consolidated from AgentWorkbench + Inspector.
 * Covers all known tool prefixes. Single source of truth for tool display names.
 */
export function toolLabel(toolId: string): string {
  if (toolId.startsWith("host.")) return "本机工具";
  if (toolId.startsWith("workspace.file.")) return "工作区文件";
  if (toolId.startsWith("workspace.artifact.")) return "工作区制品";
  if (toolId.startsWith("network.")) return "网络分析";
  if (toolId.startsWith("web.")) return "外部资料";
  if (toolId.startsWith("memory.")) return "记忆";
  if (toolId.startsWith("report.") || toolId.startsWith("data.") || toolId.startsWith("text.")) return "输出处理";
  if (toolId.startsWith("agent.")) return "多 Agent";
  if (toolId.startsWith("config_translation.")) return "配置翻译";
  if (toolId.startsWith("knowledge.")) return "知识检索";
  if (toolId.startsWith("artifact.")) return "制品操作";
  if (toolId.startsWith("review.")) return "评审流转";
  if (toolId.startsWith("runtime.")) return "运行诊断";
  return "工具调用";
}

/**
 * Extract tool plan steps from scene metadata (tool_plan or tool_chain).
 * Returns an array of ToolPlanStep objects.
 */
export function toolPlanSteps(scene: unknown): Array<Record<string, unknown>> {
  if (!scene || typeof scene !== "object") return [];
  const plan = (scene as Record<string, unknown>).tool_plan;
  const chain = (scene as Record<string, unknown>).tool_chain;
  if (Array.isArray(plan)) return plan as Array<Record<string, unknown>>;
  if (Array.isArray(chain)) return chain as Array<Record<string, unknown>>;
  return [];
}

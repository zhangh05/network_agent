import { describe, expect, it } from "vitest";
import { renderAssistantHtml, sanitizeAssistantText } from "../utils/displayText";
import { formatDate } from "../utils/format";

describe("sanitizeAssistantText", () => {
  it("rewrites old English assistant welcome copy into product-tone Chinese", () => {
    const cleaned = sanitizeAssistantText(
      "Hello! 👋 I'm Network Agent, your AI assistant for network operations.\n\n" +
        "I can help you with:\n\n" +
        "- **Config translation** — Convert network device configurations between vendors\n" +
        "- **Knowledge queries** — Search the local knowledge base\n\n" +
        "What would you like to do today?",
    );

    expect(cleaned).toContain("当前可处理");
    expect(cleaned).toContain("配置翻译");
    expect(cleaned).not.toMatch(/AI assistant|What would you like|Hello!|👋/i);
  });

  it("renders literal br markers as real line breaks instead of visible text", () => {
    const html = renderAssistantHtml("下一步验证： <br> 你可以指定一个方向\n`kubernetes.io`");

    expect(html).toContain("下一步验证：");
    expect(html).toContain("<br />");
    expect(html).toContain("<code>kubernetes.io</code>");
    expect(html).not.toMatch(/&lt;br|<br&gt;/i);
  });
});

describe("formatDate", () => {
  it("renders backend UTC timestamps in the product timezone", () => {
    expect(formatDate("2026-07-02T00:42:33+00:00", "time")).toBe("08:42");
    expect(formatDate("2026-07-02T00:42:33+00:00", "compact")).toContain("2026/07/02");
    expect(formatDate("2026-07-02T00:42:33+00:00", "compact")).toContain("08:42");
  });
});

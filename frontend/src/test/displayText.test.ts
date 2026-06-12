import { describe, expect, it } from "vitest";
import { sanitizeAssistantText } from "../utils/displayText";

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
});

/**
 * Test 2 — tool_calls 卡片
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Inspector } from "../layouts/Inspector";
import { useWorkbenchStore } from "../stores/workbench";
import type { AgentResult } from "../types";

describe("Inspector — tool_calls card", () => {
  beforeEach(() => {
    useWorkbenchStore.getState().clear();
  });

  it("renders a card per tool call with status + duration", () => {
    const result: AgentResult = {
      ok: true,
      final_response: "",
      events: [],
      trace_id: "trace-x",
      session_id: "s",
      turn_id: "t",
      tool_calls: [
        {
          call_id: "c1",
          tool_id: "config_translation.translate_config",
          ok: true,
          duration_ms: 230,
        },
        {
          call_id: "c2",
          tool_id: "knowledge.query",
          ok: false,
          duration_ms: 12,
          error: "timeout",
        },
      ],
      warnings: [],
      errors: [],
      metadata: {},
    };
    useWorkbenchStore.setState({ latestResult: result });
    render(<Inspector />);
    const calls = screen.getByTestId("inspector-tool-calls");
    expect(calls).toBeInTheDocument();
    expect(calls.textContent).toContain("config_translation.translate_config");
    expect(calls.textContent).toContain("knowledge.query");
    expect(calls.textContent).toContain("230ms");
    expect(calls.textContent).toContain("12ms");
    expect(calls.textContent).toContain("failed");
    expect(calls.textContent).toContain("timeout");
  });
});

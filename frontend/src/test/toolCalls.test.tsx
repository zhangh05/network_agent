/**
 * Test 2 — tool_calls 卡片
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Inspector } from "../layouts/Inspector";
import { useWorkbenchStore } from "../stores/workbench";
import { installMockApi, resetMocks } from "./mockServer";
import type { AgentResult } from "../types";

describe("Inspector — tool_calls card", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useWorkbenchStore.getState().clear();
  });

  async function waitForInspectorEffects() {
    await waitFor(() => {
      expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
    });
  }

  it("renders a card per tool call with status", async () => {
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
          summary: "translation complete",
          artifacts: [],
          source_count: 3,
          manual_review_count: 0,
          errors: [],
          warnings: [],
          metadata: {},
        },
        {
          call_id: "c2",
          tool_id: "knowledge.search",
          ok: false,
          summary: "query failed",
          artifacts: [],
          source_count: null,
          manual_review_count: null,
          errors: ["timeout"],
          warnings: [],
          metadata: {},
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
    expect(calls.textContent).toContain("配置翻译");
    expect(calls.textContent).toContain("知识检索");
    expect(calls.textContent).toContain("需要关注");
    expect(calls.textContent).toContain("timeout");
    await waitForInspectorEffects();
  });

  it("summarizes recovered tool retries before raw technical details", async () => {
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
          ok: false,
          summary: "missing_source_config",
          artifacts: [],
          source_count: null,
          manual_review_count: null,
          errors: ["missing_source_config"],
          warnings: [],
          metadata: {},
        },
        {
          call_id: "c2",
          tool_id: "config_translation.translate_config",
          ok: true,
          summary: "translation complete",
          artifacts: [],
          source_count: null,
          manual_review_count: 5,
          errors: [],
          warnings: ["manual review required"],
          metadata: {},
        },
      ],
      warnings: [],
      errors: [],
      metadata: {},
    };
    useWorkbenchStore.setState({ latestResult: result });
    render(<Inspector />);

    expect(screen.getByTestId("inspector-tool-summary")).toHaveTextContent(
      "配置翻译已完成，1 次内部重试已自动恢复",
    );
    await waitForInspectorEffects();
  });
});

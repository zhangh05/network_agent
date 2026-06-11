/**
 * Test 1 — AgentResult 正常渲染
 * 验证 Inspector 能正确展示 turn_id / trace_id / final_response / tool_calls。
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Inspector } from "../layouts/Inspector";
import { useWorkbenchStore } from "../stores/workbench";
import type { AgentResult } from "../types";

const sampleResult: AgentResult = {
  ok: true,
  final_response: "OSPF 是一种链路状态路由协议。",
  events: [
    {
      event_id: "ev-1",
      event_type: "tool_call.start",
      occurred_at: "2026-06-11T10:00:00Z",
      payload: { tool_id: "knowledge.query" },
    },
  ],
  trace_id: "trace-abc",
  session_id: "sess-1",
  turn_id: "turn-1",
  tool_calls: [
    {
      call_id: "call-1",
      tool_id: "knowledge.query",
      ok: true,
      duration_ms: 142,
      result: { source_count: 3 },
    },
  ],
  warnings: ["knowledge scope fallback"],
  errors: [],
  metadata: {
    selected_skills: ["knowledge_query"],
    visible_tools: ["knowledge.query"],
    source_count: 3,
    retrieval_backend: "local_bm25",
    scope: "workspace",
  },
};

describe("Inspector — AgentResult normal rendering", () => {
  beforeEach(() => {
    useWorkbenchStore.getState().clear();
  });

  it("renders empty state when no result", () => {
    useWorkbenchStore.setState({ latestResult: null });
    render(<Inspector />);
    expect(screen.getByText(/尚无 turn 结果/i)).toBeInTheDocument();
  });

  it("renders turn_id, trace_id, final_response", () => {
    useWorkbenchStore.setState({ latestResult: sampleResult });
    render(<Inspector />);
    expect(screen.getByTestId("inspector-turn-id")).toHaveTextContent("turn-1");
    expect(screen.getByTestId("inspector-trace-id")).toHaveTextContent("trace-abc");
    expect(screen.getByTestId("inspector-body")).toBeInTheDocument();
  });

  it("renders the badge for the ok status", () => {
    useWorkbenchStore.setState({ latestResult: sampleResult });
    render(<Inspector />);
    const okBadges = screen.getAllByTestId("badge-ok");
    expect(okBadges.length).toBeGreaterThan(0);
  });
});

/**
 * Test 4 — knowledge source_summary
 *
 * v1.0.1 plan-C: AgentWorkbench 现在要求 currentSessionId 有值才能把消息
 * 落到 bySession map (否则 appendUser 静默 no-op). 测试里显式设 session.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AgentWorkbench } from "../pages/AgentWorkbench/AgentWorkbench";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";
import { useWorkbenchStore } from "../stores/workbench";
import type { AgentResult } from "../types";

describe("Agent Workbench — source_summary rendering", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useWorkbenchStore.getState().clear();
    useWorkbenchStore.setState({ bySession: {}, history: [] });
    useSessionStore.setState({
      currentWorkspaceId: "ws-1",
      currentSessionId: "s-1",
    });
  });

  it("renders inline source summary from tool call metadata", async () => {
    const resp: AgentResult = {
      ok: true,
      final_response: "OSPF 是一种链路状态协议。",
      events: [],
      trace_id: "trace-1",
      session_id: "s-1",
      turn_id: "t-1",
      tool_calls: [],
      warnings: [],
      errors: [],
      metadata: {
        source_count: 1,
        source_summary: [
          {
            source_id: "src-1",
            title: "OSPF 完全手册",
            chapter: "第 1 章 OSPF 简介",
            section: "1.1 OSPF 邻居",
            snippet: "OSPF（开放式最短路径优先）是一种链路状态协议。",
            score: 4.5,
          },
        ],
      },
    };
    enqueue("/agent/message", { status: 200, data: resp });
    enqueue("/workspaces", { status: 200, data: { workspaces: [{ workspace_id: "ws-1", name: "WS1", created_at: "", is_default: true, stats: { session_count: 0, artifact_count: 0, knowledge_source_count: 0 } }] } });
    enqueue("/sessions", { status: 200, data: { sessions: [] } });
    enqueue("/runs/recent", { status: 200, data: { runs: [] } });
    // plan-C: background fetch on session switch + on turn complete
    enqueue("/sessions/s-1/messages", { status: 200, data: { ok: true, messages: [], count: 0 } });
    render(<AgentWorkbench />);
    const input = await screen.findByTestId("chat-input");
    fireEvent.change(input, { target: { value: "什么是 OSPF?" } });
    fireEvent.click(screen.getByTestId("btn-send"));
    const summary = await screen.findByTestId("inline-source-summary");
    expect(summary).toBeInTheDocument();
    // UI 在 v1.0.1 UI 重设计后中文化；inline source chip 显示 title + score
    expect(summary.textContent).toContain("OSPF 完全手册");
    expect(summary.textContent).toContain("4.50");
  });
});

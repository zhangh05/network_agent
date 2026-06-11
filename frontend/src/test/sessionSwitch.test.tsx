/**
 * Test 9 — session 切换
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Sidebar } from "../layouts/Sidebar";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";

describe("Session switch", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.getState().reset();
  });

  it("switches active session when user clicks", async () => {
    enqueue("/workspaces", { status: 200, data: { workspaces: [{ workspace_id: "ws-1", name: "WS1", created_at: "", is_default: true, stats: { session_count: 2, artifact_count: 0, knowledge_source_count: 0 } }] } });
    enqueue("/sessions", {
      status: 200,
      data: {
        sessions: [
          { session_id: "sess-A", workspace_id: "ws-1", title: "Session A", status: "active", created_at: "2026-06-11T09:00:00Z", updated_at: "2026-06-11T09:00:00Z", message_count: 3 },
          { session_id: "sess-B", workspace_id: "ws-1", title: "Session B", status: "active", created_at: "2026-06-11T09:30:00Z", updated_at: "2026-06-11T09:30:00Z", message_count: 1 },
        ],
      },
    });
    enqueue("/runs/recent", { status: 200, data: { runs: [] } });
    render(<Sidebar />);
    const sessB = await screen.findByTestId("sess-sess-B");
    fireEvent.click(sessB);
    expect(useSessionStore.getState().currentSessionId).toBe("sess-B");
  });
});

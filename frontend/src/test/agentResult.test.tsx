/**
 * Test 1 — RuntimeEventTimeline rendering
 * Verifies the Timeline correctly displays turn_id / trace_id / tool_calls / errors.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { RuntimeEventTimeline } from "../components/RuntimeEventTimeline";
import { installMockApi, resetMocks } from "./mockServer";
import type { AgentResult } from "../types";

const sampleResult: AgentResult = {
  ok: true,
  final_response: "OSPF 是一种链路状态路由协议。",
  events: [
    { event_id: "evt-1", event_type: "turn_started", summary: "Turn started" },
    { event_id: "evt-2", event_type: "tool_call", tool_id: "web.search", summary: "Searching..." },
    { event_id: "evt-3", event_type: "tool_result", tool_id: "web.search", summary: "Found 3 results" },
  ],
  trace_id: "trace_abc123",
  session_id: "sess_xyz",
  turn_id: "turn_001",
  tool_calls: [
    { call_id: "call-1", tool_id: "web.search", ok: true, duration_ms: 450, summary: "Found 3 results about OSPF" },
  ],
  warnings: [],
  errors: [],
  metadata: {
    selected_capabilities: ["knowledge"],
    workspace_id: "default",
    planner_mode: "deterministic",
    source_count: 3,
    retrieval_backend: "bm25",
  },
};

const failedResult: AgentResult = {
  ok: false,
  final_response: "",
  events: [
    { event_id: "evt-err", event_type: "error", summary: "Connection refused" },
  ],
  trace_id: "trace_fail",
  session_id: "sess_xyz",
  turn_id: "turn_002",
  tool_calls: [],
  warnings: ["Retry limit exceeded"],
  errors: ["SSH connection refused: port 22"],
  metadata: {
    workspace_id: "default",
  },
};

describe("RuntimeEventTimeline", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
  });

  it("renders turn header with turn_id", () => {
    render(<RuntimeEventTimeline result={sampleResult} />);
    expect(screen.getByTestId("runtime-timeline")).toBeInTheDocument();
    expect(screen.getByText(/turn_001/)).toBeInTheDocument();
  });

  it("shows event cards from events array", () => {
    render(<RuntimeEventTimeline result={sampleResult} />);
    expect(screen.getByTestId("event-0")).toBeInTheDocument();
    expect(screen.getByTestId("event-1")).toBeInTheDocument();
    expect(screen.getByTestId("event-2")).toBeInTheDocument();
  });

  it("shows tool calls panel", () => {
    render(<RuntimeEventTimeline result={sampleResult} />);
    expect(screen.getByTestId("tool-panel")).toBeInTheDocument();
    expect(screen.getByTestId("tool-call-call-1")).toBeInTheDocument();
  });

  it("shows diagnostics banner for errors", () => {
    render(<RuntimeEventTimeline result={failedResult} />);
    expect(screen.getByTestId("diag-banner")).toBeInTheDocument();
    expect(screen.getByText(/SSH connection refused/)).toBeInTheDocument();
  });

  it("shows workspace and planner metadata", () => {
    render(<RuntimeEventTimeline result={sampleResult} />);
    expect(screen.getByText(/default/)).toBeInTheDocument();
    expect(screen.getByText(/deterministic/)).toBeInTheDocument();
  });

  it("shows empty state when result is undefined", () => {
    render(<RuntimeEventTimeline result={undefined} />);
    expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
  });

  it("shows source panel when source_count > 0", () => {
    render(<RuntimeEventTimeline result={sampleResult} />);
    expect(screen.getByTestId("source-panel")).toBeInTheDocument();
    expect(screen.getByText(/3 个/)).toBeInTheDocument();
  });
});

import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionReportPanel } from "../components/DecisionReportPanel";
import { runtimeAuditApi } from "../api";
import { enqueue, getRequests, installMockApi, resetMocks } from "./mockServer";
import type { DecisionReport } from "../types";
import { useSessionStore } from "../stores/session";

const report: DecisionReport = {
  schema_version: "decision_report.v2",
  run_id: "run-1",
  session_id: "session-1",
  workspace_id: "default",
  created_at: "2026-06-21T00:00:00Z",
  decision_status: "complete",
  scene_decision: { category: "pcap" },
  business_capabilities: [{ capability_id: "pcap_analysis" }],
  tool_planning_decision: {
    visible_tools: ["pcap.manage"],
    required_tools: ["pcap.manage"],
    blocked_tools: [],
  },
  retrieval_decision: {
    memory: { status: "skipped", reason: "not_required" },
    knowledge: { status: "hit", count: 2 },
  },
  visibility_violations: [],
  tool_execution_summary: {
    called: ["pcap.manage"],
    blocked: [],
    failed: [],
    succeeded: ["pcap.manage"],
  },
  trace_summary: {
    real_event_count: 8,
    synthetic_event_count: 1,
    missing_event_count: 0,
  },
  warnings: [],
  errors: [],
  redaction_applied: true,
};

describe("DecisionReportPanel", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.getState().reset();
  });

  it("renders routing, retrieval, tool and trace truth", () => {
    render(<DecisionReportPanel report={report} />);
    expect(screen.getByText("pcap_analysis")).toBeInTheDocument();
    expect(screen.getByText("pcap.manage")).toBeInTheDocument();
    expect(screen.getByText(/知识：命中/)).toBeInTheDocument();
    expect(screen.getByText(/真实 8/)).toBeInTheDocument();
    expect(screen.getByText(/合成 1/)).toBeInTheDocument();
  });

  it("calls the workspace-scoped decision endpoint", async () => {
    enqueue("/workspaces/default/runs/run-1/decision", {
      status: 200,
      data: { ok: true, item: report, workspace_id: "default" },
    });
    const response = await runtimeAuditApi.decision("default", "run-1");
    expect(response.item.run_id).toBe("run-1");
    expect(getRequests().at(-1)?.url).toBe(
      "/workspaces/default/runs/run-1/decision",
    );
  });

  it("loads the selected run decision into the decision panel", async () => {
    useSessionStore.setState({
      currentWorkspaceId: "default",
      currentSessionId: "session-1",
    });
    enqueue("/workspaces/default/runs/run-1/decision", {
      status: 200,
      data: { ok: true, item: report, workspace_id: "default" },
    });
    // The RunsPage → "决策" button path was removed during the run-detail refactor; the
    // decision is rendered through DecisionReportPanel, so assert the loaded decision renders.
    const res = await runtimeAuditApi.decision("default", "run-1");
    render(<DecisionReportPanel report={res.item} />);
    expect(await screen.findByText("pcap_analysis")).toBeInTheDocument();
  });
});

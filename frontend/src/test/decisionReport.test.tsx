import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DecisionReportPanel } from "../components/DecisionReportPanel";
import { RunsPage } from "../pages/RunsPage/RunsPage";
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
  capability_route: {
    capability_ids: ["pcap_analysis"],
    confidence: { pcap_analysis: 0.9 },
    ambiguous: false,
    fallback_used: false,
  },
  tool_planning_decision: {
    visible_tools: ["pcap.analysis.run"],
    required_tools: ["pcap.analysis.run"],
    blocked_tools: [],
  },
  retrieval_decision: {
    memory: { status: "skipped", reason: "not_required" },
    knowledge: { status: "hit", count: 2 },
  },
  catalog_expansions: [],
  context_pipeline: { status: "ok", stages_run: 13 },
  visibility_violations: [],
  tool_execution_summary: {
    called: ["pcap.analysis.run"],
    blocked: [],
    failed: [],
    succeeded: ["pcap.analysis.run"],
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
    expect(screen.getByText("pcap.analysis.run")).toBeInTheDocument();
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

  it("loads the selected run decision into the decision tab", async () => {
    enqueue("/runs/recent", {
      status: 200,
      data: {
        runs: [{
          run_id: "run-1",
          turn_id: "run-1",
          session_id: "session-1",
          trace_id: "trace-1",
          status: "success",
          user_input_summary: "分析报文",
          selected_skills: [],
          visible_tools: [],
          tool_call_count: 1,
          warning_count: 0,
          error_count: 0,
          events: [],
          started_at: "",
          finished_at: "",
        }],
      },
    });
    enqueue("/workspaces/default/runs/run-1/trace", {
      status: 200,
      data: { events: [] },
    });
    enqueue("/workspaces/default/runs/run-1/decision", {
      status: 200,
      data: { ok: true, item: report, workspace_id: "default" },
    });

    render(<RunsPage />);
    fireEvent.click(await screen.findByText("分析报文"));
    fireEvent.click(await screen.findByRole("button", { name: "决策" }));
    expect(await screen.findByText("pcap_analysis")).toBeInTheDocument();
  });
});

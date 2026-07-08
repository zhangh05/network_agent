import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { CMDBPage } from "../pages/CMDB/CMDBPage";
import { TaskWorkbench } from "../pages/AgentWorkbench/AgentWorkbench";
import { App } from "../app/App";
import { enqueue, getRequests, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";
import { useWorkbenchStore } from "../stores/workbench";
import type { AgentResult } from "../types";

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

describe("CMDB inspection launch", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({
      currentWorkspaceId: "default",
      currentSessionId: "sess-cmdb",
    });
    useWorkbenchStore.getState().clear();
    useWorkbenchStore.setState({ bySession: {}, sending: false });
  });

  it("launches a region inspection through the workbench auto prompt", async () => {
    enqueue("/cmdb/assets", {
      status: 200,
      data: {
        ok: true,
        assets: [
          {
            asset_id: "asset-1",
            name: "测试服务器_1",
            type: "server",
            vendor: "H3C",
            model: "虚拟机_unbuntu",
            host: "192.168.32.72",
            port: 22,
            protocol: "ssh",
            username: "zhangh01",
            region: "测试一区",
            location: "7A-18U",
            description: "",
            tags: [],
          },
        ],
      },
    });

    render(
      <MemoryRouter initialEntries={["/cmdb"]}>
        <CMDBPage />
        <LocationProbe />
      </MemoryRouter>,
    );

    const launch = await screen.findByTestId("cmdb-inspect-region-general");
    expect(launch).toHaveTextContent("通用巡检");

    fireEvent.click(launch);

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/workbench");
    });

    const stored = localStorage.getItem("workbench_inspection");
    expect(stored).toBeTruthy();
    const payload = JSON.parse(stored || "{}");
    expect(payload.metadata).toMatchObject({
      intent: "cmdb_region_inspection",
      region: "测试一区",
      source: "cmdb_region_button",
    });
    // The launch payload now carries the inspection target + profile (the analysis prompt is
    // assembled later by the workbench on task completion), not a prebuilt prompt string.
    expect(String(payload.metadata.target)).toContain("测试一区");
    expect(payload.metadata.typeLabel).toBe("通用巡检");
  });

  it("does not expose a standalone inspection page in navigation", async () => {
    enqueue("/version", { status: 200, data: { version: "test" } });
    enqueue("/workspaces", {
      status: 200,
      data: { workspaces: [{ workspace_id: "default", name: "default", is_default: true, stats: {} }] },
    });
    enqueue("/runtime/summary", {
      status: 200,
      data: { capabilities: { total: 1, enabled: 1 }, tools: { registered: 1, model_visible: 1 } },
    });
    enqueue("/sessions", { status: 200, data: { sessions: [] } });
    enqueue("/runs/recent", { status: 200, data: { runs: [] } });

    render(<App />);

    await screen.findByText("Operations Console · vtest");
    expect(screen.queryByTestId("nav-inspection")).not.toBeInTheDocument();
    expect(screen.queryByText("设备巡检")).not.toBeInTheDocument();
  });

  it("workbench auto-sends inspection prompt with source metadata", async () => {
    const resp: AgentResult = {
      ok: true,
      final_response: "已完成测试一区基础巡检。",
      events: [],
      trace_id: "trace-inspection",
      session_id: "sess-cmdb",
      turn_id: "turn-inspection",
      tool_calls: [],
      warnings: [],
      errors: [],
      metadata: { source_count: 0 },
    };
    // New inspection flow: launch writes `localStorage.workbench_inspection`
    // (task_id + metadata); the workbench picks it up, polls, and auto-sends analysis.
    localStorage.setItem("workbench_inspection", JSON.stringify({
      task_id: "insp-task-1",
      metadata: {
        intent: "cmdb_region_inspection",
        region: "测试一区",
        source: "cmdb_region_button",
        inspection_task_id: "insp-task-1",
        target: "CMDB 区域「测试一区」",
        type: "general",
        typeLabel: "通用巡检",
        vendor: "",
      },
    }));
    enqueue("/sessions/sess-cmdb/messages", { status: 200, data: { ok: true, messages: [], count: 0 } });
    enqueue("/inspection/tasks", { status: 200, data: { ok: true, task_id: "insp-task-1" } });
    enqueue("/inspection/tasks/insp-task-1", {
      status: 200,
      data: {
        ok: true,
        task: {
          task_id: "insp-task-1",
          status: "succeeded",
          total_assets: 1,
          succeeded: 0,
          failed: 0,
          skipped: 0,
          partial: 0,
          criticals: 0,
          warnings: 0,
          infos: 0,
        },
      },
    });
    enqueue("/agent/message", { status: 200, data: resp });
    enqueue("/sessions/sess-cmdb/messages", { status: 200, data: { ok: true, messages: [], count: 0 } });

    render(<TaskWorkbench />);

    await screen.findByText("已完成测试一区基础巡检。", {}, { timeout: 3000 });
    // New flow: the workbench polls the inspection task (GET) and, on completion, auto-sends an
    // analysis prompt — it no longer POSTs a new inspection task itself.
    const pollRequests = getRequests().filter((r) => (r.url ?? "").includes("/inspection/tasks/insp-task-1"));
    expect(pollRequests.length).toBeGreaterThanOrEqual(1);
    const request = getRequests().find((r) => r.url === "/agent/message");
    expect(request?.data).toMatchObject({
      workspace_id: "default",
      session_id: "sess-cmdb",
      metadata: {
        intent: "cmdb_region_inspection",
        region: "测试一区",
        source: "cmdb_region_button",
        inspection_task_id: "insp-task-1",
      },
    });
    const msg = String(request?.data?.message || "");
    expect(msg).toContain("测试一区");
    expect(msg).toContain("通用巡检已完成");
    expect(msg).toContain("分析维度");
    expect(msg).not.toContain("device.manage");
    expect(localStorage.getItem("workbench_inspection")).toBeNull();
  });
});

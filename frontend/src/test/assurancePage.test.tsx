import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AssurancePage } from "../pages/Assurance/AssurancePage";
import { useSessionStore } from "../stores/session";
import { enqueue, getRequests, installMockApi, resetMocks } from "./mockServer";

function enqueueAssurance() {
  const overview = {
    workspace_id: "default", health: "stable",
    counts: { baselines: 0, drifts: 0, open_incidents: 0, change_plans: 0, enabled_schedules: 0, topology_nodes: 2, topology_edges: 0 },
    latest_drift: null,
  } as const;
  const topology = {
    topology_id: "topo-1", source_task_id: "", created_at: "2026-07-16T00:00:00+00:00", edges: [],
    nodes: [
      { asset_id: "asset-secret-1", name: "核心交换机-01", region: "华东", type: "switch" },
      { asset_id: "asset-secret-2", name: "出口路由器-01", region: "华东", type: "router" },
    ],
  };
  enqueue("/assurance/snapshot", { status: 200, data: { ok: true, snapshot: {
    workspace_id: "default", overview, topology, generated_at: "2026-07-16T00:00:00+00:00",
    baselines: [], checks: [], drifts: [], incidents: [], changes: [], schedules: [], operations: [],
  } } });
}

describe("Network Assurance user flow", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({ currentWorkspaceId: "default" });
    window.localStorage.clear();
    enqueueAssurance();
  });

  it("does not claim stability before a normal state is saved", async () => {
    render(<AssurancePage />);
    expect(await screen.findByText("还没有保存网络的正常状态")).toBeInTheDocument();
    expect(screen.getByText("尚未配置")).toBeInTheDocument();
    expect(screen.queryByText("当前未发现需要处理的保障问题")).not.toBeInTheDocument();
  });

  it("uses device selectors instead of asking for asset ids", async () => {
    render(<AssurancePage />);
    await screen.findByText("还没有保存网络的正常状态");
    fireEvent.click(screen.getByRole("tab", { name: "影响范围" }));
    expect(screen.queryByText("起始资产 ID")).not.toBeInTheDocument();
    const selector = screen.getByRole("combobox", { name: "设备" });
    fireEvent.change(selector, { target: { value: "asset-secret-1" } });
    expect(screen.getByRole("button", { name: "核心交换机-01 ×" })).toBeInTheDocument();
    expect(screen.queryByText("asset-secret-1")).not.toBeInTheDocument();
  });

  it("clears assurance records only after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    enqueue("/assurance/records/clear", { status: 200, data: { ok: true, deleted: 4, deleted_by_kind: {}, preserved: ["artifacts"] } });
    enqueueAssurance();
    render(<AssurancePage />);
    await screen.findByText("还没有保存网络的正常状态");
    fireEvent.click(screen.getByRole("button", { name: "清除记录" }));
    expect(confirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(getRequests().some((request) => request.url === "/assurance/records/clear")).toBe(true));
    confirm.mockRestore();
  });
});

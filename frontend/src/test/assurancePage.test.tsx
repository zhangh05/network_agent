import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    render(<MemoryRouter><AssurancePage /></MemoryRouter>);
    expect(await screen.findByText("还没有确立权威状态基线")).toBeInTheDocument();
    expect(screen.getByText("尚未配置")).toBeInTheDocument();
    expect(screen.queryByText("当前未发现需要处理的保障问题")).not.toBeInTheDocument();
  });

  it("uses device selectors instead of asking for asset ids", async () => {
    enqueue("/assurance/fault-propagation", { status: 202, data: { ok: true, operation: {
      operation_id: "op-propagation", kind: "fault_propagation", ref_id: "", inspection_task_id: "ins-propagation",
      status: "collecting", phase: "collecting_evidence", result: { source_assets: ["asset-secret-1"], depth: 2, source_mode: "hypothetical" },
      total_assets: 1, completed_assets: 0, succeeded_assets: 0, failed_assets: 0, partial_assets: 0,
      created_at: "2026-07-16T00:00:00+00:00", updated_at: "2026-07-16T00:00:00+00:00",
    } } });
    render(<AssurancePage />);
    await screen.findByText("还没有确立权威状态基线");
    fireEvent.click(screen.getByRole("tab", { name: "故障传播分析" }));
    expect(screen.queryByText("起始资产 ID")).not.toBeInTheDocument();
    const selector = screen.getByRole("combobox", { name: "假设故障设备" });
    fireEvent.change(selector, { target: { value: "asset-secret-1" } });
    expect(screen.getByRole("button", { name: "核心交换机-01 ×" })).toBeInTheDocument();
    expect(screen.queryByText("asset-secret-1")).not.toBeInTheDocument();
    expect(screen.getByText(/结果只表示“如果该设备故障/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "分析可能传播到哪里" }));
    await waitFor(() => expect(getRequests().some((request) => request.url === "/assurance/fault-propagation" && request.method === "POST")).toBe(true));
  });

  it("treats state baseline as authority establishment without a comparison workflow", async () => {
    enqueue("/assurance/baselines", { status: 202, data: { ok: true, operation: {
      operation_id: "op-baseline", kind: "baseline_capture", ref_id: "", inspection_task_id: "ins-fresh",
      status: "collecting", phase: "collecting_evidence", result: { baseline_name: "当前网络正常状态" },
      total_assets: 6, completed_assets: 0, succeeded_assets: 0, failed_assets: 0, partial_assets: 0,
      created_at: "2026-07-16T00:00:00+00:00", updated_at: "2026-07-16T00:00:00+00:00",
    } } });
    render(<AssurancePage />);
    await screen.findByText("还没有确立权威状态基线");
    fireEvent.click(screen.getByRole("tab", { name: "状态基线" }));
    expect(screen.getByText("确立权威状态基线")).toBeInTheDocument();
    expect(screen.getByText(/状态基线只负责定调/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新采集并检查" })).not.toBeInTheDocument();
    expect(screen.queryByText("检查历史")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新巡检并确立基线" }));
    await waitFor(() => expect(getRequests().some((request) => request.url === "/assurance/baselines" && request.method === "POST")).toBe(true));
    expect(screen.getByText("正在重新巡检设备 0/6")).toBeInTheDocument();
  });

  it("clears assurance records only after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    enqueue("/assurance/records/clear", { status: 200, data: { ok: true, deleted: 4, deleted_by_kind: {}, preserved: ["artifacts"] } });
    enqueueAssurance();
    render(<AssurancePage />);
    await screen.findByText("还没有确立权威状态基线");
    fireEvent.click(screen.getByRole("button", { name: "清除记录" }));
    expect(confirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(getRequests().some((request) => request.url === "/assurance/records/clear")).toBe(true));
    confirm.mockRestore();
  });

  it("shows baseline comparison, LLM status, citations and next actions for incidents", async () => {
    resetMocks();
    enqueue("/assurance/snapshot", { status: 200, data: { ok: true, snapshot: {
      workspace_id: "default",
      overview: { workspace_id: "default", health: "attention", counts: { baselines: 1, open_incidents: 1 }, latest_drift: null },
      topology: { topology_id: "topo-1", source_task_id: "", created_at: "2026-07-16T00:00:00+00:00", edges: [], nodes: [{ asset_id: "a1", name: "CE1" }] },
      baselines: [{ baseline_id: "base-1", name: "华东正常状态", scope: {}, source_task_id: "ins-base", fact_count: 10, created_at: "2026-07-16T00:00:00+00:00" }],
      checks: [], drifts: [], changes: [], schedules: [], alarms: [], operations: [],
      incidents: [{
        incident_id: "inc-1", title: "出口异常", symptom: "业务中断", status: "monitoring", severity: "critical",
        affected_assets: ["a1"], inspection_task_id: "ins-fault", evidence_refs: ["artifact:art-1"], created_at: "2026-07-16T00:00:00+00:00",
        conclusion: "发现路由消失", hypotheses: [], next_actions: ["检查 a1 对端路由发布"],
        analysis: {
          baseline_id: "base-1", current_snapshot_id: "snap-1",
          changes: [{ key: "route.10.0.0.0", asset_id: "a1", resource_id: "10.0.0.0/24", severity: "critical", rationale: "与状态基线不一致", before: { next_hop: "1.1.1.1" }, after: null, evidence_ref: "artifact:art-1" }],
          llm: { status: "completed", summary: "a1 疑似对端撤销路由", ranked_hypotheses: [{ statement: "a1 对端停止发布目标前缀", confidence: "likely", evidence_refs: ["artifact:art-1"] }] },
        },
      }],
      generated_at: "2026-07-16T00:00:00+00:00",
    } } });

    render(<MemoryRouter><AssurancePage /></MemoryRouter>);
    await screen.findByText("权威状态基线已经确立");
    fireEvent.click(screen.getByRole("tab", { name: "故障排查" }));

    expect(screen.getByText("华东正常状态")).toBeInTheDocument();
    expect(screen.getByText("LLM 已完成证据分析")).toBeInTheDocument();
    expect(screen.getByText("CE1 疑似对端撤销路由")).toBeInTheDocument();
    expect(screen.getByText("CE1 对端停止发布目标前缀")).toBeInTheDocument();
    expect(screen.getByText("依据：证据制品 art-1")).toBeInTheDocument();
    expect(screen.getByText("检查 CE1 对端路由发布")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看本次巡检制品" })).toHaveAttribute("href", "/artifacts?producer_id=ins-fault");
  });
});

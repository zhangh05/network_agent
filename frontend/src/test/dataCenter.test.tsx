import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DataCenter } from "../pages/DataCenter/DataCenter";
import { enqueue, getRequests, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";

const overview = {
  workspace_id: "default",
  files: { total: 1, active: 1, archived: 0, soft_deleted: 0, size_bytes: 2048, referenced: 0, unreferenced: 1 },
  artifacts: { total: 0, active: 0 },
  types: { pcap_input: 1 },
  health: { orphan_files: 0, missing_on_disk: 0, soft_deleted: 0, ok: true },
};

const pcapFile = {
  file_id: "file-pcap-1",
  logical_type: "pcap_input",
  file_kind: "pcap",
  original_name: "capture.pcapng",
  mime_type: "application/vnd.tcpdump.pcap",
  binary: true,
  size_bytes: 2048,
  created_at: "2026-07-22T01:00:00Z",
  source: "artifact_upload",
  sensitivity: "internal",
  lifecycle: "active",
  session_id: "",
  run_id: "",
  metadata: {},
  artifacts: [],
  reference_count: 0,
  reference_types: [],
  references: [],
};

function enqueueBase(files = [pcapFile]) {
  enqueue("/storage/overview", { status: 200, data: { ok: true, overview } });
  enqueue("/storage/files", { status: 200, data: { ok: true, files, count: files.length } });
  enqueue("/workspaces/default/retention/preview", { status: 200, data: { dry_run: true, workspace_id: "default", policy: {}, candidate_counts: {}, candidates: [], blocked_items: [], warnings: [] } });
  enqueue("/workspaces/default/archive/preview", { status: 200, data: { dry_run: true, workspace_id: "default", policy: {}, candidate_counts: {}, candidates: [], blocked_items: [], warnings: [] } });
  enqueue("/workspaces/default/archive/items", { status: 200, data: { ok: true, items: [], count: 0 } });
}

function renderPage(initialEntry = "/data") {
  render(<MemoryRouter initialEntries={[initialEntry]} future={{ v7_relativeSplatPath: true, v7_startTransition: true }}><DataCenter /></MemoryRouter>);
}

describe("DataCenter", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({ currentWorkspaceId: "default" });
  });

  it("shows active FileStore data even when no artifact points to it", async () => {
    enqueueBase();
    enqueue("/workspaces/default/artifacts", { status: 200, data: { artifacts: [], governance: {} } });
    renderPage();

    expect(await screen.findByText("数据关系正常")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部数据" }));
    const row = await screen.findByText("capture.pcapng");
    expect(row).toBeInTheDocument();
    expect(screen.getByText("独立文件")).toBeInTheDocument();
    fireEvent.click(row);
    expect(await screen.findByRole("button", { name: "打开报文分析" })).toBeInTheDocument();
  });

  it("keeps baseline authority and contextual evidence visibly distinct", async () => {
    enqueueBase([]);
    enqueue("/workspaces/default/artifacts", {
      status: 200,
      data: {
        governance: { current_state_authoritative: 1, contextual: 1 },
        artifacts: [
          {
            artifact_id: "baseline-1", workspace_id: "default", artifact_type: "inspection_raw", title: "状态基线巡检输出",
            created_at: "2026-07-22T01:00:00Z", updated_at: "2026-07-22T01:00:00Z", size_bytes: 100, mime_type: "text/plain",
            file_ext: ".txt", file_id: "f-1", relative_path: "", lifecycle: "active", scope: "workspace", source: "inspection_runner",
            sensitivity: "internal", tags: [], summary: "", run_id: "ins-base", redaction_applied: false, metadata: {},
            governance: { authority_domain: "current_state", authority_status: "authoritative", authority_reason: "状态基线是当前状态权威", version: 1, version_count: 1 },
          },
          {
            artifact_id: "impact-1", workspace_id: "default", artifact_type: "inspection_raw", title: "故障传播采集",
            created_at: "2026-07-22T02:00:00Z", updated_at: "2026-07-22T02:00:00Z", size_bytes: 100, mime_type: "text/plain",
            file_ext: ".txt", file_id: "f-2", relative_path: "", lifecycle: "active", scope: "workspace", source: "inspection_runner",
            sensitivity: "internal", tags: [], summary: "", run_id: "ins-impact", redaction_applied: false, metadata: {},
            governance: { authority_domain: "contextual", authority_status: "contextual", authority_reason: "专项任务证据不改写状态基线", version: 1, version_count: 1 },
          },
        ],
      },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "证据与制品" }));
    expect(await screen.findByText("当前权威")).toBeInTheDocument();
    expect(screen.getByText("专项证据", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByText("状态权威 1")).toBeInTheDocument();
  });

  it("passes the task producer id from assurance links to the artifact query", async () => {
    enqueueBase([]);
    enqueue("/workspaces/default/artifacts", { status: 200, data: { artifacts: [], governance: {} } });
    renderPage("/data?producer_id=inspection-42");
    await screen.findByText(/任务 inspection/);
    await waitFor(() => {
      const request = getRequests().find((item) => item.url === "/workspaces/default/artifacts");
      expect(request?.params).toMatchObject({ producer_id: "inspection-42" });
    });
  });
});

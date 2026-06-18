import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FileManager } from "../pages/FileManager/FileManager";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";

function renderFileManager() {
  render(
    <MemoryRouter>
      <FileManager />
    </MemoryRouter>,
  );
}

describe("FileManager pcap analysis entry", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({ currentWorkspaceId: "default" });
  });

  it("only exposes packet analysis actions for raw pcap files with a session id", async () => {
    enqueue("/files", {
      status: 200,
      data: {
        ok: true,
        files: [
          {
            file_id: "f-analysis",
            type: "pcap",
            title: "10.0.0.1:12345 ↔ 10.0.0.2:443",
            filename: "content.json",
            mime_type: "text/json",
            size: 1024,
            tags: ["tcp", "analysis"],
            workspace_id: "default",
            source: "agent",
            indexed: false,
            parent_id: null,
            metadata: {},
            created_at: "2026-06-18T01:00:00Z",
            updated_at: "2026-06-18T01:00:00Z",
          },
          {
            file_id: "f-pcap",
            type: "pcap",
            title: "capture.pcapng",
            filename: "capture.pcapng",
            mime_type: "application/vnd.tcpdump.pcap",
            size: 2048,
            tags: [],
            workspace_id: "default",
            source: "upload",
            indexed: false,
            parent_id: null,
            metadata: { session_id: "sid-1", total_packets: 12, connection_count: 3 },
            created_at: "2026-06-18T02:00:00Z",
            updated_at: "2026-06-18T02:00:00Z",
          },
        ],
      },
    });

    renderFileManager();

    const analysisTitle = await screen.findByText("10.0.0.1:12345 ↔ 10.0.0.2:443");
    const analysisItem = analysisTitle.closest(".card");
    expect(analysisItem).not.toBeNull();
    fireEvent.click(analysisItem!);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "分析" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "打开报文分析 →" })).not.toBeInTheDocument();
    });

    const rawPcapItem = screen.getByText("capture.pcapng").closest(".card");
    expect(rawPcapItem).not.toBeNull();
    fireEvent.click(rawPcapItem!);
    expect(screen.getByRole("button", { name: "分析" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开报文分析 →" })).toBeInTheDocument();
  });
});

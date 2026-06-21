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
    enqueue("/workspaces/default/artifacts", {
      status: 200,
      data: {
        ok: true,
        artifacts: [
          {
            artifact_id: "a-analysis",
            file_id: "f-analysis",
            artifact_type: "pcap_analysis",
            title: "10.0.0.1:12345 ↔ 10.0.0.2:443",
            file_ext: ".json",
            size_bytes: 1024,
            metadata: {},
            created_at: "2026-06-18T01:00:00Z",
            updated_at: "2026-06-18T01:00:00Z",
          },
          {
            artifact_id: "a-pcap",
            file_id: "f-pcap",
            artifact_type: "pcap_input",
            title: "capture.pcapng",
            file_ext: ".pcapng",
            size_bytes: 2048,
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
      expect(screen.queryByRole("button", { name: "打开分析" })).not.toBeInTheDocument();
    });

    const rawPcapItem = screen.getByText("capture.pcapng").closest(".card");
    expect(rawPcapItem).not.toBeNull();
    fireEvent.click(rawPcapItem!);
    expect(screen.getByRole("button", { name: "打开分析" })).toBeInTheDocument();
  });
});

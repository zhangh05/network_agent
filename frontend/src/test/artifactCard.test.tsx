/**
 * Test 3 — artifact 卡片
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ArtifactCenter } from "../pages/ArtifactCenter/ArtifactCenter";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import { useSessionStore } from "../stores/session";
import type { Artifact } from "../types";

const sampleArtifact: Artifact = {
  artifact_id: "art-1",
  workspace_id: "ws-1",
  artifact_type: "translated_config",
  title: "OSPF 翻译结果",
  created_at: "2026-06-11T10:00:00Z",
  updated_at: "2026-06-11T10:01:00Z",
  size_bytes: 4096,
  authoritative: true,
  deployable_config: false,
  sensitivity: "sensitive",
  metadata: { source_artifact: "art-0" },
  content_preview: "router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n",
};

describe("ArtifactCenter — artifact card", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({ currentWorkspaceId: "ws-1" });
  });

  it("renders list item and detail with authoritative + sensitive badges", async () => {
    enqueue("/workspaces/ws-1/artifacts", { status: 200, data: { artifacts: [sampleArtifact] } });
    render(<ArtifactCenter />);
    const item = await screen.findByTestId("artifact-art-1");
    fireEvent.click(item);
    expect(item.textContent).toContain("translated_config");
    expect(item.textContent).toContain("auth");
    // Detail panel renders the sensitivity badge.
    const detail = await screen.findByTestId("artifact-detail");
    expect(detail.textContent).toContain("sensitive");
    expect(detail.textContent).toContain("authoritative");
  });
});

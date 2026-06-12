/**
 * Test 3 — artifact 卡片
 *
 * v1.0.1 UI 重设计后: Artifact wire shape 已对齐到真实后端 (见
 * registry/loader.py / artifact pipeline)。mock data 反映真实字段。
 * 预览 tab 会懒拉取 /content 端点, 这里也 mock 一下。
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
  mime_type: "text/plain",
  file_ext: ".txt",
  sha256_short: "abc12345",
  relative_path: "translated/ospf1.txt",
  lifecycle: "active",
  scope: "workspace",
  source: "module_output",
  sensitivity: "sensitive",
  tags: ["ospf"],
  summary: "OSPF 翻译产物",
  capability_id: "config_translation",
  module: "config_translation",
  skill: "config_translation",
  run_id: "run-1",
  redaction_applied: false,
  metadata: { source_artifact: "art-0" },
};

const sampleContent = {
  ok: true,
  content: "router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n",
  title: "OSPF 翻译结果",
};

describe("ArtifactCenter — artifact card", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useSessionStore.setState({ currentWorkspaceId: "ws-1" });
  });

  it("renders list item and detail with authoritative + sensitive badges", async () => {
    enqueue("/workspaces/ws-1/artifacts", { status: 200, data: { artifacts: [sampleArtifact] } });
    enqueue("/workspaces/ws-1/artifacts/art-1", { status: 200, data: { artifact: sampleArtifact } });
    enqueue("/workspaces/ws-1/artifacts/art-1/content", { status: 200, data: sampleContent });
    enqueue("/workspaces/ws-1/artifacts/art-1/summarize", {
      status: 200,
      data: {
        ok: true,
        summary: {
          artifact_id: "art-1",
          artifact_type: "translated_config",
          title: "OSPF 翻译结果",
          summary: "OSPF 翻译产物",
          sensitivity: "sensitive",
          sha256_short: "abc12345",
          size_bytes: 4096,
        },
      },
    });
    render(<ArtifactCenter />);
    const item = await screen.findByTestId("artifact-art-1");
    fireEvent.click(item);
    expect(item.textContent).toContain("translated_config");
    // 权威 = 由某个 capability / module / skill 产出 (在 mock 中设了 capability_id)
    expect(item.textContent).toContain("权威");
    // Detail panel renders the sensitivity badge.
    const detail = await screen.findByTestId("artifact-detail");
    expect(detail.textContent).toContain("敏感");
    expect(detail.textContent).toContain("权威");
    // Preview tab lazy-fetches /content and renders the actual content.
    expect(detail.textContent).toContain("router ospf 1");
  });

  it("distinguishes duplicate artifact titles with id and created time", async () => {
    const duplicateA = { ...sampleArtifact, artifact_id: "art-a", title: "Translation output", created_at: "2026-06-11T10:00:00Z" };
    const duplicateB = { ...sampleArtifact, artifact_id: "art-b", title: "Translation output", created_at: "2026-06-11T11:00:00Z" };
    enqueue("/workspaces/ws-1/artifacts", {
      status: 200,
      data: { artifacts: [duplicateA, duplicateB] },
    });

    render(<ArtifactCenter />);

    expect(await screen.findByTestId("artifact-art-a")).toHaveTextContent("art-a");
    expect(screen.getByTestId("artifact-art-b")).toHaveTextContent("art-b");
    expect(screen.getByTestId("artifact-art-a")).toHaveTextContent("2026");
  });
});

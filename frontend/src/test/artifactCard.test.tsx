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
  file_id: "file-1",
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

  it("renders deliverables without falsely labelling them authoritative", async () => {
    enqueue("/workspaces/ws-1/artifacts", { status: 200, data: { artifacts: [sampleArtifact], governance: { policy: "latest_complete_then_latest_partial", evidence_streams: 0, authoritative: 0, provisional: 0, incomplete: 0, historical: 0, deliverables: 1 } } });
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
    expect(item.textContent).toContain("翻译配置");
    expect(item.textContent).not.toContain("translated_config");
    expect(item.textContent).toContain("交付物");
    // Detail panel renders the sensitivity badge.
    const detail = await screen.findByTestId("artifact-detail");
    expect(detail.textContent).toContain("敏感");
    expect(detail.textContent).toContain("业务交付物");
    expect(detail.textContent).toContain("证据地位");
    // Preview tab lazy-fetches /content and renders the actual content.
    expect(detail.textContent).toContain("router ospf 1");
  });

  it("shows inspection lineage and authoritative evidence status", async () => {
    const evidence: Artifact = {
      ...sampleArtifact,
      artifact_id: "raw-1",
      artifact_type: "inspection_raw",
      title: "核心交换机巡检输出",
      metadata: { asset_name: "core-1", producer_id: "ins-1", producer_trigger: "assurance:impact:op-1" },
      governance: { authority_status: "authoritative", authority_reason: "最近一次完整成功采集", version: 2, version_count: 2 },
    };
    enqueue("/workspaces/ws-1/artifacts", { status: 200, data: { artifacts: [evidence] } });
    enqueue("/workspaces/ws-1/artifacts/raw-1/content", { status: 200, data: sampleContent });
    render(<ArtifactCenter />);
    const item = await screen.findByTestId("artifact-raw-1");
    expect(item).toHaveTextContent("当前权威");
    fireEvent.click(item);
    const detail = await screen.findByTestId("artifact-detail");
    expect(detail).toHaveTextContent("core-1");
    expect(detail).toHaveTextContent("ins-1");
    expect(detail).toHaveTextContent("影响范围分析");
    expect(detail).toHaveTextContent("第 2 / 2 版");
  });

  it("keeps duplicate artifact titles readable while hiding ids by default", async () => {
    const duplicateA = { ...sampleArtifact, artifact_id: "art-a", title: "Translation output", created_at: "2026-06-11T10:00:00Z" };
    const duplicateB = { ...sampleArtifact, artifact_id: "art-b", title: "Translation output", created_at: "2026-06-11T11:00:00Z" };
    enqueue("/workspaces/ws-1/artifacts", {
      status: 200,
      data: { artifacts: [duplicateA, duplicateB] },
    });

    render(<ArtifactCenter />);

    expect(await screen.findByTestId("artifact-art-a")).toHaveTextContent("翻译配置");
    expect(screen.getByTestId("artifact-art-a")).not.toHaveTextContent("art-a");
    expect(screen.getByTestId("artifact-art-b")).not.toHaveTextContent("art-b");
    expect(screen.getByTestId("artifact-art-a")).toHaveTextContent("2026");
  });
});

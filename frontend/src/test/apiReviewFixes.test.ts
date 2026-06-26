import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { apiClient } from "../api/client";
import { toolsInvokeApi, openApprovalStream, sseApi } from "../api";

describe("API review fixes", () => {
  beforeEach(() => {
    vi.spyOn(apiClient, "request").mockResolvedValue({ data: { ok: true } } as any);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends tool arguments and workspace as backend expects", async () => {
    await toolsInvokeApi.invoke({
      tool_id: "exec.run",
      params: { command: "pwd" },
      workspace_id: "default",
    });

    expect(apiClient.request).toHaveBeenCalledWith(expect.objectContaining({
      method: "POST",
      url: "/tools/invoke",
      params: { workspace_id: "default" },
      data: { tool_id: "exec.run", arguments: { command: "pwd" } },
    }));
  });

  it("builds EventSource URLs from the configured API base", () => {
    const sources: string[] = [];
    class FakeEventSource {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor(url: string) {
        sources.push(url);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeEventSource as any);

    openApprovalStream(() => {});
    sseApi.connect("sid123");

    expect(sources).toEqual([
      "/api/agent/approvals/sse",
      "/api/agent/sse/stream/sid123",
    ]);
  });

  it("adds the configured API token to EventSource URLs", () => {
    localStorage.setItem("NA_API_TOKEN", "secret token");
    const sources: string[] = [];
    class FakeEventSource {
      constructor(url: string) {
        sources.push(url);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeEventSource as any);

    openApprovalStream(() => {});
    sseApi.connect("sid123");

    expect(sources).toEqual([
      "/api/agent/approvals/sse?access_token=secret+token",
      "/api/agent/sse/stream/sid123?access_token=secret+token",
    ]);
  });

  it("sends explicit confirm flags for retention and archive apply", async () => {
    const { retentionApi, archiveApi } = await import("../api");

    await retentionApi.apply("default");
    await archiveApi.apply("default");

    expect(apiClient.request).toHaveBeenCalledWith(expect.objectContaining({
      method: "POST",
      url: "/workspaces/default/retention/apply",
      data: { dry_run: false, confirm: true },
    }));
    expect(apiClient.request).toHaveBeenCalledWith(expect.objectContaining({
      method: "POST",
      url: "/workspaces/default/archive/apply",
      data: { dry_run: false, confirm: true },
    }));
  });
});

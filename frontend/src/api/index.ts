/**
 * API layer — 10 modules. Each module is a thin function layer; the page
 * components only call these functions and never call axios directly.
 * No business logic, no caching, no transformation. If a field is missing
 * from the backend response, the function returns `null`/empty list and
 * the page renders the empty / error state.
 *
 * All endpoints are aligned to the real backend contracts. v1.0.1 fix
 * pass: corrected /agent/message, /knowledge/sources/from-artifact,
 * /knowledge/search, /knowledge/chunks, /review-items, etc.
 */

import { apiRequest } from "./client";
import type {
  AgentResult,
  Artifact,
  CapabilityManifest,
  KnowledgeChunk,
  KnowledgeSearchResult,
  KnowledgeSource,
  ReviewItem,
  RuntimeAuditTurn,
  Session,
  Workspace,
} from "../types";

/* ──────────────────────── 1. agent ──────────────────────── */

export interface AgentRunRequest {
  message: string;
  workspace_id: string;
  session_id?: string | null;
  metadata?: Record<string, unknown>;
}

export const agentApi = {
  /** POST /api/agent/message — Codex-style runtime endpoint (v0.6+). */
  run: (req: AgentRunRequest, signal?: AbortSignal): Promise<AgentResult> =>
    apiRequest<AgentResult>(
      { method: "POST", url: "/agent/message", data: req },
      signal,
    ),
};

/* ──────────────────────── 2. sessions ──────────────────────── */

export const sessionsApi = {
  list: (
    workspace_id: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<{ sessions: Session[]; counts?: Record<string, number> }> =>
    apiRequest<{ sessions: Session[]; counts?: Record<string, number> }>(
      {
        method: "GET",
        url: "/sessions",
        params: { workspace_id, status: status || "active", limit: 200 },
      },
      signal,
    ),
  get: (
    session_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ session: Session; messages?: unknown[] }> =>
    apiRequest<{ session: Session; messages?: unknown[] }>(
      {
        method: "GET",
        url: `/sessions/${session_id}`,
        params: { workspace_id, include_messages: 1 },
      },
      signal,
    ),
  create: (
    workspace_id: string,
    title?: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; session: Session }> =>
    apiRequest<{ ok: boolean; session: Session }>(
      {
        method: "POST",
        url: "/sessions",
        data: { workspace_id, title: title || "" },
      },
      signal,
    ),
  archive: (
    session_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; session: Session }> =>
    apiRequest<{ ok: boolean; session: Session }>(
      {
        method: "POST",
        url: `/sessions/${session_id}/archive`,
        params: { workspace_id },
      },
      signal,
    ),
  rename: (
    session_id: string,
    workspace_id: string,
    title: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; session: Session }> =>
    apiRequest<{ ok: boolean; session: Session }>(
      {
        method: "PUT",
        url: `/sessions/${session_id}`,
        params: { workspace_id },
        data: { title },
      },
      signal,
    ),
  softDelete: (
    session_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; session: Session }> =>
    apiRequest<{ ok: boolean; session: Session }>(
      {
        method: "POST",
        url: `/sessions/${session_id}/soft-delete`,
        params: { workspace_id },
      },
      signal,
    ),
  delete: (
    session_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; message?: string }> =>
    apiRequest<{ ok: boolean; message?: string }>(
      {
        method: "DELETE",
        url: `/sessions/${session_id}`,
        params: { workspace_id, confirm: "true" },
      },
      signal,
    ),
};

/* ──────────────────────── 3. workspaces ──────────────────────── */

export const workspacesApi = {
  list: (signal?: AbortSignal): Promise<{ workspaces: Workspace[] }> =>
    apiRequest<{ workspaces: Workspace[] }>(
      { method: "GET", url: "/workspaces" },
      signal,
    ),
  get: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ workspace: Workspace }> =>
    apiRequest<{ workspace: Workspace }>(
      { method: "GET", url: `/workspaces/${workspace_id}/state` },
      signal,
    ),
  rename: (
    workspace_id: string,
    name: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; workspace: Workspace }> =>
    apiRequest<{ ok: boolean; workspace: Workspace }>(
      {
        method: "POST",
        url: `/workspaces/${workspace_id}/rename`,
        data: { name },
      },
      signal,
    ),
  delete: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean }> =>
    apiRequest<{ ok: boolean }>(
      { method: "DELETE", url: `/workspaces/${workspace_id}` },
      signal,
    ),
  recentRuns: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ runs: RuntimeAuditTurn[] }> =>
    apiRequest<{ runs: RuntimeAuditTurn[] }>(
      { method: "GET", url: "/runs/recent", params: { workspace_id } },
      signal,
    ),
};

/* ──────────────────────── 4. capabilities ──────────────────────── */

export const capabilitiesApi = {
  /** GET /api/capabilities — CapabilityRegistry projection. */
  manifest: (
    signal?: AbortSignal,
  ): Promise<{ capabilities: CapabilityManifest[]; enabled: string[] }> =>
    apiRequest<{ capabilities: CapabilityManifest[]; enabled: string[] }>(
      { method: "GET", url: "/capabilities" },
      signal,
    ),
  /** GET /api/tools/catalog — full tool catalog. */
  toolCatalog: (signal?: AbortSignal): Promise<{ tools: unknown[] }> =>
    apiRequest<{ tools: unknown[] }>({ method: "GET", url: "/tools/catalog" }, signal),
};

/* ──────────────────────── 5. tools ──────────────────────── */

export const toolsApi = {
  catalog: (signal?: AbortSignal): Promise<{ tools: unknown[] }> =>
    apiRequest<{ tools: unknown[] }>({ method: "GET", url: "/tools/catalog" }, signal),
};

/* ──────────────────────── 6. knowledge ──────────────────────── */

export const knowledgeApi = {
  listSources: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ sources: KnowledgeSource[]; counts?: Record<string, number> }> =>
    apiRequest<{ sources: KnowledgeSource[]; counts?: Record<string, number> }>(
      { method: "GET", url: "/knowledge/sources", params: { workspace_id } },
      signal,
    ),
  /**
   * POST /api/knowledge/sources/from-artifact
   * Body: { workspace_id, artifact_id } — JSON (NOT multipart).
   */
  importFromArtifact: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; source: KnowledgeSource }> =>
    apiRequest<{ ok: boolean; source: KnowledgeSource }>(
      {
        method: "POST",
        url: "/knowledge/sources/from-artifact",
        data: { workspace_id, artifact_id },
      },
      signal,
    ),
  reindex: (
    source_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; source?: KnowledgeSource }> =>
    apiRequest<{ ok: boolean; source?: KnowledgeSource }>(
      {
        method: "POST",
        url: `/knowledge/sources/${source_id}/reindex`,
        params: { workspace_id },
      },
      signal,
    ),
  search: (
    q: string,
    workspace_id: string,
    opts?: { limit?: number; source_id?: string; artifact_id?: string },
    signal?: AbortSignal,
  ): Promise<KnowledgeSearchResult> =>
    apiRequest<KnowledgeSearchResult>(
      {
        method: "GET",
        url: "/knowledge/search",
        params: {
          q,
          workspace_id,
          limit: opts?.limit ?? 20,
          source_id: opts?.source_id,
          artifact_id: opts?.artifact_id,
        },
      },
      signal,
    ),
  getChunk: (
    chunk_id: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ chunk: KnowledgeChunk }> =>
    apiRequest<{ chunk: KnowledgeChunk }>(
      {
        method: "GET",
        url: `/knowledge/chunks/${chunk_id}`,
        params: { workspace_id },
      },
      signal,
    ),
};

/* ──────────────────────── 7. artifacts ──────────────────────── */

export const artifactsApi = {
  list: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ artifacts: Artifact[] }> =>
    apiRequest<{ artifacts: Artifact[] }>(
      { method: "GET", url: `/workspaces/${workspace_id}/artifacts` },
      signal,
    ),
  get: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{ artifact: Artifact }> =>
    apiRequest<{ artifact: Artifact }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/artifacts/${artifact_id}`,
      },
      signal,
    ),
  /** GET /api/workspaces/<ws>/artifacts/<art>/content — full content (text). */
  content: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{ content: string; metadata?: Record<string, unknown> }> =>
    apiRequest<{ content: string; metadata?: Record<string, unknown> }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/artifacts/${artifact_id}/content`,
      },
      signal,
    ),
  /**
   * Export — content + sensitivity flags. The backend may also provide
   * a /promote endpoint for deployable promotion; we don't expose that
   * from the frontend (config.push is forbidden per the platform rules).
   */
  export: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{ content: string; metadata?: Record<string, unknown> }> =>
    apiRequest<{ content: string; metadata?: Record<string, unknown> }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/artifacts/${artifact_id}/content`,
      },
      signal,
    ),
  /**
   * GET /api/workspaces/<ws>/artifacts/<art>/summarize — backend summary.
   * Returns the artifact metadata plus a `summary` field if the
   * backend has computed one. Surface this in the "摘要" tab.
   */
  summarize: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{
    ok: boolean;
    summary: {
      artifact_id: string;
      artifact_type: string;
      title: string;
      summary: string;
      sensitivity?: string;
      sha256_short?: string;
      size_bytes?: number;
      created_at?: string;
    };
  }> =>
    apiRequest<{
      ok: boolean;
      summary: {
        artifact_id: string;
        artifact_type: string;
        title: string;
        summary: string;
        sensitivity?: string;
        sha256_short?: string;
        size_bytes?: number;
        created_at?: string;
      };
    }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/artifacts/${artifact_id}/summarize`,
      },
      signal,
    ),
};

/* ──────────────────────── 8. reviews ──────────────────────── */

export const reviewsApi = {
  /**
   * GET /api/workspaces/<ws_id>/review-items — workspace-level aggregated list.
   * Optional ?status=pending|accepted|ignored|modified filter.
   */
  list: (
    workspace_id: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<{ items: ReviewItem[]; count: number; workspace_id: string }> =>
    apiRequest<{ items: ReviewItem[]; count: number; workspace_id: string }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/review-items`,
        params: status ? { status } : undefined,
      },
      signal,
    ),
  /**
   * PUT /api/review-items/<item_id>?workspace_id=&artifact_id=
   * Body: { status, user_note }
   */
  update: (
    item_id: string,
    update: { status: string; user_note?: string; workspace_id: string; artifact_id: string },
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; item?: ReviewItem; summary?: string }> =>
    apiRequest<{ ok: boolean; item?: ReviewItem; summary?: string }>(
      {
        method: "PUT",
        url: `/review-items/${item_id}`,
        params: { workspace_id: update.workspace_id, artifact_id: update.artifact_id },
        data: { status: update.status, user_note: update.user_note ?? "" },
      },
      signal,
    ),
};

/* ──────────────────────── 9. runtime_audit ──────────────────────── */

export const runtimeAuditApi = {
  recent: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ runs: RuntimeAuditTurn[] }> =>
    apiRequest<{ runs: RuntimeAuditTurn[] }>(
      { method: "GET", url: "/runs/recent", params: { workspace_id } },
      signal,
    ),
  run: (
    run_id: string,
    signal?: AbortSignal,
  ): Promise<{ run: RuntimeAuditTurn }> =>
    apiRequest<{ run: RuntimeAuditTurn }>(
      { method: "GET", url: `/runs/${run_id}` },
      signal,
    ),
  trace: (
    workspace_id: string,
    run_id: string,
    signal?: AbortSignal,
  ): Promise<{ events: RuntimeAuditTurn["events"] }> =>
    apiRequest<{ events: RuntimeAuditTurn["events"] }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/runs/${run_id}/trace`,
      },
      signal,
    ),
};

/* ──────────────────────── 10. settings ──────────────────────── */

export const settingsApi = {
  llmConfig: (signal?: AbortSignal): Promise<{ provider?: string; model?: string; base_url?: string; [k: string]: unknown }> =>
    apiRequest<{ provider?: string; model?: string; base_url?: string; [k: string]: unknown }>(
      { method: "GET", url: "/agent/llm/config" },
      signal,
    ),
  updateLlmConfig: (
    update: { provider?: string; model?: string; base_url?: string; [k: string]: unknown },
    signal?: AbortSignal,
  ): Promise<{ ok: boolean }> =>
    apiRequest<{ ok: boolean }>(
      { method: "POST", url: "/agent/llm/config", data: update },
      signal,
    ),
};

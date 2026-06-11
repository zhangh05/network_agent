/**
 * API layer — 9 modules. Each module is a thin function layer; the page
 * components only call these functions and never call axios directly.
 * No business logic, no caching, no transformation. If a field is missing
 * from the backend response, the function returns `null`/empty list and
 * the page renders the empty / error state.
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
  stream?: boolean;
}

export const agentApi = {
  run: (req: AgentRunRequest, signal?: AbortSignal): Promise<AgentResult> =>
    apiRequest<AgentResult>({ method: "POST", url: "/agent/message", data: req }, signal),
};

/* ──────────────────────── 2. sessions ──────────────────────── */

export const sessionsApi = {
  list: (workspace_id: string, signal?: AbortSignal): Promise<{ sessions: Session[] }> =>
    apiRequest<{ sessions: Session[] }>(
      { method: "GET", url: "/sessions", params: { workspace_id, status: "active" } },
      signal,
    ),
  get: (session_id: string, signal?: AbortSignal): Promise<{ session: Session; messages: unknown[] }> =>
    apiRequest<{ session: Session; messages: unknown[] }>(
      { method: "GET", url: `/sessions/${session_id}`, params: { include_messages: 1 } },
      signal,
    ),
  create: (workspace_id: string, signal?: AbortSignal): Promise<Session> =>
    apiRequest<Session>({ method: "POST", url: "/sessions", data: { workspace_id } }, signal),
  archive: (session_id: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    apiRequest<{ ok: boolean }>(
      { method: "POST", url: `/sessions/${session_id}/archive` },
      signal,
    ),
};

/* ──────────────────────── 3. workspaces ──────────────────────── */

export const workspacesApi = {
  list: (signal?: AbortSignal): Promise<{ workspaces: Workspace[] }> =>
    apiRequest<{ workspaces: Workspace[] }>({ method: "GET", url: "/workspaces" }, signal),
  get: (workspace_id: string, signal?: AbortSignal): Promise<{ workspace: Workspace }> =>
    apiRequest<{ workspace: Workspace }>(
      { method: "GET", url: `/workspaces/${workspace_id}/state` },
      signal,
    ),
  create: (name: string, signal?: AbortSignal): Promise<Workspace> =>
    apiRequest<Workspace>({ method: "POST", url: "/workspaces", data: { name } }, signal),
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
  manifest: (signal?: AbortSignal): Promise<{ capabilities: CapabilityManifest[] }> =>
    apiRequest<{ capabilities: CapabilityManifest[] }>(
      { method: "GET", url: "/capabilities" },
      signal,
    ),
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
  ): Promise<{ sources: KnowledgeSource[] }> =>
    apiRequest<{ sources: KnowledgeSource[] }>(
      { method: "GET", url: "/knowledge/sources", params: { workspace_id } },
      signal,
    ),
  importFile: (form: FormData, signal?: AbortSignal): Promise<{ source: KnowledgeSource }> =>
    apiRequest<{ source: KnowledgeSource }>(
      {
        method: "POST",
        url: "/knowledge/sources/from-artifact",
        data: form,
        headers: { "Content-Type": "multipart/form-data" },
      },
      signal,
    ),
  reindex: (source_id: string, signal?: AbortSignal): Promise<{ ok: boolean }> =>
    apiRequest<{ ok: boolean }>(
      { method: "POST", url: `/knowledge/sources/${source_id}/reindex` },
      signal,
    ),
  search: (
    q: string,
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeSearchResult> =>
    apiRequest<KnowledgeSearchResult>(
      { method: "GET", url: "/knowledge/search", params: { q, workspace_id } },
      signal,
    ),
  getChunk: (chunk_id: string, signal?: AbortSignal): Promise<{ chunk: KnowledgeChunk }> =>
    apiRequest<{ chunk: KnowledgeChunk }>(
      { method: "GET", url: `/knowledge/chunks/${chunk_id}` },
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
      { method: "GET", url: `/workspaces/${workspace_id}/artifacts/${artifact_id}` },
      signal,
    ),
  export: (
    workspace_id: string,
    artifact_id: string,
    signal?: AbortSignal,
  ): Promise<{ url: string }> =>
    apiRequest<{ url: string }>(
      { method: "GET", url: `/workspaces/${workspace_id}/artifacts/${artifact_id}/content` },
      signal,
    ),
};

/* ──────────────────────── 8. reviews ──────────────────────── */

export const reviewsApi = {
  list: (
    workspace_id: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<{ items: ReviewItem[] }> =>
    apiRequest<{ items: ReviewItem[] }>(
      {
        method: "GET",
        url: `/workspaces/${workspace_id}/review-items`,
        params: status ? { status } : undefined,
      },
      signal,
    ),
  update: (
    item_id: string,
    update: { status?: string; user_note?: string },
    signal?: AbortSignal,
  ): Promise<{ item: ReviewItem }> =>
    apiRequest<{ item: ReviewItem }>(
      { method: "PUT", url: `/review-items/${item_id}`, data: update },
      signal,
    ),
};

/* ──────────────────────── 9. runtime_audit ──────────────────────── */

export const runtimeAuditApi = {
  turn: (
    workspace_id: string,
    turn_id: string,
    signal?: AbortSignal,
  ): Promise<{ turn: RuntimeAuditTurn }> =>
    apiRequest<{ turn: RuntimeAuditTurn }>(
      { method: "GET", url: `/workspaces/${workspace_id}/turns/${turn_id}` },
      signal,
    ),
  trace: (
    workspace_id: string,
    run_id: string,
    signal?: AbortSignal,
  ): Promise<{ events: RuntimeAuditTurn["events"] }> =>
    apiRequest<{ events: RuntimeAuditTurn["events"] }>(
      { method: "GET", url: `/workspaces/${workspace_id}/runs/${run_id}/trace` },
      signal,
    ),
  recent: (
    workspace_id: string,
    signal?: AbortSignal,
  ): Promise<{ turns: RuntimeAuditTurn[] }> =>
    apiRequest<{ turns: RuntimeAuditTurn[] }>(
      { method: "GET", url: "/runs/recent", params: { workspace_id } },
      signal,
    ),
};

/* ──────────────────────── 10. settings ──────────────────────── */

export const settingsApi = {
  llmConfig: (signal?: AbortSignal): Promise<{ provider: string; model: string; base_url: string }> =>
    apiRequest<{ provider: string; model: string; base_url: string }>(
      { method: "GET", url: "/agent/llm/config" },
      signal,
    ),
  updateLlmConfig: (
    update: { provider?: string; model?: string; base_url?: string },
    signal?: AbortSignal,
  ): Promise<{ ok: boolean }> =>
    apiRequest<{ ok: boolean }>(
      { method: "POST", url: "/agent/llm/config", data: update },
      signal,
    ),
};

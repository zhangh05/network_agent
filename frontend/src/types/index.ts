/**
 * Domain types — strict 1:1 mapping from backend Python dataclasses `as_dict()`.
 * No fields are guessed. The frontend only renders what the backend actually
 * returns. See `agent/capabilities/schemas.py` and `agent/runtime/result.py`.
 */

export type CapabilityStatus = "enabled" | "planned" | "disabled";
export type ToolStatus = "enabled" | "planned" | "disabled";
export type RiskLevel = "low" | "medium" | "high" | "forbidden";
export type Sensitivity = "public" | "internal" | "sensitive" | "secret";

/* ───────────────────────── CapabilityManifest ─────────────────────────
 *
 * Wire shape produced by `registry/loader.py::_generate_capabilities`
 * (and projected to JSON via `CapabilitySpec.as_dict`). The v1.0.1
 * frontend used the nested `agent/capabilities/schemas.py::CapabilityManifest`
 * shape; that does NOT match what `/api/capabilities` actually returns.
 * This interface reflects the REAL response.
 */

export interface CapabilityManifest {
  /** Unique capability id, e.g. `config.translate`. */
  capability_id: string;
  /** Whether the capability is callable by the LLM. */
  enabled: boolean;
  /** Lifecycle status: "enabled" | "planned" | "disabled". */
  status: CapabilityStatus;
  /** Human-readable description (may be empty). */
  description: string;
  /** Category bucket, e.g. "translation" | "knowledge" | "review". */
  category: string;
  /** Stable intent key, e.g. `translate_config`. */
  intent: string;
  /** Module id (string), e.g. `config_translation`. */
  module: string;
  /** Skill id (string), e.g. `config_translation`. */
  skill: string;
  /** Risk level for downstream reasoning / UI. */
  risk_level: RiskLevel;
  /** True if outputs of this capability can be deployed. */
  can_generate_deployable: boolean;
  /** True if a human reviewer is required before deployment. */
  requires_verification: boolean;
  /** True iff status === "enabled" (mirror of `status` for callers). */
  requires_human_review: boolean;
}

/* ──────────────────────── AgentResult & Tool Calls ──────────────────────── */

export interface ToolCallResult {
  call_id: string;
  tool_id: string;
  ok: boolean;
  result?: unknown;
  error?: string;
  warnings?: string[];
  started_at?: string;
  finished_at?: string;
  duration_ms?: number;
  metadata?: Record<string, unknown>;
}

export interface AgentResult {
  ok: boolean;
  final_response: string;
  events: RuntimeEvent[];
  trace_id: string;
  session_id: string;
  turn_id: string;
  tool_calls: ToolCallResult[];
  warnings: string[];
  errors: string[];
  metadata: {
    selected_skills?: string[];
    visible_tools?: string[];
    source_count?: number;
    manual_review_count?: number;
    retrieval_backend?: string;
    scope?: string;
    workspace_id?: string;
    [k: string]: unknown;
  };
}

export interface RuntimeEvent {
  event_id: string;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

/* ──────────────────────────── Knowledge ──────────────────────────── */

export interface KnowledgeSource {
  source_id: string;
  workspace_id: string;
  title: string;
  source_type?: string;
  artifact_id?: string;
  status?: string;
  sensitivity?: Sensitivity;
  language?: string;
  tags: string[];
  enabled?: boolean;
  chunk_count: number;
  created_at: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeChunk {
  chunk_id: string;
  source_id: string;
  artifact_id?: string;
  title?: string;
  /** Backend returns a safe excerpt (never the full content). */
  safe_excerpt?: string;
  summary?: string;
  sensitivity?: Sensitivity;
  artifact_type?: string;
  tags?: string[];
  chunk_index?: number;
  llm_safe?: boolean;
  created_at?: string;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeSearchResult {
  ok: boolean;
  query: string;
  /** Backend returns `results` (not `hits` / `source_summary`). */
  results: Array<{
    chunk_id: string;
    source_id: string;
    title?: string;
    summary?: string;
    safe_excerpt?: string;
    score: number;
    sensitivity?: Sensitivity;
    artifact_id?: string;
  }>;
  count: number;
  source_count: number;
  /** Best-effort derivation of `source_summary` for the UI. */
  source_summary: SourceSummary[];
  metadata: Record<string, unknown>;
  warnings: string[];
  note?: string;
}

export interface SourceSummary {
  source_id: string;
  title: string;
  chapter?: string;
  section?: string;
  snippet: string;
  score: number;
}

/* ──────────────────────────── Artifacts ──────────────────────────── */

export interface Artifact {
  artifact_id: string;
  workspace_id: string;
  artifact_type: string;
  title: string;
  created_at: string;
  updated_at: string;
  size_bytes: number;
  authoritative: boolean;
  deployable_config: boolean;
  sensitivity: Sensitivity;
  metadata: Record<string, unknown>;
  content_preview?: string;
}

/* ──────────────────────────── Reviews ──────────────────────────── */

export type ReviewStatus = "pending" | "accepted" | "ignored" | "modified";

export interface ReviewItem {
  item_id: string;
  workspace_id: string;
  artifact_id: string;
  severity: "info" | "warning" | "error";
  category: string;
  line_no: number | null;
  reason: string;
  requires_human_review: boolean;
  status: ReviewStatus;
  user_note: string;
  created_at: string;
  updated_at: string;
}

/* ──────────────────────────── Sessions / Workspaces ──────────────────────────── */

export interface Session {
  session_id: string;
  workspace_id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Workspace {
  workspace_id: string;
  name: string;
  created_at: string;
  is_default: boolean;
  stats: {
    session_count: number;
    artifact_count: number;
    knowledge_source_count: number;
  };
}

/* ──────────────────────────── Runtime Audit ──────────────────────────── */

export interface RuntimeAuditTurn {
  turn_id: string;
  session_id: string;
  trace_id: string;
  started_at: string;
  finished_at: string;
  status: string;
  selected_skills: string[];
  visible_tools: string[];
  tool_call_count: number;
  error_count: number;
  warning_count: number;
  events: RuntimeEvent[];
}

/* ──────────────────────────── ApiError ──────────────────────────── */

export type ApiErrorCode =
  | "network"
  | "timeout"
  | "http_4xx"
  | "http_5xx"
  | "parse"
  | "aborted"
  | "unknown";

export interface ApiError {
  ok: false;
  status: number;
  code: ApiErrorCode;
  message: string;
  request_id?: string;
  details?: unknown;
  url?: string;
  timestamp: string;
}

export function isApiError(e: unknown): e is ApiError {
  return (
    typeof e === "object" &&
    e !== null &&
    "ok" in e &&
    (e as { ok: unknown }).ok === false &&
    "code" in e &&
    "message" in e
  );
}

/* ──────────────────────────── AsyncState ──────────────────────────── */

export type AsyncState<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: T }
  | { kind: "empty"; reason?: string }
  | { kind: "error"; error: ApiError };

export function isSuccess<T>(s: AsyncState<T>): s is { kind: "success"; data: T } {
  return s.kind === "success";
}
export function isEmpty<T>(s: AsyncState<T>): s is { kind: "empty"; reason?: string } {
  return s.kind === "empty";
}
export function isError<T>(s: AsyncState<T>): s is { kind: "error"; error: ApiError } {
  return s.kind === "error";
}
export function isLoading<T>(s: AsyncState<T>): s is { kind: "loading" } {
  return s.kind === "loading";
}

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

/* ──────────────────────────── Artifacts ────────────────────────────
 *
 * Wire shape returned by
 *   GET /api/workspaces/<ws>/artifacts
 *   GET /api/workspaces/<ws>/artifacts/<art>
 * There is no `content_preview` field — full content is served by a
 * separate /content endpoint (see artifactsApi.content).
 */
export interface Artifact {
  artifact_id: string;
  workspace_id: string;
  artifact_type: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** File size in bytes (server-reported). */
  size_bytes: number;
  /** File MIME type, e.g. "text/plain". May be empty. */
  mime_type: string;
  /** File extension, e.g. ".txt". May be empty. */
  file_ext: string;
  /** Truncated SHA-256, e.g. "abc12345". May be empty. */
  sha256_short: string;
  /** Path relative to the artifact store root. */
  relative_path: string;
  /** Lifecycle, e.g. "active" | "archived" | "deleted". */
  lifecycle: string;
  /** Where this artifact lives, e.g. "workspace" | "global". */
  scope: string;
  /** Origin, e.g. "user_upload" | "module_output" | "agent_run". */
  source: string;
  /** Sensitivity tier. */
  sensitivity: Sensitivity;
  /** Free-form tags. */
  tags: string[];
  /** Optional LLM-generated or module-supplied summary. */
  summary: string;
  /** Provenance: capability / module / skill that produced this artifact. */
  capability_id: string;
  module: string;
  skill: string;
  /** Run that produced this artifact (empty for user uploads). */
  run_id: string;
  /** True if the content was redacted before persistence. */
  redaction_applied: boolean;
  /** Server-side metadata bag (varies by artifact_type). */
  metadata: Record<string, unknown>;
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

/* ────────────────────────── SessionMessage ──────────────────────────
 *
 * Wire shape from GET /api/sessions/<id>/messages (see
 * workspace/session_store.py::get_session_messages). The backend
 * reconstructs chat messages from run records (one user + one assistant
 * per run). Frontend maps these to ChatMsg in the workbench store.
 *
 * NOTE: backend currently has a bug — agent.run never appends run_id
 * to session.run_ids, so this endpoint always returns []. Plan-C fix
 * keeps the hook in place; once backend is fixed, the background fetch
 * populates messages for cross-device refresh.
 */
export interface SessionMessage {
  message_id?: string;
  session_id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  run_id?: string;
  intent?: string;
  status?: string;
  capability?: string;
  trace_id?: string;
  quality_summary?: Record<string, unknown>;
  llm_metadata?: Record<string, unknown>;
}

export interface Workspace {
  workspace_id: string;
  name: string;
  created_at: string;
  is_default: boolean;
  runs_count?: number;
  artifacts_count?: number;
  memory_count?: number;
  stats: {
    session_count: number;
    artifact_count: number;
    knowledge_source_count: number;
  };
}

export interface AppVersion {
  app?: string;
  version: string;
  build_commit?: string;
  product_ready?: boolean;
}

export interface RuntimeSummary {
  capabilities: {
    total: number;
    enabled: number;
    planned: number;
    disabled: number;
  };
  tools: {
    registered: number;
    model_visible: number;
    hidden_or_non_llm: string[];
  };
}

/* ──────────────────────────── LLM Settings ──────────────────────────── */

export interface LlmConfig {
  enabled: boolean;
  provider: string;
  safe_mode: boolean;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  key_configured: boolean;
  key_preview?: string | null;
  updated_at?: string | null;
  source?: string;
  config_source?: string;
  config_path?: string;
  global?: boolean;
  note?: string;
}

export interface LlmHealth {
  base_url_reachable: boolean;
  chat_completion_endpoint_reachable: boolean;
  chat_completion_ok: boolean;
  configured: boolean;
  connected: boolean;
  http_status: number | null;
  key_loaded: boolean;
  last_error?: string | null;
  last_error_type?: string | null;
  model: string;
  models_endpoint_ok: boolean;
  provider: string;
}

export interface LlmStatus {
  enabled: boolean;
  enabled_by_ui: boolean | null;
  provider: string;
  model: string;
  provider_type: string;
  safe_mode: boolean;
  key_loaded: boolean;
  key_source: string;
  config_source: string;
  connected: boolean;
  settings_file_exists: boolean;
  health: LlmHealth;
  red_lines?: string[];
  allowed_tasks?: string[];
  blocked_tasks?: string[];
}

export interface LlmTestResult {
  ok: boolean;
  provider?: string;
  model?: string;
  llm_used: boolean;
  config_source: string;
  policy_pass: boolean;
  response: string;
  safe_to_show: boolean;
  fallback_reason?: string;
  warnings: string[];
  metadata: Record<string, unknown>;
}

export interface LlmTestRequest {
  task?: "result_summarize" | "context_qa" | "response_compose";
  message?: string;
  signal?: AbortSignal;
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

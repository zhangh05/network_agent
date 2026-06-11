/**
 * Domain types — strict 1:1 mapping from backend Python dataclasses `as_dict()`.
 * No fields are guessed. The frontend only renders what the backend actually
 * returns. See `agent/capabilities/schemas.py` and `agent/runtime/result.py`.
 */

export type CapabilityStatus = "enabled" | "planned" | "disabled";
export type ToolStatus = "enabled" | "planned" | "disabled";
export type RiskLevel = "low" | "medium" | "high" | "forbidden";
export type Sensitivity = "public" | "internal" | "sensitive" | "secret";

/* ───────────────────────── CapabilityManifest ───────────────────────── */

export interface CapabilityModuleSpec {
  module_id: string;
  status: CapabilityStatus;
  service_path: string;
  operations: string[];
  description: string;
}

export interface CapabilitySkillSpec {
  skill_id: string;
  status: CapabilityStatus;
  related_tools: string[];
  intent_patterns: string[];
  required_inputs: string[];
  prompt_summary: string;
  preconditions: string[];
  postconditions: string[];
  safety_rules: string[];
}

export interface CapabilityToolRef {
  tool_id: string;
  status: ToolStatus;
  callable_by_llm: boolean;
  risk_level: RiskLevel;
  requires_approval: boolean;
  forbidden: boolean;
  handler_ref: string;
  input_schema: Record<string, unknown>;
  description: string;
}

export interface CapabilityOutputSpec {
  output_id: string;
  output_type: string;
  description: string;
  artifact_type: string;
  visible_to_user: boolean;
  sensitivity: Sensitivity;
  authoritative: boolean;
  metadata: Record<string, unknown>;
}

export interface CapabilitySafetySpec {
  real_device_access: boolean;
  allows_config_push: boolean;
  produces_deployable_config: boolean;
  may_fabricate_sources: boolean;
  requires_human_review: boolean;
  notes: string;
}

export interface CapabilityManifest {
  capability_id: string;
  name: string;
  status: CapabilityStatus;
  description: string;
  module: CapabilityModuleSpec;
  skills: CapabilitySkillSpec[];
  tools: CapabilityToolRef[];
  outputs: CapabilityOutputSpec[];
  safety: CapabilitySafetySpec;
  dependencies: string[];
  metadata: Record<string, unknown>;
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
  source_type: string;
  scope: string;
  language: string;
  tags: string[];
  enabled: boolean;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface KnowledgeChunk {
  chunk_id: string;
  source_id: string;
  parent_chunk_id: string;
  chapter: string;
  section: string;
  subsection: string;
  content: string;
  char_start: number;
  char_end: number;
  page_start: number;
  page_end: number;
  metadata: Record<string, unknown>;
}

export interface SourceSummary {
  source_id: string;
  title: string;
  chapter: string;
  section: string;
  snippet: string;
  score: number;
}

export interface KnowledgeSearchResult {
  ok: boolean;
  query: string;
  source_count: number;
  hits: Array<{
    chunk_id: string;
    source_id: string;
    chapter: string;
    section: string;
    subsection: string;
    title: string;
    snippet: string;
    score: number;
    lexical_score: number;
    final_score: number;
  }>;
  source_summary: SourceSummary[];
  metadata: Record<string, unknown>;
  warnings: string[];
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

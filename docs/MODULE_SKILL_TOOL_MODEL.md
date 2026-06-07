# Module / Skill / Tool Architecture Model

> **Status**: design document — no code change, no implementation  
> **Date**: 2026-06-07  
> **Scope**: clarify boundaries before Tool Runtime v0.1 design  
> **Non-goal**: implementing Tool Runtime, real device access, or new business modules

---

## 1. Purpose

Define the canonical boundaries between **Module**, **Skill**, **Capability**, and **Tool** within the Network Agent architecture. This document is based on a full source-code audit of the Foundation Baseline at commit `23a0b45`.

---

## 2. Current Source Findings

### 2.1 How Module exists today

Module is defined as a **business domain closure**:

- **Declaration**: `modules/<name>/module.yaml` → registry.json → `registry/loader.py` → `ModuleSpec`
- **Implementation**: `modules/<name>/backend/service.py` (business logic)
- **Example**: `modules/config_translation/` → `backend/service.py::translate_config()` → `translate_bundle` pipeline
- **API exposure**: `POST /api/modules/config-translation/translate` (via `backend/main.py`)

**Current Module inventory** (`modules/registry.json`):

| Module | Status | Maturity |
|--------|--------|----------|
| `config_translation` | enabled | embedded_mvp |
| `topology` | planned | planned |
| `inspection` | planned | planned |
| `knowledge_base` | planned | planned |

### 2.2 How Skill exists today

Skill is defined as a **thin Agent-to-Module adapter**:

- **Declaration**: `skills/<name>/skill.yaml` → registry.json → `registry/loader.py` → `SkillSpec`
- **Implementation**: `skills/<name>/adapter.py` — direct Python import of module service, no HTTP
- **Example**: `skills/config_translation/adapter.py::translate()` → `modules.config_translation.backend.service.translate_config()`
- **Entrypoint type**: `python_adapter`

**Current Skill inventory** (`skills/registry.json`):

| Skill | Status | Type | Module |
|-------|--------|------|--------|
| `config_translation` | enabled | python_adapter | config_translation |
| `topology_draw` | disabled | planned | topology |
| `inspection_analyze` | disabled | planned | inspection |
| `knowledge_search` | disabled | planned | knowledge_base |

### 2.3 How Capability is generated from Module + Skill

Capability is a **derived contract**, not a manually declared entity:

1. `registry/loader.py::load_capabilities()` loads both module and skill registries
2. `_generate_capabilities()` iterates each skill's `capabilities` list
3. For each capability entry, looks up parent ModuleSpec
4. Creates `CapabilitySpec` with composite policies:
   - `status = "enabled"` only when **both** module AND skill are enabled
   - `can_generate_deployable` inherited from module
   - `risk_level` from capability entry or falls back to module default
   - `input_schema` / `output_schema` from module's declared inputs/outputs
   - `policies` composite dict from module settings

**Current Capability inventory**:

| Capability ID | Status | Module | Skill |
|---------------|--------|--------|-------|
| `config.translate` | enabled | config_translation | config_translation |
| `config.review` | enabled | config_translation | config_translation |

### 2.4 How Agent executor calls Skill Adapter

Path: `agent/graph.py::wrap_trace_node("executor")` → `agent/nodes/skill_executor.py::execute()`

Steps inside `execute()`:

1. Read `state.selected_skill`, `capability_id` from state
2. Look up `SkillSpec` + `CapabilitySpec` via `registry/loader.py::get_skill()` / `get_capability()`
3. Block planned/disabled capabilities
4. Resolve artifact input if provided (`source_config` from artifact store)
5. Auto-save `source_config` as input artifact
6. Extract `adapter_path` + `entrypoint_function` from registry
7. **Dynamic import**: `_load_adapter(adapter_path, entrypoint_fn)` → `importlib.import_module()`
8. Call adapter with `(source_config, source_vendor, target_vendor)`
9. Store result in `state.skill_results` (primary) and `state.tool_results` (legacy alias)
10. Auto-save output as artifact (if translate_config)
11. Optional report export
12. Record trace events (skill_call_start/end, module_call_start/end)

### 2.5 Current Tool Runtime status

**Tool Runtime does not yet exist as a formal concept in this codebase.**

No `tools/` directory. No `ToolSpec`. No `ToolRegistry`. No `ToolExecutor`.

However, three **naming confusion points** existed in the codebase pre-cleanup:

| # | Location | Issue | Status |
|---|----------|-------|--------|
| 1 | `agent/state.py` | `tool_calls`/`tool_results` field names — these actually hold **skill** execution records and results | ✅ Cleaned: `skill_calls`/`skill_results` are now primary; `tool_calls`/`tool_results` kept as legacy aliases |
| 2 | `registry/schemas.py` | `VALID_SKILL_TYPES` includes `"external_tool"` — Tool is a Skill sub-type in the taxonomy | ✅ Documented as legacy/deprecated; must not be used for future Tool Runtime |
| 3 | `agent/nodes/skill_executor.py` | Variable `tool_call` held skill call metadata | ✅ Renamed to `skill_call` |

These were **naming issues only** — the runtime behavior is correct (skill adapter → module service). They originated from the early prototyping phase before formal boundary definitions.

---

## 3. Definitions

### 3.1 Module

Module is a **business domain closure**.

| Attribute | Description |
|-----------|-------------|
| What it is | A self-contained business capability implementation |
| Where it lives | `modules/<name>/` |
| Entry | `modules/<name>/backend/service.py` |
| Config | `modules/<name>/module.yaml` |
| Responsibilities | Business process orchestration, calling deterministic services, managing I/O, artifact/report/job orchestration, business-level validation, business security boundaries |
| Forbidden actions | Private LLM calls, bypassing Artifact/Trace/Job/Policy, direct Agent exposure as free execution, storing full sensitive configs in Memory/Trace/Prompt |

### 3.2 Skill

Skill is the **Agent-facing capability surface**.

| Attribute | Description |
|-----------|-------------|
| What it is | A thin adapter exposing a Module's capabilities to the Agent |
| Where it lives | `skills/<name>/` |
| Entry | `skills/<name>/adapter.py` |
| Config | `skills/<name>/skill.yaml` |
| Responsibilities | Declaring agent capabilities (intent, I/O schema), declaring entrypoint + adapter, declaring security red_lines, adapting Agent requests to Module calls |
| Forbidden actions | Implementing complex business logic, private LLM access, real device command execution, bypassing Module to complete business closure, faking planned capability results |

### 3.3 Capability

Capability is **the contract between Agent and system**.

| Attribute | Description |
|-----------|-------------|
| What it is | An auto-generated capability contract from Module + Skill |
| Where it lives | `registry/loader.py::_generate_capabilities()` → `CapabilitySpec` |
| Source | `module.yaml` + `skill.yaml capabilities[]` |
| Responsibilities | Telling Agent what the system can do, providing planner/executor routing info, returning coming_soon for planned, calling real skill adapter for enabled |

### 3.4 Tool

Tool is a **reusable, auditable, policy-controlled atomic action**.

| Attribute | Description |
|-----------|-------------|
| What it is | A single, well-defined operation with schema validation |
| Where it would live | `tools/<category>/<name>.py` or `tools/registry.yaml` |
| Responsibilities | Single atomic action, schema parameter validation, policy permission check, timeout, redaction, trace event, artifact output, structured result |
| Forbidden actions | Expressing full business modules, being called by Agent bypassing Module, real device command execution by default, arbitrary local path access, dumping sensitive output, Memory writes |
| Current status | **Not yet implemented** (see Section 2.5 for confusion points) |

---

## 4. Recommended Boundary

```
┌──────────────────────────────────────────────────┐
│                    User Request                    │
└─────────────────────┬────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────┐
│  Agent (router → context → planner → executor    │
│        → verifier → composer → memory)            │
└─────────────┬──────────────────┬─────────────────┘
              │                  │
              ▼                  ▼
┌─────────────────┐   ┌─────────────────────────┐
│   Capability     │   │  Context / Memory /     │
│   (contract)     │   │  Workspace / Trace      │
└────────┬────────┘   └─────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Skill Adapter   │  ← Agent-facing; thin adapter
│  (python_adapter)│    No business logic
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Module Service  │  ← Business domain closure
│  (service.py)    │    Orchestrates Tools
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Tool Runtime    │  ← Atomic operations
│  (planned)       │    Policy-checked, traced,
│                  │    redacted, artifact-backed
└─────────────────┘
```

---

## 5. Recommended Call Flow

```
Agent
  → Capability (contract lookup)
  → Skill Adapter (thin pass-through)
  → Module Service (business orchestration)
  → Tool Runtime (atomic execution, policy, trace)
  → Tool Provider (actual operation)
```

### Principles

1. **Agent never calls Tool directly**. Tool access is gated behind Module.
2. **Skill defaults to not calling Tool directly**. Module orchestrates Tool calls.
3. **Module orchestrates Tool**. Module service determines which tools to invoke and in what order.
4. **Tool does one atomic action**. Single responsibility, schema-validated inputs, structured outputs.
5. **Tool Runtime enforces security uniformly**: policy check → redaction → trace event → artifact output.
6. If Agent-level tool access is ever needed, it must be exposed via a **special allowlist capability** — never a default-available path.

---

## 6. Tool Runtime v0.1 Candidate Scope

### Allowed low-risk tool categories (v0.1)

| Category | Tool ID | Description |
|----------|---------|-------------|
| artifact | `artifact.read_summary` | Read safe artifact summary (no full config exposure) |
| artifact | `artifact.list` | List artifacts by type/workspace |
| parser | `parser.parse_config_text` | Parse config text into structured blocks |
| parser | `parser.extract_interfaces` | Extract interface definitions from parsed config |
| parser | `parser.extract_routes` | Extract route/prefix entries from parsed config |
| report | `report.render_from_safe_summary` | Render report from sanitized summary data only |
| command | `command.dry_run_echo` | Echo command text (no execution) for validation/debug |

### Proposed ToolSpec schema

```python
@dataclass
class ToolSpec:
    tool_id: str              # e.g. "parser.extract_interfaces"
    display_name: str         # Human-readable name
    description: str          # What it does
    category: str             # artifact | parser | report | command
    status: str               # enabled | planned | disabled
    tool_type: str            # python | external_command (future)
    module: str               # Owning module (or "shared")
    entrypoint: str           # Function path: "tools.parser.parser.extract_interfaces"
    input_schema: dict        # JSON Schema for parameters
    output_schema: dict       # JSON Schema for result
    risk_level: str           # low | medium | high
    can_affect_network: bool  # Must be False for v0.1
    requires_network: bool    # Must be False for v0.1
    requires_filesystem: bool # allowed for v0.1, must be policy-checked
    timeout_ms: int           # Max execution time
    redaction_required: bool  # Always True for v0.1
    trace_enabled: bool       # Always True
    artifact_output: bool     # Whether result is artifact-backed
    policies: dict
```

### Proposed ToolInvocation / ToolResult

```python
@dataclass
class ToolInvocation:
    invocation_id: str
    tool_id: str
    module: str
    call_chain: list         # ["agent", "skill:config_translation", "module:config_translation"]
    inputs: dict
    dry_run: bool            # v0.1 default: True
    trace_id: str
    workspace_id: str
    started_at: str

@dataclass
class ToolResult:
    invocation: ToolInvocation
    ok: bool
    result: dict
    error: Optional[str]
    duration_ms: float
    redaction_applied: bool
    artifact_id: Optional[str]
    trace_event_ids: list
    policy_checks: list      # Which policies were checked
```

### Tool Runtime Architecture (planned)

```
ToolExecutor
  ├── ToolRegistry (tool_id → ToolSpec + entrypoint)
  ├── ToolPolicy    (permission, input validation, output redaction)
  ├── ToolAudit     (trace events, structured result)
  └── ToolArtifact   (auto-save output, summary for LLM context)
```

---

## 7. Tool Runtime v0.1 Must-Not List

Tool Runtime v0.1 is explicitly **forbidden** from:

1. `ssh.exec` — real SSH command execution
2. `telnet.exec` — real Telnet command execution
3. `snmp.walk` — real SNMP walk/query
4. `nmap.scan` — real network scanning
5. `ping.sweep` — real ping sweep
6. Real device command execution of any kind
7. Config push / deploy
8. Arbitrary shell execution
9. Arbitrary file read (outside workspace/artifact sandbox)
10. Arbitrary file write (outside workspace/artifact sandbox)

---

## 8. Security Red Lines

Applicable to Tool Runtime design and all future implementations:

1. Agent must not execute arbitrary tools without capability gating
2. Tool Runtime must not become an arbitrary shell
3. Real device execution is out of scope for v0.1
4. SSH / Telnet / SNMP / nmap are out of scope for v0.1
5. All tools must be registered in ToolRegistry
6. Tool inputs must be schema-validated before execution
7. Tool calls must be policy-checked (permission, risk level, call chain)
8. Tool outputs must be redacted before storage/display
9. Tool results must be traceable (trace event per invocation)
10. Sensitive output must be artifact-backed and summarized — never dumped into LLM context
11. Module remains the business boundary — Agent does not skip Module to reach Tool
12. Skill remains the Agent-facing capability boundary — Skill does not become a Tool proxy

---

## 9. Open Questions

1. Should `agent/state.py` fields `tool_calls`/`tool_results` be renamed to `skill_calls`/`skill_results`?
   - **Recommendation**: In a future batch, rename to eliminate confusion before Tool Runtime is added.
2. Should `registry/schemas.py`'s `VALID_SKILL_TYPES` retain `"external_tool"`?
   - **Recommendation**: Retain for future use, but add explicit documentation that it maps to a Tool-backed skill (not a standalone Tool).
3. Should `skills/config_translation/adapter.py` be the canonical pattern for future adapters?
   - **Recommendation**: Yes — direct import of module service, no HTTP, no LLM — this is the correct pattern.
4. Should the current `agent/nodes/skill_executor.py` be renamed to distinguish Skill execution from future Tool execution?
   - **Recommendation**: Not urgent. The node name "skill_executor" is clear. If Tool Runtime adds tool-level orchestration to Module, that becomes the Module's responsibility, not the Agent's.
5. Should `state.session_id` (v3.1+) be formally part of the agent state contract?
   - **Answer**: Yes. `NetworkAgentState.session_id` is set by `run_agent()` → flows through all 7 graph nodes → used by `memory_writer` to auto-associate runs with sessions. It is a first-class state field alongside `workspace_id`. See [SESSION_MANAGEMENT.md](./SESSION_MANAGEMENT.md).

---

## 10. Naming Boundary Cleanup

As of commit `9bec6aa+`, a naming boundary cleanup was performed to resolve the confusion points identified in Section 2.5.

### Changes applied

1. **`agent/state.py`**: `skill_calls` / `skill_results` are now the **primary** fields for skill/capability execution records. `tool_calls` / `tool_results` are retained as **legacy/deprecated aliases** for backward compatibility with old state, trace, run, and test code. New code **must** use `skill_calls` / `skill_results`.

2. **`agent/nodes/skill_executor.py`**: Internal variable renamed from `tool_call` to `skill_call`. Writes to both `state.skill_calls` (primary) and `state.tool_calls` (legacy alias). All reader nodes (`composer`, `verifier`, `memory_writer`, `graph.py`, `context_builder`, `run_store`) read from `skill_results or tool_results` for backward compatibility.

3. **`registry/schemas.py`**: `external_tool` in `VALID_SKILL_TYPES` is marked as **legacy/deprecated**. It must not be used for new skills or for future Tool Runtime design.

4. **Old fallback files** (`agent/composer.py`, `agent/verifier.py`, `agent/executor.py`): Updated to read from `skill_results or tool_results` for backward compatibility.

### What these names mean

| Name | Semantic | Status |
|------|----------|--------|
| `skill_calls` | Skill/capability execution invocation records (list) | **Primary** — new code writes here |
| `skill_results` | Skill/capability execution results (dict) | **Primary** — new code writes here |
| `tool_calls` | Legacy alias for `skill_calls` — NOT Tool Runtime | Legacy/deprecated alias |
| `tool_results` | Legacy alias for `skill_results` — NOT Tool Runtime | Legacy/deprecated alias |
| `external_tool` | Legacy skill type — NOT future Tool Runtime model | Legacy/deprecated enum value |

### What these names are NOT

- `tool_calls` / `tool_results` are **NOT** Tool Runtime fields. Future Tool Runtime will use independent `ToolSpec` / `ToolRegistry` / `ToolInvocation` / `ToolResult`.
- `external_tool` is **NOT** the way to add real tool capabilities. Future tools will be registered in `ToolRegistry`, not as `skill_type=external_tool`.
- The Agent Runtime's `skill_calls` record **skill execution metadata**, not raw tool invocations. They exist at a higher abstraction level.

### Compatibility guarantee

- Old runs, traces, and state objects that reference `tool_calls` / `tool_results` remain loadable.
- New code writes to `skill_calls` / `skill_results` as primary and also populates `tool_calls` / `tool_results` for backward compat.
- Reader code uses `skill_results or tool_results` to handle both old and new state.
- No existing test was broken by this rename.

---

## 11. Non-Goals

> **Update**: Tool Runtime Foundation v0.1 has been established with independent ToolSpec / ToolRegistry / ToolInvocation / ToolResult. See [TOOL_RUNTIME.md](./TOOL_RUNTIME.md). Still no real device execution.

This document explicitly does **NOT**:

- Implement Tool Runtime
- Create `tools/` directory with real implementations
- Add real command execution
- Add SSH/Telnet/SNMP/nmap/ping sweep
- Modify `config_translation` main chain
- Modify `translate_bundle`
- Re-introduce `/api/translate` (retired surface), `backend/services/config_translation` (retired), or old GraphAgent (retired)
- Enter topology, inspection, CMDB, or knowledge_base business modules
- Relax any existing gate

---

## 11. References

- `docs/ARCHITECTURE.md` — Current architecture overview
- `docs/FOUNDATION_BASELINE.md` — Foundation Baseline documentation
- `registry/schemas.py` — ModuleSpec, SkillSpec, CapabilitySpec definitions
- `registry/loader.py` — Registry loading and capability generation
- `agent/graph.py` — Agent orchestration (LangGraph 7-node pipeline)
- `agent/nodes/skill_executor.py` — Skill execution node
- `agent/state.py` — Shared agent state

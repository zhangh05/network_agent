# Store Boundaries — authoritative store definitions

## Six stores, six boundaries

Every byte the Agent reads or writes falls into exactly one of these stores.
Tools, modules, and the runtime MUST respect these boundaries.

---

### 1. FileStore (`storage/file_store.py`)

**Responsibility:** Raw files and Agent-generated files. The single entry point for all
file I/O in the system.

| Property | Value |
|----------|-------|
| **Authority ID** | `file_id` (pattern: `file_<16 hex>`) |
| **Storage location** | `workspaces/<ws>/files/<category>/<subcategory>/` |
| **Index** | `workspaces/<ws>/index/files.jsonl` (JSONL, append-mode) |
| **Entry points** | `import_user_upload()`, `write_agent_output()`, `create_file_record()` |
| **Read path** | `read_file_content()`, `list_files()`, `get_file_record()` |

**Hard rules:**
- User uploads MUST go through `import_user_upload()` — never direct filesystem copy.
- Agent-generated files MUST use `write_agent_output()` — never direct write.
- File paths are always resolved via `resolve().relative_to()` boundary check.
- Soft-delete sets `lifecycle="soft_deleted"` — physical files are never removed by runtime.

**What it does NOT do:**
- Does NOT store artifact metadata (that's ArtifactStore).
- Does NOT store memory items (that's MemoryStore, via ContextStore).
- Does NOT store knowledge chunks (that's KnowledgeStore, via ContextStore).
- Does NOT store run summaries (that's RunStore).

---

### 2. ArtifactStore (`artifacts/store.py`)

**Responsibility:** Displayable/deliverable artifacts — the user-facing outputs of the Agent.

| Property | Value |
|----------|-------|
| **Authority ID** | `artifact_id` (pattern: `art_<16 hex>`) |
| **Content storage** | Delegated to FileStore (`write_agent_output()`) |
| **Metadata index** | `workspaces/<ws>/index/artifacts.jsonl` |
| **Lightweight index** | `workspaces/<ws>/sys/artifacts.index.json` |
| **Run index** | `workspaces/<ws>/runs/<run_id>.artifacts.json` |

**Hard rules:**
- Every Artifact MUST have a `file_id` reference (FileStore handles content).
- Content is classified (`classify_file()`) and redacted (`contains_secret()` guard).
- Artifacts are the user-facing layer — they appear in FileManager, ReviewCenter, etc.
- `source_path` reads are validated against `ALLOWED_SOURCE_DIRS` only.

**What it does NOT do:**
- Does NOT store content directly (always writes through FileStore).
- Does NOT serve as a file system for raw uploads (FileStore does that).
- Does NOT replace RunStore (run summaries are separate).

---

### 3. MemoryStore (`agent/runtime/memory/` + ContextStore backend)

**Responsibility:** Long-term facts, preferences, decisions. Persistent across turns and sessions.

| Property | Value |
|----------|-------|
| **Authority ID** | `memory_id` (pattern: `mem_<12 hex>`) |
| **Storage backend** | ContextStore (`workspaces/<ws>/context/items.jsonl`) |
| **Item type** | `memory_hit` |
| **Write path** | `memory/writer.py` → `ContextStore.put()` |
| **Read path** | `UnifiedRetriever.search_memory()` → BM25 on `item_type="memory_hit"` |

**Hard rules:**
- Memory items are TEXT-ONLY — maximum 8KB per item.
- NEVER store raw config files, binary content, or full document text.
- NEVER store API keys, passwords, or tokens (redacted before write).
- Confirmation required for high-confidence conflicts before overwrite.
- Redaction applied via `memory/redaction.py` before ContextStore write.

**What it does NOT do:**
- Does NOT store files (use FileStore).
- Does NOT store knowledge chunks (use KnowledgeStore).
- Does NOT serve as a general-purpose key-value store.
- Does NOT persist raw LLM inputs/outputs (those go to session messages).

---

### 4. KnowledgeStore (`agent/modules/knowledge/` + ContextStore backend)

**Responsibility:** Searchable document chunks for RAG retrieval.

| Property | Value |
|----------|-------|
| **Authority ID** | `source_id` (sources), `chunk_id` (chunks) |
| **Storage backend** | ContextStore (`workspaces/<ws>/context/items.jsonl`) |
| **Item types** | `knowledge_source`, `knowledge_chunk` |
| **Chunk size** | 800 characters, 100 char overlap |
| **Write path** | `store.py` → `ContextStore.put_many()` |
| **Read path** | `UnifiedRetriever.search_knowledge()` → BM25 on `item_type="knowledge_chunk"` |

**Hard rules:**
- Document source files go to FileStore FIRST, then chunks are created.
- Each chunk references its `source_file_id` and `normalized_file_id` (FileStore links).
- Chunks are searchable via BM25, reranked by `KnowledgeReranker`.
- Maximum source content: 200,000 characters.

**What it does NOT do:**
- Does NOT replace FileStore as the document source of truth.
- Does NOT store user preferences or long-term facts (use MemoryStore).
- Does NOT serve binary content or non-text documents.

---

### 5. ContextStore (`context/context_store.py`)

**Responsibility:** Turn/context-level evidence — the transient retrieval layer that
feeds memory items and knowledge chunks into the LLM context.

| Property | Value |
|----------|-------|
| **Storage location** | `workspaces/<ws>/context/items.jsonl` |
| **Backend for** | MemoryStore, KnowledgeStore |
| **Write mode** | Append-only JSONL with tombstone deletion |
| **Thread safety** | Per-workspace `threading.RLock` |
| **GC** | `compact()` via tmp+fsync+os.replace (atomic) |

**Hard rules:**
- ContextStore is an INFRASTRUCTURE store — it backs MemoryStore and KnowledgeStore,
  but is NOT directly accessed by tools or the runtime.
- ContextStore items are metadata + content pointers, not the authoritative source.
- The authoritative source for files is FileStore; for artifacts is ArtifactStore.
- ContextStore compaction is safe: tombstoned items are removed, active items preserved.

**What it does NOT do:**
- Does NOT serve as a user-facing file system.
- Does NOT replace FileStore or ArtifactStore.
- ContextStore items are NOT directly referenced in tool calls (use file_id or artifact_id).

---

### 6. RunStore (`workspace/run_store.py`)

**Responsibility:** Audit summaries — one record per Agent turn. Lightweight,
redacted, never contains raw secrets or full configurations.

| Property | Value |
|----------|-------|
| **Storage location** | `workspaces/<ws>/runs/<run_id>.json` |
| **Write mode** | Direct `write_text()` (TODO: atomic tmp+rename) |
| **Fields** | run_id, session_id, status, tool_calls summary, warnings, errors, timeline_summary, metadata |

**Hard rules:**
- Run records are SUMMARIES — never full raw content.
- `user_input_summary` is truncated to 120 chars and redacted.
- `final_response_summary` is truncated to 300 chars and redacted.
- NEVER include: `source_config`, `raw_config`, `api_key`, `password`, `token`,
  `secret`, full command outputs, full file paths with sensitive data.
- Sensitive key filtering applied at `_is_sensitive_key()` during write.

**What it does NOT do:**
- Does NOT store full LLM prompts or responses (those are in session messages).
- Does NOT store file contents (use FileStore).
- Does NOT store artifact contents (use ArtifactStore).
- Does NOT store decision reports (those go to `runs/<run_id>.decision.json`).

---

## Boundary enforcement

### Upload flow
```
User file → import_user_upload() → FileRecord (file_id)
           → (optional) ArtifactRecord (artifact_id, linked to file_id)
           → (optional) KnowledgeStore chunks (linked to file_id)
```

### Agent output flow
```
Agent generates content → write_agent_output() → FileRecord (file_id)
                        → save_artifact() → ArtifactRecord (artifact_id, links to file_id)
                        → DecisionReport → runs/<run_id>.decision.json
```

### Memory/knowledge flow
```
Runtime → MemoryQueryPlanner → UnifiedRetriever.search_memory()
        → ContextStore items (item_type="memory_hit")

Runtime → KnowledgeQueryPlanner → UnifiedRetriever.search_knowledge()
        → ContextStore items (item_type="knowledge_chunk")
```

### Run audit flow
```
Turn completes → RunStore.write_run_record() → runs/<run_id>.json
              → DecisionReport → runs/<run_id>.decision.json
              → Trace → runs/<run_id>.trace.json
```

---

## Removed Paths

| Path | Status | Action |
|------|--------|--------|
| `tracking_only` | REMOVED from code | No action. |
| Direct workspace `write_text()` | INCONSISTENT | RunStore should use atomic `tmp+rename`. FileStore already does. |
| `*.meta.json` sidecar files | inactive | New artifacts use `index/artifacts.jsonl`. |

---

## Version

- **Document version**: v1.0
- **Last updated**: 2026-06-21
- **Schema version**: store_boundaries.v1

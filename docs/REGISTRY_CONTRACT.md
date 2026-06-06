# Registry Contract

## Overview

Registry is the **contract center** for Capability, Skill, and Module. Every executable unit must be registered; no hardcoded modules or private LLM calls are allowed.

## Module Contract

```yaml
module_id: str
status: active | inactive | deprecated
deployable: bool
no_llm: bool          # True = module never calls LLM directly
no_legacy: bool       # True = no old-style imports
capabilities: [str]   # capability_ids this module provides
risk: low | medium | high | critical
io: {input_schema, output_schema}
artifacts: {input:[], output:[]}
memory: {reads:[], writes:[]}
trace: {events:[]}
security: {red_lines:[], allowed_operations:[]}
```

## Skill Contract

```yaml
skill_id: str
status: active | inactive | deprecated
module_id: str
adapter_path: str        # module-relative adapter path
entrypoints: [str]       # callable entrypoint names
calls_llm: bool          # True = this skill may call LLM
red_lines: [str]         # MUST NOT operations
capabilities: [str]
trace: {events:[]}
memory: {reads:[], writes:[]}
```

## Capability Contract

```yaml
capability_id: str       # e.g., "config.translate"
intent: str              # natural language intent pattern
module_id: str
skill_id: str
status: active | inactive | coming_soon
requires_verification: bool
llm_allowed: bool
```

## Enabled Capabilities

| Capability | Status |
|------------|--------|
| `config.translate` | active |
| `config.review` | active |
| `report.export` | active |
| `job.translate` | active (if job system present) |

## Planned Capabilities (return `coming_soon`)

| Capability | Status |
|------------|--------|
| `topology.build` | coming_soon |
| `inspection.analyze` | coming_soon |
| `knowledge.index` | coming_soon |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/registry/status` | GET | All registered capabilities + status |
| `/api/modules` | GET | All registered modules |
| `/api/skills` | GET | All registered skills |
| `/api/capabilities` | GET | All registered capabilities |

## Red Lines

- No hardcoded module imports (everything through registry)
- No skill or module may have private/internal LLM calls outside registry contract
- All capabilities capable of mutation require `requires_verification=true`

# Config Translation Module

## Status

- Module registry status: `enabled`
- Maturity: `beta_ready`
- API base: `/api/modules/config-translation`
- Main endpoint: `POST /api/modules/config-translation/translate`

## Current Source

```text
modules/config_translation/
  backend/
    client.py
    schemas.py
    service.py
  core/
    deployable_policy.py
    ir_parser.py
    quality.py
    rule_translator.py
    translation_candidate_factory.py
    translation_model.py
    typed_ir.py
    typed_renderer.py
    parser/config_block_parser.py
  module.yaml
  MODULE.md
```

## Runtime Role

This module provides deterministic network configuration translation. It is called through the unified backend and can produce:

- `deployable_config`
- `manual_review`
- `semantic_near`
- `unsupported`
- `audit`

## Boundaries

- It does not directly call the LLM.
- It does not expose direct config push.
- It must keep high-risk or uncertain items in review/unsupported outputs.
- The current retired `/api/translate` route is not exposed.

## UI

The UI is part of the unified React frontend. The module itself owns backend translation behavior, not a separate frontend.

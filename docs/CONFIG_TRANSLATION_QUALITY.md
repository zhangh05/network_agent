# Config Translation Quality

Baseline entering completion: `ac6cadd`.

The canonical config translation path remains `RuleBasedTranslator.translate_bundle()` through `modules/config_translation/backend/service.py`. The LLM must not generate or modify `deployable_config`.

## Summary Fields

Every config translation result includes `quality_summary` counts:

- `source_residue_count`
- `silent_drop_count`
- `unsupported_count`
- `safe_drop_count`
- `review_required_count`

Additional diagnostic arrays may be present in the direct module response, but run history stores only count-level summaries.

## Gates

- `source_residue_count > 0` creates warnings and high-risk manual review.
- `silent_drop_count > 0` creates warnings and high-risk manual review.
- High-risk quality findings must not be downgraded.
- Results with quality warnings must not be described as ready for device execution.

## Platform Visibility

Quality counts are surfaced in:

- `POST /api/modules/config-translation/translate`
- `POST /api/agent/run` top-level result
- Agent final response
- backend run history
- UI recent run rows
- observability trace end metadata
- report summary when a report is generated

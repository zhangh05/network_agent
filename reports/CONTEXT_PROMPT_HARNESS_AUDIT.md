# Context / Prompt / Harness Audit

**Conclusion: PASS**

## Warnings
- OK: context/schemas.py exists
- OK: context/resolver.py exists
- OK: context/loader.py exists
- OK: context/selector.py exists
- OK: context/compressor.py exists
- OK: context/builder.py exists
- OK: builder uses full pipeline (load→select→compress)
- OK: prompts/schemas.py exists
- OK: prompts/loader.py exists
- OK: prompts/renderer.py exists
- OK: prompts/policy.py exists
- OK: prompts/registry.yaml exists
- OK: 7 templates in prompts/templates/
- OK: safe_generate imports prompts runtime
- OK: rendered.text used in messages
- OK: composer has _select_prompt_task
- OK: policy detects direct deploy claims
- OK: fake ref pattern present
- OK: docs/FOUNDATION_BASELINE.md exists
- OK: docs/ARCHITECTURE.md exists
- OK: docs/AGENT_RUNTIME.md exists
- OK: docs/PROMPT_RUNTIME.md exists
- OK: docs/JOB_RUNTIME.md exists


# P3 Production Hardening

P3 makes capability selection, tool discovery, retrieval decisions, and
runtime inspection measurable and traceable without expanding the default LLM
tool surface.

## Capability routing

- Router contract: `capability_router.v2`
- ASCII keywords use token boundaries; CJK keywords use phrase matching.
- Active artifact, file, memory, knowledge, and scene signals participate in
  routing before the safe fallback is considered.
- Every route records selected capabilities, candidate scores, confidence,
  signals, ambiguity, fallback use, and routing latency.
- `python3 scripts/evaluate_capability_routing.py` is the deterministic quality
  gate. It fails when required recall is below 95%, top-1 accuracy is below
  90%, unexpected selection exceeds 10%, or any canonical case fails.

## Tool catalog

- `/api/tools/catalog` serves a process-static canonical snapshot identified by
  `tool_catalog.v2` and a structural fingerprint.
- `tool.catalog.search` records ranking version, catalog size, token count,
  latency, match count, and truncation.
- A catalog search may add at most eight governed tools to the current turn.
- Discovery never executes a tool. The model must issue a separate tool call,
  which is checked again against the current visible set and runtime policy.

## Decision report

- Sidecar schema: `decision_report.v2`
- Endpoint:
  `GET /api/workspaces/<workspace_id>/runs/<run_id>/decision`
- Success uses the canonical single-item envelope:
  `{ "ok": true, "item": { ... }, "workspace_id": "..." }`.
- Reports preserve structured scene, capability route, retrieval, tool plan,
  catalog expansion, context pipeline, execution, and real/synthetic trace
  information after redaction.
- Recent run summaries expose only compact counts and statuses; full decision
  data is loaded on demand.

## Frontend truth surfaces

- Runtime records have separate Overview, Event Timeline, and Decision tabs.
- The workbench inspector loads the same decision report for the latest turn.
- Trace counts distinguish real, synthetic, and missing events.
- File Manager only offers packet analysis for raw `.pcap` or `.pcapng`
  artifacts. Existing packet sessions are reused instead of reparsing.

## Verification

```bash
python3 scripts/evaluate_capability_routing.py
python3 -m pytest harness/test_p3_routing_evaluation.py \
  harness/test_p3_tool_catalog.py \
  harness/test_p3_decision_report.py
cd frontend && npm test -- --run && npx tsc --noEmit
```

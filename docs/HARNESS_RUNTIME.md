# Harness Runtime

## Test Suite Status

| Metric | Count |
|--------|-------|
| Passed | 493 |
| Skipped | 7 |
| Failed | 0 |

## Skipped Tests

The 7 skipped tests are **live/server/key tests** gated behind an environment variable:

```
RUN_LIVE_TESTS=1
```

Without this flag, tests that require real external resources are skipped.

## Test Isolation

- All tests use **temp directories** for workspace isolation
- No real workspace pollution during test runs
- File system state is always ephemeral

## Default Test Environment

Tests run without:
- Real MiniMax API key
- Desktop API key
- Real workspace data

## Test Markers

| Marker | Description |
|--------|-------------|
| `unit` | Isolated function/class tests |
| `integration` | Cross-component tests |
| `security` | Security boundary tests |
| `scenario` | End-to-end workflow scenarios |
| `golden` | Snapshot/regression tests |
| `prompt` | Prompt rendering and policy tests |
| `live` | Tests requiring live external services |
| `slow` | Performance or long-running tests |

## Running Tests

```bash
# Default (unit + integration + security + scenario + golden + prompt)
pytest

# Include live tests
RUN_LIVE_TESTS=1 pytest

# Specific markers
pytest -m "unit"
pytest -m "not slow and not live"
```

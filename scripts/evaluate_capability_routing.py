#!/usr/bin/env python3
"""Run the production capability-routing quality gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.runtime.capability_routing.evaluation import (
    DEFAULT_ROUTING_CASES,
    evaluate_router,
)


def main() -> int:
    report = evaluate_router(DEFAULT_ROUTING_CASES)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    passed = (
        report["required_capability_recall"] >= 0.95
        and report["top1_accuracy"] >= 0.90
        and report["unexpected_capability_rate"] <= 0.10
        and not report["failures"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

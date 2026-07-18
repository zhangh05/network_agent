"""Token usage record store."""

from __future__ import annotations

from storage.records import workspace_record_file


def token_usage_path(workspace_id: str):
    return workspace_record_file(workspace_id, "usage", "token_usage.jsonl")

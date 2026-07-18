"""CMDB asset record repository."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from storage.records import append_jsonl, jsonl_transaction, read_jsonl, rewrite_jsonl

_ASSET_PARTS = ("cmdb", "assets.jsonl")


@contextmanager
def assets_transaction(workspace_id: str) -> Iterator[None]:
    with jsonl_transaction(workspace_id, _ASSET_PARTS):
        yield


def append_asset(workspace_id: str, record: dict[str, Any]) -> None:
    append_jsonl(workspace_id, _ASSET_PARTS, record)


def read_assets(workspace_id: str) -> list[dict[str, Any]]:
    return read_jsonl(workspace_id, _ASSET_PARTS)


def replace_assets(workspace_id: str, records: list[dict[str, Any]]) -> None:
    rewrite_jsonl(workspace_id, _ASSET_PARTS, records)

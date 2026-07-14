# modules/config_translation/backend/schemas.py

from dataclasses import dataclass, field
@dataclass
class TranslateRequest:
    source_config: str
    source_vendor: str = "auto"
    target_vendor: str = ""

    def as_dict(self) -> dict:
        return {
            "source_config": self.source_config,
            "source_vendor": self.source_vendor,
            "target_vendor": self.target_vendor,
        }


@dataclass
class TranslateResponse:
    deployable_config: str = ""
    manual_review: list = field(default_factory=list)
    manual_review_items: list = field(default_factory=list)
    semantic_near: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)
    audit: dict = field(default_factory=dict)
    quality_summary: dict = field(default_factory=dict)
    manual_review_count: int = 0
    semantic_near_count: int = 0
    unsupported_count: int = 0
    mapping_log: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    build_commit: str = ""
    translator_entry: str = "translate_bundle"
    elapsed_ms: float = 0

    def as_dict(self) -> dict:
        return {
            "deployable_config": self.deployable_config,
            "manual_review": self.manual_review,
            "manual_review_items": self.manual_review_items,
            "semantic_near": self.semantic_near,
            "unsupported": self.unsupported,
            "audit": self.audit,
            "quality_summary": self.quality_summary,
            "manual_review_count": self.manual_review_count,
            "semantic_near_count": self.semantic_near_count,
            "unsupported_count": self.unsupported_count,
            "mapping_log": self.mapping_log,
            "warnings": self.warnings,
            "build_commit": self.build_commit,
            "translator_entry": self.translator_entry,
            "elapsed_ms": self.elapsed_ms,
        }

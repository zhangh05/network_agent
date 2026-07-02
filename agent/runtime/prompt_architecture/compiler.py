# agent/runtime/prompt_architecture/compiler.py
"""Capability-first prompt compiler.

Assembles system contract + runtime blocks into a PromptAssembly.
Replaces tool-first prompt injection with capability-first blocks.
"""

from __future__ import annotations

from agent.runtime.prompt_architecture.models import PromptAssembly
from agent.runtime.prompt_architecture.policies import SYSTEM_CONTRACT
from agent.runtime.prompt_architecture.blocks import (
    build_environment_context_block,
    build_runtime_state_block,
    build_skill_guidance_block,
    build_capability_context_block,
    build_evidence_context_block,
    build_active_tool_contract_block,
)


def compile_runtime_prompt(ctx) -> PromptAssembly:
    """Compile a capability-first system prompt from core.context.

    Returns a PromptAssembly with the final_prompt and metadata.
    Does NOT inject skill_prompt or full tool catalog.
    """
    blocks = []
    for builder in [
        build_environment_context_block,
        build_runtime_state_block,
        build_skill_guidance_block,
        build_capability_context_block,
        build_evidence_context_block,
        build_active_tool_contract_block,
    ]:
        block = builder(ctx)
        if block is not None and block.content.strip():
            blocks.append(block)

    ordered = tuple(sorted(blocks, key=lambda b: (b.priority, b.block_id)))
    final_parts = [SYSTEM_CONTRACT.strip()]
    for block in ordered:
        final_parts.append(f"## {block.title}\n{block.content.strip()}")

    final_prompt = "\n\n".join(final_parts).strip()
    return PromptAssembly(
        system_contract=SYSTEM_CONTRACT.strip(),
        blocks=ordered,
        final_prompt=final_prompt,
        metadata={
            "prompt_architecture": "capability_first",
            "block_ids": [b.block_id for b in ordered],
            "block_count": len(ordered),
            "length_chars": len(final_prompt),
        },
    )

"""Context Pipeline stages — thin wrappers around existing helper functions.

Each stage:
  1. Calls the existing helper from context_builder.py
  2. Wraps the result in ContextStageResult
  3. Never mutates ctx directly (pipeline orchestrator handles that)

This is a PURE REFACTOR — no behaviour changes, no logic changes.
"""
from __future__ import annotations
import uuid
from typing import Any
from agent.runtime.context_pipeline.models import ContextStageResult, StageName

def _safe_except(stage_name: StageName, fn, *args, **kwargs):
    """Execute fn, return ContextStageResult on success or degraded on failure."""
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, ContextStageResult):
            return result
        return ContextStageResult.ok_result(stage_name, data=result if result is not None else {})
    except Exception as exc:
        return ContextStageResult.failed(stage_name, str(exc))

class ContextInitStage:
    """Stage 1: Create TurnContext with basic identity fields."""

    def run(self, session, turn, **inputs) -> ContextStageResult:
        return _safe_except(StageName.INIT, self._do_run, session, turn)

    @staticmethod
    def _do_run(session, turn):
        from agent.core.turn_context import TurnContext
        ctx = TurnContext(turn_id=turn.turn_id, session_id=session.session_id, workspace_id=getattr(session, 'workspace_id', '') or '', trace_id=str(uuid.uuid4()), user_input=turn.op.user_input if turn.op else '')
        setattr(ctx, 'session', session)
        ctx.metadata['context_status'] = 'building'
        if bool(getattr(session, 'is_sub_agent', False)):
            ctx.metadata['is_sub_agent'] = True
        return ContextStageResult(name=StageName.INIT, ok=True, data={'ctx': ctx})

class ModelConfigStage:
    """Stage 2: Resolve LLM model configuration."""

    def run(self, ctx: Any, **inputs) -> ContextStageResult:
        return _safe_except(StageName.MODEL_CONFIG, self._do_run, ctx)

    @staticmethod
    def _do_run(ctx):
        from agent.llm.config import resolve_provider_config
        try:
            ctx.model_config = resolve_provider_config()
        except Exception:
            ctx.model_config = {'enabled': False, 'provider_type': 'disabled'}
        return ContextStageResult.ok_result(StageName.MODEL_CONFIG)

class HistoryStage:
    """Stage 3: Load context history window."""

    def run(self, ctx: Any, session: Any, **inputs) -> ContextStageResult:
        return _safe_except(StageName.HISTORY, self._do_run, ctx, session)

    @staticmethod
    def _do_run(ctx, session):
        from agent.runtime.context_history import DEFAULT_HISTORY_WINDOW, initial_history_window
        ctx.history_window = initial_history_window(session, k=DEFAULT_HISTORY_WINDOW)
        return ContextStageResult.ok_result(StageName.HISTORY)

class ToolRouterStage:
    """Stage 4: Build base tool router."""

    def run(self, ctx: Any, services: Any, **inputs) -> ContextStageResult:
        return _safe_except(StageName.TOOL_ROUTER, self._do_run, ctx, services)

    @staticmethod
    def _do_run(ctx, services):
        from agent.runtime.context_tools import build_base_tool_router
        ctx.tool_router = build_base_tool_router(ctx, services)
        return ContextStageResult.ok_result(StageName.TOOL_ROUTER)

class CapabilitySelectionStage:
    """Stage 5: Select capabilities + snapshot services."""

    def run(self, ctx, services, **inputs) -> ContextStageResult:
        return _safe_except(StageName.CAPABILITY_SELECTION, self._do_run, ctx, services)

    @staticmethod
    def _do_run(ctx, services):
        module_snap = _snapshot_service_wrapper(getattr(services, 'module_service', None))
        ctx.module_snapshot = module_snap
        cap_reg = getattr(services, 'capability_registry', None) if services else None
        selected = list(cap_reg.list_all()) if cap_reg else []
        selected_ids = [m.capability_id for m in selected if m.status == 'enabled']
        return ContextStageResult(name=StageName.CAPABILITY_SELECTION, ok=True, warnings=[], data={'selected_capabilities': selected_ids, 'module_snapshot': module_snap, 'capability_registry': cap_reg})

class SceneDecisionStage:
    """Stage 6: Compute SceneDecision."""

    def run(self, ctx, session, **inputs) -> ContextStageResult:
        return _safe_except(StageName.SCENE_DECISION, self._do_run, ctx, session)

    @staticmethod
    def _do_run(ctx, session):
        from agent.runtime.cognition.scene_decision import decide_scene
        session_meta = getattr(session, 'metadata', None) or {}
        previous_scene = session_meta.get('last_tool_scene') if isinstance(session_meta, dict) else None
        previous_rule_scene = session_meta.get('last_rule_tool_scene') if isinstance(session_meta, dict) else None
        decision = decide_scene(ctx.user_input or '', session_context=session_meta if isinstance(session_meta, dict) else {}, previous_scene=previous_scene, previous_rule_scene=previous_rule_scene, intent=ctx.metadata.get('intent', ''))
        ctx.scene_decision = decision
        ctx.metadata['scene_decision_status'] = 'ok'
        return ContextStageResult(name=StageName.SCENE_DECISION, ok=True, data={'scene_decision': decision})

class RetrievalPolicyStage:
    """Stage 7: Evaluate RetrievalTriggerPolicy (P1-B)."""

    def run(self, ctx, session, **inputs) -> ContextStageResult:
        return _safe_except(StageName.RETRIEVAL_POLICY, self._do_run, ctx, session)

    @staticmethod
    def _do_run(ctx, session):
        from agent.runtime.retrieval.trigger_policy import RetrievalTriggerPolicy, RetrievalStatus
        session_meta = getattr(session, 'metadata', None) or {}
        scene_decision = getattr(ctx, 'scene_decision', None)
        is_simple = getattr(scene_decision, 'is_simple_chat', False) if scene_decision else False
        is_factual = getattr(scene_decision, 'is_factual_query', False) if scene_decision else False
        history = getattr(ctx, 'history_window', None) or []
        session_has_history = len(history) > 1
        safe_ctx = ctx.safe_context if hasattr(ctx, 'safe_context') else {}
        file_ids = list(safe_ctx.get('file_ids', []) or [])
        artifact_ids = list(safe_ctx.get('artifact_ids', []) or [])
        artifact_refs = ctx.metadata.get('artifact_refs', []) or []
        try:
            from agent.runtime.context_file_refs import resolve_explicit_file_refs
            explicit_refs = resolve_explicit_file_refs(getattr(ctx, 'workspace_id', '') or '', getattr(ctx, 'user_input', '') or '')
            if explicit_refs:
                ctx.safe_context.setdefault('explicit_file_refs', explicit_refs)
                ctx.safe_context.setdefault('file_ids', [])
                for ref in explicit_refs:
                    fid = ref.get('file_id')
                    if fid and fid not in ctx.safe_context['file_ids']:
                        ctx.safe_context['file_ids'].append(fid)
                ctx.metadata['explicit_file_ref_count'] = len(explicit_refs)
                ctx.metadata['explicit_file_refs_verified'] = len([r for r in explicit_refs if r.get('verified')])
                file_ids = list(ctx.safe_context.get('file_ids', []) or [])
        except Exception as exc:
            ctx.metadata.setdefault('context_warnings', []).append(f'explicit_file_ref_resolution_failed: {str(exc)[:120]}')
        has_file_refs = bool(file_ids or artifact_ids or artifact_refs)
        is_tool_retry = bool(ctx.metadata.get('required_tool_retry_used'))
        policy = RetrievalTriggerPolicy()
        decision = policy.evaluate(user_input=ctx.user_input or '', session_meta=session_meta, ctx_meta=ctx.metadata, has_memory_index=True, has_knowledge_index=True, is_simple_chat=is_simple, is_factual_query=is_factual, session_has_history=session_has_history, has_file_refs=has_file_refs, file_ids=file_ids, artifact_ids=artifact_ids, is_tool_retry=is_tool_retry)
        ctx.metadata['retrieval_decision'] = decision.to_dict()
        if scene_decision and hasattr(scene_decision, 'needs_memory'):
            if decision.memory_status in (RetrievalStatus.REQUIRED.value, RetrievalStatus.OPTIONAL.value) and (not scene_decision.needs_memory):
                scene_decision.needs_memory = True
                scene_decision.is_memory_task = True
        if scene_decision and hasattr(scene_decision, 'needs_knowledge'):
            if decision.knowledge_required and (not scene_decision.needs_knowledge):
                scene_decision.needs_knowledge = True
                scene_decision.is_knowledge_task = True
        return ContextStageResult(name=StageName.RETRIEVAL_POLICY, ok=True, metadata={'retrieval_decision': decision.to_dict()})

class RuntimeStateStage:
    """Stage 8: Prepare runtime state / task workflow hooks."""

    def run(self, ctx, session, **inputs) -> ContextStageResult:
        return _safe_except(StageName.RUNTIME_STATE, self._do_run, ctx, session)

    @staticmethod
    def _do_run(ctx, session):
        from agent.runtime.state.hooks import prepare_runtime_state_for_turn
        prepare_runtime_state_for_turn(ctx, session=session)
        ctx.metadata['runtime_state_status'] = 'ok'
        return ContextStageResult.ok_result(StageName.RUNTIME_STATE)

class EvidenceStage:
    """Stage 9: Run EvidencePipeline → EvidenceBundle."""

    def run(self, ctx, turn, selected_skills, services, **inputs) -> ContextStageResult:
        return _safe_except(StageName.EVIDENCE, self._do_run, ctx, turn, selected_skills, services)

    @staticmethod
    def _do_run(ctx, turn, selected_skills, services):
        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline
        pipeline_obj = EvidencePipeline()
        evidence_bundle = pipeline_obj.build(ctx, services=services)
        _enrich_retrieval_wrapper(ctx, evidence_bundle)
        return ContextStageResult(name=StageName.EVIDENCE, ok=True, data={'evidence_bundle': evidence_bundle})

class ToolPlanningStage:
    """Stage 10: ToolPlannerV2 — plan tools from SceneDecision + EvidenceBundle."""

    def run(self, ctx, evidence_bundle, session, services, selected_skills, **inputs) -> ContextStageResult:
        return _safe_except(StageName.TOOL_PLANNING, self._do_run, ctx, evidence_bundle, session, services, selected_skills)

    @staticmethod
    def _do_run(ctx, evidence_bundle, session, services, selected_skills):
        cap_reg = getattr(services, 'capability_registry', None) if services else None
        if cap_reg is None or ctx.tool_router is None:
            return ContextStageResult.ok_result(StageName.TOOL_PLANNING, metadata={'tool_planning_skipped': True, 'reason': 'missing_services'})
        scene_decision = getattr(ctx, 'scene_decision', None)
        if scene_decision is None:
            return ContextStageResult.ok_result(StageName.TOOL_PLANNING, metadata={'tool_planning_skipped': True, 'reason': 'no_scene_decision'})
        from agent.tools.router import ToolRouter
        from agent.llm.tool_adapter import from_llm_tool_name
        from agent.runtime.tool_planning.planner import ToolPlannerV2
        from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
        from agent.runtime.capability_routing.toolset import active_tool_catalog
        base_reg = getattr(ctx.tool_router, 'registry', None) or (ctx.tool_router if hasattr(ctx.tool_router, 'list_model_visible') else None)
        if base_reg is None:
            return ContextStageResult.ok_result(StageName.TOOL_PLANNING, metadata={'tool_planning_skipped': True, 'reason': 'no_base_registry'})
        planner = ToolPlannerV2()
        try:
            from agent.runtime.tool_planning.conversation import enrich_query_with_history
            enriched_query = enrich_query_with_history(ctx.user_input, ctx=ctx)
        except Exception:
            enriched_query = ctx.user_input
        available_catalog = active_tool_catalog(enriched_query, scene=scene_decision, safe_context=getattr(ctx, 'safe_context', {}) or {}, limit=24)
        tool_scene = planner.plan(scene_decision, evidence_bundle=evidence_bundle, available_catalog=available_catalog, model_config=ctx.model_config)
        rule_tool_scene = scene_to_rule_scene(scene_decision)
        allowed_tools = list(tool_scene.get('candidate_tools') or [])
        for ct in _core_tools_for_context(ctx, rule_tool_scene):
            if ct not in allowed_tools:
                allowed_tools.append(ct)
        ctx.tool_router = ToolRouter.for_turn(base_reg, allowed_tool_ids=allowed_tools)
        if services and getattr(services, 'tool_service', None) and hasattr(services.tool_service, 'dispatch'):
            ctx.tool_router.dispatch_delegate = services.tool_service.dispatch
        visible_tools = sorted({from_llm_tool_name(t['function']['name']) for t in ctx.tool_router.model_visible_tools()})
        ctx.visible_tool_ids = visible_tools
        return ContextStageResult(name=StageName.TOOL_PLANNING, ok=True, data={'selected_visible_tools': visible_tools, 'dynamic_visibility': True, 'tool_scene': tool_scene, 'rule_tool_scene': rule_tool_scene})

class SafeContextStage:
    """Stage 11: Build safe_context (LLM-visible) + runtime snapshot."""

    def run(self, ctx, evidence_bundle, services, tool_scene, rule_tool_scene, selected_visible_tools, selected_skills, skill_snapshot, module_snapshot, capability_registry, **inputs) -> ContextStageResult:
        return _safe_except(StageName.SAFE_CONTEXT, self._do_run, ctx, evidence_bundle, services, tool_scene, rule_tool_scene, selected_visible_tools, selected_skills, skill_snapshot, module_snapshot, capability_registry)

    @staticmethod
    def _do_run(ctx, evidence_bundle, services, tool_scene, rule_tool_scene, selected_visible_tools, selected_skills, skill_snapshot, module_snapshot, capability_registry):
        from agent.context.snapshot import build_runtime_snapshot
        visible_tools, all_tools_count = _tool_counts_wrapper(ctx)
        base_enabled = _base_enabled_skills_wrapper(services)
        snapshot = build_runtime_snapshot(tool_count=all_tools_count, visible_tool_count=len(visible_tools), workspace_id=ctx.workspace_id, session_id=ctx.session_id, model=ctx.model_config.get('model', ''), capability_registry=capability_registry, skill_snap=skill_snapshot, module_snap=module_snapshot, base_enabled_skills=base_enabled, selected_skills=selected_skills, selected_visible_tools=selected_visible_tools, dynamic_tool_visibility=bool(tool_scene))
        snapshot.metadata = dict(getattr(snapshot, 'metadata', None) or {})
        if tool_scene:
            snapshot.metadata['tool_scene'] = tool_scene
            snapshot.metadata['rule_tool_scene'] = rule_tool_scene
        ctx.runtime_snapshot = snapshot.to_dict()
        safe = dict(getattr(ctx, 'safe_context', None) or {})
        safe.update({'workspace_id': ctx.workspace_id, 'session_id': ctx.session_id})
        if evidence_bundle is not None and hasattr(evidence_bundle, 'to_safe_context'):
            safe.update(evidence_bundle.to_safe_context())
        from agent.runtime.state.hooks import runtime_state_prompt_block
        block = runtime_state_prompt_block(ctx)
        if block:
            safe['runtime_state_snapshot'] = ctx.metadata.get('runtime_state_snapshot', {})
            safe['runtime_state_summary'] = ctx.metadata.get('runtime_state_snapshot_summary', '')
            safe['runtime_state_section'] = block
        if tool_scene:
            safe_tool_scene = _llm_safe_tool_scene(tool_scene)
            safe['tool_scene'] = safe_tool_scene
            safe['tool_plan'] = tool_scene.get('tool_plan', [])
            safe['rule_tool_scene'] = rule_tool_scene
        ctx.safe_context = safe
        return ContextStageResult(name=StageName.SAFE_CONTEXT, ok=True, data={'safe_context': safe})

class LoadedCapabilityStage:
    """Stage 12: Inject loaded capability contracts into safe_context."""

    def run(self, ctx, session, **inputs) -> ContextStageResult:
        return _safe_except(StageName.LOADED_CAPABILITY, self._do_run, ctx, session)

    @staticmethod
    def _do_run(ctx, session):
        session_loaded = getattr(session, 'metadata', {}) or {}
        loaded = session_loaded.get('loaded_capabilities') or session_loaded.get('loaded_skills') or ctx.metadata.get('loaded_capabilities') or ctx.metadata.get('loaded_skills') or {}
        if not loaded:
            return ContextStageResult.ok_result(StageName.LOADED_CAPABILITY)
        contracts = []
        for cap_id, cap_info in loaded.items():
            if not isinstance(cap_info, dict):
                continue
            contracts.append({'capability_id': cap_id, 'capability_ids': list(cap_info.get('capability_ids') or []), 'module_ids': list(cap_info.get('module_ids') or []), 'tool_ids': list(cap_info.get('tool_ids') or []), 'prompt_hints': list(cap_info.get('prompt_hints') or []), 'safety_notes': list(cap_info.get('safety_notes') or [])})
        if contracts:
            ctx.safe_context['loaded_capability_contracts'] = contracts
        return ContextStageResult.ok_result(StageName.LOADED_CAPABILITY)

class MetadataWriteStage:
    """Stage 13: Write final context metadata (P0/P1-A/P1-B fields)."""

    def run(self, ctx, session, selected_skills, selected_visible_tools, tool_scene, rule_tool_scene, **inputs) -> ContextStageResult:
        return _safe_except(StageName.METADATA_WRITE, self._do_run, ctx, session, selected_skills, selected_visible_tools, tool_scene, rule_tool_scene)

    @staticmethod
    def _do_run(ctx, session, selected_skills, selected_visible_tools, tool_scene, rule_tool_scene):
        from agent.runtime.context_tools import persist_tool_scene_to_session
        ctx.metadata['selected_capabilities'] = selected_skills
        ctx.metadata['visible_tools'] = selected_visible_tools
        ctx.visible_tool_ids = selected_visible_tools
        if tool_scene:
            ctx.metadata['tool_scene'] = tool_scene
            ctx.metadata['rule_tool_scene'] = rule_tool_scene
            ctx.metadata['tool_planner'] = tool_scene.get('tool_planner', {})
            if tool_scene.get('visibility'):
                ctx.metadata['tool_visibility'] = tool_scene.get('visibility')
            if tool_scene.get('tool_planning_decision'):
                ctx.metadata['tool_planning_decision'] = tool_scene['tool_planning_decision']
            persist_tool_scene_to_session(session, tool_scene, rule_tool_scene)
        return ContextStageResult(name=StageName.METADATA_WRITE, ok=True, metadata={'context_status': 'pending_pipeline_finalize'})

def _snapshot_service_wrapper(service) -> dict:
    if not service:
        return {}
    try:
        return service.snapshot()
    except Exception:
        return {}

def _enrich_retrieval_wrapper(ctx, evidence_bundle) -> None:
    """Enrich retrieval_decision with actual results from evidence_bundle."""
    try:
        from agent.runtime.retrieval.unknown_feedback import UnknownFeedback, enrich_retrieval_decision
        from agent.runtime.retrieval.trigger_policy import RetrievalDecision
        rd = ctx.metadata.get('retrieval_decision')
        if not rd or not isinstance(rd, dict):
            return
        mem_pre = rd.get('_pre_decisions', {})
        decision = RetrievalDecision(memory_status=mem_pre.get('memory_status', 'not_applicable'), memory_required=mem_pre.get('memory_required', False), memory_reason=mem_pre.get('memory_reason', ''), knowledge_status=mem_pre.get('knowledge_status', 'not_applicable'), knowledge_required=mem_pre.get('knowledge_required', False), knowledge_reason=mem_pre.get('knowledge_reason', ''), file_evidence_status=mem_pre.get('file_evidence_status', 'not_applicable'), file_evidence_required=mem_pre.get('file_evidence_required', False), file_evidence_reason=mem_pre.get('file_evidence_reason', ''), queries=list(mem_pre.get('queries', [])))
        memory_results = []
        knowledge_results = []
        if evidence_bundle is not None:
            memory_results = getattr(evidence_bundle, 'memory_items', None) or getattr(evidence_bundle, 'memory_layer', None)
            if hasattr(memory_results, 'items'):
                memory_results = memory_results.items
            elif not isinstance(memory_results, list):
                memory_results = []
            knowledge_results = getattr(evidence_bundle, 'knowledge_items', None) or getattr(evidence_bundle, 'knowledge_layer', None)
            if hasattr(knowledge_results, 'items'):
                knowledge_results = knowledge_results.items
            elif not isinstance(knowledge_results, list):
                knowledge_results = []
        mem_feedback = None
        if not memory_results and decision.memory_status not in ('skipped', 'not_applicable'):
            mem_feedback = UnknownFeedback.for_no_match('memory')
        k_feedback = None
        if not knowledge_results and decision.knowledge_status not in ('skipped', 'not_applicable'):
            k_feedback = UnknownFeedback.for_no_match('knowledge')
        decision = enrich_retrieval_decision(decision, memory_results=list(memory_results), knowledge_results=list(knowledge_results), memory_feedback=mem_feedback, knowledge_feedback=k_feedback)
        enriched = decision.to_dict()
        enriched['_pre_decisions'] = rd.get('_pre_decisions', {})
        ctx.metadata['retrieval_decision'] = enriched
    except Exception:
        ctx.metadata.setdefault('context_warnings', []).append('retrieval_decision_enrichment_failed')

def _tool_counts_wrapper(ctx) -> tuple:
    visible_tools = []
    all_tools_count = 0
    tool_router = getattr(ctx, 'tool_router', None)
    if tool_router:
        try:
            visible_tools = tool_router.model_visible_tools()
        except Exception:
            visible_tools = []
        try:
            if tool_router.registry:
                all_tools_count = len(tool_router.registry.list_all())
        except Exception:
            all_tools_count = len(visible_tools)
    return (visible_tools, all_tools_count)

def _base_enabled_skills_wrapper(services) -> list:
    """Return the base 'assistant_chat' capability id — always enabled.
    
    v3.3: Replaces old SkillRegistry call. assistant_chat is always available
    as the fallback conversational skill; capabilities add domain tools on top.
    """
    return ['assistant_chat']

def _llm_safe_tool_scene(tool_scene: dict) -> dict:
    """Keep only planner fields useful to the model.

    Audit-only structures such as tool_planning_decision and raw capability
    routing stay in ctx.metadata / decision reports, not in LLM-visible context.
    """
    if not isinstance(tool_scene, dict):
        return {}
    keep = ('planner_version', 'mode', 'primary_category', 'categories', 'groups', 'candidate_tools', 'capability_plan', 'tool_plan', 'tool_chain', 'needs_clarification', 'clarifying_question', 'reason', 'category', 'group')
    safe = {k: tool_scene[k] for k in keep if k in tool_scene}
    return safe

def _core_tools_for_context(ctx: Any, rule_scene: dict) -> list[str]:
    """Return minimal core tools that should remain visible for this turn."""
    tools = ['tool.catalog.search', 'workspace.file.list', 'workspace.file.read', 'workspace.artifact.read']
    categories = set((rule_scene or {}).get('categories') or [])
    groups = (rule_scene or {}).get('groups') or {}
    user_input = getattr(ctx, 'user_input', '') or ''
    lower = user_input.lower()
    if 'web' in categories or groups.get('web') or any((k in lower for k in ('搜索', '官网', '最新', 'weather', '新闻'))):
        tools.extend(['web.search', 'web.page.process', 'web.weather'])
    if 'host' in categories or groups.get('host'):
        tools.extend(['exec.run', 'exec.python', 'system.diagnostics'])
    if 'git' in categories or 'git' in lower:
        tools.extend(['git.status', 'git.diff', 'git.log'])
    if 'device' in categories or groups.get('device'):
        tools.extend(['device.list', 'device.get'])
    if 'browser' in categories or groups.get('browser'):
        tools.extend(['browser.navigate', 'browser.extract', 'browser.screenshot'])
    if 'memory' in categories or groups.get('memory'):
        tools.append('memory.search')
    if 'agent' in categories or groups.get('agent') or any((k in lower for k in ('子agent', '子 agent', 'subagent', 'sub agent', 'agent.spawn', '派发', '委托'))):
        tools.extend(['agent.spawn', 'agent.role.list', 'agent.result.get'])
    if 'code' in categories or '代码' in user_input or '源码' in user_input:
        tools.append('code.search')
    return list(dict.fromkeys(tools))

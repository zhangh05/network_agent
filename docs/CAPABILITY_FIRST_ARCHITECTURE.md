# Capability-first Architecture

This document defines the execution architecture after the Skill / Module / Tool / Prompt refactor.

## 1. Execution Chain

The runtime execution chain is:

```text
UserInput
  -> TurnContext
  -> SceneDecision
  -> RuntimeState / TaskWorkflow
  -> EvidencePipeline
  -> CapabilityRouter
  -> SkillManifest / CapabilityPackage
  -> ModuleServiceManifest
  -> ToolBundle
  -> ToolPlannerV2
  -> PromptArchitecture
  -> ActionExecutionKernel
  -> Output / Response / Memory / Observability / Truth / Stability
```

## 2. Skill

A Skill is a user-facing business capability entry.

In this architecture, a Skill is backed by a CapabilityPackage-derived SkillManifest.

A Skill:

- selects a business capability;
- declares related capability_ids;
- declares related module_ids;
- declares currently allowed tool_ids;
- may provide prompt_hints and safety_notes;
- does not own business logic;
- does not expose SKILL.md prompt bodies;
- does not inject long prompt text;
- does not execute tools directly.

Current built-in skills are generated from CapabilityPackage manifests.

## 3. CapabilityPackage

A CapabilityPackage is the internal business capability declaration.

It defines:

- capability_id;
- display_name;
- description;
- intent keywords;
- module_ids;
- tool_ids;
- prompt_hints;
- safety_notes;
- output_kinds;
- priority.

CapabilityPackage is selected before tool planning.

It limits the active tool set for the current turn.

## 4. Module

A Module is an implementation service behind tools.

Modules are not directly callable by the LLM and are not directly selected by the planner.

There are two module classes.

### 4.1 Business Module

Business modules own domain logic.

Current business modules are:

- config_translation
- config_analysis
- pcap_analysis

### 4.2 Platform Service

Platform services provide infrastructure for business execution.

Current platform services are:

- workspace
- knowledge
- memory
- artifact
- runtime
- report
- web

Platform services are not business modules.

## 5. Tool

A Tool is a callable adapter exposed to the planner and action execution layer.

Tools do not own business logic.

Tools call module services.

There are two tool classes.

### 5.1 Directory-level Tool

Directory-level tools are preferred LLM-visible business tools.

Current directory-level business tools are:

- config.analysis.run
- pcap.analysis.run

They dispatch to module-internal operations through an action argument.

## 6. Tool Visibility

ToolPlannerV2 must not default to the full TOOL_NAMESPACE.

The default tool catalog is built by active_tool_catalog().

Each turn receives a small ToolBundle.

The ToolBundle contains:

- core tools;
- selected capability tools;
- capability metadata;
- module metadata;
- a hard tool limit.

Current tool limit is 12.

## 7. Prompt Architecture

System prompt is capability-first.

The prompt is assembled from:

1. System Contract
2. Runtime State Block
3. Capability Context Block
4. Evidence Context Block
5. Active Tool Contract Block

The system prompt must not include:

- full tool catalog;
- SKILL.md bodies;
- skill_prompt;
- internal fine-grained tools;
- raw unfiltered evidence.

The prompt must state:

- Skill = CapabilityPackage manifest / business entry;
- Business Modules = config_translation, config_analysis, pcap_analysis;
- Platform Services = workspace, knowledge, memory, artifact, runtime, report, web;
- Tool = callable adapter;
- directory-level tools are preferred;

## 8. Registry Boundary

canonical_registry.py must remain a thin adapter layer.

It may contain:

- ToolSpec registration;
- input schema;
- handler binding;
- thin handler adapters.

It must not contain:

- business parsing logic;
- PCAP analysis logic;
- config translation logic;
- prompt assembly logic;
- capability routing logic.

## 9. Non-goals

The goal is not to expose more tools.

The goal is to expose fewer, better-scoped tools.

## 10. Invariants

These invariants must be protected by tests:

- SkillManifest contains no prompt body.
- CapabilityPackage is the source of built-in skills.
- Business modules are only config_translation, config_analysis, and pcap_analysis.
- Platform services are not business modules.
- Directory-level business tools are config.analysis.run and pcap.analysis.run.
- Prompt does not include full tool catalog.
- Prompt does not include skill_prompt.
- ToolPlannerV2 does not default to list(TOOL_NAMESPACE).

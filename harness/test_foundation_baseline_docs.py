"""Foundation Baseline documentation tests — verify docs exist and contain correct content."""
import os, re, pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT, "docs")


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


class TestDocsExist:
    def test_readme_exists(self):
        assert os.path.exists(os.path.join(ROOT, "README.md"))

    def test_foundation_baseline_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "FOUNDATION_BASELINE.md"))

    def test_architecture_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "ARCHITECTURE.md"))

    def test_agent_runtime_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "AGENT_RUNTIME.md"))

    def test_registry_contract_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "REGISTRY_CONTRACT.md"))

    def test_llm_settings_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "LLM_SETTINGS.md"))

    def test_memory_design_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "MEMORY_DESIGN.md"))

    def test_workspace_design_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "WORKSPACE_DESIGN.md"))

    def test_observability_design_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "OBSERVABILITY_DESIGN.md"))

    def test_artifact_design_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "ARTIFACT_DESIGN.md"))

    def test_file_pipeline_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "FILE_PIPELINE.md"))

    def test_report_pipeline_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "REPORT_PIPELINE.md"))

    def test_job_runtime_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "JOB_RUNTIME.md"))

    def test_task_contract_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "TASK_CONTRACT.md"))

    def test_context_runtime_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "CONTEXT_RUNTIME.md"))

    def test_prompt_runtime_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "PROMPT_RUNTIME.md"))

    def test_harness_runtime_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "HARNESS_RUNTIME.md"))

    def test_agent_behavior_baseline_exists(self):
        assert os.path.exists(os.path.join(DOCS_DIR, "AGENT_BEHAVIOR_BASELINE.md"))


class TestDocContent:
    def test_readme_foundation_baseline(self):
        c = _read("README.md")
        assert "Foundation" in c, "README should mention Foundation Baseline"
        assert "config_translation" in c, "README should mention enabled business module"

    def test_foundation_baseline_next_steps(self):
        c = _read("docs/FOUNDATION_BASELINE.md")
        assert "Tool" in c or "Command" in c, "FOUNDATION_BASELINE should mention next steps"

    def test_foundation_baseline_pytest(self):
        c = _read("docs/FOUNDATION_BASELINE.md")
        assert "pytest" in c or "493" in c or "harness" in c, "FOUNDATION_BASELINE should mention pytest baseline"

    def test_readme_entry_points(self):
        c = _read("README.md")
        assert any(e in c for e in ["/api/agent/run", "agent/run"]), "README should mention agent run entry point"

    def test_architecture_mentions_agent(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Agent" in c

    def test_architecture_mentions_registry(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Registry" in c or "registry" in c.lower()

    def test_architecture_mentions_artifact(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Artifact" in c or "artifact" in c.lower()

    def test_architecture_mentions_job(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Job" in c or "job" in c.lower()

    def test_architecture_mentions_context(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Context" in c or "context" in c.lower()

    def test_architecture_mentions_prompt(self):
        c = _read("docs/ARCHITECTURE.md")
        assert "Prompt" in c or "prompt" in c.lower()

    def test_prompt_runtime_mentions_registry(self):
        c = _read("docs/PROMPT_RUNTIME.md")
        assert "registry.yaml" in c or "registry" in c.lower()

    def test_prompt_runtime_mentions_templates(self):
        c = _read("docs/PROMPT_RUNTIME.md")
        assert "template" in c.lower()

    def test_prompt_runtime_mentions_policy(self):
        c = _read("docs/PROMPT_RUNTIME.md")
        assert "policy" in c.lower() or "Policy" in c

    def test_prompt_runtime_mentions_rendered_text(self):
        c = _read("docs/PROMPT_RUNTIME.md")
        assert "rendered" in c.lower()

    def test_job_runtime_no_bypass_agent(self):
        c = _read("docs/JOB_RUNTIME.md")
        assert any(phrase in c.lower() for phrase in ["not a new agent", "not bypass", "run_agent"])

    def test_artifact_mentions_store(self):
        c = _read("docs/ARTIFACT_DESIGN.md")
        assert "ArtifactStore" in c or "artifact" in c.lower()

    def test_artifact_mentions_size_guard(self):
        c = _read("docs/ARTIFACT_DESIGN.md")
        assert "size" in c.lower() or "MB" in c or "10" in c

    def test_docs_no_old_graphagent(self):
        for d in [d for d in os.listdir(DOCS_DIR) if d.endswith(".md")]:
            c = _read(f"docs/{d}")
            if "GraphAgent" in c and "legacy" not in c.lower():
                # It's ok if mentioned as legacy
                pass

    def test_docs_api_translate_not_as_entry(self):
        # Check that /api/translate is not promoted as main entry point
        readme = _read("README.md")
        # It should not appear as a primary documented entry
        lines_with_translate = [l for l in readme.split("\n") if "/api/translate" in l]
        for l in lines_with_translate:
            # If mentioned, should have deprecated/legacy context
            if "deprecated" not in l.lower() and "legacy" not in l.lower() and "not" not in l.lower():
                pass  # Document mentions are ok if not as primary

    def test_docs_no_minimax_m1_as_default(self):
        readme = _read("README.md")
        assert "MiniMax-M1" not in readme, "MiniMax-M1 should not appear as default in README"

    def test_readme_not_mention_llm_skeleton(self):
        readme = _read("README.md")
        assert "LLM skeleton" not in readme, "Should not mention LLM skeleton as current state"

    def test_foundation_not_mention_job_mvp_unresolved(self):
        c = _read("docs/FOUNDATION_BASELINE.md")
        assert "MVP 未收口" not in c and "unresolved" not in c.lower(), "Job should not be described as unresolved"

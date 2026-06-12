import pathlib

OLD = "https://api.minimax.com/v1"
NEW = "https://api.minimaxi.com/v1"

files = [
    "config/LLM_setting.json",
    "config/LLM_setting.example.json",
    "config/llm.yaml",
    "config/llm.example.yaml",
    "config/llm.local.yaml",
    "agent/llm/settings.py",
    "agent/llm/provider.py",
    "frontend/src/pages/Settings/Settings.tsx",
    "frontend/src/test/settingsLlm.test.tsx",
    "harness/test_llm_runtime_diagnostics_consistency_v051.py",
    "harness/test_assistant_chat_llm_path_completion.py",
    "harness/test_platform_runtime_closure_v02.py",
    "harness/test_llm_settings_runtime_wiring.py",
    "harness/test_llm_provider_diagnostics_v05.py",
]

for path in files:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  [skip] {path} (not found)")
        continue
    text = p.read_text()
    count = text.count(OLD)
    if count == 0:
        print(f"  [skip] {path} (no match)")
        continue
    p.write_text(text.replace(OLD, NEW))
    print(f"  [ok]   {path}  ({count} 处替换)")
import pytest


def test_translation_tool_schema_accepts_workspace_file_path():
    from agent.modules.config_translation.tools import TOOL_CONFIG_TRANSLATION

    schema = TOOL_CONFIG_TRANSLATION.input_schema
    assert "filepath" in schema["properties"]
    assert "source_config" not in schema.get("required", [])
    assert "target_vendor" in schema.get("required", [])


def test_load_source_config_reads_workspace_file(monkeypatch, tmp_path):
    from agent.modules.config_translation import tools
    import tool_runtime.path_security as path_security

    workspace_root = tmp_path / "workspaces"
    config_path = workspace_root / "ws1" / "files" / "upload" / "f_1" / "content" / "device.txt"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("sysname H3C-EDGE\ninterface GigabitEthernet1/0/1\n", encoding="utf-8")
    monkeypatch.setattr(path_security, "WS_ROOT", workspace_root)

    content, error = tools._load_source_config(
        source_config="",
        filepath="files/upload/f_1/content/device.txt",
        workspace_id="ws1",
    )

    assert error == ""
    assert content.startswith("sysname H3C-EDGE")


def test_load_source_config_rejects_path_escape():
    from agent.modules.config_translation import tools

    with pytest.raises(ValueError, match="path_escape_denied"):
        tools._load_source_config(
            source_config="",
            filepath="../outside.txt",
            workspace_id="default",
        )


def test_skill_adapter_rejects_path_escape():
    from skills.config_translation.adapter import translate

    result = translate({
        "filepath": "../outside.txt",
        "workspace_id": "default",
        "target_vendor": "cisco",
    })

    assert result["ok"] is False
    assert "path_escape_denied" in result["error"]

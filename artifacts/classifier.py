# artifacts/classifier.py
"""Artifact classifier — determine artifact_type, sensitivity, tags from content."""

import re


def classify_file(path: str = "", content: str = "") -> dict:
    """Classify a file's artifact_type, sensitivity, and tags. Returns dict."""
    result = {
        "artifact_type": "unknown",
        "mime_type": "text/plain",
        "file_ext": "",
        "sensitivity": "internal",
        "probable_vendor": "",
        "line_count": 0,
        "contains_secret": False,
        "tags": [],
    }

    if path:
        result["file_ext"] = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        ext = result["file_ext"]
        result["mime_type"] = _ext_mime(ext)

    if content:
        from artifacts.redaction import contains_secret
        lines = content.strip().split("\n")
        result["line_count"] = len(lines)
        result["contains_secret"] = contains_secret(content)
        result["probable_vendor"] = _guess_vendor(content)

        # Config detection
        if re.search(r'(hostname|interface|ip address|router|switch)', content, re.I):
            result["artifact_type"] = "input_config"
            result["sensitivity"] = "sensitive"
            result["tags"].append("config")

        # Topology JSON
        if re.search(r'"[nodes"]\s*:\s*\[', content) or re.search(r'"[links"]\s*:\s*\[', content):
            result["artifact_type"] = "topology_json"
            result["tags"].append("topology")

        # Log detection
        if re.search(r'(show\s|display\s|WARNING|ERROR|INFO)', content, re.I) and len(lines) > 10:
            result["artifact_type"] = "inspection_log"
            result["tags"].append("log")

        # Output config
        if re.search(r'deployable_config|translation_output', content, re.I):
            result["artifact_type"] = "output_config"
            result["sensitivity"] = "sensitive"

        # Secret override
        if result["contains_secret"]:
            result["sensitivity"] = "secret"

    return result


def _ext_mime(ext: str) -> str:
    m = {
        "json": "application/json", "yaml": "text/yaml", "yml": "text/yaml",
        "cfg": "text/plain", "conf": "text/plain", "txt": "text/plain",
        "svg": "image/svg+xml", "png": "image/png",
        "md": "text/markdown", "pdf": "application/pdf", "docx": "application/docx",
        "log": "text/plain", "csv": "text/csv",
    }
    return m.get(ext, "text/plain")


def _guess_vendor(content: str) -> str:
    if re.search(r'interface\s+GigabitEthernet|interface\s+FastEthernet|^router\s+(ospf|bgp|eigrp)', content, re.I | re.M):
        return "cisco"
    if re.search(r'interface\s+\S+-GigabitEthernet|interface\s+\S+-GE|sysname|vlan\s+batch', content, re.I):
        return "huawei"
    if re.search(r'interface\s+.\S+GE|sysname', content, re.I):
        return "h3c"
    return ""

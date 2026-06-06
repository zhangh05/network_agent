"""MiniMax Live Acceptance Test — verify LLM connectivity and safety."""

import json, os, sys, urllib.request, urllib.error

BASE = "http://127.0.0.1:8010"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_MD = os.path.join(ROOT, "reports", "MINIMAX_LIVE_ACCEPTANCE.md")
REPORT_JSON = os.path.join(ROOT, "reports", "minimax_live_acceptance.json")

def _get(p):
    with urllib.request.urlopen(f"{BASE}{p}", timeout=10) as r:
        return json.loads(r.read().decode())

def _post(p, b):
    d = json.dumps(b).encode()
    r = urllib.request.Request(f"{BASE}{p}", data=d, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode())

def redact(s):
    return s[:100] if s else ""

def main():
    results = {"key_loaded": False, "key_source": "none", "llm_connected": False,
               "llm_test_ok": False, "agent_translate_ok": False, "llm_used_in_translate": False,
               "context_qa_ok": False, "security_audit_ok": False, "key_leak_found": False,
               "deployable_modified_by_llm": False, "manual_review_hidden": False}

    print("=" * 50)
    print("MiniMax Live Acceptance Test")
    print("=" * 50)

    # 1. Key & LLM status
    try:
        s = _get("/api/agent/llm/status")
        results["key_loaded"] = s.get("key_loaded", False)
        results["key_source"] = s.get("key_source", "none")
        results["llm_connected"] = s.get("connected", False)
        print(f"[STATUS] enabled={s.get('enabled')} connected={s.get('connected')} key_loaded={s.get('key_loaded')} key_source={s.get('key_source')}")
        # Verify key not leaked
        raw = json.dumps(s).lower()
        results["key_leak_found"] = "sk-" in raw and len(raw.split("sk-")[1].split('"')[0]) > 20
        if results["key_leak_found"]:
            print("[FAIL] Key leaked in status response!")
    except Exception as e:
        print(f"[FAIL] LLM status error: {redact(str(e))}")

    # 2. LLM test
    if results["llm_connected"]:
        try:
            t = _post("/api/agent/llm/test", {"task": "result_summarize", "message": "请用一句话回复：LLM 连接正常"})
            results["llm_test_ok"] = t.get("llm_used", False)
            print(f"[TEST] llm_used={t.get('llm_used')} policy_pass={t.get('policy_pass')} response={t.get('response','')[:80]}")
        except Exception as e:
            print(f"[FAIL] LLM test error: {redact(str(e))}")
    else:
        print("[SKIP] LLM not connected, skipping live test")

    # 3. Agent translate
    SAMPLE = "interface Gi0/1\n ip address 10.1.1.1 255.255.255.0\n no shutdown\n"
    try:
        a = _post("/api/agent/run", {"message": "翻译这份Cisco配置","payload": {"source_config": SAMPLE, "source_vendor": "cisco", "target_vendor": "huawei"}, "workspace_id": "default"})
        results["agent_translate_ok"] = a.get("ok", False)
        llm = a.get("llm", {})
        results["llm_used_in_translate"] = llm.get("used", False)
        dc = a.get("result", {}).get("deployable_config", "")
        results["deployable_modified_by_llm"] = "LLM" in dc or "AI" in dc
        results["manual_review_hidden"] = "manual_review" not in a.get("result", {})
        print(f"[TRANSLATE] ok={a.get('ok')} llm_used={llm.get('used')} provider={llm.get('provider')} deployable_lines={len(dc.split(chr(10)))}")
    except Exception as e:
        print(f"[FAIL] Translate error: {redact(str(e))}")

    # 4. Context QA
    try:
        cq = _post("/api/agent/run", {"message": "刚才的结果有什么需要人工复核？", "workspace_id": "default", "context_ref": "last_result"})
        results["context_qa_ok"] = cq.get("ok", False)
        print(f"[QA] ok={cq.get('ok')} intent={cq.get('intent')} response={cq.get('final_response','')[:80]}")
    except Exception as e:
        print(f"[FAIL] Context QA error: {redact(str(e))}")

    # 5. Security audit
    try:
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "audit_llm_security.py")], cwd=ROOT, capture_output=True, text=True)
        results["security_audit_ok"] = r.returncode == 0
        print(f"[AUDIT] passed={r.returncode==0}")
    except Exception as e:
        print(f"[FAIL] Audit error: {e}")

    # Write reports
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    with open(REPORT_JSON, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    md = f"""# MiniMax Live Acceptance Report

| Test | Result |
|------|--------|
| key_loaded | {results['key_loaded']} |
| key_source | {results['key_source']} |
| llm_connected | {results['llm_connected']} |
| llm_test_ok | {results['llm_test_ok']} |
| agent_translate_ok | {results['agent_translate_ok']} |
| llm_used_in_translate | {results['llm_used_in_translate']} |
| context_qa_ok | {results['context_qa_ok']} |
| security_audit_ok | {results['security_audit_ok']} |
| key_leak_found | {results['key_leak_found']} |
| deployable_modified_by_llm | {results['deployable_modified_by_llm']} |
| manual_review_hidden | {results['manual_review_hidden']} |

"""
    with open(REPORT_MD, "w") as f:
        f.write(md)

    print(f"\nReports: {REPORT_MD}, {REPORT_JSON}")
    all_pass = results["llm_connected"] and results["llm_test_ok"] and results["agent_translate_ok"] and results["security_audit_ok"]
    print(f"\n{'PASS' if all_pass else 'PARTIAL'} (connected={results['llm_connected']} translate={results['agent_translate_ok']} audit={results['security_audit_ok']})")
    sys.exit(0 if all_pass else 1)

if __name__ == "__main__":
    main()

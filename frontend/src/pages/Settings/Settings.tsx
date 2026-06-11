import { useEffect, useState } from "react";
import { settingsApi } from "../../api";
import { Badge, EmptyState, InlineCode, LoadingState } from "../../components/common";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";

interface LlmConfig {
  provider: string;
  model: string;
  base_url: string;
}

/**
 * Settings — only LLM config (read-only view + update form).
 * Strict: no business logic, no hardcoded values.
 */
export function Settings() {
  const toast = useToastStore((s) => s.show);
  const [data, setData] = useState<LlmConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<LlmConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    settingsApi
      .llmConfig()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setDraft(d);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(isApiError(e) ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    try {
      await settingsApi.updateLlmConfig(draft);
      setData(draft);
      toast({ kind: "success", title: "LLM 配置已更新" });
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "保存失败",
        body: isApiError(e) ? e.message : String(e),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{ display: "flex", flexDirection: "column", height: "100%" }}
      data-testid="page-settings"
    >
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <div className="subtitle">LLM provider 配置（仅展示后端实际字段）</div>
        </div>
      </div>
      <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
        {loading && <LoadingState />}
        {error && (
          <div className="text-sm" style={{ color: "var(--danger)" }}>
            {error}
          </div>
        )}
        {!loading && !error && !data && (
          <EmptyState text="后端未返回 LLM 配置" />
        )}
        {!loading && !error && data && (
          <div className="card" style={{ maxWidth: 480 }}>
            <div className="card-title">LLM Provider</div>
            <Field
              label="provider"
              value={draft?.provider ?? ""}
              onChange={(v) => setDraft((d) => d && { ...d, provider: v })}
            />
            <Field
              label="model"
              value={draft?.model ?? ""}
              onChange={(v) => setDraft((d) => d && { ...d, model: v })}
            />
            <Field
              label="base_url"
              value={draft?.base_url ?? ""}
              onChange={(v) => setDraft((d) => d && { ...d, base_url: v })}
            />
            <div className="row-flex mt-2">
              <Badge kind="pri">read from /api/agent/llm/config</Badge>
              <span className="spacer" />
              <button
                type="button"
                className="btn primary"
                disabled={saving || !draft}
                onClick={onSave}
                data-testid="btn-save-llm"
              >
                {saving ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        )}
        {!loading && !error && data && (
          <div className="text-xs muted mt-2">
            <InlineCode>GET /api/agent/llm/config</InlineCode> ·{" "}
            <InlineCode>POST /api/agent/llm/config</InlineCode>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="mb-2">
      <label
        className="text-xs muted"
        style={{ display: "block", marginBottom: 4 }}
      >
        {label}
      </label>
      <input
        className="input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`field-${label}`}
      />
    </div>
  );
}

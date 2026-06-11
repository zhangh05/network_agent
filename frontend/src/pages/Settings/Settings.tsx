import { useEffect, useState } from "react";
import { settingsApi } from "../../api";
import { Badge, EmptyState, InlineCode, LoadingState } from "../../components/common";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import { IconKey, IconSettings } from "../../components/Icon";

interface LlmConfig {
  provider?: string;
  model?: string;
  base_url?: string;
  [k: string]: unknown;
}

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
    <div className="page" data-testid="page-settings">
      <div className="page-header">
        <div>
          <h1>
            系统设置{" "}
            <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
              · Settings
            </span>
          </h1>
          <div className="subtitle">LLM provider 配置（仅展示后端实际字段）</div>
        </div>
      </div>
      <div className="page-body">
        {loading && <LoadingState />}
        {error && (
          <div
            className="card"
            style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
          >
            {error}
          </div>
        )}
        {!loading && !error && !data && <EmptyState text="后端未返回 LLM 配置" />}
        {!loading && !error && data && (
          <>
            <div className="card" style={{ maxWidth: 540 }}>
              <div className="card-title">
                <IconKey size={11} /> LLM Provider
              </div>
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
              <div className="row-flex mt-3" style={{ gap: 8 }}>
                <Badge kind="accent" withDot>
                  已连接 /api/agent/llm/config
                </Badge>
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
            <div className="text-xs muted mt-3 row-flex" style={{ gap: 6 }}>
              <IconSettings size={11} />
              <InlineCode>GET /api/agent/llm/config</InlineCode>
              <span>·</span>
              <InlineCode>POST /api/agent/llm/config</InlineCode>
            </div>
          </>
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
    <div style={{ marginBottom: 14 }}>
      <label
        style={{
          display: "block",
          marginBottom: 4,
          fontSize: 11,
          color: "var(--ink-mute)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
        }}
      >
        {label}
      </label>
      <input
        className="input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`field-${label}`}
        spellCheck={false}
        autoComplete="off"
      />
    </div>
  );
}

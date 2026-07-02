/**
 * Settings — LLM Provider configuration (v2).
 *
 * Layout: left provider sidebar (cards) → right form panel.
 * Each provider has its own config file; click to edit, "应用" to activate.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { settingsApi } from "../../api";
import { EmptyState, LoadingState } from "../../components/common";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { ProviderConfig, LlmTestResult } from "../../types";
import { sanitizeAssistantText } from "../../utils/displayText";
import { formatDate } from "../../utils/format";

/* ──────────────────────── Provider Presets ──────────────────────── */

interface ProviderPreset {
  id: string;
  label: string;
  base_url: string;
  model: string;
  hint: string;
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  { id: "minimax", label: "MiniMax", base_url: "https://api.minimaxi.com/v1", model: "MiniMax-M3", hint: "api.minimaxi.com" },
  { id: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", hint: "api.deepseek.com" },
  { id: "ark", label: "方舟 (豆包)", base_url: "https://ark.cn-beijing.volces.com/api/coding/v3", model: "ark-code-latest", hint: "ark.volces.com" },
  { id: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", hint: "api.openai.com" },
  { id: "anthropic", label: "Anthropic", base_url: "https://api.anthropic.com/v1", model: "claude-3-haiku-20240307", hint: "api.anthropic.com" },
  { id: "ollama", label: "Ollama (本地)", base_url: "http://localhost:11434/v1", model: "llama3.1", hint: "localhost:11434" },
  { id: "custom", label: "自定义", base_url: "", model: "", hint: "OpenAI 兼容 API" },
];

const presetMap = new Map(PROVIDER_PRESETS.map((p) => [p.id, p]));

/* ──────────────────────── Settings Page ──────────────────────── */

export function Settings() {
  const toast = useToastStore((s) => s.show);
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);

  // ── State ──
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<ProviderConfig> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [apiKeyRevealed, setApiKeyRevealed] = useState(false);
  const [clearKeyOnSave, setClearKeyOnSave] = useState(false);
  const aliveRef = useRef(true);

  // ── Workspace settings (memory_gating) ──
  const [memoryGating, setMemoryGating] = useState<boolean>(false);
  const [memoryGatingLoading, setMemoryGatingLoading] = useState(false);
  const [memoryGatingLoaded, setMemoryGatingLoaded] = useState(false);

  // ── Load workspace settings on mount ──
  useEffect(() => {
    let alive = true;
    if (!currentWorkspaceId) {
      setMemoryGatingLoaded(true);
      return () => { alive = false; };
    }
    setMemoryGatingLoaded(false);
    settingsApi.workspaceSettings(currentWorkspaceId)
      .then((res) => {
        if (!alive) return;
        const mode = String(res?.workspace?.memory_gating ?? "rule_only");
        setMemoryGating(mode === "llm_first");
        setMemoryGatingLoaded(true);
      })
      .catch(() => {
        // If endpoint unavailable (pre-update backend), default to off
        if (alive) setMemoryGatingLoaded(true);
      });
    return () => { alive = false; };
  }, [currentWorkspaceId]);

  // ── Load on mount ──
  useEffect(() => {
    aliveRef.current = true;
    setLoading(true);
    settingsApi.providersList()
      .then((res) => {
        if (!aliveRef.current) return;

        // Guard: old backend (no new /providers endpoint) may return a 404 HTML page
        // or an unexpected shape. Tolerate gracefully.
        const list = Array.isArray(res?.providers) ? res.providers : [];
        const active = res?.active ?? "";

        if (list.length === 0) {
          // Fallback: build provider list from presets if API returns empty/malformed
          throw new Error("未获取到厂商列表，请检查 LLM 服务是否正常启动");
        }

        setProviders(list);
        setActiveId(active);
        const act = list.find((p) => p.is_active) ?? list[0];
        if (act) {
          setSelectedId(act.provider);
          setDraft({ ...act });
        }
      })
      .catch((e: unknown) => {
        if (!aliveRef.current) return;
        setError(isApiError(e) ? e.message : String(e));
      })
      .finally(() => {
        if (aliveRef.current) setLoading(false);
      });
    return () => { aliveRef.current = false; };
  }, []);

  // ── Select provider → load its config ──
  const selectProvider = useCallback(async (providerId: string) => {
    setSelectedId(providerId);
    setTestResult(null);
    setApiKeyDirty(false);
    setApiKeyDraft("");
    setClearKeyOnSave(false);
    setApiKeyRevealed(false);

    // Check local cache first
    const cached = providers.find((p) => p.provider === providerId);
    if (cached) {
      setDraft({ ...cached });
      return;
    }
    // Fetch from server
    try {
      const res = await settingsApi.providerGet(providerId);
      setDraft({ ...res.config });
    } catch {
      // Fallback to preset
      const preset = presetMap.get(providerId);
      if (preset) {
        setDraft({
          provider: preset.id,
          label: preset.label,
          enabled: false,
          base_url: preset.base_url,
          model: preset.model,
          temperature: 0.2,
          max_tokens: 1200,
          safe_mode: true,
          key_configured: false,
          is_active: false,
        });
      }
    }
  }, [providers]);

  // ── Refresh single provider in list ──
  const refreshProvider = useCallback((config: ProviderConfig) => {
    setProviders((prev) =>
      prev.map((p) => (p.provider === config.provider
        ? { ...config, api_key: undefined } // never store key in state
        : p))
    );
    setActiveId(config.is_active ? config.provider : activeId);
  }, [activeId]);

  // ── Actions ──

  async function onSave() {
    if (!draft || !selectedId) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        enabled: draft.enabled,
        base_url: draft.base_url,
        model: draft.model,
        temperature: draft.temperature,
        max_tokens: draft.max_tokens,
        safe_mode: draft.safe_mode,
      };
      if (apiKeyDirty) {
        if (clearKeyOnSave) payload.clear_api_key = true;
        else if (apiKeyDraft) payload.api_key = apiKeyDraft;
      }
      const res = await settingsApi.providerSave(selectedId, payload);
      refreshProvider(res.config);
      setDraft({ ...res.config });
      setApiKeyDirty(false);
      setApiKeyDraft("");
      setClearKeyOnSave(false);
      setApiKeyRevealed(false);
      toast({ kind: "success", title: `${draft.label ?? selectedId} 配置已保存` });
    } catch (e: unknown) {
      toast({ kind: "error", title: "保存失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  async function onApply() {
    if (!draft || !selectedId) return;
    setApplying(true);
    try {
      const payload: Record<string, unknown> = {
        enabled: draft.enabled,
        base_url: draft.base_url,
        model: draft.model,
        temperature: draft.temperature,
        max_tokens: draft.max_tokens,
        safe_mode: draft.safe_mode,
      };
      if (apiKeyDirty) {
        if (clearKeyOnSave) payload.clear_api_key = true;
        else if (apiKeyDraft) payload.api_key = apiKeyDraft;
      }
      const res = await settingsApi.llmActivate(selectedId, payload);
      refreshProvider(res.config);
      setDraft({ ...res.config });
      setActiveId(selectedId);
      setApiKeyDirty(false);
      setApiKeyDraft("");
      setClearKeyOnSave(false);
      setApiKeyRevealed(false);
      toast({ kind: "success", title: res.message ?? `已切换到 ${draft.label ?? selectedId}` });
    } catch (e: unknown) {
      toast({ kind: "error", title: "应用失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setApplying(false);
    }
  }

  async function onTest() {
    if (!draft || !selectedId) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await settingsApi.llmTest({
        task: "result_summarize",
        message: "ping from settings UI",
        base_url: draft.base_url ?? undefined,
        model: draft.model ?? undefined,
        provider: selectedId,
        api_key: apiKeyDirty ? (clearKeyOnSave ? undefined : (apiKeyDraft || undefined)) : undefined,
      });
      setTestResult(res);
      toast({
        kind: res.llm_used ? "success" : "warning",
        title: res.llm_used ? "LLM 可用" : "LLM 不可用",
        body: res.fallback_reason ? `fallback_reason=${res.fallback_reason}` : `model=${res.model ?? "?"}`,
      });
    } catch (e: unknown) {
      toast({ kind: "error", title: "测试请求失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }

  async function onReset() {
    if (!selectedId) return;
    const label = draft?.label ?? selectedId;
    if (!window.confirm(`确认重置 ${label} 配置？将恢复为默认值。`)) return;
    setSaving(true);
    try {
      await settingsApi.providerDelete(selectedId);
      const res = await settingsApi.providerGet(selectedId);
      refreshProvider(res.config);
      setDraft({ ...res.config });
      setApiKeyDirty(false);
      setApiKeyDraft("");
      setClearKeyOnSave(false);
      setTestResult(null);
      toast({ kind: "success", title: `${label} 已重置为默认配置` });
    } catch (e: unknown) {
      toast({ kind: "error", title: "重置失败", body: isApiError(e) ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  // ── Memory gating toggle ──
  async function onMemoryGatingToggle(enabled: boolean) {
    if (!currentWorkspaceId) {
      toast({ kind: "warning", title: "未选择工作区", body: "请先在左侧选择工作区" });
      return;
    }
    setMemoryGatingLoading(true);
    const newMode = enabled ? "llm_first" : "rule_only";
    try {
      await settingsApi.updateWorkspaceSettings({ memory_gating: newMode }, currentWorkspaceId);
      setMemoryGating(enabled);
      toast({
        kind: "success",
        title: enabled ? "已启用 LLM 记忆门控" : "已切换为纯规则记忆门控",
      });
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "设置失败",
        body: isApiError(e) ? e.message : String(e),
      });
    } finally {
      setMemoryGatingLoading(false);
    }
  }
  const selectedPreset = selectedId ? presetMap.get(selectedId) : null;
  const isActiveProvider = selectedId === activeId;
  const isBusy = saving || applying || testing;

  // ── Render states ──

  if (loading) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body"><LoadingState /></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body">
          <div className="card" style={{ borderColor: "var(--danger)", color: "var(--danger)" }}>{error}</div>
        </div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body"><EmptyState text="后端未返回 LLM 配置" /></div>
      </div>
    );
  }

  return (
    <div className="page" data-testid="page-settings">
      <PageHeader activeId={activeId} />
      <div className="page-body no-pad">
        <details style={{ margin: "0 0 4px", fontSize: "var(--fs-12)", color: "var(--text-3)", padding: "0 16px" }}>
          <summary style={{ cursor: "pointer", fontWeight: 680 }}>💡 使用帮助</summary>
          <div style={{ marginTop: 4, padding: "8px 12px", background: "var(--surface-2)", borderRadius: "var(--r-6)", lineHeight: 1.6 }}>
            左侧选择 LLM 厂商 → 填写 API Key 和参数 → 保存生效。支持 DeepSeek、OpenAI、Claude 等。
          </div>
        </details>
        <div className="settings-layout">
          {/* ── Left: Provider sidebar ── */}
          <aside className="provider-sidebar" data-testid="provider-sidebar">
            <div className="provider-sidebar-label">LLM 厂商</div>
            {PROVIDER_PRESETS.map((preset) => {
              const prov = providers.find((p) => p.provider === preset.id);
              const active = preset.id === activeId;
              const selected = preset.id === selectedId;
              return (
                <button
                  key={preset.id}
                  type="button"
                  className={"provider-card" + (active ? " active" : "") + (selected ? " selected" : "")}
                  onClick={() => selectProvider(preset.id)}
                  data-testid={`provider-${preset.id}`}
                >
                  <div className="provider-card-top">
                    <span className="provider-card-label">{preset.label}</span>
                    {active && <span className="provider-badge active-badge">当前</span>}
                  </div>
                  <div className="provider-card-hint">{preset.hint}</div>
                  <div className="provider-card-meta">
                    {prov?.key_configured ? (
                      <span style={{ color: "var(--ok)", fontSize: 11 }}>✓ key 已配置</span>
                    ) : (
                      <span className="muted" style={{ fontSize: 11 }}>未配置 key</span>
                    )}
                  </div>
                </button>
              );
            })}
          </aside>

          {/* ── Right: Form panel ── */}
          <section className="settings-form-panel">
            {selectedPreset && (
              <div className="settings-form-card" data-testid="form-card">
                {/* Header */}
                <div className="settings-form-header">
                  <div>
                    <h2 className="settings-form-title">
                      {selectedPreset.label}
                      {isActiveProvider && (
                        <span className="badge ok" style={{ marginLeft: 10 }}>当前活跃</span>
                      )}
                    </h2>
                    <div className="muted" style={{ fontSize: 12 }}>{selectedPreset.hint}</div>
                  </div>
                  <div className="settings-toggle-row">
                    <ToggleField
                      label="启用"
                      hint={draft.enabled ? "LLM 已启用" : "LLM 已关闭"}
                      checked={!!draft.enabled}
                      onChange={(v) => setDraft({ ...draft, enabled: v })}
                      testid="toggle-enabled"
                    />
                  </div>
                </div>

                {/* Fields */}
                <div className="settings-row">
                  <TextField label="base_url" value={draft.base_url ?? ""} onChange={(v) => setDraft({ ...draft, base_url: v })} testid="field-base_url" placeholder="http:// 或 https://" />
                </div>

                <div className="settings-row">
                  <TextField label="model" value={draft.model ?? ""} onChange={(v) => setDraft({ ...draft, model: v })} testid="field-model" placeholder="模型名称" />
                </div>

                <div className="settings-row">
                  <ApiKeyField
                    configured={!!draft.key_configured}
                    preview={draft.key_preview}
                    revealed={apiKeyRevealed}
                    onRevealToggle={() => setApiKeyRevealed((v) => !v)}
                    draft={apiKeyDraft}
                    onDraftChange={(v) => { setApiKeyDraft(v); setApiKeyDirty(true); setClearKeyOnSave(false); }}
                    clearRequested={clearKeyOnSave}
                    onClearToggle={(v) => {
                      setClearKeyOnSave(v);
                      if (v) { setApiKeyDraft(""); setApiKeyDirty(true); }
                    }}
                  />
                </div>

                <div className="settings-row-grid">
                  <NumberField label="temperature" value={draft.temperature ?? 0.2} min={0} max={2} step={0.1} onChange={(v) => setDraft({ ...draft, temperature: v })} testid="field-temperature" />
                  <NumberField label="max_tokens" value={draft.max_tokens ?? 1200} min={1} max={128000} step={100} onChange={(v) => setDraft({ ...draft, max_tokens: v })} testid="field-max_tokens" />
                </div>

                <div className="settings-row" style={{ paddingTop: 4 }}>
                  <ToggleField
                    label="safe_mode"
                    hint="阻止生成/修改 deployable_config"
                    checked={!!draft.safe_mode}
                    onChange={(v) => setDraft({ ...draft, safe_mode: v })}
                    testid="toggle-safe_mode"
                  />
                </div>

                {/* Test result */}
                {testResult && (
                  <div
                    className="card mt-3"
                    style={{ borderColor: testResult.llm_used ? "var(--ok)" : "var(--warn)", fontSize: 12, padding: 12, marginTop: 12 }}
                    data-testid="test-result"
                  >
                    <div style={{ marginBottom: 6 }}>
                      <strong>{testResult.llm_used ? "✓ LLM 可用" : "✗ LLM 不可用"}</strong>
                      <span className="muted" style={{ marginLeft: 8 }}>
                        provider={testResult.provider ?? "?"} · model={testResult.model ?? "?"} · source={testResult.config_source}
                      </span>
                    </div>
                    {testResult.fallback_reason && (
                      <div className="muted" style={{ marginBottom: 4 }}>fallback: {testResult.fallback_reason}</div>
                    )}
                    {testResult.response && (
                      <pre style={{
                        margin: 0, padding: 8, background: "var(--bg-soft, #f5f5f5)", borderRadius: 4,
                        maxHeight: 160, overflow: "auto", whiteSpace: "pre-wrap", fontSize: 11,
                      }}>
                        {sanitizeAssistantText(testResult.response)}
                      </pre>
                    )}
                    {testResult.warnings?.length > 0 && (
                      <div className="muted" style={{ marginTop: 4, fontSize: 11 }}>
                        warnings: {testResult.warnings.join("; ")}
                      </div>
                    )}
                  </div>
                )}

                {/* Actions */}
                <div className="settings-actions">
                  <button type="button" className="btn" onClick={onTest} disabled={isBusy} data-testid="btn-test-llm">
                    {testing ? "测试中…" : "🧪 测试连接"}
                  </button>
                  <button type="button" className="btn" onClick={onSave} disabled={isBusy} data-testid="btn-save-llm">
                    {saving ? "保存中…" : "💾 保存"}
                  </button>
                  <button type="button" className="btn primary" onClick={onApply} disabled={isBusy} data-testid="btn-apply-llm">
                    {applying ? "应用中…" : "⚡ 应用"}
                  </button>
                  <span style={{ flex: 1 }} />
                  {draft.updated_at && (
                    <span className="muted" style={{ fontSize: 11 }} data-testid="last-updated">
                      {formatDate(draft.updated_at, "compact")}
                    </span>
                  )}
                  <button
                    type="button" className="btn danger-ghost" onClick={onReset}
                    disabled={isBusy} title="重置为默认值" data-testid="btn-reset-llm"
                  >
                    🗑 重置
                  </button>
                </div>
              </div>
            )}

            {/* ── Memory Gating settings ── */}
            <MemoryGatingCard
              enabled={memoryGating}
              loading={memoryGatingLoading}
              loaded={memoryGatingLoaded}
              onToggle={onMemoryGatingToggle}
            />
          </section>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────── Sub-components ──────────────────────── */

function PageHeader({ activeId }: { activeId?: string }) {
  const activePreset = activeId ? presetMap.get(activeId) : null;
  return (
    <div className="page-header">
      <div>
        <h1>系统设置<span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}> · Settings</span></h1>
        <div className="subtitle">
          LLM Provider 配置
          {activePreset && (
            <span className="badge ok" style={{ marginLeft: 10, fontSize: 11 }}>
              {activePreset.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function TextField({ label, value, onChange, testid, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; testid?: string; placeholder?: string;
}) {
  return (
    <div>
      <label className="settings-field-label">{label}</label>
      <input className="input" type="text" value={value} onChange={(e) => onChange(e.target.value)} data-testid={testid} spellCheck={false} autoComplete="off" placeholder={placeholder} />
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange, testid }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; testid?: string;
}) {
  return (
    <div>
      <label className="settings-field-label">{label}</label>
      <input className="input" type="number" value={value} min={min} max={max} step={step} onChange={(e) => { const n = Number(e.target.value); if (!Number.isNaN(n)) onChange(n); }} data-testid={testid} />
    </div>
  );
}

function ToggleField({ label, hint, checked, onChange, testid }: {
  label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void; testid?: string;
}) {
  return (
    <div>
      <label className="settings-field-label">{label}</label>
      <button
        type="button"
        className={"toggle" + (checked ? " on" : "")}
        onClick={() => onChange(!checked)}
        role="switch"
        aria-checked={checked}
        data-testid={testid}
      >
        <span className="toggle-knob" />
        <span className="toggle-label">{hint ? <span className="muted text-xs">{hint}</span> : null}</span>
      </button>
    </div>
  );
}

function ApiKeyField({
  configured, preview, revealed, onRevealToggle,
  draft, onDraftChange, clearRequested, onClearToggle,
}: {
  configured: boolean;
  preview: string | null | undefined;
  revealed: boolean;
  onRevealToggle: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  clearRequested: boolean;
  onClearToggle: (v: boolean) => void;
}) {
  const placeholder = configured
    ? revealed ? "粘贴新 key 替换当前" : "已配置 · 输入新 key 替换"
    : "粘贴 API key";
  return (
    <div>
      <label className="settings-field-label">api_key</label>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          className="input"
          type={revealed ? "text" : "password"}
          value={clearRequested ? "" : draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder={placeholder}
          data-testid="field-api_key"
          autoComplete="off"
          spellCheck={false}
          style={{ fontFamily: "ui-monospace,Menlo,monospace", flex: 1 }}
        />
        {configured && !draft && !clearRequested && (
          <span className="muted text-xs" data-testid="api-key-preview"><code>{preview ?? "已配置"}</code></span>
        )}
        <button type="button" className="btn" onClick={onRevealToggle} data-testid="btn-toggle-key-reveal" title={revealed ? "隐藏" : "显示"}>
          {revealed ? "隐藏" : "显示"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6, fontSize: 11 }}>
        {configured ? <span style={{ color: "var(--ok)" }}>✓ 已配置</span> : <span className="muted">未配置</span>}
        {configured && (
          <label style={{ display: "flex", gap: 4, cursor: "pointer", alignItems: "center" }}>
            <input type="checkbox" checked={clearRequested} onChange={(e) => onClearToggle(e.target.checked)} data-testid="cb-clear-key" />
            <span className="muted">保存时清空 key</span>
          </label>
        )}
      </div>
    </div>
  );
}

/* ──────────────────────── Memory Gating Card ──────────────────────── */

function MemoryGatingCard({
  enabled, loading, loaded, onToggle,
}: {
  enabled: boolean; loading: boolean; loaded: boolean; onToggle: (v: boolean) => void;
}) {
  return (
    <div className="card" style={{ marginTop: 16, padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 680, marginBottom: 2 }}>记忆门控 Memory Gating</div>
          <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
            控制每轮对话后，系统如何判断哪些信息值得长期记忆
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: enabled ? "var(--ok)" : "var(--ink-mute)" }}>
            {enabled ? "LLM" : "规则"}
          </span>
          <button type="button" className={"toggle" + (enabled ? " on" : "")} onClick={() => onToggle(!enabled)}
            disabled={loading} role="switch" aria-checked={enabled} data-testid="toggle-memory-gating">
            <span className="toggle-knob" />
          </button>
        </div>
      </div>
      {loaded && (
        <div style={{
          background: enabled ? "rgba(52, 199, 89, 0.06)" : "var(--surface-2)",
          border: "1px solid " + (enabled ? "rgba(52, 199, 89, 0.2)" : "var(--border-2)"),
          borderRadius: 8, padding: "14px 16px", fontSize: 12, lineHeight: 1.7,
        }}>
          <div style={{ fontWeight: 680, marginBottom: 6, fontSize: 13 }}>
            <span style={{ marginRight: 8 }}>{enabled ? "🔮" : "🔧"}</span>
            当前：{enabled ? "LLM 优先 + 规则兜底" : "纯规则模式"}
          </div>
          <div style={{ color: "var(--text-2)", lineHeight: 1.7 }}>
            {enabled ? "每轮对话结束后，LLM 会批量评估候选记忆的质量（1-5分），标记语义重复，生成可检索摘要。"
              : "使用确定性算法：前缀去重 + 类型感知阈值 + 安全过滤。"}
          </div>
          <div style={{ color: "var(--text-2)", lineHeight: 1.7, marginTop: 2 }}>
            {enabled ? "规则作为硬性安全门：过滤敏感信息（密码、IP、Key）、限制每类记忆数量上限。"
              : "不会调用额外的 LLM，零额外 Token 开销。"}
          </div>
          <div style={{ marginTop: 8, padding: "6px 10px", background: "var(--bg-soft, #f5f5f5)", borderRadius: 5,
            fontSize: 11, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ opacity: 0.6 }}>⏱</span>
            {enabled ? "额外延迟 ≈ 0.3-0.5s（淹没在主 LLM 调用的 2-8s 内，用户无感知）"
              : "每轮最多写入 3 条记忆 · 全局上限 500 条 · 同类型上限自动淘汰"}
          </div>
        </div>
      )}
    </div>
  );
}

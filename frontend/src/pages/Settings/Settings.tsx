/**
 * Settings — LLM Provider control center (v1.0.3 redesign).
 *
 * Layout (user-approved B): full-width HealthBar on top,
 * two-column body (Provider sidebar + Form card).
 *
 * Endpoints (backend unchanged):
 *   GET    /api/agent/llm/config    — current sanitized config
 *   POST   /api/agent/llm/config    — save
 *   DELETE /api/agent/llm/config    — reset to auto_default
 *   GET    /api/agent/llm/status    — health (auto-refresh every 10s)
 *   POST   /api/agent/llm/test      — one-shot connectivity test
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { settingsApi } from "../../api";
import { EmptyState, InlineCode, LoadingState } from "../../components/common";
import { useToastStore } from "../../stores/toast";
import { isApiError } from "../../types";
import type { LlmConfig, LlmStatus, LlmTestResult } from "../../types";
import { IconAlert, IconKey, IconSettings } from "../../components/Icon";
import { sanitizeAssistantText } from "../../utils/displayText";

interface ProviderPreset {
  id: string;
  label: string;
  base_url: string;
  model: string;
  hint?: string;
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "minimax",
    label: "MiniMax",
    base_url: "https://api.minimax.chat/v1",
    model: "MiniMax-M3",
    hint: "默认 MiniMax-M3",
  },
  {
    id: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    hint: "api.openai.com",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    hint: "api.deepseek.com",
  },
  {
    id: "ollama",
    label: "Ollama",
    base_url: "http://localhost:11434/v1",
    model: "llama3.1",
    hint: "localhost:11434",
  },
  {
    id: "custom",
    label: "Custom",
    base_url: "",
    model: "",
    hint: "openai 兼容",
  },
];

function pickPresetId(provider: string, baseUrl: string, model: string): string {
  const match = PROVIDER_PRESETS.find(
    (p) => p.id === provider && p.base_url === baseUrl && p.model === model,
  );
  if (match) return match.id;
  const byProvider = PROVIDER_PRESETS.find((p) => p.id === provider);
  if (byProvider) return byProvider.id;
  return "custom";
}

export function Settings() {
  const toast = useToastStore((s) => s.show);
  const [config, setConfig] = useState<LlmConfig | null>(null);
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [draft, setDraft] = useState<LlmConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [healthRefreshing, setHealthRefreshing] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [apiKeyRevealed, setApiKeyRevealed] = useState(false);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [clearKeyOnSave, setClearKeyOnSave] = useState(false);
  const [activePreset, setActivePreset] = useState<string>("custom");
  const aliveRef = useRef(true);
  const statusRequestSeq = useRef(0);
  const statusInFlight = useRef(0);

  // 初始加载只阻塞 config。健康检查可能触发供应商探测，放到后台刷新，
  // 避免设置页打开时卡在空白 loading。
  useEffect(() => {
    aliveRef.current = true;
    setLoading(true);
    settingsApi.llmConfig()
      .then((cfg) => {
        if (!aliveRef.current) return;
        setConfig(cfg);
        setDraft(cfg);
        setActivePreset(pickPresetId(cfg.provider, cfg.base_url, cfg.model));
        setHealthRefreshing(true);
        void refreshHealth({ showPending: true });
      })
      .catch((e: unknown) => {
        if (!aliveRef.current) return;
        setError(isApiError(e) ? e.message : String(e));
      })
      .finally(() => {
        if (aliveRef.current) setLoading(false);
      });
    return () => {
      aliveRef.current = false;
    };
  }, []);

  // 定时刷新 health（10s 一次, 改完保存后立刻刷一次）
  useEffect(() => {
    if (!config) return;
    const id = window.setInterval(() => {
      refreshHealth({ showPending: false, skipIfBusy: true });
    }, 10_000);
    return () => window.clearInterval(id);
  }, [config]);

  async function refreshHealth(options: { showPending?: boolean; skipIfBusy?: boolean } = {}) {
    if (options.skipIfBusy && statusInFlight.current > 0) {
      return;
    }
    statusInFlight.current += 1;
    const requestId = ++statusRequestSeq.current;
    if (options.showPending) setHealthRefreshing(true);
    try {
      const st = await settingsApi.llmStatus();
      if (aliveRef.current && requestId === statusRequestSeq.current) {
        setStatus(st);
      }
    } catch {
      // Keep the last known status visible; diagnostics are in the next good response.
    } finally {
      statusInFlight.current = Math.max(0, statusInFlight.current - 1);
      if (aliveRef.current && requestId === statusRequestSeq.current) {
        setHealthRefreshing(false);
      }
    }
  }

  function applyPreset(preset: ProviderPreset) {
    if (!draft) return;
    setActivePreset(preset.id);
    setDraft({
      ...draft,
      provider: preset.id,
      base_url: draft.base_url || preset.base_url,
      model: draft.model || preset.model,
    });
  }

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    try {
      const payload: Parameters<typeof settingsApi.updateLlmConfig>[0] = {
        enabled: draft.enabled,
        provider: draft.provider,
        base_url: draft.base_url,
        model: draft.model,
        temperature: draft.temperature,
        max_tokens: draft.max_tokens,
        safe_mode: draft.safe_mode,
      };
      if (apiKeyDirty) {
        if (clearKeyOnSave) {
          payload.clear_api_key = true;
        } else if (apiKeyDraft) {
          payload.api_key = apiKeyDraft;
        }
      }
      const res = await settingsApi.updateLlmConfig(payload);
      setConfig(res.config);
      setDraft(res.config);
      setApiKeyDirty(false);
      setApiKeyDraft("");
      setClearKeyOnSave(false);
      setApiKeyRevealed(false);
      toast({ kind: "success", title: "LLM 配置已保存" });
      // 立刻刷一次 health；不阻塞表单恢复，避免旧状态闪烁。
      void refreshHealth({ showPending: true });
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

  async function onTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await settingsApi.llmTest({
        task: "result_summarize",
        message: "ping from settings UI",
      });
      setTestResult(res);
      toast({
        kind: res.llm_used ? "success" : "warning",
        title: res.llm_used ? "LLM 可用" : "LLM 不可用",
        body: res.fallback_reason
          ? `fallback_reason=${res.fallback_reason}`
          : `model=${res.model ?? "?"}`,
      });
      void refreshHealth({ showPending: true });
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "测试请求失败",
        body: isApiError(e) ? e.message : String(e),
      });
    } finally {
      setTesting(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("确认重置 LLM 配置?将清空 config/LLM_setting.json, 环境变量中的 key 仍会生效。")) {
      return;
    }
    setSaving(true);
    try {
      await settingsApi.deleteLlmConfig();
      // 重新拉 config (auto_default)，健康检查放到后台，避免重置操作被供应商探测拖慢。
      const cfg = await settingsApi.llmConfig();
      setConfig(cfg);
      setDraft(cfg);
      setActivePreset(pickPresetId(cfg.provider, cfg.base_url, cfg.model));
      setApiKeyDirty(false);
      setApiKeyDraft("");
      setClearKeyOnSave(false);
      setTestResult(null);
      toast({ kind: "success", title: "已重置为默认配置" });
      void refreshHealth({ showPending: true });
    } catch (e: unknown) {
      toast({
        kind: "error",
        title: "重置失败",
        body: isApiError(e) ? e.message : String(e),
      });
    } finally {
      setSaving(false);
    }
  }

  const lastUpdated = useMemo(() => {
    if (!draft?.updated_at) return null;
    try {
      return new Date(draft.updated_at).toLocaleString();
    } catch {
      return draft.updated_at;
    }
  }, [draft?.updated_at]);

  if (loading) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body">
          <LoadingState />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body">
          <div
            className="card"
            style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
          >
            {error}
          </div>
        </div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="page" data-testid="page-settings">
        <PageHeader />
        <div className="page-body">
          <EmptyState text="后端未返回 LLM 配置" />
        </div>
      </div>
    );
  }

  return (
    <div className="page" data-testid="page-settings">
      <PageHeader />
      <div className="page-body">
        {/* v1.0.3.4: show recent failure alert prominently */}
        {status?.recent_failure && (
          <div
            className="card mb-3"
            style={{
              borderColor: "var(--warn)",
              background: "var(--warn-soft, #fff8e1)",
              padding: 12,
            }}
            data-testid="llm-recent-failure-alert"
          >
            <div className="row-flex" style={{ gap: 8 }}>
              <IconAlert size={14} style={{ color: "var(--warn)" }} />
              <div>
                <strong style={{ color: "var(--warn)" }}>最近对话失败</strong>
                <div className="text-sm mt-1" style={{ color: "var(--ink)" }}>
                  {status.recent_failure.error_summary}
                </div>
                <div className="text-xs mt-1" style={{ color: "var(--ink-mute)" }}>
                  {status.recent_failure.at ? `发生时间：${new Date(status.recent_failure.at).toLocaleString()}` : ""}
                  {status.recent_failure.error_type ? ` · 类型：${status.recent_failure.error_type}` : ""}
                </div>
                <div className="text-xs mt-2" style={{ color: "var(--ink-mute)" }}>
                  建议：检查网络连接、缩短问题长度或更换 LLM 供应商。
                </div>
              </div>
            </div>
          </div>
        )}
        <HealthBar status={status} config={draft} refreshing={healthRefreshing} />

        <div className="settings-grid" data-testid="settings-grid">
          <aside className="provider-sidebar" data-testid="provider-sidebar">
            <div className="provider-sidebar-label">PROVIDER</div>
            {PROVIDER_PRESETS.map((p) => {
              const active = activePreset === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  className={"provider-card" + (active ? " active" : "")}
                  onClick={() => applyPreset(p)}
                  data-testid={`provider-${p.id}`}
                >
                  <div className="provider-card-label">{p.label}</div>
                  <div className="provider-card-hint">{p.hint ?? p.base_url}</div>
                </button>
              );
            })}
          </aside>

          <div className="settings-form-card">
            <div className="card-title">
              <IconKey size={11} /> LLM Provider
            </div>

            <div className="settings-row">
              <Field
                label="base_url"
                value={draft.base_url}
                onChange={(v) => setDraft({ ...draft, base_url: v })}
                testid="field-base_url"
              />
            </div>

            <div className="settings-row">
              <Field
                label="model"
                value={draft.model}
                onChange={(v) => setDraft({ ...draft, model: v })}
                testid="field-model"
              />
            </div>

            <div className="settings-row">
              <ApiKeyField
                configured={draft.key_configured}
                preview={draft.key_preview}
                revealed={apiKeyRevealed}
                onRevealToggle={() => setApiKeyRevealed((v) => !v)}
                draft={apiKeyDraft}
                onDraftChange={(v) => {
                  setApiKeyDraft(v);
                  setApiKeyDirty(true);
                  setClearKeyOnSave(false);
                }}
                clearRequested={clearKeyOnSave}
                onClearToggle={(v) => {
                  setClearKeyOnSave(v);
                  if (v) {
                    setApiKeyDraft("");
                    setApiKeyDirty(true);
                  }
                }}
              />
            </div>

            <div className="settings-row settings-row-grid">
              <ToggleRow
                label="enabled"
                hint="启用 LLM (关闭后 agent 走 stub fallback)"
                checked={draft.enabled}
                onChange={(v) => setDraft({ ...draft, enabled: v })}
                testid="toggle-enabled"
              />
              <ToggleRow
                label="safe_mode"
                hint="阻止生成 / 修改 deployable_config 等"
                checked={draft.safe_mode}
                onChange={(v) => setDraft({ ...draft, safe_mode: v })}
                testid="toggle-safe_mode"
              />
            </div>

            <div className="settings-row settings-row-grid">
              <NumberField
                label="temperature"
                value={draft.temperature}
                min={0}
                max={2}
                step={0.1}
                onChange={(v) => setDraft({ ...draft, temperature: v })}
                testid="field-temperature"
              />
              <NumberField
                label="max_tokens"
                value={draft.max_tokens}
                min={1}
                max={128000}
                step={100}
                onChange={(v) => setDraft({ ...draft, max_tokens: v })}
                testid="field-max_tokens"
              />
            </div>

            {testResult && (
              <div
                className="card mt-3"
                style={{
                  borderColor: testResult.llm_used ? "var(--ok)" : "var(--warn)",
                  fontSize: 12,
                }}
                data-testid="test-result"
              >
                <div>
                  <strong>{testResult.llm_used ? "✓ LLM 可用" : "✗ LLM 不可用"}</strong>{" "}
                  <span className="muted">
                    · provider={testResult.provider ?? "?"} · model=
                    {testResult.model ?? "?"} · config_source=
                    {testResult.config_source}
                  </span>
                </div>
                {testResult.fallback_reason && (
                  <div className="muted">fallback_reason={testResult.fallback_reason}</div>
                )}
                {testResult.response && (
                  <pre
                    style={{
                      margin: "6px 0 0",
                      padding: 8,
                      background: "var(--bg-2)",
                      borderRadius: 4,
                      maxHeight: 140,
                      overflow: "auto",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                  {sanitizeAssistantText(testResult.response)}
                  </pre>
                )}
                {testResult.warnings.length > 0 && (
                  <div className="muted" style={{ marginTop: 4 }}>
                    warnings: {testResult.warnings.join("; ")}
                  </div>
                )}
              </div>
            )}

            <div className="settings-actions">
              <button
                type="button"
                className="btn"
                onClick={onTest}
                disabled={testing || saving}
                data-testid="btn-test-llm"
              >
                {testing ? "测试中…" : "🧪 测试连接"}
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={onSave}
                disabled={saving || testing}
                data-testid="btn-save-llm"
              >
                {saving ? "保存中…" : "保存"}
              </button>
              <span className="spacer" />
              {lastUpdated && (
                <span className="muted text-xs" data-testid="last-updated">
                  上次更新: {lastUpdated} · source: {draft.source ?? "auto_default"}
                </span>
              )}
              <button
                type="button"
                className="btn danger-ghost"
                onClick={onDelete}
                disabled={saving || testing}
                title="重置为 auto_default, 环境变量 key 仍生效"
                data-testid="btn-reset-llm"
              >
                🗑 重置为默认
              </button>
            </div>
          </div>
        </div>

        <details className="collapse mt-3">
          <summary>开发诊断</summary>
          <div className="text-xs muted row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
            <IconSettings size={11} />
            <span>provider={status?.provider ?? "?"}</span>
            <span>·</span>
            <span>model={status?.model ?? draft.model}</span>
            <span>·</span>
            <span>config_source={status?.config_source ?? draft.source ?? "?"}</span>
          </div>
          <div className="text-xs muted row-flex mt-2" style={{ gap: 6, flexWrap: "wrap" }}>
            <InlineCode>GET /api/agent/llm/config</InlineCode>
            <span>·</span>
            <InlineCode>POST /api/agent/llm/config</InlineCode>
            <span>·</span>
            <InlineCode>DELETE /api/agent/llm/config</InlineCode>
            <span>·</span>
            <InlineCode>GET /api/agent/llm/status</InlineCode>
            <span>·</span>
            <InlineCode>POST /api/agent/llm/test</InlineCode>
          </div>
        </details>
      </div>
    </div>
  );
}

function PageHeader() {
  return (
    <div className="page-header">
      <div>
        <h1>
          系统设置{" "}
          <span style={{ color: "var(--ink-mute)", fontWeight: 400, fontSize: 14 }}>
            · Settings
          </span>
        </h1>
        <div className="subtitle">LLM provider 控制中心</div>
      </div>
    </div>
  );
}

function HealthBar({
  status,
  config,
  refreshing = false,
}: {
  status: LlmStatus | null;
  config: LlmConfig | null;
  refreshing?: boolean;
}) {
  if (!config) return null;
  if (!status) {
    return (
      <div
        className="card mb-3 row-flex"
        style={{
          background: "var(--secondary-soft)",
          borderColor: "var(--secondary)",
          alignItems: "center",
          gap: 12,
        }}
        data-testid="llm-health-bar"
      >
        <span className="spinner" style={{ width: 12, height: 12 }} />
        <strong style={{ color: "var(--secondary)" }}>
          {refreshing ? "正在检查服务状态" : "服务状态待刷新"}
        </strong>
        <span className="muted text-xs">
          · provider={config.provider} · model={config.model}
        </span>
      </div>
    );
  }
  // 优先级: 未配置 key (warn) > 连接失败 (err) > 已连接但近期有失败 (warn) > 已连接 (ok)
  const warn = !status.key_loaded;
  const err = !warn && status.health.last_error && !status.connected;
  // Recent failure: health check passes but a real turn failed recently
  const recentFailure = !err && !warn && status.recent_failure;
  const recentFailureActive = recentFailure &&
    Date.now() - new Date(recentFailure.at).getTime() < 15 * 60_000; // 15 min window
  let color = "var(--ok)";
  let bg = "#e8f5e9";
  let border = "#66bb6a";
  let dot = "#2e7d32";
  let label = "已连接";
  if (refreshing) {
    color = "var(--ink)";
    bg = "#eef5ff";
    border = "#5b8def";
    dot = "#2f6fd6";
    label = "检查中";
  } else if (err) {
    color = "var(--danger)";
    bg = "#ffebee";
    border = "#c62828";
    dot = "#c62828";
    label = "连接失败";
  } else if (recentFailureActive) {
    color = "var(--warn)";
    bg = "#fff8e1";
    border = "#f9a825";
    dot = "#f9a825";
    label = "已连接 · 近期超时";
  } else if (warn) {
    color = "var(--warn)";
    bg = "#fff8e1";
    border = "#f9a825";
    dot = "#f9a825";
    label = "未配置 key";
  }
  const diagnostic = status.health.last_error;
  return (
    <>
    <div
      className="card mb-3 row-flex"
      style={{
        background: bg,
        borderColor: border,
        alignItems: "center",
        gap: 12,
      }}
      data-testid="llm-health-bar"
    >
      <span
        style={{
          width: 10,
          height: 10,
          background: dot,
          borderRadius: "50%",
          flexShrink: 0,
        }}
      />
      <strong style={{ color }}>{label}</strong>
      <span className="muted text-xs">
        · enabled={String(status.enabled)} · key_loaded={String(status.key_loaded)}
      </span>
    </div>
    {recentFailureActive && (
      <div
        className="card mb-3"
        style={{
          borderColor: "var(--warn)",
          color: "var(--warn)",
          boxShadow: "none",
          padding: 10,
        }}
        data-testid="llm-recent-failure"
      >
        <strong>最近请求失败</strong>
        <span className="text-xs" style={{ marginLeft: 8 }}>
          {recentFailure.error_summary}
          {recentFailure.at ? ` · ${new Date(recentFailure.at).toLocaleTimeString()}` : ""}
        </span>
      </div>
    )}
    {diagnostic && (
      <div
        className="card mb-3"
        style={{
          borderColor: status.connected ? "var(--warn)" : "var(--danger)",
          color: status.connected ? "var(--warn)" : "var(--danger)",
          boxShadow: "none",
          padding: 10,
        }}
        data-testid="llm-health-diagnostic"
      >
        <strong>{status.connected ? "最近诊断提示" : "连接诊断"}</strong>
        <span className="text-xs" style={{ marginLeft: 8 }}>
          {diagnostic}
          {status.health.last_error_type ? ` · ${status.health.last_error_type}` : ""}
        </span>
      </div>
    )}
    </>
  );
}

function Field({
  label,
  value,
  onChange,
  testid,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testid?: string;
  type?: string;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="settings-field-label">{label}</label>
      <input
        className="input"
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
        spellCheck={false}
        autoComplete="off"
        placeholder={placeholder}
      />
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
  testid,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  testid?: string;
}) {
  return (
    <div>
      <label className="settings-field-label">{label}</label>
      <input
        className="input"
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        data-testid={testid}
      />
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
  testid,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testid?: string;
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
        <span className="toggle-label">
          {hint ? <span className="muted text-xs">{hint}</span> : null}
        </span>
      </button>
    </div>
  );
}

function ApiKeyField({
  configured,
  preview,
  revealed,
  onRevealToggle,
  draft,
  onDraftChange,
  clearRequested,
  onClearToggle,
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
    ? revealed
      ? "粘贴新 key 替换当前"
      : "已配置 · 输入新 key 替换"
    : "粘贴 API key";
  return (
    <div>
      <label className="settings-field-label">api_key</label>
      <div className="row-flex" style={{ gap: 6 }}>
        <input
          className="input"
          type={revealed ? "text" : "password"}
          value={clearRequested ? "" : draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder={placeholder}
          data-testid="field-api_key"
          autoComplete="off"
          spellCheck={false}
          style={{ fontFamily: "ui-monospace,Menlo,monospace" }}
        />
        {configured && !draft && !clearRequested && (
          <span className="muted text-xs" data-testid="api-key-preview">
            <code>{preview ?? "已配置"}</code>
          </span>
        )}
        <button
          type="button"
          className="btn"
          onClick={onRevealToggle}
          data-testid="btn-toggle-key-reveal"
          title={revealed ? "隐藏" : "显示"}
        >
          {revealed ? "隐藏" : "显示"}
        </button>
      </div>
      <div className="row-flex text-xs" style={{ gap: 8, marginTop: 6 }}>
        {configured ? (
          <span style={{ color: "var(--ok)" }}>✓ 已配置</span>
        ) : (
          <span className="muted">未配置</span>
        )}
        {configured && (
          <label className="row-flex" style={{ gap: 4, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={clearRequested}
              onChange={(e) => onClearToggle(e.target.checked)}
              data-testid="cb-clear-key"
            />
            <span className="muted">保存时清空 key</span>
          </label>
        )}
      </div>
    </div>
  );
}

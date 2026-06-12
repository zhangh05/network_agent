/**
 * Settings — LLM Provider control center tests.
 *
 * Validates: initial load, preset fill, save flow, test button,
 * delete (reset) flow, health bar states, api_key 3-state (已配置 / 显示 / 替换),
 * safe_mode toggle, error state.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { Settings } from "../pages/Settings/Settings";
import { settingsApi } from "../api";
import type { LlmConfig, LlmStatus, LlmTestResult } from "../types";

const baseConfig: LlmConfig = {
  enabled: false,
  provider: "disabled",
  safe_mode: true,
  base_url: "",
  model: "",
  temperature: 0.2,
  max_tokens: 1200,
  key_configured: false,
  key_preview: null,
  updated_at: "2026-06-11T10:00:00Z",
  source: "auto_default",
  config_path: "/tmp/LLM_setting.json",
  global: true,
};

const liveConfig: LlmConfig = {
  ...baseConfig,
  enabled: true,
  provider: "minimax",
  base_url: "https://api.minimax.chat/v1",
  model: "MiniMax-M3",
  key_configured: true,
  key_preview: "eyJ0****8a3f",
  source: "ui_settings",
};

const okStatus: LlmStatus = {
  enabled: true,
  enabled_by_ui: true,
  provider: "minimax",
  model: "MiniMax-M3",
  provider_type: "openai_compatible",
  safe_mode: true,
  key_loaded: true,
  key_source: "ui_settings",
  config_source: "ui_settings",
  connected: true,
  settings_file_exists: true,
  health: {
    base_url_reachable: true,
    chat_completion_endpoint_reachable: true,
    chat_completion_ok: true,
    configured: true,
    connected: true,
    http_status: 200,
    key_loaded: true,
    model: "MiniMax-M3",
    models_endpoint_ok: true,
    provider: "minimax",
  },
};

const noKeyStatus: LlmStatus = {
  ...okStatus,
  key_loaded: false,
  connected: false,
  health: { ...okStatus.health, key_loaded: false, connected: false, last_error: "no_api_key", last_error_type: "missing_api_key" },
};

const staleErrorStatus: LlmStatus = {
  ...okStatus,
  connected: true,
  health: {
    ...okStatus.health,
    connected: true,
    chat_completion_ok: true,
    http_status: 404,
    last_error: "HTTP Error 404: 404 Page not found",
    last_error_type: "provider_http_404",
  },
};

function mockApi(overrides: Partial<{
  config: LlmConfig;
  status: LlmStatus;
  update: ReturnType<typeof vi.fn>;
  del: ReturnType<typeof vi.fn>;
  test: ReturnType<typeof vi.fn>;
}> = {}) {
  const config = overrides.config ?? baseConfig;
  const status = overrides.status ?? noKeyStatus;
  const spy = {
    llmConfig: vi.fn().mockResolvedValue(config),
    llmStatus: vi.fn().mockResolvedValue(status),
    updateLlmConfig: overrides.update ?? vi.fn().mockResolvedValue({ ok: true, config }),
    deleteLlmConfig: overrides.del ?? vi.fn().mockResolvedValue({ ok: true, deleted: true }),
    llmTest: overrides.test ?? vi.fn().mockResolvedValue({} as LlmTestResult),
  };
  vi.spyOn(settingsApi, "llmConfig").mockImplementation(spy.llmConfig);
  vi.spyOn(settingsApi, "llmStatus").mockImplementation(spy.llmStatus);
  vi.spyOn(settingsApi, "updateLlmConfig").mockImplementation(spy.updateLlmConfig);
  vi.spyOn(settingsApi, "deleteLlmConfig").mockImplementation(spy.deleteLlmConfig);
  vi.spyOn(settingsApi, "llmTest").mockImplementation(spy.llmTest);
  return spy;
}

beforeEach(() => {
  vi.restoreAllMocks();
  // auto_default window.confirm 默认 true
  window.confirm = vi.fn().mockReturnValue(true);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Settings — LLM provider control center", () => {
  it("加载后渲染 health bar + provider sidebar + form", async () => {
    mockApi();
    render(<Settings />);
    await waitFor(() => {
      expect(screen.getByTestId("llm-health-bar")).toBeInTheDocument();
    });
    expect(screen.getByTestId("provider-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("provider-minimax")).toBeInTheDocument();
    expect(screen.getByTestId("provider-openai")).toBeInTheDocument();
    expect(screen.getByTestId("provider-deepseek")).toBeInTheDocument();
    expect(screen.getByTestId("provider-ollama")).toBeInTheDocument();
    expect(screen.getByTestId("provider-custom")).toBeInTheDocument();
    expect(screen.getByTestId("field-base_url")).toBeInTheDocument();
    expect(screen.getByTestId("field-model")).toBeInTheDocument();
    expect(screen.getByTestId("field-api_key")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-enabled")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-safe_mode")).toBeInTheDocument();
    expect(screen.getByTestId("btn-save-llm")).toBeInTheDocument();
    expect(screen.getByTestId("btn-test-llm")).toBeInTheDocument();
    expect(screen.getByTestId("btn-reset-llm")).toBeInTheDocument();
  });

  it("加载后 health bar 显示「未配置 key」(无 key 时)", async () => {
    mockApi({ config: baseConfig, status: noKeyStatus });
    render(<Settings />);
    await waitFor(() => {
      expect(screen.getByTestId("llm-health-bar").textContent).toMatch(/未配置 key/);
    });
  });

  it("已配置 key 时 health bar 显示「已连接」+ key_preview", async () => {
    mockApi({ config: liveConfig, status: okStatus });
    render(<Settings />);
    await waitFor(() => {
      expect(screen.getByTestId("llm-health-bar").textContent).toMatch(/已连接/);
    });
    expect(screen.getByTestId("api-key-preview").textContent).toContain("eyJ0****8a3f");
    expect(screen.getByText("✓ 已配置")).toBeInTheDocument();
  });

  it("provider 近期错误单独作为诊断提示, 不混在绿色已连接摘要里", async () => {
    mockApi({ config: liveConfig, status: staleErrorStatus });
    render(<Settings />);
    const health = await screen.findByTestId("llm-health-bar");
    expect(health.textContent).toMatch(/已连接/);
    expect(health.textContent).not.toContain("HTTP Error 404");
    expect(await screen.findByTestId("llm-health-diagnostic")).toHaveTextContent(
      "HTTP Error 404",
    );
  });

  it("点 provider 卡片会预填 base_url + model (空表单时)", async () => {
    mockApi({ config: baseConfig, status: noKeyStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("provider-openai"));
    fireEvent.click(screen.getByTestId("provider-openai"));
    expect((screen.getByTestId("field-base_url") as HTMLInputElement).value).toBe(
      "https://api.openai.com/v1",
    );
    expect((screen.getByTestId("field-model") as HTMLInputElement).value).toBe("gpt-4o-mini");
  });

  it("点 provider 卡片不会覆盖已填的 base_url/model", async () => {
    mockApi({ config: { ...baseConfig, base_url: "https://custom.example/v1", model: "my-model" }, status: noKeyStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("provider-deepseek"));
    fireEvent.click(screen.getByTestId("provider-deepseek"));
    expect((screen.getByTestId("field-base_url") as HTMLInputElement).value).toBe("https://custom.example/v1");
    expect((screen.getByTestId("field-model") as HTMLInputElement).value).toBe("my-model");
  });

  it("点保存会调 updateLlmConfig (启用 + base_url + model + temp + max_tokens + safe_mode)", async () => {
    const spy = mockApi({ config: baseConfig, status: noKeyStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("toggle-enabled"));
    // 打开 enabled
    fireEvent.click(screen.getByTestId("toggle-enabled"));
    // 改 temperature
    fireEvent.change(screen.getByTestId("field-temperature"), { target: { value: "0.5" } });
    // 保存
    await act(async () => {
      fireEvent.click(screen.getByTestId("btn-save-llm"));
    });
    expect(spy.updateLlmConfig).toHaveBeenCalled();
    const payload = spy.updateLlmConfig.mock.calls[0][0];
    expect(payload.enabled).toBe(true);
    expect(payload.temperature).toBe(0.5);
    expect(payload.safe_mode).toBe(true);
    expect(payload).not.toHaveProperty("api_key");
    expect(payload).not.toHaveProperty("clear_api_key");
  });

  it("测试连接会调 llmTest, 成功后显示 result block", async () => {
    const testResult: LlmTestResult = {
      ok: true,
      provider: "minimax",
      model: "MiniMax-M3",
      llm_used: true,
      config_source: "ui_settings",
      policy_pass: true,
      response: "pong",
      safe_to_show: true,
      warnings: [],
      metadata: {},
    };
    const spy = mockApi({ config: liveConfig, status: okStatus, test: vi.fn().mockResolvedValue(testResult) });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("btn-test-llm"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("btn-test-llm"));
    });
    expect(spy.llmTest).toHaveBeenCalledWith(expect.objectContaining({ task: "result_summarize" }));
    await waitFor(() => {
      expect(screen.getByTestId("test-result").textContent).toMatch(/LLM 可用/);
    });
    expect(screen.getByTestId("test-result").textContent).toContain("pong");
  });

  it("点重置会弹 confirm, 确认后调 deleteLlmConfig 并刷新 config", async () => {
    const del = vi.fn().mockResolvedValue({ ok: true, deleted: true });
    mockApi({ config: liveConfig, status: okStatus, del });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("btn-reset-llm"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("btn-reset-llm"));
    });
    expect(window.confirm).toHaveBeenCalled();
    expect(del).toHaveBeenCalled();
  });

  it("api_key 「显示」按钮在 password ↔ text 切换", async () => {
    mockApi({ config: liveConfig, status: okStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("field-api_key"));
    const input = screen.getByTestId("field-api_key") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByTestId("btn-toggle-key-reveal"));
    expect((screen.getByTestId("field-api_key") as HTMLInputElement).type).toBe("text");
    fireEvent.click(screen.getByTestId("btn-toggle-key-reveal"));
    expect((screen.getByTestId("field-api_key") as HTMLInputElement).type).toBe("password");
  });

  it("safe_mode toggle 切换 draft.safe_mode", async () => {
    mockApi({ config: { ...baseConfig, safe_mode: true }, status: noKeyStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("toggle-safe_mode"));
    const toggle = screen.getByTestId("toggle-safe_mode");
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  it("加载失败时显示 error card", async () => {
    vi.spyOn(settingsApi, "llmConfig").mockRejectedValue(new Error("boom"));
    vi.spyOn(settingsApi, "llmStatus").mockResolvedValue(noKeyStatus);
    render(<Settings />);
    await waitFor(() => {
      expect(screen.getByText(/boom/)).toBeInTheDocument();
    });
  });

  it("pickPresetId — 当前 config 匹配 minimax preset 时, 加载后自动 active", async () => {
    mockApi({ config: liveConfig, status: okStatus });
    render(<Settings />);
    await waitFor(() => screen.getByTestId("provider-minimax"));
    const minimax = screen.getByTestId("provider-minimax");
    expect(minimax.className).toContain("active");
  });
});

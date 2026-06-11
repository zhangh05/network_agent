import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from "axios";
import type { ApiError, ApiErrorCode } from "../types";

/**
 * HTTP client wrapper. All API calls go through `apiClient`.
 * Network errors are uniformly converted to `ApiError` so callers
 * can handle them without inspecting axios internals.
 *
 * Base URL precedence:
 *  1. `VITE_API_BASE` environment variable (production / staging)
 *  2. Vite dev-server proxy at `/api` (default for `npm run dev`)
 *  3. Fallback to `/api` (same-origin)
 */

const REQUEST_TIMEOUT_MS = 12000;

const envBase =
  (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE ?? "";
const baseURL = envBase
  ? envBase.replace(/\/+$/, "") + "/api"
  : "/api";

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

let requestSeq = 0;
function nextRequestId(): string {
  requestSeq += 1;
  return `req-${Date.now()}-${requestSeq}`;
}

apiClient.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  (config.headers as Record<string, string>)["X-Request-Id"] = nextRequestId();
  return config;
});

function toApiError(err: unknown, url?: string): ApiError {
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<{ message?: string; error?: string; summary?: string }>;
    if (ax.code === "ECONNABORTED") {
      return mkError("timeout", 0, "请求超时", url, ax.response);
    }
    if (ax.code === "ERR_CANCELED") {
      return mkError("aborted", 0, "请求被取消", url, ax.response);
    }
    if (!ax.response) {
      return mkError("network", 0, "后端不可达", url, undefined);
    }
    const status = ax.response.status;
    const body = ax.response.data as
      | { message?: string; error?: string; summary?: string }
      | undefined;
    const msg =
      body?.message || body?.error || body?.summary || ax.message || "请求失败";
    let code: ApiErrorCode = status >= 500 ? "http_5xx" : "http_4xx";
    if (status === 401) code = "http_4xx";
    if (status === 403) code = "http_4xx";
    if (status === 404) code = "http_4xx";
    if (status === 408) code = "timeout";
    if (status === 413 || status === 422) code = "http_4xx";
    if (status === 429) code = "http_4xx";
    return mkError(code, status, msg, url, ax.response);
  }
  if (err instanceof SyntaxError) {
    return mkError("parse", 0, "响应解析失败", url, undefined);
  }
  return mkError("unknown", 0, "未知错误", url, undefined);
}

function mkError(
  code: ApiErrorCode,
  status: number,
  message: string,
  url: string | undefined,
  response: AxiosError["response"],
): ApiError {
  return {
    ok: false,
    code,
    status,
    message,
    url,
    request_id: (response?.headers as Record<string, string> | undefined)?.["x-request-id"],
    details: response?.data,
    timestamp: new Date().toISOString(),
  };
}

/**
 * Public request helper. Throws `ApiError` on any failure.
 * On success, returns the raw parsed JSON body. We do NOT normalize here —
 * pages normalize against their typed contracts.
 */
export async function apiRequest<T = unknown>(
  config: AxiosRequestConfig,
  signal?: AbortSignal,
): Promise<T> {
  try {
    const merged: AxiosRequestConfig = { ...config };
    if (signal) {
      merged.signal = signal;
    }
    const res = await apiClient.request<T>(merged);
    return res.data;
  } catch (err) {
    const url = (err as AxiosError)?.config?.url;
    throw toApiError(err, url);
  }
}

export const apiBaseURL = baseURL;

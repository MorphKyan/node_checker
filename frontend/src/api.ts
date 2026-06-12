import type {
  ExportFormat,
  ExportMode,
  JobStatus,
  RuntimeSettings,
  RuntimeSettingsMetadata,
  SubscriptionResults,
  SubscriptionSummary,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const location = "loc" in item && Array.isArray(item.loc) ? `${item.loc.join(".")}: ` : "";
          return `${location}${String(item.msg)}`;
        }
        return "";
      })
      .filter(Boolean);
    return messages.length ? messages.join("; ") : fallback;
  }
  if (detail && typeof detail === "object") {
    if ("message" in detail && typeof detail.message === "string") return detail.message;
    if ("msg" in detail && typeof detail.msg === "string") return detail.msg;
  }
  return fallback;
}

export interface ApiClient {
  listSubscriptions(): Promise<SubscriptionSummary[]>;
  getSubscription(id: string): Promise<SubscriptionSummary>;
  createSubscription(input: { name?: string; url: string }): Promise<{ subscription_id: string; job_id: string; status: string }>;
  updateSubscription(id: string, input: { name?: string; url?: string }): Promise<SubscriptionSummary>;
  deleteSubscription(id: string): Promise<{ deleted: boolean; subscription_id: string }>;
  refreshSubscription(id: string, input: { speedtest_limit?: number; force_probe?: boolean }): Promise<{ subscription_id: string; job_id: string; status: string }>;
  getJob(id: string): Promise<JobStatus>;
  cancelJob(id: string): Promise<JobStatus>;
  getResults(id: string): Promise<SubscriptionResults>;
  getEnhanced(id: string, params: { mode: ExportMode; format: ExportFormat; valid_only: boolean }): Promise<string>;
  getSettings(): Promise<RuntimeSettings>;
  getSettingsMetadata(): Promise<RuntimeSettingsMetadata>;
  updateSettings(input: Partial<RuntimeSettings>): Promise<RuntimeSettings>;
}

function joinUrl(baseUrl: string, path: string): string {
  if (!baseUrl) return path;
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function pathSegment(value: string): string {
  return encodeURIComponent(value);
}

async function request<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(joinUrl(baseUrl, path), {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    let message = response.statusText;
    const errorText = await response.text();
    try {
      const body = JSON.parse(errorText);
      message = formatDetail(body.detail, message);
    } catch {
      message = errorText || message;
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json() as Promise<T>;
  }
  return response.text() as Promise<T>;
}

export function createApiClient(baseUrl: string): ApiClient {
  return {
    listSubscriptions: () => request(baseUrl, "/subscriptions"),
    getSubscription: (id) => request(baseUrl, `/subscriptions/${pathSegment(id)}`),
    createSubscription: (input) =>
      request(baseUrl, "/subscriptions", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    updateSubscription: (id, input) =>
      request(baseUrl, `/subscriptions/${pathSegment(id)}`, {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    deleteSubscription: (id) =>
      request(baseUrl, `/subscriptions/${pathSegment(id)}`, {
        method: "DELETE",
      }),
    refreshSubscription: (id, input) =>
      request(baseUrl, `/subscriptions/${pathSegment(id)}/refresh`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    getJob: (id) => request(baseUrl, `/jobs/${pathSegment(id)}`),
    cancelJob: (id) =>
      request(baseUrl, `/jobs/${pathSegment(id)}/cancel`, {
        method: "POST",
      }),
    getResults: (id) => request(baseUrl, `/subscriptions/${pathSegment(id)}/results`),
    getEnhanced: (id, params) => {
      const query = new URLSearchParams({
        mode: params.mode,
        format: params.format,
        valid_only: String(params.valid_only),
      });
      return request(baseUrl, `/subscriptions/${pathSegment(id)}/enhanced?${query.toString()}`);
    },
    getSettings: () => request(baseUrl, "/settings"),
    getSettingsMetadata: () => request(baseUrl, "/settings/metadata"),
    updateSettings: (input) =>
      request(baseUrl, "/settings", {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
  };
}

export function enhancedUrl(baseUrl: string, id: string, params: { mode: ExportMode; format: ExportFormat; valid_only: boolean }): string {
  const query = new URLSearchParams({
    mode: params.mode,
    format: params.format,
    valid_only: String(params.valid_only),
  });
  return joinUrl(baseUrl, `/subscriptions/${pathSegment(id)}/enhanced?${query.toString()}`);
}

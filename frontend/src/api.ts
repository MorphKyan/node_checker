import type {
  ExportFormat,
  ExportMode,
  JobStatus,
  RuntimeSettings,
  RuntimeSettingsMetadata,
  SubscriptionResults,
  SubscriptionSummary,
  SingboxTemplate,
  ApiSite,
  ApiSiteInput,
  ApiSitesConfig,
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
  getEnhanced(id: string | string[], params: { mode: ExportMode; format: ExportFormat; valid_only: boolean; limit?: number; max_risk?: number }): Promise<string>;
  getSettings(): Promise<RuntimeSettings>;
  getSettingsMetadata(): Promise<RuntimeSettingsMetadata>;
  updateSettings(input: Partial<RuntimeSettings>): Promise<RuntimeSettings>;
  getApiSites(): Promise<ApiSitesConfig>;
  getApiSiteProviders(): Promise<string[]>;
  createApiSite(input: ApiSiteInput): Promise<ApiSite>;
  updateApiSite(id: string, input: Partial<ApiSiteInput>): Promise<ApiSite>;
  deleteApiSite(id: string): Promise<{ deleted: boolean; id: string }>;
  orderApiSites(ids: string[]): Promise<ApiSite[]>;
  updateExitIpEndpoint(exit_ip_endpoint: string): Promise<{ exit_ip_endpoint: string }>;

  listSingboxTemplates(): Promise<SingboxTemplate[]>;
  getSingboxTemplate(id: string): Promise<SingboxTemplate>;
  createSingboxTemplate(input: { name: string; content: string }): Promise<SingboxTemplate>;
  updateSingboxTemplate(id: string, input: { name?: string; content?: string }): Promise<SingboxTemplate>;
  deleteSingboxTemplate(id: string): Promise<{ deleted: boolean; template_id: string }>;
  getSingboxExport(subscriptionIds: string[], templateId?: string, params?: { mode?: string; valid_only?: boolean; limit?: number; max_risk?: number }): Promise<string>;
  getSingboxExportUrl(subscriptionIds: string[], templateId?: string, params?: { mode?: string; valid_only?: boolean; limit?: number; max_risk?: number }): string;
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
    getEnhanced: (id, params) => request(baseUrl, enhancedPath(id, params)),
    getSettings: () => request(baseUrl, "/settings"),
    getSettingsMetadata: () => request(baseUrl, "/settings/metadata"),
    updateSettings: (input) =>
      request(baseUrl, "/settings", {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    getApiSites: () => request(baseUrl, "/api-sites"),
    getApiSiteProviders: () => request(baseUrl, "/api-sites/providers"),
    createApiSite: (input) => request(baseUrl, "/api-sites", { method: "POST", body: JSON.stringify(input) }),
    updateApiSite: (id, input) => request(baseUrl, `/api-sites/${pathSegment(id)}`, { method: "PATCH", body: JSON.stringify(input) }),
    deleteApiSite: (id) => request(baseUrl, `/api-sites/${pathSegment(id)}`, { method: "DELETE" }),
    orderApiSites: (ids) => request(baseUrl, "/api-sites/order", { method: "PUT", body: JSON.stringify({ ids }) }),
    updateExitIpEndpoint: (exit_ip_endpoint) => request(baseUrl, "/exit-ip-endpoint", { method: "PATCH", body: JSON.stringify({ exit_ip_endpoint }) }),

    listSingboxTemplates: () => request(baseUrl, "/singbox/templates"),
    getSingboxTemplate: (id) => request(baseUrl, `/singbox/templates/${pathSegment(id)}`),
    createSingboxTemplate: (input) =>
      request(baseUrl, "/singbox/templates", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    updateSingboxTemplate: (id, input) =>
      request(baseUrl, `/singbox/templates/${pathSegment(id)}`, {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    deleteSingboxTemplate: (id) =>
      request(baseUrl, `/singbox/templates/${pathSegment(id)}`, {
        method: "DELETE",
      }),
    getSingboxExport: (subscriptionIds, templateId, params) => {
      const query = new URLSearchParams();
      subscriptionIds.forEach((id) => query.append("subscription_id", id));
      if (templateId) query.append("template_id", templateId);
      if (params?.mode) query.append("mode", params.mode);
      if (params?.valid_only !== undefined) query.append("valid_only", String(params.valid_only));
      if (params?.limit !== undefined) query.append("limit", String(params.limit));
      if (params?.max_risk !== undefined) query.append("max_risk", String(params.max_risk));
      return request(baseUrl, `/subscriptions/singbox?${query.toString()}`);
    },
    getSingboxExportUrl: (subscriptionIds, templateId, params) => {
      return singboxUrl(baseUrl, subscriptionIds, templateId, params);
    },
  };
}

function enhancedPath(id: string | string[], params: { mode: ExportMode; format: ExportFormat; valid_only: boolean; limit?: number; max_risk?: number }): string {
  const query = new URLSearchParams();
  const ids = Array.isArray(id) ? id : [id];
  ids.forEach((subscriptionId) => query.append("subscription_id", subscriptionId));
  query.append("mode", params.mode);
  query.append("format", params.format);
  query.append("valid_only", String(params.valid_only));
  if (params.limit !== undefined) query.append("limit", String(params.limit));
  if (params.max_risk !== undefined) query.append("max_risk", String(params.max_risk));
  return `/subscriptions/enhanced?${query.toString()}`;
}

export function enhancedUrl(baseUrl: string, id: string | string[], params: { mode: ExportMode; format: ExportFormat; valid_only: boolean; limit?: number; max_risk?: number }): string {
  return joinUrl(baseUrl, enhancedPath(id, params));
}

export function singboxUrl(
  baseUrl: string,
  subscriptionIds: string[],
  templateId?: string,
  params?: { mode?: string; valid_only?: boolean; limit?: number; max_risk?: number }
): string {
  const query = new URLSearchParams();
  subscriptionIds.forEach((id) => query.append("subscription_id", id));
  if (templateId) query.append("template_id", templateId);
  if (params?.mode) query.append("mode", params.mode);
  if (params?.valid_only !== undefined) query.append("valid_only", String(params.valid_only));
  if (params?.limit !== undefined) query.append("limit", String(params.limit));
  if (params?.max_risk !== undefined) query.append("max_risk", String(params.max_risk));
  return joinUrl(baseUrl, `/subscriptions/singbox?${query.toString()}`);
}

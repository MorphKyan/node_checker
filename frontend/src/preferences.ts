import type { ExportFormat, ExportMode, LocalPreferences } from "./types";

const storageKey = "vless-node-checker.preferences";

function defaultApiBaseUrl(): string {
  if (typeof window === "undefined") return "";
  return window.location.port === "5173" ? "" : "";
}

export const defaultPreferences: LocalPreferences = {
  apiBaseUrl: defaultApiBaseUrl(),
  autoRefresh: true,
  defaultExportMode: "compact",
  defaultExportFormat: "base64",
  pageSize: 20,
};

export function loadPreferences(): LocalPreferences {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return defaultPreferences;
    return { ...defaultPreferences, ...JSON.parse(raw) };
  } catch {
    return defaultPreferences;
  }
}

export function savePreferences(preferences: LocalPreferences): void {
  localStorage.setItem(storageKey, JSON.stringify(preferences));
}

export function isExportMode(value: string): value is ExportMode {
  return value === "compact" || value === "detailed";
}

export function isExportFormat(value: string): value is ExportFormat {
  return value === "base64" || value === "plain";
}

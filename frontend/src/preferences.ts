import type { ExportMode, LocalPreferences } from "./types";

const storageKey = "node-checker.preferences";

export const defaultPreferences: LocalPreferences = {
  apiBaseUrl: "",
  autoRefresh: true,
  defaultExportMode: "compact",
  pageSize: 20,
};

export function loadPreferences(): LocalPreferences {
  try {
    const raw = localStorage.getItem(storageKey);
    // Keep existing browser preferences when upgrading the project name.
    const stored = JSON.parse(raw ?? localStorage.getItem("vless-node-checker.preferences") ?? "null");
    if (!stored) return defaultPreferences;
    const { apiBaseUrl, autoRefresh, defaultExportMode, pageSize } = { ...defaultPreferences, ...stored };
    const preferences: LocalPreferences = { apiBaseUrl, autoRefresh, defaultExportMode, pageSize };
    if (stored.autoRefreshVersion !== 1) {
      preferences.autoRefresh = true;
    }
    savePreferences(preferences);
    return preferences;
  } catch {
    return defaultPreferences;
  }
}

export function savePreferences(preferences: LocalPreferences): void {
  localStorage.setItem(storageKey, JSON.stringify({ ...preferences, autoRefreshVersion: 1 }));
}

export function isExportMode(value: string): value is ExportMode {
  return value === "compact" || value === "detailed";
}

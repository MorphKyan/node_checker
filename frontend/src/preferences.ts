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
    if (!stored || typeof stored !== "object") return { ...defaultPreferences };
    const preferences: LocalPreferences = {
      apiBaseUrl: typeof stored.apiBaseUrl === "string" ? stored.apiBaseUrl : defaultPreferences.apiBaseUrl,
      autoRefresh: stored.autoRefreshVersion === 1 && typeof stored.autoRefresh === "boolean" ? stored.autoRefresh : true,
      defaultExportMode: isExportMode(stored.defaultExportMode) ? stored.defaultExportMode : defaultPreferences.defaultExportMode,
      pageSize: Number.isSafeInteger(stored.pageSize) && stored.pageSize > 0 ? stored.pageSize : defaultPreferences.pageSize,
    };
    savePreferences(preferences);
    return preferences;
  } catch {
    return { ...defaultPreferences };
  }
}

export function savePreferences(preferences: LocalPreferences): void {
  localStorage.setItem(storageKey, JSON.stringify({ ...preferences, autoRefreshVersion: 1 }));
}

export function isExportMode(value: string): value is ExportMode {
  return value === "compact" || value === "detailed";
}

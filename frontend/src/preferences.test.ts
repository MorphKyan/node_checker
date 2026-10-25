import { afterEach, expect, it } from "vitest";
import { defaultPreferences, loadPreferences, savePreferences } from "./preferences";

afterEach(() => localStorage.clear());

it("enables polling for old preferences once and preserves subsequent choices", () => {
  localStorage.setItem("vless-node-checker.preferences", JSON.stringify({ ...defaultPreferences, autoRefresh: false, pageSize: 50 }));
  expect(loadPreferences()).toMatchObject({ autoRefresh: true, pageSize: 50 });
  savePreferences({ ...loadPreferences(), autoRefresh: false });
  expect(loadPreferences().autoRefresh).toBe(false);
});

it("migrates current legacy preferences without resetting user choices", () => {
  localStorage.setItem("vless-node-checker.preferences", JSON.stringify({
    ...defaultPreferences, autoRefresh: false, autoRefreshVersion: 1, pageSize: 50,
  }));
  expect(loadPreferences()).toMatchObject({ autoRefresh: false, pageSize: 50 });
  expect(JSON.parse(localStorage.getItem("node-checker.preferences")!)).toMatchObject({
    autoRefresh: false, pageSize: 50,
  });
  savePreferences({ ...defaultPreferences, pageSize: 10 });
  expect(loadPreferences()).toMatchObject({ autoRefresh: true, pageSize: 10 });
});

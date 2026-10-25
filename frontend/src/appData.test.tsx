import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { createApiClient } from "./api";
import { useAppData } from "./appData";
import { defaultPreferences } from "./preferences";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("polls subscriptions, results and active jobs every three seconds and respects disabling", async () => {
  vi.useFakeTimers();
  const subscriptions = [{ id: "sub", url: "https://sub.test", last_job_id: "job" }];
  const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(
    url === "/subscriptions" ? subscriptions : url.startsWith("/jobs/") ? { status: "running" } : { nodes: [] },
  ), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(["subscriptions", ""], subscriptions);
  client.setQueryData(["results", "", "sub", "https://sub.test"], { nodes: [] });
  client.setQueryData(["job", "", "job"], { status: "running" });
  const api = createApiClient("");
  const { rerender } = renderHook(({ enabled }) => useAppData(api, { ...defaultPreferences, autoRefresh: enabled }), {
    initialProps: { enabled: true },
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
  expect(fetchMock).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(fetchMock.mock.calls.map(([url]) => url).sort()).toEqual(["/jobs/job", "/subscriptions", "/subscriptions/sub/results"]);
  rerender({ enabled: false });
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  client.clear();
});

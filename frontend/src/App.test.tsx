import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the console navigation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings")) {
        return new Response(JSON.stringify({
          FILTER_CONCURRENCY: 10,
          SPEEDTEST_CONCURRENCY: 2,
          API_DEFAULT_SPEEDTEST_LIMIT: 3,
          CACHE_ENABLED: true,
          PROBE_CACHE_TTL_SECONDS: 86400,
          CACHE_FAILURE_RESULTS: false,
          SUBSCRIPTION_MAX_BYTES: 2097152,
          SPEEDTEST_MAX_BYTES: 8388608,
          SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: 64,
          SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: 96,
          TTFB_TARGET_URL: "http://example.com",
          SPEEDTEST_URL: "http://example.com/file.zip",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
    }));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("VLESS 订阅运维控制台")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /订阅管理/ })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

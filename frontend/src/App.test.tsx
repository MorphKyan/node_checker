import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import App, { NodesView } from "./App";
import type { NodeResult, SubscriptionResults } from "./types";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the console navigation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings")) {
        if (url.includes("/settings/metadata")) {
          return new Response(JSON.stringify({
            FILTER_CONCURRENCY: { type: "int", min: 1, max: 100 },
            PROBE_CACHE_TTL_SECONDS: { type: "int", min: 60 },
          }), { status: 200, headers: { "content-type": "application/json" } });
        }
        return new Response(JSON.stringify({
          FILTER_CONCURRENCY: 10,
          SPEEDTEST_CONCURRENCY: 2,
          API_DEFAULT_SPEEDTEST_LIMIT: 3,
          CACHE_ENABLED: true,
          PROBE_CACHE_TTL_SECONDS: 86400,
          CACHE_FAILURE_RESULTS: false,
          SUBSCRIPTION_MAX_M: 2,
          SPEEDTEST_MAX_M: 8,
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
  });

  it("shows mutation errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/settings")) {
        if (url.includes("/settings/metadata")) {
          return new Response(JSON.stringify({
            FILTER_CONCURRENCY: { type: "int", min: 1, max: 100 },
          }), { status: 200, headers: { "content-type": "application/json" } });
        }
        return new Response(JSON.stringify({
          FILTER_CONCURRENCY: 10,
          SPEEDTEST_CONCURRENCY: 2,
          API_DEFAULT_SPEEDTEST_LIMIT: 3,
          CACHE_ENABLED: true,
          PROBE_CACHE_TTL_SECONDS: 86400,
          CACHE_FAILURE_RESULTS: false,
          SUBSCRIPTION_MAX_M: 2,
          SPEEDTEST_MAX_M: 8,
          SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: 64,
          SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: 96,
          TTFB_TARGET_URL: "http://example.com",
          SPEEDTEST_URL: "http://example.com/file.zip",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/subscriptions") && init?.method === "POST") {
        return new Response(JSON.stringify({ detail: "Subscription source not found" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
    }));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /订阅管理/ }));
    fireEvent.change(screen.getByPlaceholderText("订阅 URL 或本地文件路径"), { target: { value: "missing.txt" } });
    fireEvent.click(screen.getByRole("button", { name: /添加并检测/ }));

    expect(await screen.findByText("404: Subscription source not found")).toBeInTheDocument();
  });

  it("applies settings metadata to numeric inputs", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings/metadata")) {
        return new Response(JSON.stringify({
          FILTER_CONCURRENCY: { type: "int", min: 1, max: 100 },
          PROBE_CACHE_TTL_SECONDS: { type: "int", min: 60 },
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/settings")) {
        return new Response(JSON.stringify({
          FILTER_CONCURRENCY: 10,
          SPEEDTEST_CONCURRENCY: 2,
          API_DEFAULT_SPEEDTEST_LIMIT: 3,
          CACHE_ENABLED: true,
          PROBE_CACHE_TTL_SECONDS: 86400,
          CACHE_FAILURE_RESULTS: false,
          SUBSCRIPTION_MAX_M: 2,
          SPEEDTEST_MAX_M: 8,
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

    fireEvent.click(await screen.findByRole("button", { name: /设置/ }));
    const filterInput = await screen.findByLabelText("过滤并发");
    const speedtestLimitInput = screen.getByLabelText("每区域默认测速数量");
    const ttlInput = screen.getByLabelText("缓存 TTL 秒");

    expect(filterInput).toHaveAttribute("min", "1");
    expect(filterInput).toHaveAttribute("max", "100");
    expect(speedtestLimitInput).toBeInTheDocument();
    expect(ttlInput).toHaveAttribute("min", "60");
    expect(ttlInput).not.toHaveAttribute("max");
  });

  it("opens the API sites page", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api-sites/providers")) return new Response(JSON.stringify(["ipwhois"]), { status: 200, headers: { "content-type": "application/json" } });
      if (url.includes("/api-sites")) return new Response(JSON.stringify({ exit_ip_endpoint: "https://ip.example", sites: [] }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "API 站点" }));
    expect(await screen.findByDisplayValue("https://ip.example")).toBeInTheDocument();
  });

  it("operates API-site controls and speed refresh from the UI", async () => {
    let endpoint = "https://old-exit.example";
    let sites = [
      { id: "alpha", column_name: "Alpha", provider: "ipwhois", url_template: "https://alpha.example/{ip}", weight: 1, enabled: true, order: 0, api_key_configured: true },
      { id: "beta", column_name: "Beta", provider: "ipwhois", url_template: "https://beta.example/{ip}", weight: 1, enabled: false, order: 1, api_key_configured: false },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (url.includes("/settings/metadata")) return new Response(JSON.stringify({}), { status: 200, headers: { "content-type": "application/json" } });
      if (url.includes("/settings")) return new Response(JSON.stringify({}), { status: 200, headers: { "content-type": "application/json" } });
      if (url.endsWith("/subscriptions") && method === "GET") return new Response(JSON.stringify([{ id: "sub_1", name: "Demo", url: "https://sub.example", last_status: "completed", node_count: 0, valid_count: 0, updated_at: 1, last_job_id: null }]), { status: 200, headers: { "content-type": "application/json" } });
      if (url.endsWith("/subscriptions/sub_1/results")) return new Response(JSON.stringify({ subscription_id: "sub_1", status: "completed", subscription_status: "completed", node_count: 0, valid_count: 0, updated_at: 1, nodes: [], api_sites_snapshot: [] }), { status: 200, headers: { "content-type": "application/json" } });
      if (url.includes("/api-sites/providers")) return new Response(JSON.stringify(["ipwhois"]), { status: 200, headers: { "content-type": "application/json" } });
      if (url.endsWith("/api-sites") && method === "GET") return new Response(JSON.stringify({ exit_ip_endpoint: endpoint, sites }), { status: 200, headers: { "content-type": "application/json" } });
      if (url.endsWith("/api-sites") && method === "POST") {
        sites = [...sites, { ...body, order: sites.length, api_key_configured: Boolean(body.api_key) }];
        return new Response(JSON.stringify(sites.at(-1)), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/api-sites/") && method === "PATCH") {
        const id = url.split("/").at(-1)!;
        sites = sites.map((site) => site.id === id ? { ...site, ...body, api_key_configured: body.clear_api_key ? false : site.api_key_configured } : site);
        return new Response(JSON.stringify(sites.find((site) => site.id === id)), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/api-sites/order") && method === "PUT") {
        sites = body.ids.map((id: string, order: number) => ({ ...sites.find((site) => site.id === id)!, order }));
        return new Response(JSON.stringify(sites), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/exit-ip-endpoint") && method === "PATCH") {
        endpoint = body.exit_ip_endpoint;
        return new Response(JSON.stringify({ exit_ip_endpoint: endpoint }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/api-sites/") && method === "DELETE") {
        sites = sites.filter((site) => site.id !== url.split("/").at(-1));
        return new Response(JSON.stringify({ deleted: true }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/refresh") && method === "POST") return new Response(JSON.stringify({ subscription_id: "sub_1", job_id: "job_1", status: "queued" }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify([]), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><App /></QueryClientProvider>);

    fireEvent.click(screen.getByRole("button", { name: /API/ }));
    await screen.findByDisplayValue(endpoint);
    fireEvent.change(screen.getByDisplayValue(endpoint), { target: { value: "https://saved-exit.example" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    fireEvent.change(screen.getByPlaceholderText("唯一 ID"), { target: { value: "created" } });
    fireEvent.change(screen.getByPlaceholderText("表格列名"), { target: { value: "Created" } });
    fireEvent.change(screen.getByPlaceholderText("URL 模板，必须含 {ip}"), { target: { value: "https://created.example/{ip}" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api-sites") && (init as RequestInit).method === "POST")).toBe(true));

    fireEvent.click(screen.getAllByRole("button", { name: "编辑" })[0]);
    fireEvent.click(screen.getByLabelText("清除 Key"));
    fireEvent.click(screen.getAllByRole("button", { name: "保存" })[1]);
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getAllByRole("button", { name: "↓" })[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api-sites/order") && (init as RequestInit).method === "PUT")).toBe(true));
    const alphaRow = screen.getByText("Alpha").closest("tr");
    fireEvent.click(alphaRow!.querySelectorAll("button")[3]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/api-sites/alpha") && (init as RequestInit).method === "DELETE")).toBe(true));
    await waitFor(() => expect(screen.queryByText("Alpha")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /订阅管理/ }));
    const speedInput = await screen.findByTitle("每区域测速数量");
    fireEvent.change(speedInput, { target: { value: "3" } });
    fireEvent.click(screen.getByLabelText("强制探测"));
    fireEvent.click(screen.getByRole("button", { name: "测速刷新" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/subscriptions/sub_1/refresh") && String((init as RequestInit).body) === JSON.stringify({ speedtest_limit: 3, force_probe: true }))).toBe(true));

    const apiMutations = fetchMock.mock.calls.filter(([url, init]) => String(url).includes("api-sites") && (init as RequestInit).method !== "GET");
    expect(apiMutations.some(([, init]) => String((init as RequestInit).body).includes("clear_api_key"))).toBe(true);
    expect(apiMutations.some(([, init]) => (init as RequestInit).method === "PATCH" && String((init as RequestInit).body).includes("enabled"))).toBe(true);
    expect(apiMutations.some(([url, init]) => String(url).endsWith("/api-sites/alpha") && (init as RequestInit).method === "DELETE")).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/exit-ip-endpoint"))).toBe(true);
  });

  it("aligns API snapshot headers with their node cells", () => {
    const node: NodeResult = {
      fingerprint: "fp", original_name: "node", enhanced_name_compact: "node", enhanced_name_detailed: "node", raw_uri: "vless://x", compact_uri: "vless://x", detailed_uri: "vless://x", is_valid: true, reject_reason: "", download_speed_mbps: null, speedtest_status: "not_tested",
      probe: { tcp_ping_ms: 1, ttfb_ms: 2, actual_ip: "1.1.1.1", actual_geo: "US", asn_org: "asn", ipv6_support: false, actual_ipv6: "", risk_score: 10, network_labels: [], type_labels: [], confidence: "low", is_detour: false, is_backbone: false, backbone_info: "", evidence: [{ source: "One", site_id: "one", status: "success", network_labels: [], risk_labels: [], risk_score: 12, raw_summary: "" }, { source: "Two", site_id: "two", status: "timeout", network_labels: [], risk_labels: [], risk_score: null, raw_summary: "" }] },
    };
    const result: SubscriptionResults = { subscription_id: "sub", status: "completed", subscription_status: "completed", node_count: 1, valid_count: 1, updated_at: 1, nodes: [node], api_sites_snapshot: [{ id: "one", column_name: "One", provider: "ipwhois", url_template: "https://x/{ip}", weight: 1, enabled: true, order: 0, api_key_configured: false }, { id: "two", column_name: "Two", provider: "ipapi", url_template: "https://x/{ip}", weight: 1, enabled: true, order: 1, api_key_configured: false }] };
    render(<NodesView subscriptions={[]} selectedId="sub" result={result} filteredNodes={[node]} pagedNodes={[node]} page={1} totalPages={1} pageSize={20} geoOptions={[]} networkOptions={[]} typeOptions={[]} filters={{ nodeSearch: "", nodeValidity: "all", nodeGeo: "all", nodeNetwork: "all", nodeType: "all", maxRisk: "", maxTtfb: "", minSpeed: "", detourFilter: "all", backboneFilter: "all" }} onSelectSubscription={() => {}} onFilters={() => {}} onPage={() => {}} onDetails={() => {}} />);
    const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(headers.slice(0, 2)).toEqual(["One", "Two"]);
    const cells = screen.getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells.slice(0, 2)).toEqual(["-风险 12", "timeout"]);
  });
});

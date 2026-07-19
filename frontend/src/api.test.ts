import { describe, expect, it, vi } from "vitest";
import { createApiClient, enhancedUrl } from "./api";

describe("api client", () => {
  it("lists subscriptions", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([{ id: "sub_1", name: "demo" }]), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("http://api.local");
    const result = await client.listSubscriptions();

    expect(result[0].id).toBe("sub_1");
    expect(fetch).toHaveBeenCalledWith("http://api.local/subscriptions", expect.any(Object));
    vi.unstubAllGlobals();
  });

  it("builds enhanced subscription URLs", () => {
    expect(enhancedUrl("", "sub_1", { mode: "detailed", format: "plain", valid_only: false, limit: 20 })).toBe(
      "/subscriptions/enhanced?subscription_id=sub_1&mode=detailed&format=plain&valid_only=false&limit=20",
    );
    expect(enhancedUrl("", ["sub_1", "sub_2"], { mode: "compact", format: "base64", valid_only: true })).toBe(
      "/subscriptions/enhanced?subscription_id=sub_1&subscription_id=sub_2&mode=compact&format=base64&valid_only=true",
    );
  });

  it("passes enhanced export limits to preview requests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("payload", {
      status: 200,
      headers: { "content-type": "text/plain" },
    })));

    const client = createApiClient("http://api.local");
    const result = await client.getEnhanced("sub_1", {
      mode: "compact",
      format: "base64",
      valid_only: true,
      limit: 10,
    });

    expect(result).toBe("payload");
    expect(fetch).toHaveBeenCalledWith(
      "http://api.local/subscriptions/enhanced?subscription_id=sub_1&mode=compact&format=base64&valid_only=true&limit=10",
      expect.any(Object),
    );
    vi.unstubAllGlobals();
  });

  it("passes multiple subscriptions to enhanced preview requests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("payload", {
      status: 200,
      headers: { "content-type": "text/plain" },
    })));

    const client = createApiClient("http://api.local");
    const result = await client.getEnhanced(["sub_1", "sub_2"], {
      mode: "compact",
      format: "base64",
      valid_only: true,
    });

    expect(result).toBe("payload");
    expect(fetch).toHaveBeenCalledWith(
      "http://api.local/subscriptions/enhanced?subscription_id=sub_1&subscription_id=sub_2&mode=compact&format=base64&valid_only=true",
      expect.any(Object),
    );
    vi.unstubAllGlobals();
  });

  it("loads settings metadata", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      FILTER_CONCURRENCY: { type: "int", min: 1, max: 100 },
    }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("http://api.local");
    const result = await client.getSettingsMetadata();

    expect(result.FILTER_CONCURRENCY?.min).toBe(1);
    expect(fetch).toHaveBeenCalledWith("http://api.local/settings/metadata", expect.any(Object));
    vi.unstubAllGlobals();
  });

  it("manages API sites without exposing keys", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ sites: [{ id: "ipwhois", api_key_configured: true }], exit_ip_endpoint: "https://ip.example" }), {
      status: 200, headers: { "content-type": "application/json" },
    })));
    const client = createApiClient("http://api.local");
    const result = await client.getApiSites();
    expect(result.sites[0].api_key_configured).toBe(true);
    expect(fetch).toHaveBeenCalledWith("http://api.local/api-sites", expect.any(Object));
    vi.unstubAllGlobals();
  });

  it("sends API-site CRUD, ordering, key clear, endpoint, and speed-refresh requests", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: "site", deleted: true, exit_ip_endpoint: "https://exit.example", job_id: "job", subscription_id: "sub", status: "queued" }), {
      status: 200, headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const client = createApiClient("http://api.local");

    await client.createApiSite({ id: "site", column_name: "Site", provider: "ipwhois", url_template: "https://site.example/{ip}?key={key}", api_key: "secret", weight: 1, enabled: true });
    await client.updateApiSite("site", { clear_api_key: true, enabled: false });
    await client.orderApiSites(["site", "other"]);
    await client.updateExitIpEndpoint("https://exit.example");
    await client.deleteApiSite("site");
    await client.refreshSubscription("sub", { speedtest_limit: 2, force_probe: true });

    const requests = (fetchMock.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit]>).map(([url, init]) => ({ url, method: init.method, body: init.body }));
    expect(requests).toEqual([
      { url: "http://api.local/api-sites", method: "POST", body: JSON.stringify({ id: "site", column_name: "Site", provider: "ipwhois", url_template: "https://site.example/{ip}?key={key}", api_key: "secret", weight: 1, enabled: true }) },
      { url: "http://api.local/api-sites/site", method: "PATCH", body: JSON.stringify({ clear_api_key: true, enabled: false }) },
      { url: "http://api.local/api-sites/order", method: "PUT", body: JSON.stringify({ ids: ["site", "other"] }) },
      { url: "http://api.local/exit-ip-endpoint", method: "PATCH", body: JSON.stringify({ exit_ip_endpoint: "https://exit.example" }) },
      { url: "http://api.local/api-sites/site", method: "DELETE", body: undefined },
      { url: "http://api.local/subscriptions/sub/refresh", method: "POST", body: JSON.stringify({ speedtest_limit: 2, force_probe: true }) },
    ]);
    vi.unstubAllGlobals();
  });

  it("cancels jobs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      job_id: "job_1",
      subscription_id: "sub_1",
      status: "canceled",
      phase: "canceled",
      processed_nodes: 0,
      total_nodes: 0,
      error: "Canceled by user",
      created_at: 1,
      started_at: null,
      finished_at: 2,
    }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("http://api.local");
    const result = await client.cancelJob("job_1");

    expect(result.status).toBe("canceled");
    expect(fetch).toHaveBeenCalledWith("http://api.local/jobs/job_1/cancel", expect.objectContaining({ method: "POST" }));
    vi.unstubAllGlobals();
  });

  it("encodes path parameters", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ nodes: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("");
    await client.getResults("sub/with space");

    expect(fetch).toHaveBeenCalledWith("/subscriptions/sub%2Fwith%20space/results", expect.any(Object));
    expect(enhancedUrl("", "sub/with space", { mode: "compact", format: "base64", valid_only: true })).toBe(
      "/subscriptions/enhanced?subscription_id=sub%2Fwith+space&mode=compact&format=base64&valid_only=true",
    );
    vi.unstubAllGlobals();
  });

  it("formats validation error detail arrays", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      detail: [{ loc: ["body", "speedtest_limit"], msg: "Input should be less than or equal to 100" }],
    }), {
      status: 422,
      statusText: "Unprocessable Entity",
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("");

    await expect(client.refreshSubscription("sub_1", { speedtest_limit: 101 })).rejects.toThrow(
      "body.speedtest_limit: Input should be less than or equal to 100",
    );
    vi.unstubAllGlobals();
  });

  it("formats object and plain text errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      detail: { message: "Subscription not found" },
    }), {
      status: 404,
      statusText: "Not Found",
      headers: { "content-type": "application/json" },
    })));

    const client = createApiClient("");
    await expect(client.getSubscription("missing")).rejects.toThrow("Subscription not found");

    vi.stubGlobal("fetch", vi.fn(async () => new Response("upstream failed", {
      status: 500,
      statusText: "Server Error",
    })));
    await expect(client.getSubscription("missing")).rejects.toThrow("upstream failed");
    vi.unstubAllGlobals();
  });
});

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
    expect(enhancedUrl("", "sub_1", { mode: "detailed", format: "plain", valid_only: false })).toBe(
      "/subscriptions/sub_1/enhanced?mode=detailed&format=plain&valid_only=false",
    );
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
      "/subscriptions/sub%2Fwith%20space/enhanced?mode=compact&format=base64&valid_only=true",
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

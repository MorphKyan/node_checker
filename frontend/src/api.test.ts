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
});

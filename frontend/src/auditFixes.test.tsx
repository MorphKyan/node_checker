import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}

function renderConsole(preview: (url: URL) => Promise<Response>) {
  const subscriptions = ["a", "b"].map((id) => ({ id, name: `订阅 ${id.toUpperCase()}`, url: `https://${id}.test`, last_status: "completed", node_count: 0, valid_count: 0, updated_at: 1, last_job_id: null }));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin);
    if (url.pathname === "/subscriptions/enhanced") return preview(url);
    if (url.pathname === "/subscriptions") return jsonResponse(subscriptions);
    if (url.pathname.endsWith("/results")) return jsonResponse({ subscription_id: url.pathname.split("/")[2], nodes: [], node_count: 0, valid_count: 0, updated_at: 1, api_sites_snapshot: [] });
    if (url.pathname === "/api-sites") return jsonResponse({ exit_ip_endpoint: "https://exit.test", sites: [] });
    if (url.pathname.startsWith("/settings")) return jsonResponse({});
    return jsonResponse([]);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
}

describe("audit export fixes", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("ties enhanced content to the current subscription and options, ignoring late responses", async () => {
    let resolveOld!: (response: Response) => void;
    const delayed = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const preview = vi.fn(async (url: URL) => {
      const id = url.searchParams.get("subscription_id");
      const mode = url.searchParams.get("mode");
      if (id === "b" && mode === "compact") return delayed;
      return new Response(`${id}-${mode}`);
    });
    renderConsole(preview);
    expect(screen.queryByRole("button", { name: "Sing-box 配置" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "增强订阅" }));
    expect(screen.getAllByRole("combobox")).toHaveLength(3);
    await screen.findByRole("option", { name: "订阅 A" });
    await waitFor(() => expect(screen.getByRole("button", { name: "预览" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await screen.findByDisplayValue("a-compact");
    expect(screen.getByRole("button", { name: "下载" })).toBeEnabled();

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "b" } });
    expect(screen.getByRole("button", { name: "复制内容" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "detailed" } });
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await screen.findByDisplayValue("b-detailed");
    await act(async () => { resolveOld(new Response("obsolete-b-compact")); await delayed; });
    expect(screen.getByDisplayValue("b-detailed")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("obsolete-b-compact")).not.toBeInTheDocument();

    fireEvent.change(screen.getAllByRole("combobox")[2], { target: { value: "false" } });
    expect(screen.getByRole("button", { name: "下载" })).toBeDisabled();
  });
});

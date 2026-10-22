import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { stripComments } from "./appUtils";

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}

function renderConsole(preview: (url: URL) => Promise<Response>) {
  const subscriptions = ["a", "b"].map((id) => ({ id, name: `订阅 ${id.toUpperCase()}`, url: `https://${id}.test`, last_status: "completed", node_count: 0, valid_count: 0, updated_at: 1, last_job_id: null }));
  const templates = ["a", "b"].map((id) => ({ id, name: `模板 ${id.toUpperCase()}`, content: '{/* first\nsecond */ "outbounds": []}', created_at: 1, updated_at: 1 }));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), window.location.origin);
    if (["/subscriptions/enhanced", "/subscriptions/singbox"].includes(url.pathname)) return preview(url);
    if (url.pathname === "/subscriptions") return jsonResponse(subscriptions);
    if (url.pathname.endsWith("/results")) return jsonResponse({ subscription_id: url.pathname.split("/")[2], nodes: [], node_count: 0, valid_count: 0, updated_at: 1, api_sites_snapshot: [] });
    if (url.pathname === "/singbox/templates") return jsonResponse(templates);
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
    fireEvent.click(screen.getByRole("button", { name: "增强订阅" }));
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

    fireEvent.change(screen.getAllByRole("combobox")[2], { target: { value: "plain" } });
    expect(screen.getByRole("button", { name: "下载" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await screen.findByDisplayValue("b-detailed");
    fireEvent.change(screen.getAllByRole("combobox")[3], { target: { value: "false" } });
    expect(screen.getByRole("button", { name: "下载" })).toBeDisabled();
  });

  it("ties sing-box content to the template, filters and sources, ignoring late responses", async () => {
    let resolveOld!: (response: Response) => void;
    const delayed = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const preview = vi.fn(async (url: URL) => {
      const template = url.searchParams.get("template_id");
      if (template === "a" && url.searchParams.has("max_risk")) return delayed;
      return jsonResponse({ template });
    });
    renderConsole(preview);
    fireEvent.click(screen.getByRole("button", { name: "Sing-box 配置" }));
    await screen.findByText("模板 A");
    await screen.findByText("JSON 语法正确");
    fireEvent.click(screen.getByRole("button", { name: "配置预览与导出" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "预览生成配置" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "预览生成配置" }));
    await screen.findByDisplayValue(/"template": "a"/);
    expect(screen.getByRole("button", { name: "下载 JSON" })).toBeEnabled();

    fireEvent.change(screen.getByPlaceholderText("0-100"), { target: { value: "50" } });
    expect(screen.queryByRole("button", { name: "下载 JSON" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "预览生成配置" }));
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByText("模板 B"));
    fireEvent.click(screen.getByRole("button", { name: "预览生成配置" }));
    await screen.findByDisplayValue(/"template": "b"/);
    await act(async () => { resolveOld(jsonResponse({ template: "obsolete-a" })); await delayed; });
    expect(screen.getByDisplayValue(/"template": "b"/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/"template": "obsolete-a"/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("订阅 B"));
    expect(screen.queryByRole("button", { name: "复制内容" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载 JSON" })).not.toBeInTheDocument();
  });

  it("preserves escaped strings while stripping multiline and line comments", () => {
    const value = { path: "C:\\cache\\", url: "https://example.test", quote: '\\" /* keep */ // keep' };
    expect(JSON.parse(stripComments(`/* first\nsecond */\n${JSON.stringify(value)} // tail`))).toEqual(value);
    expect(() => JSON.parse(stripComments('{"value": 1/* comment */2}'))).toThrow();
  });
});

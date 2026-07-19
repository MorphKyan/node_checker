import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  ChevronDown,
  Clipboard,
  Download,
  ExternalLink,
  FileDown,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Network,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
  Trash2,
  XCircle,
  AlertTriangle,
  FileCode,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, createApiClient, enhancedUrl, singboxUrl } from "./api";
import type { ApiClient } from "./api";
import { useAppData } from "./appData";
import { duration, formatTime, groupCount, riskBuckets, statusTone } from "./appUtils";
import { filterNodes } from "./nodeFilters";
import { defaultPreferences, isExportFormat, isExportMode, loadPreferences, savePreferences } from "./preferences";
import type {
  ApiVerdict,
  ExportFormat,
  ExportMode,
  JobStatus,
  LocalPreferences,
  NodeResult,
  RuntimeSettings,
  RuntimeSettingsMetadata,
  SubscriptionResults,
  SubscriptionSummary,
  SingboxTemplate,
  ApiSite,
  ApiSiteInput,
} from "./types";
import { Badge, Button, EmptyState, Input, Label, Panel, Select } from "./components/ui";

type View = "dashboard" | "subscriptions" | "nodes" | "jobs" | "export" | "settings" | "singbox" | "api-sites";

const navItems: Array<{ id: View; label: string; icon: typeof LayoutDashboard }> = [
  { id: "dashboard", label: "总览", icon: LayoutDashboard },
  { id: "subscriptions", label: "订阅管理", icon: ListChecks },
  { id: "nodes", label: "节点详情", icon: Network },
  { id: "jobs", label: "任务监控", icon: Activity },
  { id: "export", label: "增强订阅", icon: FileDown },
  { id: "singbox", label: "Sing-box 配置", icon: FileCode },
  { id: "settings", label: "设置", icon: Settings },
];

const chartColors = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#64748b"];

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (e) {
      console.warn("Failed to copy using clipboard API, trying fallback:", e);
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand("copy");
  } catch (err) {
    console.error("Fallback copy failed:", err);
  }
  document.body.removeChild(textArea);
}

function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return "操作失败";
}

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [preferences, setPreferencesState] = useState<LocalPreferences>(() => loadPreferences());
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<string>("");
  const [nodeSearch, setNodeSearch] = useState("");
  const [nodeValidity, setNodeValidity] = useState("all");
  const [nodeGeo, setNodeGeo] = useState("all");
  const [nodeNetwork, setNodeNetwork] = useState("all");
  const [nodeType, setNodeType] = useState("all");
  const [maxTtfb, setMaxTtfb] = useState("");
  const [maxRisk, setMaxRisk] = useState("");
  const [minSpeed, setMinSpeed] = useState("");
  const [detourFilter, setDetourFilter] = useState("all");
  const [backboneFilter, setBackboneFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [detailsNode, setDetailsNode] = useState<NodeResult | null>(null);
  const [exportMode, setExportMode] = useState<ExportMode>(preferences.defaultExportMode);
  const [exportFormat, setExportFormat] = useState<ExportFormat>(preferences.defaultExportFormat);
  const [exportValidOnly, setExportValidOnly] = useState(true);
  const [exportPreview, setExportPreview] = useState("");
  const [subscriptionForm, setSubscriptionForm] = useState({ name: "", url: "" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [operationError, setOperationError] = useState("");

  const queryClient = useQueryClient();
  const api = useMemo(() => createApiClient(preferences.apiBaseUrl), [preferences.apiBaseUrl]);
  const apiSites = useQuery({ queryKey: ["api-sites", preferences.apiBaseUrl], queryFn: api.getApiSites });
  const providers = useQuery({ queryKey: ["api-site-providers", preferences.apiBaseUrl], queryFn: api.getApiSiteProviders });
  const { subscriptions, results, jobs } = useAppData(api, preferences);
  const subscriptionList = subscriptions.data || [];

  const selectedSubscription = subscriptionList.find((item) => item.id === selectedSubscriptionId) || subscriptionList[0];
  const effectiveSubscriptionId = selectedSubscription?.id || "";
  const resultById = new Map<string, SubscriptionResults | null>();
  subscriptionList.forEach((subscription, index) => {
    resultById.set(subscription.id, (results[index]?.data as SubscriptionResults | null | undefined) || null);
  });
  const selectedResult = effectiveSubscriptionId ? resultById.get(effectiveSubscriptionId) || null : null;
  const allResults = Array.from(resultById.values()).filter(Boolean) as SubscriptionResults[];
  const allNodes = allResults.flatMap((result) => result.nodes);
  const jobList = jobs.map((job) => job.data).filter(Boolean) as JobStatus[];

  const runningJobs = jobList.filter((job) => job.status === "queued" || job.status === "running");
  const knownRiskNodes = allNodes.filter((node) => node.probe.risk_score !== null);
  const averageRisk = knownRiskNodes.length ? knownRiskNodes.reduce((sum, node) => sum + (node.probe.risk_score || 0), 0) / knownRiskNodes.length : null;
  const averageTtfb = allNodes.length ? allNodes.reduce((sum, node) => sum + node.probe.ttfb_ms, 0) / allNodes.length : 0;
  const maxSpeed = allNodes.reduce((max, node) => Math.max(max, node.download_speed_mbps || 0), 0);

  const nodeFilters = { nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, maxRisk, maxTtfb, minSpeed, detourFilter, backboneFilter };
  const filteredNodes = useMemo(
    () => filterNodes(selectedResult?.nodes || [], nodeFilters),
    [selectedResult, nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, maxRisk, maxTtfb, minSpeed, detourFilter, backboneFilter],
  );

  const totalPages = Math.max(1, Math.ceil(filteredNodes.length / preferences.pageSize));
  const pagedNodes = filteredNodes.slice((page - 1) * preferences.pageSize, page * preferences.pageSize);

  const createSubscription = useMutation({
    mutationFn: api.createSubscription,
    onSuccess: (response) => {
      setOperationError("");
      setSubscriptionForm({ name: "", url: "" });
      setSelectedSubscriptionId(response.subscription_id);
      setView("jobs");
      void queryClient.invalidateQueries();
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const updateSubscription = useMutation({
    mutationFn: ({ id, input }: { id: string; input: { name?: string; url?: string } }) => api.updateSubscription(id, input),
    onSuccess: () => {
      setOperationError("");
      setEditingId(null);
      setSubscriptionForm({ name: "", url: "" });
      void queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const deleteSubscription = useMutation({
    mutationFn: api.deleteSubscription,
    onSuccess: () => {
      setOperationError("");
      setSelectedSubscriptionId("");
      void queryClient.invalidateQueries();
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const refreshSubscription = useMutation({
    mutationFn: ({ id, speedtest_limit, force_probe }: { id: string; speedtest_limit?: number; force_probe?: boolean }) =>
      api.refreshSubscription(id, { speedtest_limit, force_probe }),
    onSuccess: () => {
      setOperationError("");
      setView("jobs");
      void queryClient.invalidateQueries();
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });
  const refreshApiSites = () => void queryClient.invalidateQueries({ queryKey: ["api-sites"] });
  const createApiSite = useMutation({ mutationFn: api.createApiSite, onSuccess: refreshApiSites, onError: (error) => setOperationError(errorMessage(error)) });
  const updateApiSite = useMutation({ mutationFn: ({ id, input }: { id: string; input: Partial<ApiSiteInput> }) => api.updateApiSite(id, input), onSuccess: refreshApiSites, onError: (error) => setOperationError(errorMessage(error)) });
  const deleteApiSite = useMutation({ mutationFn: api.deleteApiSite, onSuccess: refreshApiSites, onError: (error) => setOperationError(errorMessage(error)) });
  const orderApiSites = useMutation({ mutationFn: api.orderApiSites, onSuccess: refreshApiSites, onError: (error) => setOperationError(errorMessage(error)) });
  const updateExitIpEndpoint = useMutation({ mutationFn: api.updateExitIpEndpoint, onSuccess: refreshApiSites, onError: (error) => setOperationError(errorMessage(error)) });

  const cancelJob = useMutation({
    mutationFn: api.cancelJob,
    onSuccess: () => {
      setOperationError("");
      void queryClient.invalidateQueries();
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const settingsQuery = useQuery({
    queryKey: ["settings", preferences.apiBaseUrl],
    queryFn: api.getSettings,
  });
  const settingsMetadataQuery = useQuery({
    queryKey: ["settings-metadata", preferences.apiBaseUrl],
    queryFn: api.getSettingsMetadata,
  });

  const updateSettings = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      setOperationError("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const singboxTemplatesQuery = useQuery({
    queryKey: ["singbox-templates", preferences.apiBaseUrl],
    queryFn: api.listSingboxTemplates,
  });
  const templates = singboxTemplatesQuery.data || [];

  const createTemplate = useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      api.createSingboxTemplate({ name, content }),
    onSuccess: () => {
      setOperationError("");
      void queryClient.invalidateQueries({ queryKey: ["singbox-templates"] });
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const updateTemplate = useMutation({
    mutationFn: ({ id, name, content }: { id: string; name?: string; content?: string }) =>
      api.updateSingboxTemplate(id, { name, content }),
    onSuccess: () => {
      setOperationError("");
      void queryClient.invalidateQueries({ queryKey: ["singbox-templates"] });
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  const deleteTemplate = useMutation({
    mutationFn: (id: string) => api.deleteSingboxTemplate(id),
    onSuccess: () => {
      setOperationError("");
      void queryClient.invalidateQueries({ queryKey: ["singbox-templates"] });
    },
    onError: (error) => setOperationError(errorMessage(error)),
  });

  function setPreferences(next: LocalPreferences) {
    setPreferencesState(next);
    savePreferences(next);
  }

  async function previewExport() {
    if (!effectiveSubscriptionId) return;
    try {
      const content = await api.getEnhanced(effectiveSubscriptionId, {
        mode: exportMode,
        format: exportFormat,
        valid_only: exportValidOnly,
      });
      setOperationError("");
      setExportPreview(content);
    } catch (error) {
      setOperationError(errorMessage(error));
    }
  }

  const geoOptions = Array.from(new Set((selectedResult?.nodes || []).map((node) => node.probe.actual_geo).filter(Boolean)));
  const networkOptions = Array.from(new Set((selectedResult?.nodes || []).flatMap((node) => node.probe.network_labels)));
  const typeOptions = Array.from(new Set((selectedResult?.nodes || []).flatMap((node) => node.probe.type_labels)));

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="fixed inset-y-0 left-0 w-60 border-r border-border bg-white">
        <div className="border-b border-border px-5 py-5">
          <div className="text-lg font-semibold text-slate-950">Node Console</div>
          <div className="mt-1 text-xs text-slate-500">VLESS 订阅运维控制台</div>
        </div>
        <nav className="space-y-1 p-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className={`flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium transition ${
                  view === item.id ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
          <button onClick={() => setView("api-sites")} className={`flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium transition ${view === "api-sites" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>
            <SlidersHorizontal className="h-4 w-4" />API 站点
          </button>
        </nav>
      </aside>

      <main className="ml-60 min-h-screen flex-1">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-border bg-white/95 px-6 backdrop-blur">
          <div>
            <div className="text-sm font-medium text-slate-900">API {subscriptions.isError ? "异常" : "在线"}</div>
            <div className="text-xs text-slate-500">{preferences.apiBaseUrl || "同源 API"} · {preferences.autoRefresh ? "自动刷新开启" : "自动刷新关闭"}</div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => void queryClient.invalidateQueries()}>
              <RefreshCw className="h-4 w-4" />
              刷新数据
            </Button>
            <Button variant={preferences.autoRefresh ? "primary" : "secondary"} onClick={() => setPreferences({ ...preferences, autoRefresh: !preferences.autoRefresh })}>
              {preferences.autoRefresh ? "暂停轮询" : "开启轮询"}
            </Button>
          </div>
        </header>

        <div className="space-y-5 p-6">
          {operationError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {operationError}
            </div>
          )}

          {view === "dashboard" && (
            <Dashboard
              subscriptions={subscriptionList}
              nodes={allNodes}
              runningJobs={runningJobs.length}
              averageRisk={averageRisk}
              averageTtfb={averageTtfb}
              maxSpeed={maxSpeed}
            />
          )}

          {view === "subscriptions" && (
            <SubscriptionsView
              subscriptions={subscriptionList}
              form={subscriptionForm}
              editingId={editingId}
              onFormChange={setSubscriptionForm}
              onCreate={() => createSubscription.mutate(subscriptionForm)}
              onStartEdit={(subscription) => {
                setEditingId(subscription.id);
                setSubscriptionForm({ name: subscription.name, url: subscription.url });
              }}
              onCancelEdit={() => {
                setEditingId(null);
                setSubscriptionForm({ name: "", url: "" });
              }}
              onSaveEdit={() => editingId && updateSubscription.mutate({ id: editingId, input: subscriptionForm })}
              onDelete={(id) => deleteSubscription.mutate(id)}
              onRefresh={(id, speedtest_limit, force_probe) => refreshSubscription.mutate({ id, speedtest_limit, force_probe })}
              onOpenNodes={(id) => {
                setSelectedSubscriptionId(id);
                setView("nodes");
              }}
              onOpenExport={(id) => {
                setSelectedSubscriptionId(id);
                setView("export");
              }}
            />
          )}

          {view === "api-sites" && <ApiSitesView sites={apiSites.data?.sites || []} exitIpEndpoint={apiSites.data?.exit_ip_endpoint || ""} providers={providers.data || []} onCreate={(input) => createApiSite.mutate(input)} onUpdate={(id, input) => updateApiSite.mutate({ id, input })} onDelete={(id) => deleteApiSite.mutate(id)} onOrder={(ids) => orderApiSites.mutate(ids)} onUpdateEndpoint={(value) => updateExitIpEndpoint.mutate(value)} />}

          {view === "nodes" && (
            <NodesView
              subscriptions={subscriptionList}
              selectedId={effectiveSubscriptionId}
              result={selectedResult}
              filteredNodes={filteredNodes}
              pagedNodes={pagedNodes}
              page={page}
              totalPages={totalPages}
              pageSize={preferences.pageSize}
              geoOptions={geoOptions}
              networkOptions={networkOptions}
              typeOptions={typeOptions}
              filters={{ nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, maxRisk, maxTtfb, minSpeed, detourFilter, backboneFilter }}
              onSelectSubscription={(id) => {
                setPage(1);
                setSelectedSubscriptionId(id);
              }}
              onFilters={(next) => {
                setPage(1);
                if (next.nodeSearch !== undefined) setNodeSearch(next.nodeSearch);
                if (next.nodeValidity !== undefined) setNodeValidity(next.nodeValidity);
                if (next.nodeGeo !== undefined) setNodeGeo(next.nodeGeo);
                if (next.nodeNetwork !== undefined) setNodeNetwork(next.nodeNetwork);
                if (next.nodeType !== undefined) setNodeType(next.nodeType);
                if (next.maxRisk !== undefined) setMaxRisk(next.maxRisk);
                if (next.maxTtfb !== undefined) setMaxTtfb(next.maxTtfb);
                if (next.minSpeed !== undefined) setMinSpeed(next.minSpeed);
                if (next.detourFilter !== undefined) setDetourFilter(next.detourFilter);
                if (next.backboneFilter !== undefined) setBackboneFilter(next.backboneFilter);
              }}
              onPage={setPage}
              onDetails={setDetailsNode}
            />
          )}

          {view === "jobs" && <JobsView subscriptions={subscriptionList} jobs={jobList} cancelingJobId={cancelJob.variables || ""} onCancelJob={(jobId) => cancelJob.mutate(jobId)} />}

          {view === "export" && (
            <ExportView
              subscriptions={subscriptionList}
              selectedId={effectiveSubscriptionId}
              mode={exportMode}
              format={exportFormat}
              validOnly={exportValidOnly}
              preview={exportPreview}
              apiBaseUrl={preferences.apiBaseUrl}
              onSelect={setSelectedSubscriptionId}
              onMode={setExportMode}
              onFormat={setExportFormat}
              onValidOnly={setExportValidOnly}
              onPreview={() => void previewExport()}
            />
          )}

          {view === "singbox" && (
            <SingboxView
              subscriptions={subscriptionList}
              templates={templates}
              onCreateTemplate={(name, content) => createTemplate.mutate({ name, content })}
              onUpdateTemplate={(id, name, content) => updateTemplate.mutate({ id, name, content })}
              onDeleteTemplate={(id) => deleteTemplate.mutate(id)}
              apiBaseUrl={preferences.apiBaseUrl}
              api={api}
            />
          )}

          {view === "settings" && (
            <SettingsView
              settings={settingsQuery.data}
              metadata={settingsMetadataQuery.data}
              preferences={preferences}
              onSaveSettings={(next) => updateSettings.mutate(next)}
              onPreferences={setPreferences}
              onReset={() => void settingsQuery.refetch()}
            />
          )}
        </div>
      </main>

      {detailsNode && <NodeDrawer node={detailsNode} onClose={() => setDetailsNode(null)} />}
    </div>
  );
}

function Dashboard({
  subscriptions,
  nodes,
  runningJobs,
  averageRisk,
  averageTtfb,
  maxSpeed,
}: {
  subscriptions: SubscriptionSummary[];
  nodes: NodeResult[];
  runningJobs: number;
  averageRisk: number | null;
  averageTtfb: number;
  maxSpeed: number;
}) {
  const validCount = nodes.filter((node) => node.is_valid).length;
  const networkData = groupCount(nodes.flatMap((node) => node.probe.network_labels));
  const typeData = groupCount(nodes.flatMap((node) => node.probe.type_labels));
  const geoData = groupCount(nodes.map((node) => node.probe.actual_geo));
  const speedTop = [...nodes].filter((node) => node.download_speed_mbps !== null).sort((a, b) => (b.download_speed_mbps || 0) - (a.download_speed_mbps || 0)).slice(0, 10).map((node) => ({ name: node.original_name || node.probe.actual_geo, value: Number((node.download_speed_mbps || 0).toFixed(2)) }));
  const ttfbTop = [...nodes].sort((a, b) => a.probe.ttfb_ms - b.probe.ttfb_ms).slice(0, 10).map((node) => ({ name: node.original_name || node.probe.actual_geo, value: Math.round(node.probe.ttfb_ms) }));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-4">
        <Stat title="订阅总数" value={subscriptions.length} />
        <Stat title="节点总数" value={nodes.length} />
        <Stat title="有效节点" value={`${validCount} / ${nodes.length || 0}`} />
        <Stat title="运行任务" value={runningJobs} />
        <Stat title="平均风险" value={averageRisk === null ? "未知" : averageRisk.toFixed(1)} />
        <Stat title="平均 TTFB" value={`${averageTtfb.toFixed(0)} ms`} />
        <Stat title="最高测速" value={`${maxSpeed.toFixed(2)} Mbps`} />
        <Stat title="有效率" value={`${nodes.length ? ((validCount / nodes.length) * 100).toFixed(1) : "0.0"}%`} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ChartPanel title="风险分布" data={riskBuckets(nodes)} />
        <ChartPanel title="网络分类" data={networkData} />
        <ChartPanel title="类型分类" data={typeData} />
        <ChartPanel title="地区分布" data={geoData} />
        <ChartPanel title="测速 Top 10" data={speedTop} />
        <ChartPanel title="TTFB Top 10" data={ttfbTop} />
      </div>
    </div>
  );
}

function Stat({ title, value }: { title: string; value: string | number }) {
  return (
    <Panel>
      <div className="text-xs font-medium text-slate-500">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
    </Panel>
  );
}

function ChartPanel({ title, data }: { title: string; data: Array<{ name: string; value: number }> }) {
  return (
    <Panel className="h-80">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
        <BarChart3 className="h-4 w-4 text-blue-600" />
        {title}
      </div>
      {data.length ? (
        <ResponsiveContainer width="100%" height={235}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={58} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="value" name="数量/数值" radius={[4, 4, 0, 0]}>
              {data.map((_, index) => <Cell key={index} fill={chartColors[index % chartColors.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <EmptyState title="暂无数据" />
      )}
    </Panel>
  );
}

function SubscriptionsView(props: {
  subscriptions: SubscriptionSummary[];
  form: { name: string; url: string };
  editingId: string | null;
  onFormChange: (value: { name: string; url: string }) => void;
  onCreate: () => void;
  onStartEdit: (subscription: SubscriptionSummary) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onDelete: (id: string) => void;
  onRefresh: (id: string, speedtest_limit?: number, force_probe?: boolean) => void;
  onOpenNodes: (id: string) => void;
  onOpenExport: (id: string) => void;
}) {
  const [speedtestLimit, setSpeedtestLimit] = useState("1");
  const [forceProbe, setForceProbe] = useState(false);
  return (
    <div className="space-y-4">
      <Panel>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Plus className="h-4 w-4 text-blue-600" />{props.editingId ? "编辑订阅" : "添加订阅"}</div>
        <div className="grid grid-cols-[220px_1fr_auto_auto] gap-3">
          <Input placeholder="名称" value={props.form.name} onChange={(event) => props.onFormChange({ ...props.form, name: event.target.value })} />
          <Input placeholder="订阅 URL 或本地文件路径" value={props.form.url} onChange={(event) => props.onFormChange({ ...props.form, url: event.target.value })} />
          {props.editingId ? <Button onClick={props.onSaveEdit}><Save className="h-4 w-4" />保存</Button> : <Button onClick={props.onCreate}><Plus className="h-4 w-4" />添加并检测</Button>}
          {props.editingId && <Button variant="secondary" onClick={props.onCancelEdit}>取消</Button>}
        </div>
      </Panel>

      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">订阅列表</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">名称</th>
                <th className="px-3 py-2">URL</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">节点</th>
                <th className="px-3 py-2">有效率</th>
                <th className="px-3 py-2">更新时间</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {props.subscriptions.map((subscription) => (
                <tr key={subscription.id} className="border-t border-border">
                  <td className="px-3 py-3 font-medium">{subscription.name}</td>
                  <td className="max-w-md truncate px-3 py-3 text-slate-600">{subscription.url}</td>
                  <td className="px-3 py-3"><Badge tone={statusTone(subscription.last_status)}>{subscription.last_status}</Badge></td>
                  <td className="px-3 py-3">{subscription.valid_count}/{subscription.node_count}</td>
                  <td className="px-3 py-3">{subscription.node_count ? ((subscription.valid_count / subscription.node_count) * 100).toFixed(1) : "0.0"}%</td>
                  <td className="px-3 py-3 text-slate-500">{formatTime(subscription.updated_at)}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Button variant="secondary" onClick={() => props.onRefresh(subscription.id)}>刷新</Button>
                      <Input className="w-16" type="number" min="0" value={speedtestLimit} onChange={(event) => setSpeedtestLimit(event.target.value)} title="每区域测速数量" />
                      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={forceProbe} onChange={(event) => setForceProbe(event.target.checked)} />强制探测</label>
                      <Button variant="secondary" onClick={() => props.onRefresh(subscription.id, Math.max(0, Number(speedtestLimit) || 0), forceProbe)}>测速刷新</Button>
                      <Button variant="ghost" onClick={() => props.onStartEdit(subscription)}>编辑</Button>
                      <Button variant="ghost" onClick={() => props.onOpenNodes(subscription.id)}>节点</Button>
                      <Button variant="ghost" onClick={() => props.onOpenExport(subscription.id)}>导出</Button>
                      <Button variant="danger" onClick={() => props.onDelete(subscription.id)}><Trash2 className="h-4 w-4" /></Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!props.subscriptions.length && <EmptyState title="还没有订阅" detail="添加订阅后会自动创建后台检测任务。" />}
      </Panel>
    </div>
  );
}

function ApiSitesView(props: {
  sites: ApiSite[];
  exitIpEndpoint: string;
  providers: string[];
  onCreate: (input: ApiSiteInput) => void;
  onUpdate: (id: string, input: Partial<ApiSiteInput>) => void;
  onDelete: (id: string) => void;
  onOrder: (ids: string[]) => void;
  onUpdateEndpoint: (value: string) => void;
}) {
  const blank = (): ApiSiteInput => ({ id: "", column_name: "", provider: props.providers[0] || "ipwhois", url_template: "https://example.com/{ip}", api_key: "", weight: 1, enabled: false });
  const [draft, setDraft] = useState<ApiSiteInput>(blank);
  const [editing, setEditing] = useState<string | null>(null);
  const [endpoint, setEndpoint] = useState(props.exitIpEndpoint);
  useEffect(() => setEndpoint(props.exitIpEndpoint), [props.exitIpEndpoint]);
  const save = () => {
    if (editing) props.onUpdate(editing, draft);
    else props.onCreate(draft);
    setEditing(null); setDraft(blank());
  };
  const begin = (site: ApiSite) => {
    setEditing(site.id);
    setDraft({ id: site.id, column_name: site.column_name, provider: site.provider, url_template: site.url_template, api_key: "", weight: site.weight, enabled: site.enabled });
  };
  return <div className="space-y-4">
    <Panel>
      <div className="mb-2 text-sm font-semibold">出口 IP 端点</div>
      <div className="flex gap-2"><Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://..." /><Button onClick={() => props.onUpdateEndpoint(endpoint)}>保存</Button></div>
      <p className="mt-2 text-xs text-slate-500">通过代理查询出口 IP；不参与风险评分。</p>
    </Panel>
    <Panel>
      <div className="mb-3 text-sm font-semibold">{editing ? "编辑 API 站点" : "新增 API 站点"}</div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Input disabled={Boolean(editing)} value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} placeholder="唯一 ID" />
        <Input value={draft.column_name} onChange={(e) => setDraft({ ...draft, column_name: e.target.value })} placeholder="表格列名" />
        <Select value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value })}>{props.providers.map((provider) => <option key={provider}>{provider}</option>)}</Select>
        <Input type="number" min="0.01" step="0.1" value={draft.weight} onChange={(e) => setDraft({ ...draft, weight: Number(e.target.value) })} placeholder="权重" />
        <Input className="col-span-2" value={draft.url_template} onChange={(e) => setDraft({ ...draft, url_template: e.target.value })} placeholder="URL 模板，必须含 {ip}" />
        <Input type="password" value={draft.api_key || ""} onChange={(e) => setDraft({ ...draft, api_key: e.target.value, clear_api_key: false })} placeholder="API Key（留空保持不变）" />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用</label>
        {editing && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(draft.clear_api_key)} onChange={(e) => setDraft({ ...draft, clear_api_key: e.target.checked })} />清除 Key</label>}
      </div>
      <div className="mt-3 flex gap-2"><Button onClick={save}>{editing ? "保存" : "创建"}</Button>{editing && <Button variant="secondary" onClick={() => { setEditing(null); setDraft(blank()); }}>取消</Button>}</div>
    </Panel>
    <Panel>
      <table className="w-full text-left text-sm"><thead><tr><th>顺序</th><th>列名</th><th>Provider</th><th>URL</th><th>Key</th><th>权重</th><th>状态</th><th>操作</th></tr></thead><tbody>{props.sites.map((site, index) => <tr className="border-t" key={site.id}><td>{index + 1}</td><td>{site.column_name}</td><td>{site.provider}</td><td className="max-w-xs truncate">{site.url_template}</td><td>{site.api_key_configured ? "已配置" : "未配置"}</td><td>{site.weight}</td><td><input type="checkbox" checked={site.enabled} onChange={(e) => props.onUpdate(site.id, { enabled: e.target.checked })} /></td><td className="space-x-2"><Button variant="ghost" onClick={() => props.onOrder(props.sites.map((s, i) => i === index && index > 0 ? props.sites[index - 1].id : i === index - 1 ? site.id : s.id))}>↑</Button><Button variant="ghost" onClick={() => props.onOrder(props.sites.map((s, i) => i === index && index < props.sites.length - 1 ? props.sites[index + 1].id : i === index + 1 ? site.id : s.id))}>↓</Button><Button variant="ghost" onClick={() => begin(site)}>编辑</Button><Button variant="danger" onClick={() => props.onDelete(site.id)}>删除</Button></td></tr>)}</tbody></table>
    </Panel>
  </div>;
}

export function NodesView(props: {
  subscriptions: SubscriptionSummary[];
  selectedId: string;
  result: SubscriptionResults | null;
  filteredNodes: NodeResult[];
  pagedNodes: NodeResult[];
  page: number;
  totalPages: number;
  pageSize: number;
  geoOptions: string[];
  networkOptions: string[];
  typeOptions: string[];
  filters: Record<string, string>;
  onSelectSubscription: (id: string) => void;
  onFilters: (next: Record<string, string>) => void;
  onPage: (page: number) => void;
  onDetails: (node: NodeResult) => void;
}) {
  const [copiedKey, setCopiedKey] = useState("");
  const [activeCopyDropdown, setActiveCopyDropdown] = useState<string | null>(null);

  useEffect(() => {
    function handleOutsideClick() {
      setActiveCopyDropdown(null);
    }
    window.addEventListener("click", handleOutsideClick);
    return () => {
      window.removeEventListener("click", handleOutsideClick);
    };
  }, []);

  async function copyNodeUri(key: string, uri: string) {
    await copyText(uri);
    setCopiedKey(key);
    window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? "" : current));
    }, 1500);
  }

  return (
    <div className="space-y-4">
      <Panel>
        <div className="grid grid-cols-6 gap-3">
          <div>
            <Label>订阅</Label>
            <Select className="mt-1 w-full" value={props.selectedId} onChange={(event) => props.onSelectSubscription(event.target.value)}>
              {props.subscriptions.map((subscription) => <option key={subscription.id} value={subscription.id}>{subscription.name}</option>)}
            </Select>
          </div>
          <div>
            <Label>搜索</Label>
            <Input className="mt-1" value={props.filters.nodeSearch} onChange={(event) => props.onFilters({ nodeSearch: event.target.value })} placeholder="名称/IP/ASN" />
          </div>
          <FilterSelect label="状态" value={props.filters.nodeValidity} onChange={(value) => props.onFilters({ nodeValidity: value })} options={[["all", "全部"], ["valid", "有效"], ["invalid", "失败"]]} />
          <FilterSelect label="地区" value={props.filters.nodeGeo} onChange={(value) => props.onFilters({ nodeGeo: value })} options={[["all", "全部"], ...props.geoOptions.map((item) => [item, item] as [string, string])]} />
          <FilterSelect label="网络分类" value={props.filters.nodeNetwork} onChange={(value) => props.onFilters({ nodeNetwork: value })} options={[["all", "全部"], ...props.networkOptions.map((item) => [item, item] as [string, string])]} />
          <FilterSelect label="类型分类" value={props.filters.nodeType} onChange={(value) => props.onFilters({ nodeType: value })} options={[["all", "全部"], ...props.typeOptions.map((item) => [item, item] as [string, string])]} />
          <div><Label>最高风险</Label><Input className="mt-1" type="number" value={props.filters.maxRisk} onChange={(event) => props.onFilters({ maxRisk: event.target.value })} /></div>
          <div><Label>最高 TTFB</Label><Input className="mt-1" type="number" value={props.filters.maxTtfb} onChange={(event) => props.onFilters({ maxTtfb: event.target.value })} /></div>
          <div><Label>最低测速</Label><Input className="mt-1" type="number" value={props.filters.minSpeed} onChange={(event) => props.onFilters({ minSpeed: event.target.value })} /></div>
          <FilterSelect label="绕路" value={props.filters.detourFilter} onChange={(value) => props.onFilters({ detourFilter: value })} options={[["all", "全部"], ["yes", "是"], ["no", "否"]]} />
          <FilterSelect label="骨干网" value={props.filters.backboneFilter} onChange={(value) => props.onFilters({ backboneFilter: value })} options={[["all", "全部"], ["yes", "是"], ["no", "否"]]} />
        </div>
      </Panel>

      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">节点表格 · {props.filteredNodes.length} 条</div>
          <div className="text-xs text-slate-500">每页 {props.pageSize} 条</div>
        </div>
        {!props.result ? <EmptyState title="暂无检测结果" detail="订阅完成刷新后会在这里展示节点详情。" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1280px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  {(props.result?.api_sites_snapshot || []).map((site) => <th key={site.id} className="px-3 py-2">{site.column_name}</th>)}
                  <th className="px-3 py-2">状态</th><th className="px-3 py-2">增强名称</th><th className="px-3 py-2">地区</th><th className="px-3 py-2">网络</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">风险</th><th className="px-3 py-2">Ping</th><th className="px-3 py-2">TTFB</th><th className="px-3 py-2">测速</th><th className="px-3 py-2">ASN</th><th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {props.pagedNodes.map((node, index) => {
                  const rawKey = `${node.fingerprint}:raw`;
                  const compactKey = `${node.fingerprint}:compact`;
                  const detailedKey = `${node.fingerprint}:detailed`;
                  return (
                    <tr key={`${node.fingerprint}-${index}`} className="border-t border-border">
                      {(props.result?.api_sites_snapshot || []).map((site) => {
                        const verdictForSite = node.probe.evidence.find((item) => item.site_id === site.id);
                        if (!verdictForSite) return <td key={site.id} className="px-3 py-3 text-slate-400">无数据</td>;
                        if (verdictForSite.status !== "success") return <td key={site.id} className="px-3 py-3 text-red-600">{verdictForSite.status}</td>;
                        const labels = [...verdictForSite.network_labels, ...verdictForSite.risk_labels].map((label) => label.display).join("/");
                        return <td key={site.id} className="px-3 py-3">{labels || "-"}<br />{verdictForSite.risk_score === null ? "风险未知" : `风险 ${verdictForSite.risk_score.toFixed(0)}`}</td>;
                      })}
                      <td className="px-3 py-3"><Badge tone={node.is_valid ? "green" : "red"}>{node.is_valid ? "有效" : "失败"}</Badge></td>
                      <td className="max-w-xs truncate px-3 py-3 font-medium">{node.enhanced_name_compact}</td>
                      <td className="px-3 py-3">{node.probe.actual_geo}</td>
                      <td className="px-3 py-3">{node.probe.network_labels.join("/") || "-"}</td>
                      <td className="px-3 py-3">{node.probe.type_labels.join("/") || "-"}</td>
                      <td className="px-3 py-3">{node.probe.risk_score === null ? "未知" : node.probe.risk_score.toFixed(1)}</td>
                      <td className="px-3 py-3">{node.probe.tcp_ping_ms.toFixed(0)}</td>
                      <td className="px-3 py-3">{node.probe.ttfb_ms.toFixed(0)}</td>
                      <td className="px-3 py-3">{node.download_speed_mbps === null ? (node.speedtest_status === "failed" ? "失败" : "未测速") : node.download_speed_mbps.toFixed(2)}</td>
                      <td className="max-w-xs truncate px-3 py-3">{node.probe.asn_org}</td>
                      <td className="px-3 py-3 relative">
                        <div className="flex gap-2">
                          <div className="relative inline-block text-left">
                            <Button
                              variant="ghost"
                              onClick={(e) => {
                                e.nativeEvent.stopImmediatePropagation();
                                setActiveCopyDropdown(activeCopyDropdown === node.fingerprint ? null : node.fingerprint);
                              }}
                              className="flex items-center gap-1"
                            >
                              {copiedKey && copiedKey.startsWith(node.fingerprint) ? "已复制" : "复制"}
                              <ChevronDown className="h-4 w-4 text-slate-400" />
                            </Button>
                            {activeCopyDropdown === node.fingerprint && (
                              <div className="absolute right-0 mt-1 w-32 rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none z-20 border border-slate-200 divide-y divide-slate-100">
                                <div className="py-1">
                                  <button
                                    onClick={() => {
                                      void copyNodeUri(rawKey, node.raw_uri);
                                      setActiveCopyDropdown(null);
                                    }}
                                    className="block w-full px-4 py-2 text-left text-xs text-slate-700 hover:bg-slate-50 font-medium"
                                  >
                                    原始链接
                                  </button>
                                  <button
                                    onClick={() => {
                                      void copyNodeUri(compactKey, node.compact_uri);
                                      setActiveCopyDropdown(null);
                                    }}
                                    className="block w-full px-4 py-2 text-left text-xs text-slate-700 hover:bg-slate-50 font-medium"
                                  >
                                    紧凑 (compact)
                                  </button>
                                  <button
                                    onClick={() => {
                                      void copyNodeUri(detailedKey, node.detailed_uri);
                                      setActiveCopyDropdown(null);
                                    }}
                                    className="block w-full px-4 py-2 text-left text-xs text-slate-700 hover:bg-slate-50 font-medium"
                                  >
                                    详细 (detailed)
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                          <Button variant="secondary" onClick={() => props.onDetails(node)}>详情</Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button variant="secondary" disabled={props.page <= 1} onClick={() => props.onPage(props.page - 1)}>上一页</Button>
          <span className="text-sm text-slate-500">{props.page} / {props.totalPages}</span>
          <Button variant="secondary" disabled={props.page >= props.totalPages} onClick={() => props.onPage(props.page + 1)}>下一页</Button>
        </div>
      </Panel>
    </div>
  );
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: Array<[string, string]>; onChange: (value: string) => void }) {
  return <div><Label>{label}</Label><Select className="mt-1 w-full" value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</Select></div>;
}

function JobsView({ subscriptions, jobs, cancelingJobId, onCancelJob }: { subscriptions: SubscriptionSummary[]; jobs: JobStatus[]; cancelingJobId: string; onCancelJob: (jobId: string) => void }) {
  const nameById = new Map(subscriptions.map((subscription) => [subscription.id, subscription.name]));
  return (
    <Panel>
      <div className="mb-3 text-sm font-semibold text-slate-900">任务监控</div>
      {!jobs.length ? <EmptyState title="暂无任务" detail="添加订阅或刷新订阅后会显示任务进度。" /> : (
        <div className="space-y-3">
          {jobs.map((job) => {
            const percent = job.total_nodes ? Math.round((job.processed_nodes / job.total_nodes) * 100) : 0;
            const canCancel = job.status === "queued" || job.status === "running";
            return (
              <div key={job.job_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <div><div className="font-medium">{nameById.get(job.subscription_id) || job.subscription_id}</div><div className="text-xs text-slate-500">{job.job_id}</div></div>
                  <div className="flex items-center gap-2">
                    {canCancel && <Button variant="secondary" disabled={cancelingJobId === job.job_id} onClick={() => onCancelJob(job.job_id)}><XCircle className="h-4 w-4" />取消</Button>}
                    <Badge tone={statusTone(job.status)}>{job.status}</Badge>
                  </div>
                </div>
                <div className="mt-3 h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-blue-600" style={{ width: `${percent}%` }} /></div>
                <div className="mt-2 grid grid-cols-6 gap-3 text-xs text-slate-600">
                  <div>阶段: {job.phase}</div><div>进度: {job.processed_nodes}/{job.total_nodes}</div><div>创建: {formatTime(job.created_at)}</div><div>开始: {formatTime(job.started_at)}</div><div>结束: {formatTime(job.finished_at)}</div><div>耗时: {duration(job)}</div>
                </div>
                {job.error && <div className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{job.error}</div>}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function ExportView(props: {
  subscriptions: SubscriptionSummary[];
  selectedId: string;
  mode: ExportMode;
  format: ExportFormat;
  validOnly: boolean;
  preview: string;
  apiBaseUrl: string;
  onSelect: (id: string) => void;
  onMode: (mode: ExportMode) => void;
  onFormat: (format: ExportFormat) => void;
  onValidOnly: (value: boolean) => void;
  onPreview: () => void;
}) {
  const url = props.selectedId ? enhancedUrl(props.apiBaseUrl, props.selectedId, { mode: props.mode, format: props.format, valid_only: props.validOnly }) : "";
  return (
    <div className="space-y-4">
      <Panel>
        <div className="grid grid-cols-5 gap-3">
          <FilterSelect label="订阅" value={props.selectedId} onChange={props.onSelect} options={props.subscriptions.map((item) => [item.id, item.name])} />
          <FilterSelect label="命名模式" value={props.mode} onChange={(value) => isExportMode(value) && props.onMode(value)} options={[["compact", "compact"], ["detailed", "detailed"]]} />
          <FilterSelect label="格式" value={props.format} onChange={(value) => isExportFormat(value) && props.onFormat(value)} options={[["base64", "base64"], ["plain", "plain"]]} />
          <div><Label>有效节点</Label><Select className="mt-1 w-full" value={String(props.validOnly)} onChange={(event) => props.onValidOnly(event.target.value === "true")}><option value="true">只导出有效</option><option value="false">包含失败</option></Select></div>
          <div className="flex items-end gap-2"><Button onClick={props.onPreview}><Search className="h-4 w-4" />预览</Button><Button variant="secondary" onClick={() => copyText(url)}><ExternalLink className="h-4 w-4" />复制 URL</Button></div>
        </div>
      </Panel>
      <Panel>
        <div className="mb-3 flex items-center justify-between"><div className="text-sm font-semibold">订阅内容</div><div className="flex gap-2"><Button variant="secondary" onClick={() => copyText(props.preview)}><Clipboard className="h-4 w-4" />复制内容</Button><Button variant="secondary" onClick={() => downloadText(`enhanced_${props.mode}_${props.format}.txt`, props.preview)}><Download className="h-4 w-4" />下载</Button></div></div>
        <textarea className="h-96 w-full rounded-md border border-border bg-slate-950 p-3 font-mono text-xs text-slate-50" value={props.preview} readOnly placeholder="点击预览后显示增强订阅内容" />
      </Panel>
      <Panel><div className="text-sm font-semibold">命名示例</div><div className="mt-2 space-y-2 text-sm text-slate-600"><div>🇯🇵 JP | 机房 | Clean | 风险 10 | 210ms</div><div>🇯🇵 JP | 机房 | Clean | 风险 10 | 80ms/210ms | 12.34Mbps | Example ASN | JP</div></div></Panel>
    </div>
  );
}

function SettingsView({ settings, metadata, preferences, onSaveSettings, onPreferences, onReset }: { settings?: RuntimeSettings; metadata?: RuntimeSettingsMetadata; preferences: LocalPreferences; onSaveSettings: (settings: Partial<RuntimeSettings>) => void; onPreferences: (preferences: LocalPreferences) => void; onReset: () => void }) {
  const [draft, setDraft] = useState<Partial<RuntimeSettings>>({});
  const current = { ...(settings || {}), ...draft } as RuntimeSettings;
  const hasDraft = Object.keys(draft).length > 0;
  return (
    <div className="grid grid-cols-2 gap-4">
      <Panel>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><SlidersHorizontal className="h-4 w-4 text-blue-600" />后端运行设置</div>
        {!settings ? <EmptyState title="设置加载中" /> : (
          <div className="grid grid-cols-2 gap-3">
            <SettingNumber label="过滤并发" metadata={metadata?.FILTER_CONCURRENCY} value={current.FILTER_CONCURRENCY} onChange={(value) => setDraft({ ...draft, FILTER_CONCURRENCY: value })} />
            <SettingNumber label="测速并发" metadata={metadata?.SPEEDTEST_CONCURRENCY} value={current.SPEEDTEST_CONCURRENCY} onChange={(value) => setDraft({ ...draft, SPEEDTEST_CONCURRENCY: value })} />
            <SettingNumber label="每区域默认测速数量" metadata={metadata?.API_DEFAULT_SPEEDTEST_LIMIT} value={current.API_DEFAULT_SPEEDTEST_LIMIT} onChange={(value) => setDraft({ ...draft, API_DEFAULT_SPEEDTEST_LIMIT: value })} />
            <SettingNumber label="缓存 TTL 秒" metadata={metadata?.PROBE_CACHE_TTL_SECONDS} value={current.PROBE_CACHE_TTL_SECONDS} onChange={(value) => setDraft({ ...draft, PROBE_CACHE_TTL_SECONDS: value })} />
            <SettingNumber
              label="订阅最大 (M)"
              metadata={metadata?.SUBSCRIPTION_MAX_M}
              value={current.SUBSCRIPTION_MAX_M}
              onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_MAX_M: value })}
            />
            <SettingNumber
              label="测速最大 (M)"
              metadata={metadata?.SPEEDTEST_MAX_M}
              value={current.SPEEDTEST_MAX_M}
              onChange={(value) => setDraft({ ...draft, SPEEDTEST_MAX_M: value })}
            />
            <SettingNumber label="compact 长度" metadata={metadata?.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH} value={current.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH} onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: value })} />
            <SettingNumber label="detailed 长度" metadata={metadata?.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH} value={current.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH} onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: value })} />
            <div><Label>缓存开关</Label><Select className="mt-1 w-full" value={String(current.CACHE_ENABLED)} onChange={(event) => setDraft({ ...draft, CACHE_ENABLED: event.target.value === "true" })}><option value="true">开启</option><option value="false">关闭</option></Select></div>
            <div><Label>缓存失败结果</Label><Select className="mt-1 w-full" value={String(current.CACHE_FAILURE_RESULTS)} onChange={(event) => setDraft({ ...draft, CACHE_FAILURE_RESULTS: event.target.value === "true" })}><option value="false">关闭</option><option value="true">开启</option></Select></div>
            <div><Label>代理内核</Label><Select className="mt-1 w-full" value={current.PROXY_CORE || "sing-box"} onChange={(event) => setDraft({ ...draft, PROXY_CORE: event.target.value })}><option value="sing-box">Sing-box</option><option value="xray">Xray</option></Select></div>
            <div className="col-span-2"><Label>TTFB URL</Label><Input className="mt-1" value={current.TTFB_TARGET_URL || ""} onChange={(event) => setDraft({ ...draft, TTFB_TARGET_URL: event.target.value })} /></div>
            <div className="col-span-2"><Label>测速 URL</Label><Input className="mt-1" value={current.SPEEDTEST_URL || ""} onChange={(event) => setDraft({ ...draft, SPEEDTEST_URL: event.target.value })} /></div>
            <div className="col-span-2 flex justify-end gap-2"><Button variant="secondary" onClick={() => { setDraft({}); onReset(); }}>重置</Button><Button disabled={!hasDraft} onClick={() => { if (!hasDraft) return; onSaveSettings(draft); setDraft({}); }}><Save className="h-4 w-4" />保存设置</Button></div>
          </div>
        )}
      </Panel>
      <Panel>
        <div className="mb-3 text-sm font-semibold">前端本地设置</div>
        <div className="space-y-3">
          <div><Label>API Base URL</Label><Input className="mt-1" value={preferences.apiBaseUrl} onChange={(event) => onPreferences({ ...preferences, apiBaseUrl: event.target.value })} placeholder="留空表示同源或 Vite 代理" /></div>
          <div><Label>自动刷新</Label><Select className="mt-1 w-full" value={String(preferences.autoRefresh)} onChange={(event) => onPreferences({ ...preferences, autoRefresh: event.target.value === "true" })}><option value="true">开启</option><option value="false">关闭</option></Select></div>
          <div><Label>默认导出模式</Label><Select className="mt-1 w-full" value={preferences.defaultExportMode} onChange={(event) => isExportMode(event.target.value) && onPreferences({ ...preferences, defaultExportMode: event.target.value })}><option value="compact">compact</option><option value="detailed">detailed</option></Select></div>
          <div><Label>默认导出格式</Label><Select className="mt-1 w-full" value={preferences.defaultExportFormat} onChange={(event) => isExportFormat(event.target.value) && onPreferences({ ...preferences, defaultExportFormat: event.target.value })}><option value="base64">base64</option><option value="plain">plain</option></Select></div>
          <div><Label>表格每页数量</Label><Input className="mt-1" type="number" value={preferences.pageSize} onChange={(event) => onPreferences({ ...preferences, pageSize: Number(event.target.value) || defaultPreferences.pageSize })} /></div>
        </div>
      </Panel>
    </div>
  );
}

function SettingNumber({ label, value, metadata, step, onChange }: { label: string; value: number; metadata?: { min?: number; max?: number }; step?: string; onChange: (value: number) => void }) {
  const inputId = `setting-${label}`;
  return <div><Label htmlFor={inputId}>{label}</Label><Input id={inputId} className="mt-1" type="number" min={metadata?.min} max={metadata?.max} step={step} value={value ?? 0} onChange={(event) => onChange(Number(event.target.value))} /></div>;
}

interface ConflictInfo {
  type: "geo" | "network" | "risk";
  description: string;
}

function detectConflicts(evidence: ApiVerdict[], actualGeo: string): ConflictInfo[] {
  const conflicts: ConflictInfo[] = [];
  if (!evidence || evidence.length === 0) return conflicts;

  // 1. Network type conflict
  let hasResidential = false;
  let hasDatacenter = false;
  const resSources: string[] = [];
  const dcSources: string[] = [];

  for (const verdict of evidence) {
    for (const lbl of verdict.network_labels) {
      if (
        lbl.label === "residential" ||
        lbl.label === "likely_residential" ||
        lbl.label === "mobile" ||
        lbl.label === "business"
      ) {
        hasResidential = true;
        resSources.push(`${verdict.source} (${lbl.display || lbl.label})`);
      } else if (lbl.label === "datacenter" || lbl.label === "hosting") {
        hasDatacenter = true;
        dcSources.push(`${verdict.source} (${lbl.display || lbl.label})`);
      }
    }
  }
  if (hasResidential && hasDatacenter) {
    conflicts.push({
      type: "network",
      description: `网络属性冲突：部分数据源判定为家宽/商宽/移动网络 [${resSources.join(
        ", "
      )}]，而其他判定为机房/托管 [${dcSources.join(", ")}]。`,
    });
  }

  // 2. Risk evaluation conflict
  let hasHighRisk = false;
  let hasClean = false;
  const riskSources: string[] = [];
  const cleanSources: string[] = [];

  for (const verdict of evidence) {
    if (verdict.risk_score !== null && verdict.risk_score > 50) {
      hasHighRisk = true;
      riskSources.push(`${verdict.source} (风险评分: ${verdict.risk_score}%)`);
    }
    for (const lbl of verdict.risk_labels) {
      if (
        lbl.label === "vpn" ||
        lbl.label === "proxy" ||
        lbl.label === "tor" ||
        lbl.label === "abuser"
      ) {
        hasHighRisk = true;
        if (!riskSources.some((s) => s.startsWith(verdict.source))) {
          riskSources.push(`${verdict.source} (${lbl.display || lbl.label})`);
        }
      } else if (lbl.label === "clean" && lbl.confidence > 0.6) {
        hasClean = true;
        cleanSources.push(`${verdict.source} (置信度: ${Math.round(lbl.confidence * 100)}%)`);
      }
    }
  }
  if (hasHighRisk && hasClean) {
    conflicts.push({
      type: "risk",
      description: `信誉风险冲突：部分数据源报告高风险评分/标签 [${riskSources.join(
        ", "
      )}]，而其他数据源判定为干净信誉 [${cleanSources.join(", ")}]。`,
    });
  }

  return conflicts;
}

function NodeDrawer({ node, onClose }: { node: NodeResult; onClose: () => void }) {
  const conflicts = useMemo(() => detectConflicts(node.probe.evidence, node.probe.actual_geo), [node]);

  return (
    <div className="fixed inset-0 z-30 bg-slate-950/20">
      <aside className="absolute inset-y-0 right-0 w-[580px] overflow-y-auto border-l border-border bg-white p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="text-lg font-semibold">节点详情</div>
          <Button variant="secondary" onClick={onClose}>关闭</Button>
        </div>
        <div className="mt-4 space-y-4 text-sm">
          <Panel>
            <div className="font-semibold text-slate-800">{node.enhanced_name_detailed}</div>
            <div className="mt-2 text-slate-500 break-all text-xs">{node.original_name}</div>
          </Panel>

          <Panel>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider">节点链接</span>
            </div>
            <pre className="whitespace-pre-wrap break-all text-xs bg-slate-50 p-2 rounded-md border border-slate-100 font-mono text-slate-600">{node.raw_uri}</pre>
          </Panel>

          {conflicts.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 mt-0.5" />
                <div>
                  <div className="font-semibold text-amber-950">画像数据源冲突警告</div>
                  <div className="mt-1.5 space-y-1.5 text-xs text-amber-800">
                    {conflicts.map((c, i) => (
                      <div key={i} className="flex gap-1">
                        <span className="shrink-0">•</span>
                        <span>{c.description}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          <Panel>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-2">网络及延迟属性</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              <Detail label="实际出口 IP" value={node.probe.actual_ip} />
              <Detail label="IPv6 出口" value={node.probe.ipv6_support ? `支持 (${node.probe.actual_ipv6})` : "不支持"} />
              <Detail label="归属国家/地区 (Geo)" value={node.probe.actual_geo} />
              <Detail label="ASN" value={node.probe.asn_org} />
              <Detail label="拒绝原因" value={node.reject_reason || "-"} />
              <Detail label="骨干网" value={node.probe.backbone_info || "-"} />
              <Detail label="绕路状态" value={node.probe.is_detour ? "Yes" : "No"} />
              <Detail label="判定置信度" value={node.probe.confidence} />
              <Detail label="TCP 延迟" value={`${node.probe.tcp_ping_ms} ms`} />
              <Detail label="HTTP TTFB" value={`${node.probe.ttfb_ms} ms`} />
            </div>
          </Panel>

          <Panel>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-3">数据源画像详情 (Evidence)</div>
            <div className="space-y-3">
              {node.probe.evidence && node.probe.evidence.length ? (
                node.probe.evidence.map((verdict) => (
                  <div key={verdict.source} className="rounded-lg border border-slate-100 bg-slate-50/50 p-3 text-xs">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-2">
                      <span className="font-bold text-slate-700">{verdict.source}</span>
                      {verdict.risk_score !== null && (
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          verdict.risk_score > 70 ? 'bg-red-100 text-red-700' :
                          verdict.risk_score > 30 ? 'bg-amber-100 text-amber-700' :
                          'bg-emerald-100 text-emerald-700'
                        }`}>
                          风险评分: {verdict.risk_score}%
                        </span>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      {verdict.network_labels && verdict.network_labels.length > 0 && (
                        <div className="flex items-start gap-1 flex-wrap">
                          <span className="text-slate-400 font-medium shrink-0">网络属性:</span>
                          {verdict.network_labels.map((lbl) => (
                            <span key={lbl.label} className="inline-flex items-center bg-blue-50 text-blue-700 border border-blue-100 px-1.5 py-0.5 rounded text-[10px] font-medium">
                              {lbl.display} ({(lbl.confidence * 100).toFixed(0)}%)
                            </span>
                          ))}
                        </div>
                      )}

                      {verdict.risk_labels && verdict.risk_labels.length > 0 && (
                        <div className="flex items-start gap-1 flex-wrap">
                          <span className="text-slate-400 font-medium shrink-0">信誉评级:</span>
                          {verdict.risk_labels.map((lbl) => (
                            <span key={lbl.label} className={`inline-flex items-center border px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              lbl.label === 'clean' 
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-100'
                                : 'bg-red-50 text-red-700 border-red-100'
                            }`}>
                              {lbl.display} ({(lbl.confidence * 100).toFixed(0)}%)
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="flex items-start gap-1">
                        <span className="text-slate-400 font-medium shrink-0">原始摘要:</span>
                        <span className="text-slate-600 break-all font-mono">{verdict.raw_summary || "No signal"}</span>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-slate-500 py-2 text-center">No source evidence available</div>
              )}
            </div>
          </Panel>
        </div>
      </aside>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs text-slate-500">{label}</div><div className="mt-1 break-all font-medium">{value}</div></div>;
}

function SingboxView(props: {
  subscriptions: SubscriptionSummary[];
  templates: SingboxTemplate[];
  onCreateTemplate: (name: string, content: string) => void;
  onUpdateTemplate: (id: string, name: string, content: string) => void;
  onDeleteTemplate: (id: string) => void;
  apiBaseUrl: string;
  api: ApiClient;
}) {
  const { subscriptions, templates, onCreateTemplate, onUpdateTemplate, onDeleteTemplate, api } = props;
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [activeSubTab, setActiveSubTab] = useState<"edit" | "preview">("edit");

  // Selection defaults
  useEffect(() => {
    if (templates.length > 0 && !selectedTemplateId) {
      setSelectedTemplateId(templates[0].id);
    }
  }, [templates, selectedTemplateId]);

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId) || templates[0];

  // Editor Draft State
  const [draftName, setDraftName] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [lastSelectedId, setLastSelectedId] = useState("");

  useEffect(() => {
    if (selectedTemplate) {
      setDraftName(selectedTemplate.name);
      setDraftContent(selectedTemplate.content);
      setLastSelectedId(selectedTemplate.id);
    } else {
      setDraftName("");
      setDraftContent("");
      setLastSelectedId("");
    }
  }, [selectedTemplate]);

  // JSON Validation
  let jsonError = "";
  if (draftContent) {
    try {
      const clean = stripCommentsLocal(draftContent);
      JSON.parse(clean);
    } catch (e: any) {
      jsonError = e.message;
    }
  }

  // Preview State
  const [selectedSubIds, setSelectedSubIds] = useState<string[]>([]);
  useEffect(() => {
    if (subscriptions.length > 0 && selectedSubIds.length === 0) {
      setSelectedSubIds([subscriptions[0].id]);
    }
  }, [subscriptions, selectedSubIds]);

  const [previewMode, setPreviewMode] = useState<"compact" | "detailed">("compact");
  const [previewValidOnly, setPreviewValidOnly] = useState(true);
  const [previewLimit, setPreviewLimit] = useState("");
  const [previewMaxRisk, setPreviewMaxRisk] = useState("");
  const [generatedConfig, setGeneratedConfig] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [genError, setGenError] = useState("");

  const exportUrl = selectedTemplateId && selectedSubIds.length > 0
    ? props.api.getSingboxExportUrl(
        selectedSubIds,
        selectedTemplateId,
        {
          mode: previewMode,
          valid_only: previewValidOnly,
          limit: previewLimit ? parseInt(previewLimit) : undefined,
          max_risk: previewMaxRisk ? parseFloat(previewMaxRisk) : undefined
        }
      )
    : "";

  async function handlePreview() {
    if (selectedSubIds.length === 0) {
      setGenError("请选择至少一个订阅");
      return;
    }
    setIsGenerating(true);
    setGenError("");
    try {
      const res = await api.getSingboxExport(
        selectedSubIds,
        selectedTemplateId,
        {
          mode: previewMode,
          valid_only: previewValidOnly,
          limit: previewLimit ? parseInt(previewLimit) : undefined,
          max_risk: previewMaxRisk ? parseFloat(previewMaxRisk) : undefined
        }
      );
      const formatted = typeof res === "string" ? res : JSON.stringify(res, null, 2);
      setGeneratedConfig(formatted);
    } catch (e: any) {
      setGenError(e.message || "生成配置失败");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="grid grid-cols-4 gap-4">
      {/* Templates List Column */}
      <Panel className="col-span-1 flex flex-col h-[750px]">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-800">配置模板</div>
          <Button
            className="h-8 px-2 py-0"
            onClick={() => {
              const defaultTpl = `{
  "experimental": {
    "cache_file": {
      "enabled": true,
      "path": "/etc/sing-box/cache.db",
      "store_fakeip": true
    }
  },
  "outbounds": [
    { "tag": "🚀 节点选择", "type": "selector", "outbounds": [ "♻️ 自动选择", "👉 手动选择" ] },
    { "tag": "♻️ 自动选择", "type": "urltest", "use_all_nodes": true },
    { "tag": "👉 手动选择", "type": "selector", "use_all_nodes": true }
  ],
  "route": {
    "rules": [
      { "action": "sniff" }
    ],
    "final": "👉 手动选择"
  }
}`;
              onCreateTemplate("新模板", defaultTpl);
            }}
          >
            <Plus className="h-3.5 w-3.5 mr-1" />添加
          </Button>
        </div>
        
        {templates.length === 0 ? (
          <EmptyState title="无模板" detail="点击上方添加模板" />
        ) : (
          <div className="flex-1 overflow-y-auto space-y-1 pr-1">
            {templates.map((tpl) => (
              <div
                key={tpl.id}
                onClick={() => setSelectedTemplateId(tpl.id)}
                className={`group flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer transition ${
                  selectedTemplateId === tpl.id
                    ? "bg-blue-50 text-blue-700 font-medium"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <span className="truncate flex-1 pr-2">{tpl.name}</span>
                {templates.length > 1 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`确定要删除模板 "${tpl.name}" 吗？`)) {
                        onDeleteTemplate(tpl.id);
                        if (selectedTemplateId === tpl.id) {
                          setSelectedTemplateId("");
                        }
                      }
                    }}
                    className="hidden group-hover:block p-1 text-slate-400 hover:text-red-600 transition"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>

      {/* Editor & Preview Column */}
      <div className="col-span-3 space-y-4">
        {selectedTemplate ? (
          <Panel className="min-h-[750px] flex flex-col">
            <div className="mb-4 border-b border-border flex items-center justify-between">
              <div className="flex gap-4">
                <button
                  onClick={() => setActiveSubTab("edit")}
                  className={`pb-2 text-sm font-semibold border-b-2 transition ${
                    activeSubTab === "edit"
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-slate-500 hover:text-slate-700"
                  }`}
                >
                  模板编辑
                </button>
                <button
                  onClick={() => setActiveSubTab("preview")}
                  className={`pb-2 text-sm font-semibold border-b-2 transition ${
                    activeSubTab === "preview"
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-slate-500 hover:text-slate-700"
                  }`}
                >
                  配置预览与导出
                </button>
              </div>

              {activeSubTab === "edit" && (
                <div className="flex items-center gap-2 pb-1">
                  {jsonError ? (
                    <span className="text-xs text-red-500 bg-red-50 px-2 py-1 rounded border border-red-200">
                      JSON 格式错误
                    </span>
                  ) : (
                    <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded border border-green-200">
                      JSON 语法正确
                    </span>
                  )}
                  <Button
                    className="h-8 px-3 py-0"
                    disabled={draftName === selectedTemplate.name && draftContent === selectedTemplate.content}
                    onClick={() => onUpdateTemplate(selectedTemplate.id, draftName, draftContent)}
                  >
                    <Save className="h-3.5 w-3.5 mr-1" />保存
                  </Button>
                </div>
              )}
            </div>

            {/* TAB 1: EDIT */}
            {activeSubTab === "edit" && (
              <div className="flex-1 flex flex-col space-y-3">
                <div>
                  <Label>模板名称</Label>
                  <Input
                    className="mt-1"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    placeholder="请输入模板名称"
                  />
                </div>
                <div className="flex-1 flex flex-col min-h-[480px]">
                  <Label className="mb-1">JSON5 模板内容 (支持 // 与 /* 注释)</Label>
                  <textarea
                    className="flex-1 w-full rounded-md border border-border bg-slate-950 p-3 font-mono text-xs text-slate-50 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                    value={draftContent}
                    onChange={(e) => setDraftContent(e.target.value)}
                    placeholder="请输入 sing-box 模板 JSON5 配置"
                  />
                  {jsonError && (
                    <div className="mt-2 text-xs text-red-500 font-mono bg-red-50 p-2 rounded border border-red-200 whitespace-pre-wrap">
                      语法错误: {jsonError}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: PREVIEW / EXPORT */}
            {activeSubTab === "preview" && (
              <div className="flex-1 flex flex-col space-y-4">
                {/* Export Options Panel */}
                <div className="bg-slate-50 p-3 rounded-lg border border-border grid grid-cols-6 gap-3">
                  <div className="col-span-2">
                    <Label>选择订阅数据源 (可多选)</Label>
                    <div className="mt-1 border border-border rounded bg-white max-h-[80px] overflow-y-auto p-1.5 space-y-1">
                      {subscriptions.map((sub) => {
                        const isChecked = selectedSubIds.includes(sub.id);
                        return (
                          <label key={sub.id} className="flex items-center gap-2 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => {
                                if (isChecked) {
                                  setSelectedSubIds(selectedSubIds.filter((id) => id !== sub.id));
                                } else {
                                  setSelectedSubIds([...selectedSubIds, sub.id]);
                                }
                              }}
                              className="rounded text-blue-600 focus:ring-blue-500"
                            />
                            <span className="truncate">{sub.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <Label>命名模式</Label>
                    <Select
                      className="mt-1 w-full text-xs"
                      value={previewMode}
                      onChange={(e) => setPreviewMode(e.target.value as any)}
                    >
                      <option value="compact">compact (极简)</option>
                      <option value="detailed">detailed (详细)</option>
                    </Select>
                  </div>
                  <div>
                    <Label>过滤无效节点</Label>
                    <Select
                      className="mt-1 w-full text-xs"
                      value={String(previewValidOnly)}
                      onChange={(e) => setPreviewValidOnly(e.target.value === "true")}
                    >
                      <option value="true">仅有效节点</option>
                      <option value="false">包含所有节点</option>
                    </Select>
                  </div>
                  <div>
                    <Label>最高风险</Label>
                    <Input
                      type="number"
                      className="mt-1 w-full text-xs"
                      value={previewMaxRisk}
                      onChange={(e) => setPreviewMaxRisk(e.target.value)}
                      placeholder="0-100"
                    />
                  </div>
                  <div>
                    <Label>出站限制数量</Label>
                    <Input
                      type="number"
                      className="mt-1 w-full text-xs"
                      value={previewLimit}
                      onChange={(e) => setPreviewLimit(e.target.value)}
                      placeholder="不限"
                    />
                  </div>
                </div>

                {/* Operations & Direct Link */}
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <div className="flex gap-2">
                      <Button onClick={handlePreview} disabled={isGenerating}>
                        <Search className="h-4 w-4 mr-1" />
                        {isGenerating ? "正在生成..." : "预览生成配置"}
                      </Button>
                      {generatedConfig && (
                        <>
                          <Button variant="secondary" onClick={() => copyText(generatedConfig)}>
                            <Clipboard className="h-4 w-4 mr-1" />复制内容
                          </Button>
                          <Button variant="secondary" onClick={() => downloadText(`${selectedTemplate.name}_export.json`, generatedConfig)}>
                            <Download className="h-4 w-4 mr-1" />下载 JSON
                          </Button>
                        </>
                      )}
                    </div>
                    {exportUrl && (
                      <Button variant="secondary" onClick={() => copyText(exportUrl)}>
                        <ExternalLink className="h-4 w-4 mr-1" />复制订阅链接
                      </Button>
                    )}
                  </div>
                  {exportUrl && (
                    <div className="text-xs text-slate-500 bg-slate-50 p-2 rounded border border-border truncate select-all">
                      订阅 URL: <span className="font-mono text-slate-700">{exportUrl}</span>
                    </div>
                  )}
                </div>

                {/* Preview Textbox */}
                <div className="flex-1 flex flex-col min-h-[350px]">
                  {genError && (
                    <div className="mb-2 text-xs text-red-500 bg-red-50 p-2 rounded border border-red-200">
                      {genError}
                    </div>
                  )}
                  <textarea
                    className="flex-1 w-full rounded-md border border-border bg-slate-950 p-3 font-mono text-xs text-slate-50 focus:outline-none resize-none"
                    value={generatedConfig}
                    readOnly
                    placeholder="点击 '预览生成配置' 按钮查看生成结果"
                  />
                </div>
              </div>
            )}
          </Panel>
        ) : (
          <Panel className="h-[750px] flex items-center justify-center">
            <EmptyState title="请选择或创建一个配置模板" />
          </Panel>
        )}
      </div>
    </div>
  );
}

function stripCommentsLocal(json_str: string): string {
  const pattern = /(\".*?(?<!\\)\")|(\/\*.*?\*\/|\/\/[^\r\n]*)/g;
  return json_str.replace(pattern, (match, g1, g2) => {
    if (g2) return "";
    return g1;
  });
}

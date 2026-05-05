import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
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
import { createApiClient, enhancedUrl } from "./api";
import { useAppData } from "./appData";
import { duration, formatTime, groupCount, scoreBuckets, statusTone } from "./appUtils";
import { filterNodes } from "./nodeFilters";
import { defaultPreferences, isExportFormat, isExportMode, loadPreferences, savePreferences } from "./preferences";
import type {
  ExportFormat,
  ExportMode,
  JobStatus,
  LocalPreferences,
  NodeResult,
  RuntimeSettings,
  SubscriptionResults,
  SubscriptionSummary,
} from "./types";
import { Badge, Button, EmptyState, Input, Label, Panel, Select } from "./components/ui";

type View = "dashboard" | "subscriptions" | "nodes" | "jobs" | "export" | "settings";

const navItems: Array<{ id: View; label: string; icon: typeof LayoutDashboard }> = [
  { id: "dashboard", label: "总览", icon: LayoutDashboard },
  { id: "subscriptions", label: "订阅管理", icon: ListChecks },
  { id: "nodes", label: "节点详情", icon: Network },
  { id: "jobs", label: "任务监控", icon: Activity },
  { id: "export", label: "增强订阅", icon: FileDown },
  { id: "settings", label: "设置", icon: Settings },
];

const chartColors = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#64748b"];

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text);
}

function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
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
  const [minScore, setMinScore] = useState("");
  const [minSpeed, setMinSpeed] = useState("");
  const [detourFilter, setDetourFilter] = useState("all");
  const [backboneFilter, setBackboneFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [detailsNode, setDetailsNode] = useState<NodeResult | null>(null);
  const [exportMode, setExportMode] = useState<ExportMode>(preferences.defaultExportMode);
  const [exportFormat, setExportFormat] = useState<ExportFormat>(preferences.defaultExportFormat);
  const [exportValidOnly, setExportValidOnly] = useState(true);
  const [exportPreview, setExportPreview] = useState("");
  const [customSpeedLimit, setCustomSpeedLimit] = useState(3);
  const [subscriptionForm, setSubscriptionForm] = useState({ name: "", url: "" });
  const [editingId, setEditingId] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const api = useMemo(() => createApiClient(preferences.apiBaseUrl), [preferences.apiBaseUrl]);
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
  const averageScore = allNodes.length ? allNodes.reduce((sum, node) => sum + node.total_score, 0) / allNodes.length : 0;
  const averageTtfb = allNodes.length ? allNodes.reduce((sum, node) => sum + node.probe.ttfb_ms, 0) / allNodes.length : 0;
  const maxSpeed = allNodes.reduce((max, node) => Math.max(max, node.download_speed_mbps), 0);

  const nodeFilters = { nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, minScore, maxTtfb, minSpeed, detourFilter, backboneFilter };
  const filteredNodes = useMemo(
    () => filterNodes(selectedResult?.nodes || [], nodeFilters),
    [selectedResult, nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, minScore, maxTtfb, minSpeed, detourFilter, backboneFilter],
  );

  const totalPages = Math.max(1, Math.ceil(filteredNodes.length / preferences.pageSize));
  const pagedNodes = filteredNodes.slice((page - 1) * preferences.pageSize, page * preferences.pageSize);

  const createSubscription = useMutation({
    mutationFn: api.createSubscription,
    onSuccess: (response) => {
      setSubscriptionForm({ name: "", url: "" });
      setSelectedSubscriptionId(response.subscription_id);
      setView("jobs");
      void queryClient.invalidateQueries();
    },
  });

  const updateSubscription = useMutation({
    mutationFn: ({ id, input }: { id: string; input: { name?: string; url?: string } }) => api.updateSubscription(id, input),
    onSuccess: () => {
      setEditingId(null);
      setSubscriptionForm({ name: "", url: "" });
      void queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    },
  });

  const deleteSubscription = useMutation({
    mutationFn: api.deleteSubscription,
    onSuccess: () => {
      setSelectedSubscriptionId("");
      void queryClient.invalidateQueries();
    },
  });

  const refreshSubscription = useMutation({
    mutationFn: ({ id, speedtest_limit, force_probe }: { id: string; speedtest_limit?: number; force_probe?: boolean }) =>
      api.refreshSubscription(id, { speedtest_limit, force_probe }),
    onSuccess: () => {
      setView("jobs");
      void queryClient.invalidateQueries();
    },
  });

  const settingsQuery = useQuery({
    queryKey: ["settings", preferences.apiBaseUrl],
    queryFn: api.getSettings,
  });

  const updateSettings = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  function setPreferences(next: LocalPreferences) {
    setPreferencesState(next);
    savePreferences(next);
  }

  async function previewExport() {
    if (!effectiveSubscriptionId) return;
    const content = await api.getEnhanced(effectiveSubscriptionId, {
      mode: exportMode,
      format: exportFormat,
      valid_only: exportValidOnly,
    });
    setExportPreview(content);
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
          {view === "dashboard" && (
            <Dashboard
              subscriptions={subscriptionList}
              nodes={allNodes}
              runningJobs={runningJobs.length}
              averageScore={averageScore}
              averageTtfb={averageTtfb}
              maxSpeed={maxSpeed}
            />
          )}

          {view === "subscriptions" && (
            <SubscriptionsView
              subscriptions={subscriptionList}
              form={subscriptionForm}
              editingId={editingId}
              customSpeedLimit={customSpeedLimit}
              onFormChange={setSubscriptionForm}
              onCustomSpeedLimit={setCustomSpeedLimit}
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
              filters={{ nodeSearch, nodeValidity, nodeGeo, nodeNetwork, nodeType, minScore, maxTtfb, minSpeed, detourFilter, backboneFilter }}
              onSelectSubscription={setSelectedSubscriptionId}
              onFilters={(next) => {
                setPage(1);
                if (next.nodeSearch !== undefined) setNodeSearch(next.nodeSearch);
                if (next.nodeValidity !== undefined) setNodeValidity(next.nodeValidity);
                if (next.nodeGeo !== undefined) setNodeGeo(next.nodeGeo);
                if (next.nodeNetwork !== undefined) setNodeNetwork(next.nodeNetwork);
                if (next.nodeType !== undefined) setNodeType(next.nodeType);
                if (next.minScore !== undefined) setMinScore(next.minScore);
                if (next.maxTtfb !== undefined) setMaxTtfb(next.maxTtfb);
                if (next.minSpeed !== undefined) setMinSpeed(next.minSpeed);
                if (next.detourFilter !== undefined) setDetourFilter(next.detourFilter);
                if (next.backboneFilter !== undefined) setBackboneFilter(next.backboneFilter);
              }}
              onPage={setPage}
              onDetails={setDetailsNode}
            />
          )}

          {view === "jobs" && <JobsView subscriptions={subscriptionList} jobs={jobList} />}

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

          {view === "settings" && (
            <SettingsView
              settings={settingsQuery.data}
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
  averageScore,
  averageTtfb,
  maxSpeed,
}: {
  subscriptions: SubscriptionSummary[];
  nodes: NodeResult[];
  runningJobs: number;
  averageScore: number;
  averageTtfb: number;
  maxSpeed: number;
}) {
  const validCount = nodes.filter((node) => node.is_valid).length;
  const networkData = groupCount(nodes.flatMap((node) => node.probe.network_labels));
  const typeData = groupCount(nodes.flatMap((node) => node.probe.type_labels));
  const geoData = groupCount(nodes.map((node) => node.probe.actual_geo));
  const speedTop = [...nodes].sort((a, b) => b.download_speed_mbps - a.download_speed_mbps).slice(0, 10).map((node) => ({ name: node.original_name || node.probe.actual_geo, value: Number(node.download_speed_mbps.toFixed(2)) }));
  const ttfbTop = [...nodes].sort((a, b) => a.probe.ttfb_ms - b.probe.ttfb_ms).slice(0, 10).map((node) => ({ name: node.original_name || node.probe.actual_geo, value: Math.round(node.probe.ttfb_ms) }));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-4">
        <Stat title="订阅总数" value={subscriptions.length} />
        <Stat title="节点总数" value={nodes.length} />
        <Stat title="有效节点" value={`${validCount} / ${nodes.length || 0}`} />
        <Stat title="运行任务" value={runningJobs} />
        <Stat title="平均分" value={averageScore.toFixed(1)} />
        <Stat title="平均 TTFB" value={`${averageTtfb.toFixed(0)} ms`} />
        <Stat title="最高测速" value={`${maxSpeed.toFixed(2)} Mbps`} />
        <Stat title="有效率" value={`${nodes.length ? ((validCount / nodes.length) * 100).toFixed(1) : "0.0"}%`} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ChartPanel title="评分分布" data={scoreBuckets(nodes)} />
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
  customSpeedLimit: number;
  onFormChange: (value: { name: string; url: string }) => void;
  onCustomSpeedLimit: (value: number) => void;
  onCreate: () => void;
  onStartEdit: (subscription: SubscriptionSummary) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onDelete: (id: string) => void;
  onRefresh: (id: string, speedtest_limit?: number, force_probe?: boolean) => void;
  onOpenNodes: (id: string) => void;
  onOpenExport: (id: string) => void;
}) {
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
          <div className="flex items-center gap-2">
            <Label>自定义测速数量</Label>
            <Input className="w-20" type="number" min={0} value={props.customSpeedLimit} onChange={(event) => props.onCustomSpeedLimit(Number(event.target.value))} />
          </div>
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
                      <Button variant="secondary" onClick={() => props.onRefresh(subscription.id, props.customSpeedLimit, false)}>自定义</Button>
                      <Button variant="secondary" onClick={() => props.onRefresh(subscription.id, 0, false)}>不测速</Button>
                      <Button variant="secondary" onClick={() => props.onRefresh(subscription.id, props.customSpeedLimit, true)}>强制</Button>
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

function NodesView(props: {
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
          <div><Label>最低分</Label><Input className="mt-1" type="number" value={props.filters.minScore} onChange={(event) => props.onFilters({ minScore: event.target.value })} /></div>
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
                  <th className="px-3 py-2">状态</th><th className="px-3 py-2">增强名称</th><th className="px-3 py-2">地区</th><th className="px-3 py-2">网络</th><th className="px-3 py-2">类型</th><th className="px-3 py-2">总分</th><th className="px-3 py-2">风险</th><th className="px-3 py-2">Ping</th><th className="px-3 py-2">TTFB</th><th className="px-3 py-2">测速</th><th className="px-3 py-2">ASN</th><th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {props.pagedNodes.map((node) => (
                  <tr key={node.fingerprint} className="border-t border-border">
                    <td className="px-3 py-3"><Badge tone={node.is_valid ? "green" : "red"}>{node.is_valid ? "有效" : "失败"}</Badge></td>
                    <td className="max-w-xs truncate px-3 py-3 font-medium">{node.enhanced_name_compact}</td>
                    <td className="px-3 py-3">{node.probe.actual_geo}</td>
                    <td className="px-3 py-3">{node.probe.network_labels.join("/") || "-"}</td>
                    <td className="px-3 py-3">{node.probe.type_labels.join("/") || "-"}</td>
                    <td className="px-3 py-3">{node.total_score.toFixed(1)}</td>
                    <td className="px-3 py-3">{node.probe.risk_score.toFixed(1)}</td>
                    <td className="px-3 py-3">{node.probe.tcp_ping_ms.toFixed(0)}</td>
                    <td className="px-3 py-3">{node.probe.ttfb_ms.toFixed(0)}</td>
                    <td className="px-3 py-3">{node.download_speed_mbps.toFixed(2)}</td>
                    <td className="max-w-xs truncate px-3 py-3">{node.probe.asn_org}</td>
                    <td className="px-3 py-3"><div className="flex gap-2"><Button variant="ghost" onClick={() => copyText(node.raw_uri)}>原始</Button><Button variant="ghost" onClick={() => copyText(node.enhanced_name_compact)}>compact</Button><Button variant="ghost" onClick={() => copyText(node.enhanced_name_detailed)}>detailed</Button><Button variant="secondary" onClick={() => props.onDetails(node)}>详情</Button></div></td>
                  </tr>
                ))}
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

function JobsView({ subscriptions, jobs }: { subscriptions: SubscriptionSummary[]; jobs: JobStatus[] }) {
  const nameById = new Map(subscriptions.map((subscription) => [subscription.id, subscription.name]));
  return (
    <Panel>
      <div className="mb-3 text-sm font-semibold text-slate-900">任务监控</div>
      {!jobs.length ? <EmptyState title="暂无任务" detail="添加订阅或刷新订阅后会显示任务进度。" /> : (
        <div className="space-y-3">
          {jobs.map((job) => {
            const percent = job.total_nodes ? Math.round((job.processed_nodes / job.total_nodes) * 100) : 0;
            return (
              <div key={job.job_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <div><div className="font-medium">{nameById.get(job.subscription_id) || job.subscription_id}</div><div className="text-xs text-slate-500">{job.job_id}</div></div>
                  <Badge tone={statusTone(job.status)}>{job.status}</Badge>
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
      <Panel><div className="text-sm font-semibold">命名示例</div><div className="mt-2 space-y-2 text-sm text-slate-600"><div>🇯🇵 JP | 机房 | Clean | 92分 | 210ms</div><div>🇯🇵 JP | 机房 | Clean | 92分 | 80ms/210ms | 12.34Mbps | Example ASN | JP</div></div></Panel>
    </div>
  );
}

function SettingsView({ settings, preferences, onSaveSettings, onPreferences, onReset }: { settings?: RuntimeSettings; preferences: LocalPreferences; onSaveSettings: (settings: Partial<RuntimeSettings>) => void; onPreferences: (preferences: LocalPreferences) => void; onReset: () => void }) {
  const [draft, setDraft] = useState<Partial<RuntimeSettings>>({});
  const current = { ...(settings || {}), ...draft } as RuntimeSettings;
  return (
    <div className="grid grid-cols-2 gap-4">
      <Panel>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><SlidersHorizontal className="h-4 w-4 text-blue-600" />后端运行设置</div>
        {!settings ? <EmptyState title="设置加载中" /> : (
          <div className="grid grid-cols-2 gap-3">
            <SettingNumber label="过滤并发" value={current.FILTER_CONCURRENCY} onChange={(value) => setDraft({ ...draft, FILTER_CONCURRENCY: value })} />
            <SettingNumber label="测速并发" value={current.SPEEDTEST_CONCURRENCY} onChange={(value) => setDraft({ ...draft, SPEEDTEST_CONCURRENCY: value })} />
            <SettingNumber label="默认测速数量" value={current.API_DEFAULT_SPEEDTEST_LIMIT} onChange={(value) => setDraft({ ...draft, API_DEFAULT_SPEEDTEST_LIMIT: value })} />
            <SettingNumber label="缓存 TTL 秒" value={current.PROBE_CACHE_TTL_SECONDS} onChange={(value) => setDraft({ ...draft, PROBE_CACHE_TTL_SECONDS: value })} />
            <SettingNumber label="订阅最大字节" value={current.SUBSCRIPTION_MAX_BYTES} onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_MAX_BYTES: value })} />
            <SettingNumber label="测速最大字节" value={current.SPEEDTEST_MAX_BYTES} onChange={(value) => setDraft({ ...draft, SPEEDTEST_MAX_BYTES: value })} />
            <SettingNumber label="compact 长度" value={current.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH} onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: value })} />
            <SettingNumber label="detailed 长度" value={current.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH} onChange={(value) => setDraft({ ...draft, SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: value })} />
            <div><Label>缓存开关</Label><Select className="mt-1 w-full" value={String(current.CACHE_ENABLED)} onChange={(event) => setDraft({ ...draft, CACHE_ENABLED: event.target.value === "true" })}><option value="true">开启</option><option value="false">关闭</option></Select></div>
            <div><Label>缓存失败结果</Label><Select className="mt-1 w-full" value={String(current.CACHE_FAILURE_RESULTS)} onChange={(event) => setDraft({ ...draft, CACHE_FAILURE_RESULTS: event.target.value === "true" })}><option value="false">关闭</option><option value="true">开启</option></Select></div>
            <div className="col-span-2"><Label>TTFB URL</Label><Input className="mt-1" value={current.TTFB_TARGET_URL || ""} onChange={(event) => setDraft({ ...draft, TTFB_TARGET_URL: event.target.value })} /></div>
            <div className="col-span-2"><Label>测速 URL</Label><Input className="mt-1" value={current.SPEEDTEST_URL || ""} onChange={(event) => setDraft({ ...draft, SPEEDTEST_URL: event.target.value })} /></div>
            <div className="col-span-2 flex justify-end gap-2"><Button variant="secondary" onClick={() => { setDraft({}); onReset(); }}>重置</Button><Button onClick={() => { onSaveSettings(draft); setDraft({}); }}><Save className="h-4 w-4" />保存设置</Button></div>
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

function SettingNumber({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <div><Label>{label}</Label><Input className="mt-1" type="number" value={value ?? 0} onChange={(event) => onChange(Number(event.target.value))} /></div>;
}

function NodeDrawer({ node, onClose }: { node: NodeResult; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-30 bg-slate-950/20">
      <aside className="absolute inset-y-0 right-0 w-[560px] overflow-y-auto border-l border-border bg-white p-5 shadow-2xl">
        <div className="flex items-center justify-between"><div className="text-lg font-semibold">节点详情</div><Button variant="secondary" onClick={onClose}>关闭</Button></div>
        <div className="mt-4 space-y-4 text-sm">
          <Panel><div className="font-medium">{node.enhanced_name_detailed}</div><div className="mt-2 text-slate-500">{node.original_name}</div></Panel>
          <Panel><pre className="whitespace-pre-wrap break-all text-xs">{node.raw_uri}</pre></Panel>
          <Panel><div className="grid grid-cols-2 gap-2"><Detail label="出口 IP" value={node.probe.actual_ip} /><Detail label="ASN" value={node.probe.asn_org} /><Detail label="拒绝原因" value={node.reject_reason || "-"} /><Detail label="骨干网" value={node.probe.backbone_info || "-"} /><Detail label="绕路" value={node.probe.is_detour ? "Yes" : "No"} /><Detail label="置信度" value={node.probe.confidence} /></div></Panel>
          <Panel><div className="mb-2 font-medium">Evidence</div><div className="space-y-2">{node.probe.evidence.length ? node.probe.evidence.map((item) => <div key={item} className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">{item}</div>) : <div className="text-slate-500">No evidence</div>}</div></Panel>
        </div>
      </aside>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs text-slate-500">{label}</div><div className="mt-1 break-all font-medium">{value}</div></div>;
}

export type Status = "new" | "queued" | "running" | "completed" | "failed" | "canceled";
export type Phase = "queued" | "fetch" | "filter" | "speedtest" | "completed" | "failed" | "canceled";
export type ExportMode = "compact" | "detailed";
export type ExportFormat = "base64" | "plain";

export interface SubscriptionSummary {
  id: string;
  name: string;
  url: string;
  last_status: Status;
  node_count: number;
  valid_count: number;
  updated_at: number;
  last_job_id?: string | null;
}

export interface JobStatus {
  job_id: string;
  subscription_id: string;
  status: Status;
  phase: Phase;
  processed_nodes: number;
  total_nodes: number;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface LabelEvidence {
  label: string;
  confidence: number;
  display: string;
}

export interface ApiVerdict {
  source: string;
  site_id: string;
  status: "success" | "timeout" | "rate_limited" | "error" | "no_data";
  network_labels: LabelEvidence[];
  risk_labels: LabelEvidence[];
  risk_score: number | null;
  raw_summary: string;
}

export interface NodeProbe {
  tcp_ping_ms: number;
  ttfb_ms: number;
  actual_ip: string;
  actual_geo: string;
  asn_org: string;
  ipv6_support: boolean;
  actual_ipv6: string;
  risk_score: number | null;
  network_labels: string[];
  type_labels: string[];
  confidence: string;
  is_detour: boolean;
  is_backbone: boolean;
  backbone_info: string;
  evidence: ApiVerdict[];
}

export interface NodeResult {
  fingerprint: string;
  original_name: string;
  enhanced_name_compact: string;
  enhanced_name_detailed: string;
  raw_uri: string;
  compact_uri: string;
  detailed_uri: string;
  is_valid: boolean;
  reject_reason: string;
  download_speed_mbps: number | null;
  speedtest_status: "not_tested" | "failed" | "success";
  probe: NodeProbe;
}

export interface SubscriptionResults {
  subscription_id: string;
  status: "completed";
  subscription_status: Status;
  last_job_id?: string | null;
  node_count: number;
  valid_count: number;
  updated_at: number;
  api_sites_snapshot: ApiSite[];
  nodes: NodeResult[];
}

export interface ApiSite {
  id: string;
  column_name: string;
  provider: string;
  url_template: string;
  weight: number;
  enabled: boolean;
  order: number;
  api_key_configured: boolean;
}

export interface ApiSitesConfig {
  exit_ip_endpoint: string;
  sites: ApiSite[];
}

export interface ApiSiteInput {
  id: string;
  column_name: string;
  provider: string;
  url_template: string;
  api_key?: string;
  clear_api_key?: boolean;
  weight: number;
  enabled: boolean;
}

export interface RuntimeSettings {
  FILTER_CONCURRENCY: number;
  SPEEDTEST_CONCURRENCY: number;
  API_DEFAULT_SPEEDTEST_LIMIT: number;
  CACHE_ENABLED: boolean;
  PROBE_CACHE_TTL_SECONDS: number;
  CACHE_FAILURE_RESULTS: boolean;
  SUBSCRIPTION_MAX_M: number;
  SPEEDTEST_MAX_M: number;
  SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH: number;
  SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH: number;
  TTFB_TARGET_URL: string;
  SPEEDTEST_URL: string;
  PROXY_CORE: string;
}

export interface RuntimeSettingMetadata {
  type: "int" | "bool" | "str";
  min?: number;
  max?: number;
  min_length?: number;
}

export type RuntimeSettingsMetadata = Partial<Record<keyof RuntimeSettings, RuntimeSettingMetadata>>;

export interface LocalPreferences {
  apiBaseUrl: string;
  autoRefresh: boolean;
  defaultExportMode: ExportMode;
  defaultExportFormat: ExportFormat;
  pageSize: number;
}

export interface SingboxTemplate {
  id: string;
  name: string;
  content: string;
  created_at: number;
  updated_at: number;
}

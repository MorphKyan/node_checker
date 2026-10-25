import type { NodeResult } from "./types";

export function groupNodesByExitIp(nodes: NodeResult[]) {
  const groups = new Map<string, { key: string; ip: string; nodes: NodeResult[] }>();
  nodes.forEach((node, index) => {
    const ip = node.probe.actual_ip.trim();
    const key = ip ? `ip:${ip}` : `unknown:${node.fingerprint}:${index}`;
    const group = groups.get(key);
    if (group) group.nodes.push(node);
    else groups.set(key, { key, ip, nodes: [node] });
  });
  return Array.from(groups.values());
}

export type NodeSortKey = "name" | "status" | "geo" | "ping" | "ttfb" | "risk" | "speed" | "asn" | `site:${string}`;
export interface NodeSort { key: NodeSortKey; direction: "asc" | "desc" }

export function sortNodes(nodes: NodeResult[], sort: NodeSort | null): NodeResult[] {
  if (!sort) return nodes;
  const { key, direction } = sort;
  function value(node: NodeResult): string | number | null {
    switch (key) {
      case "name": return node.original_name;
      case "status": return node.is_valid ? 1 : 0;
      case "geo": return node.probe.actual_geo || null;
      case "ping": return node.probe.tcp_ping_ms;
      case "ttfb": return node.probe.ttfb_ms;
      case "risk": return node.probe.risk_score;
      case "speed": return node.download_speed_mbps;
      case "asn": return node.probe.asn_org || null;
      default: {
        const verdict = node.probe.evidence.find((item) => item.site_id === key.slice(5));
        return verdict?.status === "success" ? verdict.risk_score : null;
      }
    }
  }
  return [...nodes].sort((a, b) => {
    const left = value(a), right = value(b);
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    const comparison = typeof left === "number" && typeof right === "number"
      ? left - right : String(left).localeCompare(String(right), "zh-CN", { numeric: true });
    return direction === "asc" ? comparison : -comparison;
  });
}

export interface NodeFilters {
  nodeSearch: string;
  nodeValidity: string;
  nodeGeo: string;
  nodeNetwork: string;
  nodeType: string;
  maxRisk: string;
  maxTtfb: string;
  minSpeed: string;
  detourFilter: string;
  backboneFilter: string;
}

export function filterNodes(nodes: NodeResult[], filters: NodeFilters): NodeResult[] {
  const search = filters.nodeSearch.trim().toLowerCase();
  return nodes.filter((node) => {
    if (search && !node.original_name.toLowerCase().includes(search)) return false;
    if (filters.nodeValidity === "valid" && !node.is_valid) return false;
    if (filters.nodeValidity === "invalid" && node.is_valid) return false;
    if (filters.nodeGeo !== "all" && node.probe.actual_geo !== filters.nodeGeo) return false;
    if (filters.nodeNetwork !== "all" && !node.probe.network_labels.includes(filters.nodeNetwork)) return false;
    if (filters.nodeType !== "all" && !node.probe.type_labels.includes(filters.nodeType)) return false;
    if (filters.maxRisk && (node.probe.risk_score === null || node.probe.risk_score > Number(filters.maxRisk))) return false;
    if (filters.maxTtfb && node.probe.ttfb_ms > Number(filters.maxTtfb)) return false;
    if (filters.minSpeed && (node.download_speed_mbps === null || node.download_speed_mbps < Number(filters.minSpeed))) return false;
    if (filters.detourFilter === "yes" && node.probe.is_detour !== true) return false;
    if (filters.detourFilter === "no" && node.probe.is_detour !== false) return false;
    if (filters.backboneFilter === "yes" && node.probe.is_backbone !== true) return false;
    if (filters.backboneFilter === "no" && node.probe.is_backbone !== false) return false;
    return true;
  });
}

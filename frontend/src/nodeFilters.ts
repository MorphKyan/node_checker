import type { NodeResult } from "./types";

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
  return nodes.filter((node) => {
    const search = filters.nodeSearch.trim().toLowerCase();
    const searchableText = `${node.original_name} ${node.enhanced_name_compact} ${node.probe.actual_ip} ${node.probe.asn_org}`.toLowerCase();
    if (search && !searchableText.includes(search)) return false;
    if (filters.nodeValidity === "valid" && !node.is_valid) return false;
    if (filters.nodeValidity === "invalid" && node.is_valid) return false;
    if (filters.nodeGeo !== "all" && node.probe.actual_geo !== filters.nodeGeo) return false;
    if (filters.nodeNetwork !== "all" && !node.probe.network_labels.includes(filters.nodeNetwork)) return false;
    if (filters.nodeType !== "all" && !node.probe.type_labels.includes(filters.nodeType)) return false;
    if (filters.maxRisk && (node.probe.risk_score === null || node.probe.risk_score > Number(filters.maxRisk))) return false;
    if (filters.maxTtfb && node.probe.ttfb_ms > Number(filters.maxTtfb)) return false;
    if (filters.minSpeed && (node.download_speed_mbps === null || node.download_speed_mbps < Number(filters.minSpeed))) return false;
    if (filters.detourFilter === "yes" && !node.probe.is_detour) return false;
    if (filters.detourFilter === "no" && node.probe.is_detour) return false;
    if (filters.backboneFilter === "yes" && !node.probe.is_backbone) return false;
    if (filters.backboneFilter === "no" && node.probe.is_backbone) return false;
    return true;
  });
}

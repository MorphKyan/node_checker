import { describe, expect, it } from "vitest";
import { filterNodes, groupNodesByExitIp, sortNodes, type NodeSortKey } from "./nodeFilters";
import type { NodeResult } from "./types";

function makeNode(overrides: Partial<NodeResult>): NodeResult {
  return {
    fingerprint: "fp",
    original_name: "JP",
    enhanced_name_compact: "JP | 机房 | Clean | 风险 35",
    enhanced_name_detailed: "JP | 机房 | Clean | 风险 35 | Example ASN",
    raw_uri: "vless://uuid@example.com:443#JP",
    compact_uri: "vless://uuid@example.com:443#JP%20%7C%20risk%2035",
    detailed_uri: "vless://uuid@example.com:443#JP%20%7C%20risk%2035%20%7C%20Example%20ASN",
    is_valid: true,
    reject_reason: "",
    download_speed_mbps: 12,
    speedtest_status: "success",
    probe: {
      tcp_ping_ms: 80,
      ttfb_ms: 210,
      actual_ip: "203.0.113.10",
      actual_geo: "JP",
      asn_org: "Example ASN",
      risk_score: 35,
      network_labels: ["机房"],
      type_labels: ["Clean"],
      confidence: "high",
      is_detour: false,
      is_backbone: true,
      backbone_info: "CN2",
      evidence: [],
      ipv6_support: false,
      actual_ipv6: "",
    },
    ...overrides,
  };
}

const emptyFilters = {
  nodeSearch: "",
  nodeValidity: "all",
  nodeGeo: "all",
  nodeNetwork: "all",
  nodeType: "all",
  maxRisk: "",
  maxTtfb: "",
  minSpeed: "",
  detourFilter: "all",
  backboneFilter: "all",
};

describe("sortNodes", () => {
  it("sorts numbers, names and site risk without mutating input; missing values stay last", () => {
    const nodes = [
      makeNode({ original_name: "node 10", download_speed_mbps: 10 }),
      makeNode({ original_name: "node 2", download_speed_mbps: 2 }),
      makeNode({ original_name: "node 20", download_speed_mbps: null }),
    ];
    for (const key of ["name", "speed"] as NodeSortKey[]) {
      expect(sortNodes(nodes, { key, direction: "asc" }).map((node) => node.original_name)).toEqual(["node 2", "node 10", "node 20"]);
    }
    expect(sortNodes(nodes, { key: "speed", direction: "desc" }).map((node) => node.download_speed_mbps)).toEqual([10, 2, null]);
    const siteNodes = nodes.map((node) => ({ ...node, probe: { ...node.probe, evidence: [{ source: "test", site_id: "site", status: "success" as const, network_labels: [], risk_labels: [], risk_score: node.download_speed_mbps, raw_summary: "" }] } }));
    expect(sortNodes(siteNodes, { key: "site:site", direction: "asc" }).map((node) => node.download_speed_mbps)).toEqual([2, 10, null]);
    expect(sortNodes(siteNodes, { key: "site:site", direction: "desc" }).map((node) => node.download_speed_mbps)).toEqual([10, 2, null]);
    expect(nodes.map((node) => node.original_name)).toEqual(["node 10", "node 2", "node 20"]);
  });
});

describe("filterNodes", () => {
  it("searches only the original name, ignoring case and surrounding whitespace", () => {
    const node = makeNode({ original_name: "JP Tokyo" });
    expect(filterNodes([node], { ...emptyFilters, nodeSearch: "  tOKyo  " })).toEqual([node]);
    for (const nodeSearch of ["机房", "Clean", "203.0.113.10", "Example ASN"]) {
      expect(filterNodes([node], { ...emptyFilters, nodeSearch })).toEqual([]);
    }
    expect(filterNodes([node], { ...emptyFilters, nodeSearch: "   " })).toEqual([node]);
  });

  it("keeps unmeasured routes out of both yes and no filters", () => {
    const node = makeNode({ probe: { ...makeNode({}).probe, is_detour: null, is_backbone: null } });
    expect(filterNodes([node], emptyFilters)).toEqual([node]);
    for (const field of ["detourFilter", "backboneFilter"]) {
      for (const value of ["yes", "no"]) {
        expect(filterNodes([node], { ...emptyFilters, [field]: value })).toEqual([]);
      }
    }
  });

  it("filters by profile, risk, latency, and route attributes", () => {
    const nodes = [
      makeNode({ fingerprint: "good" }),
      makeNode({
        fingerprint: "slow",
        // risk is intentionally below the max-risk threshold
        probe: { ...makeNode({}).probe, ttfb_ms: 900, network_labels: ["家宽"], is_backbone: false },
      }),
    ];

    const result = filterNodes(nodes, {
      ...emptyFilters,
      nodeNetwork: "机房",
      maxRisk: "80",
      maxTtfb: "300",
      backboneFilter: "yes",
    });

    expect(result.map((node) => node.fingerprint)).toEqual(["good"]);
  });
});

describe("groupNodesByExitIp", () => {
  it("groups nonadjacent exits and keeps unknown exits separate", () => {
    const first = makeNode({ original_name: "first" });
    const second = makeNode({ probe: { ...first.probe, actual_ip: "203.0.113.20" } });
    const duplicate = makeNode({ original_name: "duplicate" });
    const unknown = makeNode({ probe: { ...first.probe, actual_ip: "" } });
    const nodes = [first, second, duplicate, unknown, unknown];
    const groups = groupNodesByExitIp(nodes);
    expect(groups.map((group) => group.nodes)).toEqual([[first, duplicate], [second], [unknown], [unknown]]);
    expect(new Set(groups.map((group) => group.key)).size).toBe(4);
    expect(groupNodesByExitIp(filterNodes(nodes, { ...emptyFilters, nodeSearch: "duplicate" }))[0].nodes).toEqual([duplicate]);
    expect(groupNodesByExitIp([])).toEqual([]);
    expect(nodes).toEqual([first, second, duplicate, unknown, unknown]);
  });
});

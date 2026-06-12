import { describe, expect, it } from "vitest";
import { filterNodes } from "./nodeFilters";
import type { NodeResult } from "./types";

function makeNode(overrides: Partial<NodeResult>): NodeResult {
  return {
    fingerprint: "fp",
    original_name: "JP",
    enhanced_name_compact: "JP | 机房 | Clean | 92分",
    enhanced_name_detailed: "JP | 机房 | Clean | 92分 | Example ASN",
    raw_uri: "vless://uuid@example.com:443#JP",
    compact_uri: "vless://uuid@example.com:443#JP%20%7C%20%E6%9C%BA%E6%88%BF%20%7C%20Clean%20%7C%2092%E5%88%86",
    detailed_uri: "vless://uuid@example.com:443#JP%20%7C%20%E6%9C%BA%E6%88%BF%20%7C%20Clean%20%7C%2092%E5%88%86%20%7C%20Example%20ASN",
    is_valid: true,
    reject_reason: "",
    total_score: 92,
    download_speed_mbps: 12,
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
  minScore: "",
  maxTtfb: "",
  minSpeed: "",
  detourFilter: "all",
  backboneFilter: "all",
};

describe("filterNodes", () => {
  it("filters by profile, score, latency, and route attributes", () => {
    const nodes = [
      makeNode({ fingerprint: "good" }),
      makeNode({
        fingerprint: "slow",
        total_score: 50,
        probe: { ...makeNode({}).probe, ttfb_ms: 900, network_labels: ["家宽"], is_backbone: false },
      }),
    ];

    const result = filterNodes(nodes, {
      ...emptyFilters,
      nodeNetwork: "机房",
      minScore: "80",
      maxTtfb: "300",
      backboneFilter: "yes",
    });

    expect(result.map((node) => node.fingerprint)).toEqual(["good"]);
  });
});

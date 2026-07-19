import { describe, expect, it } from "vitest";
import { filterNodes } from "./nodeFilters";
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

describe("filterNodes", () => {
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

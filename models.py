from dataclasses import dataclass, field

@dataclass
class VlessNode:
    raw_uri: str
    uuid: str
    server_ip: str
    server_port: int
    remark: str
    expected_geo: str
    # Vless 额外参数
    flow: str = ""
    security: str = "" # none, tls, reality
    sni: str = ""
    alpn: str = ""
    fp: str = ""
    pbk: str = ""
    sid: str = ""
    type: str = "tcp" # network type: tcp, ws, grpc, etc.
    path: str = ""
    host: str = ""
    mode: str = ""

@dataclass
class LabelEvidence:
    label: str
    confidence: float

@dataclass
class ApiVerdict:
    source: str
    site_id: str = ""
    status: str = "success"
    network_labels: list[LabelEvidence] = field(default_factory=list)
    risk_labels: list[LabelEvidence] = field(default_factory=list)
    risk_score: float | None = None
    raw_summary: str = ""

@dataclass
class NodeProfile:
    display_labels: list[str] = field(default_factory=lambda: ["未知"])
    network_labels: list[LabelEvidence] = field(default_factory=list)
    risk_labels: list[LabelEvidence] = field(default_factory=list)
    risk_score: float | None = None
    confidence: str = "low"
    evidence: list[ApiVerdict] = field(default_factory=list)

@dataclass
class ProbeData:
    tcp_ping_ms: float
    ttfb_ms: float
    actual_ip: str
    actual_geo: str
    asn_org: str
    trace_path: str = ""
    is_detour: bool = False
    is_backbone: bool = False
    backbone_info: str = ""
    profile: NodeProfile = field(default_factory=NodeProfile)
    ipv6_support: bool = False
    actual_ipv6: str = ""

@dataclass
class AnalyzedNode:
    node: VlessNode
    probe: ProbeData
    is_valid: bool
    reject_reason: str = ""

@dataclass
class TestedNode:
    __test__ = False

    analyzed_node: AnalyzedNode
    download_speed_mbps: float | None = None
    speedtest_status: str = "not_tested"

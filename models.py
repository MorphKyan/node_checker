from dataclasses import dataclass

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
    fp: str = ""
    pbk: str = ""
    sid: str = ""
    type: str = "tcp" # network type: tcp, ws, grpc, etc.
    path: str = ""
    host: str = ""

@dataclass
class ProbeData:
    tcp_ping_ms: float
    ttfb_ms: float
    actual_ip: str
    actual_geo: str
    asn_org: str
    fraud_score: int
    risk_tags: str = ""
    ipwhois_info: str = ""
    ipapi_info: str = ""
    scamalytics_info: str = ""
    trace_path: str = ""
    is_detour: bool = False
    is_backbone: bool = False
    backbone_info: str = ""

@dataclass
class AnalyzedNode:
    node: VlessNode
    probe: ProbeData
    is_valid: bool
    total_score: float
    reject_reason: str
    score_details: str = ""

@dataclass
class TestedNode:
    analyzed_node: AnalyzedNode
    download_speed_mbps: float

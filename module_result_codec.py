from dataclasses import fields

from models import ApiVerdict, AnalyzedNode, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode, Hy2Node, ProxyNode, SsNode


def restore_proxy_node(node_data: dict) -> ProxyNode:
    protocol = node_data.get("protocol", "")
    raw_uri = node_data.get("raw_uri", "")
    if protocol == "ss" or raw_uri.startswith("ss://"):
        node_type = SsNode
    elif protocol in {"hy2", "hysteria2"} or raw_uri.startswith("hy2://") or raw_uri.startswith("hysteria2://"):
        node_type = Hy2Node
    else:
        node_type = VlessNode
    allowed = {field.name for field in fields(node_type)}
    return node_type(**{key: value for key, value in node_data.items() if key in allowed})


def _restore_label_evidence(items) -> list[LabelEvidence]:
    restored = []
    for item in items or []:
        if isinstance(item, LabelEvidence):
            restored.append(item)
        elif isinstance(item, dict):
            restored.append(LabelEvidence(**item))
    return restored


def _restore_api_verdict(data) -> ApiVerdict:
    if isinstance(data, ApiVerdict):
        return data
    return ApiVerdict(
        source=data.get("source", ""),
        site_id=data.get("site_id", ""),
        status=data.get("status", "no_data"),
        network_labels=_restore_label_evidence(data.get("network_labels")),
        risk_labels=_restore_label_evidence(data.get("risk_labels")),
        risk_score=data.get("risk_score"),
        raw_summary=data.get("raw_summary", ""),
        raw_data=data.get("raw_data"),
    )


def restore_node_profile(data) -> NodeProfile:
    if isinstance(data, NodeProfile):
        return data
    if not isinstance(data, dict):
        return NodeProfile()
    return NodeProfile(
        display_labels=list(data.get("display_labels") or ["未知"]),
        network_labels=_restore_label_evidence(data.get("network_labels")),
        risk_labels=_restore_label_evidence(data.get("risk_labels")),
        risk_score=float(data["risk_score"]) if data.get("risk_score") is not None else None,
        confidence=data.get("confidence", "low"),
        evidence=[
            _restore_api_verdict(item)
            for item in data.get("evidence", [])
            if isinstance(item, (ApiVerdict, dict))
        ],
    )


def restore_probe_data(data: dict) -> ProbeData:
    allowed = {field.name for field in fields(ProbeData)}
    data = {key: value for key, value in dict(data).items() if key in allowed}
    if not data.get("trace_path"):
        # Historical probes stored false even when no route was measured.
        data["is_detour"] = data["is_backbone"] = None
    if "profile" in data:
        data["profile"] = restore_node_profile(data["profile"])
    return ProbeData(**data)


def restore_tested_nodes(data: list[dict]) -> list[TestedNode]:
    restored = []
    for item in data:
        analyzed_data = item["analyzed_node"]
        node = restore_proxy_node(analyzed_data["node"])
        probe = restore_probe_data(analyzed_data["probe"])
        analyzed = AnalyzedNode(
            node=node,
            probe=probe,
            is_valid=analyzed_data["is_valid"],
            reject_reason=analyzed_data.get("reject_reason", ""),
        )
        restored.append(
            TestedNode(
                analyzed_node=analyzed,
                download_speed_mbps=item.get("download_speed_mbps"),
                speedtest_status=item.get("speedtest_status", "not_tested"),
            )
        )
    return restored

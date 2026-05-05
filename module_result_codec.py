import json
from dataclasses import asdict

from models import ApiVerdict, AnalyzedNode, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode


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
        network_labels=_restore_label_evidence(data.get("network_labels")),
        risk_labels=_restore_label_evidence(data.get("risk_labels")),
        risk_score=data.get("risk_score"),
        raw_summary=data.get("raw_summary", ""),
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
        risk_score=float(data.get("risk_score", 0.0) or 0.0),
        confidence=data.get("confidence", "low"),
        evidence=[
            _restore_api_verdict(item)
            for item in data.get("evidence", [])
            if isinstance(item, (ApiVerdict, dict))
        ],
    )


def restore_probe_data(data: dict) -> ProbeData:
    data = dict(data)
    if "profile" in data:
        data["profile"] = restore_node_profile(data["profile"])
    return ProbeData(**data)


def probe_data_to_json(probe_data: ProbeData) -> str:
    return json.dumps(asdict(probe_data), ensure_ascii=False)


def tested_nodes_to_json(nodes: list[TestedNode]) -> str:
    return json.dumps([asdict(node) for node in nodes], ensure_ascii=False)


def tested_nodes_from_json(payload: str) -> list[TestedNode]:
    return restore_tested_nodes(json.loads(payload))


def restore_tested_nodes(data: list[dict]) -> list[TestedNode]:
    restored = []
    for item in data:
        analyzed_data = item["analyzed_node"]
        node = VlessNode(**analyzed_data["node"])
        probe = restore_probe_data(analyzed_data["probe"])
        analyzed = AnalyzedNode(
            node=node,
            probe=probe,
            is_valid=analyzed_data["is_valid"],
            total_score=analyzed_data["total_score"],
            reject_reason=analyzed_data.get("reject_reason", ""),
            score_details=analyzed_data.get("score_details", ""),
        )
        restored.append(
            TestedNode(
                analyzed_node=analyzed,
                download_speed_mbps=item.get("download_speed_mbps", 0.0),
            )
        )
    return restored

from typing import Literal

from models import TestedNode
from module_node_identity import make_node_fingerprint
from module_subscription_exporter import SubscriptionExporter
from settings import settings


def normalize_job(row: dict) -> dict:
    return {
        "job_id": row["id"],
        "subscription_id": row["subscription_id"],
        "status": row["status"],
        "phase": row["phase"],
        "processed_nodes": row["processed_nodes"],
        "total_nodes": row["total_nodes"],
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def build_plain_subscription(
    nodes: list[TestedNode],
    *,
    mode: Literal["compact", "detailed"],
    valid_only: bool,
) -> str:
    max_length = (
        settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH
        if mode == "compact"
        else settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH
    )
    uris = SubscriptionExporter.build_uris(
        nodes,
        mode,
        max_length,
        valid_only=valid_only,
    )
    content = "\n".join(uris)
    return content + "\n" if content else ""


def build_detail_nodes(nodes: list[TestedNode]) -> list[dict]:
    from module_profile import DISPLAY_LABELS
    sorted_nodes = SubscriptionExporter.sort_nodes(nodes, valid_only=False)
    compact_names = SubscriptionExporter.deduplicate_names(
        [
            SubscriptionExporter.build_remark(
                node,
                "compact",
                settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH,
            )
            for node in sorted_nodes
        ],
        settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH,
    )
    detailed_names = SubscriptionExporter.deduplicate_names(
        [
            SubscriptionExporter.build_remark(
                node,
                "detailed",
                settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH,
            )
            for node in sorted_nodes
        ],
        settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH,
    )

    response_nodes = []
    for tested, compact_name, detailed_name in zip(sorted_nodes, compact_names, detailed_names):
        analyzed = tested.analyzed_node
        node = analyzed.node
        probe = analyzed.probe
        profile = probe.profile
        response_nodes.append(
            {
                "fingerprint": make_node_fingerprint(node),
                "original_name": node.remark,
                "enhanced_name_compact": compact_name,
                "enhanced_name_detailed": detailed_name,
                "raw_uri": node.raw_uri,
                "compact_uri": SubscriptionExporter.rewrite_vless_remark(node.raw_uri, compact_name),
                "detailed_uri": SubscriptionExporter.rewrite_vless_remark(node.raw_uri, detailed_name),
                "is_valid": analyzed.is_valid,
                "reject_reason": analyzed.reject_reason,
                "download_speed_mbps": tested.download_speed_mbps,
                "speedtest_status": tested.speedtest_status,
                "probe": {
                    "tcp_ping_ms": probe.tcp_ping_ms,
                    "ttfb_ms": probe.ttfb_ms,
                    "actual_ip": probe.actual_ip,
                    "actual_geo": probe.actual_geo,
                    "asn_org": probe.asn_org,
                    "ipv6_support": probe.ipv6_support,
                    "actual_ipv6": probe.actual_ipv6,
                    "risk_score": profile.risk_score,
                    "network_labels": [
                        SubscriptionExporter.format_labels([label], "")
                        for label in profile.network_labels
                    ],
                    "type_labels": [
                        SubscriptionExporter.format_labels([label], "")
                        for label in profile.risk_labels
                    ],
                    "confidence": profile.confidence,
                    "is_detour": probe.is_detour,
                    "is_backbone": probe.is_backbone,
                    "backbone_info": probe.backbone_info,
                    "evidence": [
                        {
                            "source": verdict.source,
                            "site_id": verdict.site_id,
                            "status": verdict.status,
                            "network_labels": [
                                {
                                    "label": label.label,
                                    "confidence": label.confidence,
                                    "display": DISPLAY_LABELS.get(label.label, label.label),
                                }
                                for label in verdict.network_labels
                            ],
                            "risk_labels": [
                                {
                                    "label": label.label,
                                    "confidence": label.confidence,
                                    "display": DISPLAY_LABELS.get(label.label, label.label),
                                }
                                for label in verdict.risk_labels
                            ],
                            "risk_score": verdict.risk_score,
                            "raw_summary": verdict.raw_summary,
                        }
                        for verdict in profile.evidence
                    ],
                },
            }
        )
    return response_nodes

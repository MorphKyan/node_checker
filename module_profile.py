from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from math import isfinite
from typing import Any

from models import ApiVerdict, LabelEvidence, NodeProfile

NETWORK_LABELS = {
    "residential",
    "likely_residential",
    "mobile",
    "business",
    "datacenter",
    "hosting",
    "unknown",
}

RISK_LABELS = {
    "clean",
    "vpn",
    "proxy",
    "tor",
    "abuser",
    "unknown",
}

DISPLAY_LABELS = {
    "residential": "家宽",
    "likely_residential": "家宽",
    "mobile": "移动网络",
    "business": "商宽",
    "datacenter": "机房",
    "hosting": "机房",
    "clean": "Clean",
    "vpn": "VPN",
    "proxy": "Proxy",
    "tor": "Tor",
    "abuser": "Abuse",
    "unknown": "未知",
}

RISK_BY_LABEL = {
    "clean": 0.0,
    "hosting": 40.0,
    "datacenter": 40.0,
    "vpn": 70.0,
    "proxy": 80.0,
    "abuser": 85.0,
    "tor": 95.0,
}

COMPANY_TYPE_MAP = {
    "hosting": ("hosting", 0.70),
    "host": ("hosting", 0.70),
    "datacenter": ("datacenter", 0.75),
    "data center": ("datacenter", 0.75),
    "cloud": ("datacenter", 0.65),
    "isp": ("likely_residential", 0.65),
    "telecom": ("likely_residential", 0.60),
    "mobile": ("mobile", 0.70),
    "wireless": ("mobile", 0.65),
    "business": ("business", 0.65),
    "education": ("business", 0.55),
}


def _label(label: str, confidence: float) -> LabelEvidence:
    return LabelEvidence(label, max(0.0, min(1.0, confidence)))


def _first_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except ValueError:
        return None


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _all_false(data: dict, keys: tuple[str, ...]) -> bool:
    return all(data.get(key) is False for key in keys)


def _estimated_risk(labels: list[LabelEvidence]) -> float | None:
    scores = [RISK_BY_LABEL[l.label] for l in labels if l.label in RISK_BY_LABEL]
    return max(scores) if scores else None


def _company_type_label(company_type: str) -> LabelEvidence | None:
    normalized = company_type.strip().lower()
    for token, (label, confidence) in COMPANY_TYPE_MAP.items():
        if token in normalized:
            return _label(label, confidence)
    return None


class ProfileAdapters:
    @staticmethod
    def from_ipwhois(data: dict[str, Any] | None) -> ApiVerdict:
        if not isinstance(data, dict) or data.get("success") is not True:
            return ApiVerdict("ipwho.is", status="no_data", raw_summary="No successful response")

        security = _mapping(data.get("security"))
        network_labels = []
        risk_labels = []
        summary = []

        if security.get("hosting") is True:
            network_labels.append(_label("hosting", 0.85))
            summary.append("hosting=true")
        if security.get("proxy") is True:
            risk_labels.append(_label("proxy", 0.90))
            summary.append("proxy=true")
        if security.get("vpn") is True:
            risk_labels.append(_label("vpn", 0.90))
            summary.append("vpn=true")
        if security.get("tor") is True:
            risk_labels.append(_label("tor", 0.95))
            summary.append("tor=true")

        if not risk_labels and _all_false(security, ("proxy", "vpn", "tor")):
            risk_labels.append(_label("clean", 0.55))
            summary.append("security clean")

        all_risk_labels = risk_labels + network_labels
        return ApiVerdict(
            source="ipwho.is",
            status="success" if risk_labels else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=_estimated_risk(all_risk_labels) if risk_labels else None,
            raw_summary=", ".join(summary),
        )

    @staticmethod
    def from_ipapi(data: dict[str, Any] | None) -> ApiVerdict:
        if not isinstance(data, dict) or not data or data.get("error"):
            return ApiVerdict("ipapi.is", status="no_data", raw_summary="No successful response")

        network_labels = []
        risk_labels = []
        summary = []

        if data.get("is_datacenter") is True:
            network_labels.append(_label("datacenter", 0.90))
            summary.append("is_datacenter=true")
        if data.get("is_proxy") is True:
            risk_labels.append(_label("proxy", 0.90))
            summary.append("is_proxy=true")
        if data.get("is_vpn") is True:
            risk_labels.append(_label("vpn", 0.90))
            summary.append("is_vpn=true")
        if data.get("is_tor") is True:
            risk_labels.append(_label("tor", 0.95))
            summary.append("is_tor=true")
        if data.get("is_abuser") is True:
            risk_labels.append(_label("abuser", 0.85))
            summary.append("is_abuser=true")

        company_type = str(_mapping(data.get("company")).get("type") or "")
        company_label = _company_type_label(company_type)
        if company_label:
            network_labels.append(company_label)
            summary.append(f"company.type={company_type}")

        if not risk_labels and _all_false(data, ("is_proxy", "is_vpn", "is_tor", "is_abuser")):
            risk_labels.append(_label("clean", 0.55))
            summary.append("risk clean")

        all_risk_labels = risk_labels + network_labels
        return ApiVerdict(
            source="ipapi.is",
            status="success" if risk_labels else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=_estimated_risk(all_risk_labels) if risk_labels else None,
            raw_summary=", ".join(summary),
        )

    @staticmethod
    def from_scamalytics(data: dict[str, Any] | None) -> ApiVerdict:
        if not isinstance(data, dict) or not data:
            return ApiVerdict("Scamalytics", status="no_data", raw_summary="No successful response")

        scam = data.get("scamalytics") if isinstance(data.get("scamalytics"), dict) else data
        proxy_data = _mapping(scam.get("scamalytics_proxy"))
        network_labels = []
        risk_labels = []
        summary = []

        score = _first_number(
            scam.get("scamalytics_score", scam.get("score", scam.get("fraud_score")))
        )
        risk = str(scam.get("scamalytics_risk", scam.get("risk", ""))).strip()
        if score is not None:
            summary.append(f"score={score:g}")
        if risk:
            summary.append(f"risk={risk}")

        if proxy_data.get("is_datacenter") is True:
            network_labels.append(_label("datacenter", 0.85))
            summary.append("is_datacenter=true")
        if proxy_data.get("is_vpn") is True:
            risk_labels.append(_label("vpn", 0.90))
            summary.append("is_vpn=true")
        if proxy_data.get("is_tor") is True:
            risk_labels.append(_label("tor", 0.95))
            summary.append("is_tor=true")
        if proxy_data.get("is_public_proxy") is True or proxy_data.get("is_web_proxy") is True:
            risk_labels.append(_label("proxy", 0.90))
            summary.append("is_proxy=true")

        if not risk_labels:
            lowered_risk = risk.lower()
            if "high" in lowered_risk and score is not None and score >= 70:
                risk_labels.append(_label("abuser", 0.65))
            elif score is not None and score < 70 and _all_false(proxy_data, ("is_vpn", "is_tor", "is_public_proxy", "is_web_proxy")):
                risk_labels.append(_label("clean", 0.50))
                summary.append("proxy clean")

        return ApiVerdict(
            source="Scamalytics",
            status="success" if risk_labels or score is not None else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=score if score is not None else (_estimated_risk(risk_labels + network_labels) if risk_labels else None),
            raw_summary=", ".join(summary),
        )

    @staticmethod
    def from_proxycheck(data: dict[str, Any] | None, ip: str = "") -> ApiVerdict:
        if not isinstance(data, dict) or data.get("status") != "ok":
            return ApiVerdict("proxycheck.io", status="no_data", raw_summary="No successful response")

        result = data.get(ip) if ip else None
        if not isinstance(result, dict):
            for key, value in data.items():
                if key not in {"status", "query_time"} and isinstance(value, dict):
                    result = value
                    break
        if not isinstance(result, dict):
            return ApiVerdict("proxycheck.io", status="no_data", raw_summary="No IP result")

        detections = _mapping(result.get("detections"))
        network = _mapping(result.get("network"))
        network_labels = []
        risk_labels = []
        summary = []

        network_type = str(network.get("type") or "").strip()
        network_label = _company_type_label(network_type)
        if network_label:
            network_labels.append(network_label)
            summary.append(f"network.type={network_type}")

        if detections.get("hosting") is True:
            network_labels.append(_label("hosting", 0.85))
            summary.append("hosting=true")
        if detections.get("proxy") is True:
            risk_labels.append(_label("proxy", 0.95))
            summary.append("proxy=true")
        if detections.get("vpn") is True:
            risk_labels.append(_label("vpn", 0.90))
            summary.append("vpn=true")
        if detections.get("tor") is True:
            risk_labels.append(_label("tor", 0.98))
            summary.append("tor=true")
        if detections.get("compromised") is True:
            risk_labels.append(_label("abuser", 0.80))
            summary.append("compromised=true")

        risk = _first_number(detections.get("risk"))
        confidence = _first_number(detections.get("confidence"))
        if risk is not None:
            summary.append(f"risk={risk:g}")
        if confidence is not None:
            summary.append(f"confidence={confidence:g}")

        if not risk_labels and _all_false(detections, ("proxy", "vpn", "tor")):
            risk_labels.append(_label("clean", 0.80 if confidence is None else min(0.90, confidence / 100)))
            summary.append("detections clean")

        return ApiVerdict(
            source="proxycheck.io",
            status="success" if risk_labels or risk is not None else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=risk if risk is not None else (_estimated_risk(risk_labels + network_labels) if risk_labels else None),
            raw_summary=", ".join(summary),
        )

    @staticmethod
    def from_abstract(data: dict[str, Any] | None) -> ApiVerdict:
        if not isinstance(data, dict) or not isinstance(data.get("security"), dict):
            return ApiVerdict("Abstract API", status="no_data", raw_summary="No successful response")

        security = _mapping(data.get("security"))
        asn = _mapping(data.get("asn"))
        company = _mapping(data.get("company"))
        network_labels = []
        risk_labels = []
        summary = []

        company_type = str(company.get("type") or asn.get("type") or "").strip()
        company_label = _company_type_label(company_type)
        if company_label:
            network_labels.append(company_label)
            summary.append(f"company.type={company_type}")

        if security.get("is_hosting") is True:
            network_labels.append(_label("hosting", 0.80))
            summary.append("is_hosting=true")
        if security.get("is_mobile") is True:
            network_labels.append(_label("mobile", 0.75))
            summary.append("is_mobile=true")
        if security.get("is_proxy") is True:
            risk_labels.append(_label("proxy", 0.85))
            summary.append("is_proxy=true")
        if security.get("is_vpn") is True:
            risk_labels.append(_label("vpn", 0.55))
            summary.append("is_vpn=true")
        if security.get("is_tor") is True:
            risk_labels.append(_label("tor", 0.95))
            summary.append("is_tor=true")
        if security.get("is_abuse") is True:
            risk_labels.append(_label("abuser", 0.80))
            summary.append("is_abuse=true")

        if not risk_labels and _all_false(security, ("is_proxy", "is_vpn", "is_tor", "is_abuse")):
            risk_labels.append(_label("clean", 0.55))
            summary.append("security clean")

        return ApiVerdict(
            source="Abstract API",
            status="success" if risk_labels else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=_estimated_risk(risk_labels + network_labels) if risk_labels else None,
            raw_summary=", ".join(summary),
        )

    @staticmethod
    def from_ip2location(data: dict[str, Any] | None) -> ApiVerdict:
        if not isinstance(data, dict) or data.get("error"):
            return ApiVerdict("IP2Location.io", status="no_data", raw_summary="No successful response")

        network_labels = []
        risk_labels = []
        summary = []

        usage_type = str(data.get("usage_type") or "").strip()
        usage_upper = usage_type.upper()
        if usage_type:
            summary.append(f"usage_type={usage_type}")
        if usage_upper in {"DCH", "CDN"}:
            network_labels.append(_label("datacenter", 0.75))
        elif usage_upper in {"ISP", "MOB"}:
            label = "mobile" if usage_upper == "MOB" else "likely_residential"
            network_labels.append(_label(label, 0.60))
        elif usage_upper in {"COM", "ORG", "EDU", "GOV", "MIL"}:
            network_labels.append(_label("business", 0.55))

        proxy = data.get("proxy") if isinstance(data.get("proxy"), dict) else {}
        proxy_type = str(proxy.get("proxy_type") or data.get("proxy_type") or "").strip().upper()
        if data.get("is_proxy") is True:
            risk_labels.append(_label("proxy", 0.80))
            summary.append("is_proxy=true")
        if proxy_type:
            summary.append(f"proxy_type={proxy_type}")
        if proxy_type == "VPN":
            risk_labels.append(_label("vpn", 0.85))
        elif proxy_type == "TOR":
            risk_labels.append(_label("tor", 0.95))
        elif proxy_type in {"PUB", "WEB", "SES", "RES"}:
            risk_labels.append(_label("proxy", 0.85))

        fraud_score = _first_number(proxy.get("fraud_score", data.get("fraud_score")))
        if fraud_score is not None:
            summary.append(f"fraud_score={fraud_score:g}")
            if fraud_score >= 75 and not risk_labels:
                risk_labels.append(_label("abuser", 0.65))

        if not risk_labels and data.get("is_proxy") is False:
            risk_labels.append(_label("clean", 0.50))
            summary.append("proxy clean")

        return ApiVerdict(
            source="IP2Location.io",
            status="success" if risk_labels or fraud_score is not None else "no_data",
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=fraud_score if fraud_score is not None else (_estimated_risk(risk_labels + network_labels) if risk_labels else None),
            raw_summary=", ".join(summary),
        )


class NodeProfileAggregator:
    NETWORK_THRESHOLD = 0.50
    RISK_THRESHOLD = 0.50
    MAX_NETWORK_LABELS = 2

    @staticmethod
    def aggregate(verdicts: list[ApiVerdict], source_weights: dict[str, float] | None = None) -> NodeProfile:
        source_weights = source_weights or {}
        network_scores: dict[str, float] = defaultdict(float)
        risk_scores_by_label: dict[str, float] = defaultdict(float)
        weighted_risk_score = 0.0
        risk_score_weight = 0.0

        for verdict in verdicts:
            weight = source_weights.get(verdict.site_id or verdict.source, 1.0)
            for item in verdict.network_labels:
                if item.label in NETWORK_LABELS and item.label != "unknown":
                    network_scores[item.label] += item.confidence * weight
            for item in verdict.risk_labels:
                if item.label in RISK_LABELS and item.label != "unknown":
                    risk_scores_by_label[item.label] += item.confidence * weight
            if verdict.status == "success" and verdict.risk_score is not None:
                confidence = max(
                    [i.confidence for i in verdict.network_labels + verdict.risk_labels],
                    default=0.5,
                )
                weighted_risk_score += verdict.risk_score * confidence * weight
                risk_score_weight += confidence * weight

        network_labels = NodeProfileAggregator._ranked_labels(
            network_scores,
            NodeProfileAggregator.NETWORK_THRESHOLD,
            NodeProfileAggregator.MAX_NETWORK_LABELS,
        )
        risk_labels = NodeProfileAggregator._ranked_labels(
            risk_scores_by_label,
            NodeProfileAggregator.RISK_THRESHOLD,
            None,
        )
        if any(item.label != "clean" for item in risk_labels):
            risk_labels = [item for item in risk_labels if item.label != "clean"]

        if not network_labels and not risk_labels:
            display_labels = ["未知"]
        else:
            display_labels = [
                DISPLAY_LABELS[item.label]
                for item in network_labels + risk_labels
                if item.label != "unknown"
            ] or ["未知"]

        top_confidence = max(
            [i.confidence for i in network_labels + risk_labels],
            default=0.0,
        )
        risk_score = (
            weighted_risk_score / risk_score_weight
            if risk_score_weight
            else None
        )

        return NodeProfile(
            display_labels=display_labels,
            network_labels=network_labels,
            risk_labels=risk_labels,
            risk_score=max(0.0, min(100.0, risk_score)) if risk_score is not None else None,
            confidence=NodeProfileAggregator._confidence_label(top_confidence),
            evidence=[replace(v) for v in verdicts],
        )

    @staticmethod
    def _ranked_labels(
        scores: dict[str, float],
        threshold: float,
        limit: int | None,
    ) -> list[LabelEvidence]:
        ranked = [
            _label(label, score)
            for label, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
            if score >= threshold
        ]
        return ranked[:limit] if limit is not None else ranked

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.45:
            return "medium"
        return "low"

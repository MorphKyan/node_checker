from models import VlessNode, ProbeData, AnalyzedNode
from settings import settings

class NodeAnalyzer:
    @staticmethod
    def analyze(node: VlessNode, probe: ProbeData) -> AnalyzedNode:
        is_valid = True
        reject_reason = ""
        total_score = 0.0
        score_details = "N/A"

        if probe.tcp_ping_ms >= 9999.0 or probe.ttfb_ms >= 9999.0:
            is_valid = False
            reject_reason = "Timeout"
            return AnalyzedNode(node, probe, is_valid, total_score, reject_reason, score_details)

        if probe.fraud_score > settings.FRAUD_SCORE_TOLERANCE:
            is_valid = False
            reject_reason = f"High Risk (Score {probe.fraud_score})"
            return AnalyzedNode(node, probe, is_valid, total_score, reject_reason, score_details)

        if node.expected_geo != "Unknown" and probe.actual_geo != "Unknown":
            if node.expected_geo != probe.actual_geo:
                is_valid = False
                reject_reason = f"Geo Mismatch (Expected {node.expected_geo}, Actual {probe.actual_geo})"
                return AnalyzedNode(node, probe, is_valid, total_score, reject_reason, score_details)

        ttfb_deduct = max(0, (probe.ttfb_ms - 500) / 50.0)
        total_score = max(0.0, 100.0 - ttfb_deduct - probe.fraud_score)
        
        score_details = f"Base: 100, TTFB Deduct: -{ttfb_deduct:.1f}, Risk Deduct: -{probe.fraud_score}"

        if total_score < settings.MIN_TOTAL_SCORE:
            is_valid = False
            reject_reason = f"Score Too Low ({total_score:.1f})"

        return AnalyzedNode(node, probe, is_valid, total_score, reject_reason, score_details)

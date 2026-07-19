from models import VlessNode, ProbeData, AnalyzedNode


class NodeAnalyzer:
    @staticmethod
    def analyze(node: VlessNode, probe: ProbeData) -> AnalyzedNode:
        """TTFB is the sole validity signal; all other probes are evidence."""
        is_valid = probe.ttfb_ms is not None and probe.ttfb_ms < 9999.0
        return AnalyzedNode(node, probe, is_valid, "" if is_valid else "TTFB timeout")

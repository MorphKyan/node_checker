from models import ProxyNode, ProbeData, AnalyzedNode


class NodeAnalyzer:
    @staticmethod
    def analyze(node: ProxyNode, probe: ProbeData) -> AnalyzedNode:
        """TTFB is the sole validity signal; all other probes are evidence."""
        is_valid = probe.ttfb_ms is not None and probe.ttfb_ms < 9999.0
        return AnalyzedNode(node, probe, is_valid, "" if is_valid else "HTTP connectivity check failed")

import unittest

from models import AnalyzedNode, ApiVerdict, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode
from module_result_codec import restore_probe_data, tested_nodes_from_json, tested_nodes_to_json


def make_node() -> TestedNode:
    node = VlessNode(
        raw_uri="vless://uuid@example.com:443?security=tls#JP",
        uuid="uuid",
        server_ip="example.com",
        server_port=443,
        remark="JP",
        expected_geo="JP",
    )
    probe = ProbeData(
        tcp_ping_ms=80.0,
        ttfb_ms=210.0,
        actual_ip="203.0.113.10",
        actual_geo="JP",
        asn_org="Example ASN",
        fraud_score=20,
        profile=NodeProfile(
            network_labels=[LabelEvidence("hosting", 0.9)],
            risk_labels=[LabelEvidence("vpn", 0.8)],
            risk_score=72.5,
            confidence="high",
            evidence=[ApiVerdict("ipapi.is", raw_summary="is_vpn=true")],
        ),
    )
    return TestedNode(AnalyzedNode(node, probe, True, 92.0, "", "test score"), 12.34)


class ResultCodecTests(unittest.TestCase):
    def test_round_trips_tested_nodes_with_profile_evidence(self):
        restored = tested_nodes_from_json(tested_nodes_to_json([make_node()]))

        profile = restored[0].analyzed_node.probe.profile
        self.assertIsInstance(profile.network_labels[0], LabelEvidence)
        self.assertIsInstance(profile.evidence[0], ApiVerdict)
        self.assertEqual(profile.network_labels[0].label, "hosting")
        self.assertEqual(profile.evidence[0].raw_summary, "is_vpn=true")

    def test_restore_probe_data_accepts_missing_profile(self):
        probe = restore_probe_data(
            {
                "tcp_ping_ms": 9999.0,
                "ttfb_ms": 9999.0,
                "actual_ip": "",
                "actual_geo": "Unknown",
                "asn_org": "",
                "fraud_score": 0,
            }
        )

        self.assertEqual(probe.profile.display_labels, ["未知"])


if __name__ == "__main__":
    unittest.main()

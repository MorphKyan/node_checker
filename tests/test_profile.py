import unittest
from pathlib import Path

from models import AnalyzedNode, ProbeData, TestedNode, VlessNode
from module_exporter import ResultExporter
from module_profile import ProfileAdapters, NodeProfileAggregator


class ProfileAdapterTests(unittest.TestCase):
    def test_ipwhois_vpn_hosting(self):
        verdict = ProfileAdapters.from_ipwhois({
            "success": True,
            "security": {
                "proxy": False,
                "vpn": True,
                "tor": False,
                "hosting": True,
            },
        })

        self.assertEqual([item.label for item in verdict.network_labels], ["hosting"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["vpn"])
        self.assertGreaterEqual(verdict.risk_score, 70)

    def test_ipapi_company_type_does_not_turn_clean_into_residential(self):
        verdict = ProfileAdapters.from_ipapi({
            "is_proxy": False,
            "is_vpn": False,
            "is_tor": False,
            "is_datacenter": False,
            "is_abuser": False,
            "company": {"type": "isp"},
        })

        self.assertEqual([item.label for item in verdict.network_labels], ["likely_residential"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["clean"])

    def test_scamalytics_datacenter_proxy(self):
        verdict = ProfileAdapters.from_scamalytics({
            "scamalytics": {
                "scamalytics_score": 82,
                "scamalytics_risk": "high",
                "scamalytics_proxy": {
                    "is_datacenter": True,
                    "is_public_proxy": True,
                },
            },
        })

        self.assertEqual([item.label for item in verdict.network_labels], ["datacenter"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["proxy"])
        self.assertEqual(verdict.risk_score, 82)

    def test_proxycheck_tor_proxy(self):
        verdict = ProfileAdapters.from_proxycheck({
            "status": "ok",
            "185.220.101.1": {
                "network": {"type": "Business"},
                "detections": {
                    "proxy": True,
                    "vpn": False,
                    "tor": True,
                    "hosting": False,
                    "compromised": True,
                    "risk": 100,
                    "confidence": 100,
                },
            },
        }, "185.220.101.1")

        self.assertEqual([item.label for item in verdict.network_labels], ["business"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["proxy", "tor", "abuser"])
        self.assertEqual(verdict.risk_score, 100)

    def test_abstract_security_flags(self):
        verdict = ProfileAdapters.from_abstract({
            "security": {
                "is_vpn": True,
                "is_proxy": False,
                "is_tor": True,
                "is_hosting": False,
                "is_abuse": True,
            },
            "company": {"type": "isp"},
        })

        self.assertEqual([item.label for item in verdict.network_labels], ["likely_residential"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["vpn", "tor", "abuser"])

    def test_ip2location_basic_proxy_and_usage_type(self):
        verdict = ProfileAdapters.from_ip2location({
            "is_proxy": True,
            "usage_type": "DCH",
            "proxy": {"proxy_type": "VPN", "fraud_score": 88},
        })

        self.assertEqual([item.label for item in verdict.network_labels], ["datacenter"])
        self.assertEqual([item.label for item in verdict.risk_labels], ["proxy", "vpn"])
        self.assertEqual(verdict.risk_score, 88)

    def test_failed_api_returns_no_effective_labels(self):
        verdict = ProfileAdapters.from_ipwhois(None)

        self.assertEqual(verdict.network_labels, [])
        self.assertEqual(verdict.risk_labels, [])


class NodeProfileAggregatorTests(unittest.TestCase):
    def test_datacenter_vpn_compound_label(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipapi({
                "is_datacenter": True,
                "is_vpn": True,
                "company": {"type": "hosting"},
            }),
            ProfileAdapters.from_scamalytics({
                "scamalytics": {
                    "scamalytics_score": 74,
                    "scamalytics_risk": "medium",
                    "scamalytics_proxy": {
                        "is_datacenter": True,
                        "is_vpn": True,
                    },
                },
            }),
        ])

        self.assertIn("机房", profile.display_labels)
        self.assertIn("VPN", profile.display_labels)
        self.assertNotIn("Clean", profile.display_labels)
        self.assertEqual(profile.confidence, "high")

    def test_hosting_proxy_compound_label(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipwhois({
                "success": True,
                "security": {
                    "hosting": True,
                    "proxy": True,
                    "vpn": False,
                    "tor": False,
                },
            }),
        ])

        self.assertEqual(profile.display_labels, ["机房", "Proxy"])

    def test_clean_only_does_not_become_residential(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipwhois({
                "success": True,
                "security": {
                    "hosting": False,
                    "proxy": False,
                    "vpn": False,
                    "tor": False,
                },
            }),
        ])

        self.assertEqual(profile.display_labels, ["Clean"])
        self.assertEqual(profile.network_labels, [])

    def test_weak_residential_evidence_is_likely_residential(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipapi({
                "is_proxy": False,
                "is_vpn": False,
                "is_tor": False,
                "is_datacenter": False,
                "is_abuser": False,
                "company": {"type": "isp"},
            }),
        ])

        self.assertIn("家宽", profile.display_labels)

    def test_no_successful_evidence_is_unknown(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipwhois(None),
            ProfileAdapters.from_ipapi(None),
            ProfileAdapters.from_scamalytics(None),
        ])

        self.assertEqual(profile.display_labels, ["未知"])
        self.assertEqual(profile.confidence, "low")

    def test_proxycheck_clean_downweights_abstract_vpn_only(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_proxycheck({
                "status": "ok",
                "8.8.8.8": {
                    "detections": {
                        "proxy": False,
                        "vpn": False,
                        "tor": False,
                        "hosting": False,
                        "risk": 0,
                        "confidence": 100,
                    },
                },
            }, "8.8.8.8"),
            ProfileAdapters.from_abstract({
                "security": {
                    "is_vpn": True,
                    "is_proxy": False,
                    "is_tor": False,
                    "is_hosting": False,
                    "is_abuse": False,
                },
            }),
        ], source_weights={
            "proxycheck.io": 1.3,
            "Abstract API": 0.8,
        })

        self.assertNotIn("VPN", profile.display_labels)
        self.assertLess(profile.risk_score, 50)


class ProfileExportIntegrationTests(unittest.TestCase):
    def test_markdown_report_contains_profile(self):
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipwhois({
                "success": True,
                "security": {
                    "hosting": True,
                    "proxy": True,
                    "vpn": False,
                    "tor": False,
                },
            }),
        ])
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
            profile=profile,
        )
        tested = TestedNode(
            AnalyzedNode(node, probe, True, ""),
            123.45,
        )

        base_dir = Path("result/test_profile_report")
        ResultExporter.export_markdown_report([tested], base_dir=str(base_dir))
        report = Path(base_dir, "report.md").read_text(encoding="utf-8")
        detail = next(Path(base_dir, "node_details").glob("*.md")).read_text(encoding="utf-8")

        self.assertIn("Profile", report)
        self.assertIn("机房/Proxy", report)
        self.assertIn("### Node Profile", detail)
        self.assertIn("ipwho.is: hosting=true, proxy=true", detail)


if __name__ == "__main__":
    unittest.main()

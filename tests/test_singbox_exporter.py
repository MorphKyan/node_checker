import unittest
from models import LabelEvidence, TestedNode, VlessNode, AnalyzedNode, NodeProfile, ProbeData
from module_singbox_exporter import strip_comments, generate_singbox_config

def make_mock_tested_node(
    raw_uri: str,
    remark: str,
    score: float,
    ttfb: float,
    speed: float,
    valid: bool = True,
    actual_geo: str = "JP",
    security: str = "tls",
    sni: str = "example.com",
    transport_type: str = "tcp"
) -> TestedNode:
    node = VlessNode(
        raw_uri=raw_uri,
        uuid="uuid",
        server_ip="example.com",
        server_port=443,
        remark=remark,
        expected_geo=actual_geo,
        security=security,
        sni=sni,
        type=transport_type
    )
    profile = NodeProfile(
        network_labels=[LabelEvidence("datacenter", 1.0)],
        risk_labels=[LabelEvidence("clean", 1.0)],
    )
    probe = ProbeData(
        tcp_ping_ms=80.0,
        ttfb_ms=ttfb,
        actual_ip="203.0.113.10",
        actual_geo=actual_geo,
        asn_org="Example ASN",
        fraud_score=20,
        profile=profile,
    )
    return TestedNode(
        AnalyzedNode(node, probe, valid, score, "" if valid else "Timeout", "test score"),
        speed,
    )

class SingboxExporterTests(unittest.TestCase):
    def test_strip_comments(self):
        json_with_comments = """
        {
            // This is a comment
            "key": "value", /* Multi-line
            comment */
            "url": "https://github.com" // string with slashes is not a comment
        }
        """
        stripped = strip_comments(json_with_comments)
        import json
        parsed = json.loads(stripped)
        self.assertEqual(parsed["key"], "value")
        self.assertEqual(parsed["url"], "https://github.com")

    def test_generate_singbox_config(self):
        template_str = """{
            "experimental": {},
            "outbounds": [
                { "tag": "🚀 HK Outbounds", "type": "selector", "include": "(?i)HK" },
                { "tag": "♻️ US Outbounds", "type": "urltest", "include": "(?i)US", "exclude": "40分" },
                { "tag": "👉 All Outbounds", "type": "selector", "use_all_nodes": true }
            ]
        }"""
        
        node1 = make_mock_tested_node("vless://1@ex.com:443#hk", "HK 1", 90.0, 100.0, 15.0, actual_geo="HK")
        node2 = make_mock_tested_node("vless://2@ex.com:443#us", "US 1", 85.0, 150.0, 12.0, actual_geo="US")
        node3 = make_mock_tested_node("vless://3@ex.com:443#failed", "US failed", 40.0, 9999.0, 0.0, valid=False, actual_geo="US")
        
        config = generate_singbox_config(template_str, [node1, node2, node3], mode="compact")
        
        # Verify outbounds structure
        outbounds = config["outbounds"]
        self.assertEqual(len(outbounds), 6) # 3 from template + 3 raw node outbounds
        
        # HK selector should match only HK 1
        hk_selector = outbounds[0]
        self.assertEqual(hk_selector["tag"], "🚀 HK Outbounds")
        self.assertEqual(len(hk_selector["outbounds"]), 1)
        self.assertTrue(any("HK" in tag for tag in hk_selector["outbounds"]))
        self.assertNotIn("include", hk_selector)
        
        # US urltest should match US 1 but exclude US failed
        us_urltest = outbounds[1]
        self.assertEqual(us_urltest["tag"], "♻️ US Outbounds")
        self.assertEqual(len(us_urltest["outbounds"]), 1)
        self.assertNotIn("exclude", us_urltest)
        self.assertNotIn("include", us_urltest)
        
        # All selector should use all 3 nodes
        all_selector = outbounds[2]
        self.assertEqual(all_selector["tag"], "👉 All Outbounds")
        self.assertEqual(len(all_selector["outbounds"]), 3)
        self.assertNotIn("use_all_nodes", all_selector)
        
        # Verify parsed node outbound values
        raw_hk_node = outbounds[3]
        self.assertEqual(raw_hk_node["type"], "vless")
        self.assertEqual(raw_hk_node["server_port"], 443)
        self.assertEqual(raw_hk_node["tls"]["enabled"], True)

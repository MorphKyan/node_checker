import json
import unittest

from models import Hy2Node, VlessNode, AnalyzedNode, ProbeData, TestedNode
from module_parser import NodeParser
from module_tunnel import TunnelController
from module_subscription_exporter import SubscriptionExporter
from module_result_codec import tested_nodes_to_json, tested_nodes_from_json


class Hy2ParserTests(unittest.TestCase):
    def test_parse_hy2_basic(self):
        raw = "hy2://my_password@n109.edume.top:443?sni=u151782.example.com&insecure=1#US-Fremont_%23109"
        nodes = NodeParser.parse_nodes(raw)
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertIsInstance(node, Hy2Node)
        self.assertEqual(node.protocol, "hy2")
        self.assertEqual(node.password, "my_password")
        self.assertEqual(node.server_ip, "n109.edume.top")
        self.assertEqual(node.server_port, 443)
        self.assertEqual(node.sni, "u151782.example.com")
        self.assertTrue(node.insecure)
        self.assertEqual(node.remark, "US-Fremont_#109")
        self.assertEqual(node.expected_geo, "US")

    def test_parse_hysteria2_scheme_with_obfs(self):
        raw = "hysteria2://secret_pass@1.2.3.4:8443?sni=test.com&obfs=salamander&obfs-password=obfs_pass&up=100&down=500#JP_Osaka"
        nodes = NodeParser.parse_nodes(raw)
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertIsInstance(node, Hy2Node)
        self.assertEqual(node.password, "secret_pass")
        self.assertEqual(node.server_ip, "1.2.3.4")
        self.assertEqual(node.server_port, 8443)
        self.assertEqual(node.sni, "test.com")
        self.assertEqual(node.obfs, "salamander")
        self.assertEqual(node.obfs_password, "obfs_pass")
        self.assertEqual(node.up_mbps, 100)
        self.assertEqual(node.down_mbps, 500)
        self.assertEqual(node.expected_geo, "JP")

    def test_parse_mixed_subscription(self):
        content = (
            "vless://uuid1@server1.com:443?security=tls#HK_Node\n"
            "hy2://pass2@server2.com:443?sni=server2.com#US_Node\n"
        )
        nodes = NodeParser.parse_nodes(content)
        self.assertEqual(len(nodes), 2)
        self.assertIsInstance(nodes[0], VlessNode)
        self.assertIsInstance(nodes[1], Hy2Node)
        self.assertEqual(nodes[0].protocol, "vless")
        self.assertEqual(nodes[1].protocol, "hy2")

    def test_singbox_tunnel_config_generation(self):
        hy2_node = Hy2Node(
            raw_uri="hy2://pass@1.1.1.1:443?sni=example.com&obfs=salamander&obfs_password=obfs123",
            password="pass",
            server_ip="1.1.1.1",
            server_port=443,
            remark="Test_Node",
            expected_geo="US",
            sni="example.com",
            insecure=True,
            obfs="salamander",
            obfs_password="obfs123"
        )
        config_path = TunnelController.generate_singbox_config(hy2_node, 10808)
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            outbound = data["outbounds"][0]
            self.assertEqual(outbound["type"], "hysteria2")
            self.assertEqual(outbound["server"], "1.1.1.1")
            self.assertEqual(outbound["server_port"], 443)
            self.assertEqual(outbound["password"], "pass")
            self.assertEqual(outbound["tls"]["server_name"], "example.com")
            self.assertTrue(outbound["tls"]["insecure"])
            self.assertEqual(outbound["obfs"]["type"], "salamander")
            self.assertEqual(outbound["obfs"]["password"], "obfs123")
        finally:
            import os
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_xray_tunnel_config_generation(self):
        hy2_node = Hy2Node(
            raw_uri="hy2://pass@1.1.1.1:443?sni=example.com",
            password="pass",
            server_ip="1.1.1.1",
            server_port=443,
            remark="Test_Node",
            expected_geo="US",
            sni="example.com",
            insecure=False
        )
        config_path = TunnelController.generate_xray_config(hy2_node, 10808)
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            outbound = data["outbounds"][0]
            self.assertEqual(outbound["protocol"], "hysteria")
            self.assertEqual(outbound["settings"]["version"], 2)
            self.assertEqual(outbound["streamSettings"]["network"], "hysteria")
            self.assertEqual(outbound["streamSettings"]["hysteriaSettings"]["version"], 2)
            self.assertEqual(outbound["streamSettings"]["hysteriaSettings"]["auth"], "pass")
        finally:
            import os
            if os.path.exists(config_path):
                os.remove(config_path)

    def test_subscription_exporter_rewrite_hy2_remark(self):
        raw_uri = "hy2://pass@1.1.1.1:443?sni=example.com#Old_Remark"
        new_uri = SubscriptionExporter.rewrite_vless_remark(raw_uri, "New_Remark_With_Info")
        self.assertEqual(new_uri, "hy2://pass@1.1.1.1:443?sni=example.com#New_Remark_With_Info")

    def test_json_codec_hy2_node(self):
        hy2_node = Hy2Node(
            raw_uri="hy2://pass@1.1.1.1:443?sni=example.com#US",
            password="pass",
            server_ip="1.1.1.1",
            server_port=443,
            remark="US",
            expected_geo="US",
            sni="example.com"
        )
        probe = ProbeData(tcp_ping_ms=150.0, ttfb_ms=200.0, actual_ip="1.1.1.1", actual_geo="US", asn_org="Cloudflare")
        analyzed = AnalyzedNode(node=hy2_node, probe=probe, is_valid=True)
        tested = TestedNode(analyzed_node=analyzed)

        json_str = tested_nodes_to_json([tested])
        restored = tested_nodes_from_json(json_str)
        self.assertEqual(len(restored), 1)
        restored_node = restored[0].analyzed_node.node
        self.assertIsInstance(restored_node, Hy2Node)
        self.assertEqual(restored_node.password, "pass")
        self.assertEqual(restored_node.protocol, "hy2")

    def test_export_markdown_report_hy2_node(self):
        import tempfile
        import shutil
        from module_exporter import ResultExporter

        hy2_node = Hy2Node(
            raw_uri="hy2://pass@1.1.1.1:443?sni=example.com#US_Node",
            password="pass",
            server_ip="1.1.1.1",
            server_port=443,
            remark="US_Node",
            expected_geo="US",
            sni="example.com",
            insecure=True
        )
        probe = ProbeData(tcp_ping_ms=150.0, ttfb_ms=200.0, actual_ip="1.1.1.1", actual_geo="US", asn_org="Cloudflare")
        analyzed = AnalyzedNode(node=hy2_node, probe=probe, is_valid=True)
        tested = TestedNode(analyzed_node=analyzed)

        temp_dir = tempfile.mkdtemp(prefix="report_test_")
        try:
            ResultExporter.export_markdown_report([tested], base_dir=temp_dir)
            import os
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "report.md")))
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "node_details")))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

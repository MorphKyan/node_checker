import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from api_server import app
from module_api_store import ApiStore
from module_subscription_exporter import SubscriptionExporter
import unittest
from models import LabelEvidence, TestedNode, VlessNode, AnalyzedNode, NodeProfile, ProbeData
from module_api_presenter import build_detail_nodes, build_subscription
from settings import settings

def make_mock_tested_node(
    raw_uri: str,
    remark: str,
    risk: float,
    ttfb: float,
    speed: float,
    valid: bool = True,
    actual_geo: str = "JP",
    security: str = "tls",
    sni: str = "example.com",
    transport_type: str = "tcp",
    alpn: str = "",
    path: str = "",
    host: str = "",
    fp: str = "",
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
        alpn=alpn,
        fp=fp,
        type=transport_type,
        path=path,
        host=host,
    )
    profile = NodeProfile(
        network_labels=[LabelEvidence("datacenter", 1.0)],
        risk_labels=[LabelEvidence("clean", 1.0)],
        risk_score=risk,
    )
    probe = ProbeData(
        tcp_ping_ms=80.0,
        ttfb_ms=ttfb,
        actual_ip="203.0.113.10",
        actual_geo=actual_geo,
        asn_org="Example ASN",
        profile=profile,
    )
    return TestedNode(
        AnalyzedNode(node, probe, valid, "" if valid else "Timeout"),
        speed,
    )

class SubscriptionExporterTests(unittest.TestCase):
    def test_detail_names_match_base64_subscription(self):
        nodes = [
            make_mock_tested_node(f"vless://{index}@ex.com:443?type=tcp#old", "重复节点" * 20,
                                  risk, 100, 15, valid=valid)
            for index, risk, valid in [(1, 40, False), (2, 10, True), (3, 10, True)]
        ]
        details = build_detail_nodes(nodes)
        for mode, max_length in [("compact", settings.SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH),
                                 ("detailed", settings.SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH)]:
            with self.subTest(mode=mode):
                names = [detail[f"enhanced_name_{mode}"] for detail in details]
                self.assertEqual(len(set(names)), len(nodes))
                encoded = build_subscription(nodes, mode=mode, valid_only=False)
                self.assertNotIn("\n", encoded)
                plain = base64.b64decode(encoded, validate=True).decode("utf-8")
                self.assertEqual(plain.splitlines(), [detail[f"{mode}_uri"] for detail in details])
                self.assertEqual([uri.split("#")[0] for uri in plain.splitlines()],
                                 [detail["raw_uri"].split("#")[0] for detail in details])

    def test_cli_exports_only_single_line_base64_files(self):
        nodes = [make_mock_tested_node("vless://uuid@example.test:443?type=ws&path=%2Fsocket#旧名", "旧名", 10, 100, 15)]
        with tempfile.TemporaryDirectory() as directory:
            SubscriptionExporter.export_enhanced_subscriptions(nodes, directory)
            files = sorted(Path(directory).iterdir())
            self.assertEqual([p.name for p in files], ["enhanced_compact_base64.txt", "enhanced_detailed_base64.txt"])
            for p in files:
                encoded = p.read_text(encoding="utf-8")
                self.assertNotIn("\n", encoded)
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
                self.assertEqual(decoded.split("#")[0], nodes[0].analyzed_node.node.raw_uri.split("#")[0])
            self.assertEqual(SubscriptionExporter.encode_subscription([]), "")

    def test_retired_routes_and_format_options_are_removed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory), patch("api_server.FRONTEND_DIST_DIR", Path(directory)), TestClient(app) as client:
            Path(directory, "index.html").write_text("frontend")
            for url in ("/singbox/templates", "/singbox/templates/old", "/subscriptions/singbox"):
                self.assertEqual(client.get(url).status_code, 404)
            for path in ("/subscriptions/enhanced", "/subscriptions/{subscription_id}/enhanced"):
                parameters = client.get("/openapi.json").json()["paths"][path]["get"]["parameters"]
                self.assertNotIn("format", [p["name"] for p in parameters])
            sub = ApiStore.create_subscription("https://subscription.test")
            ApiStore.save_results(sub["id"], [make_mock_tested_node("vless://uuid@example.test:443#旧名", "旧名", 10, 100, 15)])
            for path in (f"/subscriptions/{sub['id']}/enhanced", f"/subscriptions/enhanced?subscription_id={sub['id']}"):
                response = client.get(path + ("&" if "?" in path else "?") + "format=plain")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("\n", response.text)
                self.assertTrue(base64.b64decode(response.text, validate=True).decode().startswith("vless://"))

    def test_upgrade_removes_stored_templates_and_preserves_subscriptions(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory):
            path = Path(directory, "config.json")
            config = {"singbox_templates": [{"id": "old", "content": "{}"}], "subscriptions": [{"id": "keep"}], "runtime_settings": {"FILTER_CONCURRENCY": 12}}
            path.write_text(json.dumps(config))
            loaded = ApiStore.load_config()
            self.assertNotIn("singbox_templates", loaded)
            stored = json.loads(path.read_text())
            self.assertNotIn("singbox_templates", stored)
            self.assertEqual(stored["subscriptions"], config["subscriptions"])
            self.assertEqual(stored["runtime_settings"], config["runtime_settings"])

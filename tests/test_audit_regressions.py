import asyncio
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack, chdir
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import deploy
from api_server import app
from models import AnalyzedNode, Hy2Node, ProbeData, SsNode, TestedNode, VlessNode
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_exporter import ResultExporter
from module_node_identity import make_node_fingerprint
from module_probe import LightweightProbe
from module_profile import ProfileAdapters
from module_singbox_exporter import generate_singbox_config
from module_subscription_service import SubscriptionRefreshService
from module_tunnel import TunnelController
from settings import settings


def tested_node(**changes):
    node = VlessNode("vless://uuid@example.test:443#n", "example.test", 443, "n", "JP", uuid="uuid")
    return TestedNode(AnalyzedNode(replace(node, **changes), ProbeData(1, 100, "1.1.1.1", "JP", "ASN"), True))


class AuditRegressionTests(unittest.TestCase):
    def test_missing_or_malformed_risk_data_stays_unknown(self):
        cases = [
            ("ipwhois", {}),
            ("ipwhois", {"success": True, "ip": "1.1.1.1"}),
            ("ipwhois", {"success": True, "security": {"proxy": False}}),
            ("ipwhois", {"success": True, "security": "text"}),
            ("ipapi", {"error": "quota exceeded"}),
            ("ipapi", {"ip": "1.1.1.1", "company": "text"}),
            ("ipapi", {"is_datacenter": True}),
            ("scamalytics", {"ip": "1.1.1.1", "scamalytics_proxy": "text"}),
            ("proxycheck", {"status": "ok", "1.1.1.1": {"detections": {}}}),
            ("abstract", {"security": {}, "company": "text", "asn": []}),
            ("ip2location", {"ip": "1.1.1.1", "usage_type": "DCH"}),
        ]
        for provider, data in cases:
            with self.subTest(provider=provider, data=data):
                verdict = LightweightProbe._verdict_for_site({"id": provider, "provider": provider}, data, "success", "1.1.1.1")
                self.assertEqual(verdict.status, "no_data")
                self.assertEqual(verdict.risk_labels, [])
                self.assertIsNone(verdict.risk_score)
        verdict = ProfileAdapters.from_ipapi({"is_vpn": True, "company": "text"})
        self.assertEqual([label.label for label in verdict.risk_labels], ["vpn"])

    def test_connection_identity_and_core_invalidate_cache(self):
        node = tested_node().analyzed_node.node
        for changes in ({"alpn": "h3"}, {"mode": "packet-up"}):
            self.assertNotEqual(make_node_fingerprint(node), make_node_fingerprint(replace(node, **changes)))
        config = {"api_sites": [], "exit_ip_endpoint": "https://exit.test"}
        with patch.object(settings, "PROXY_CORE", "sing-box"):
            first = ProbeCache.config_signature(probe_config=config)
        with patch.object(settings, "PROXY_CORE", "xray"):
            self.assertNotEqual(first, ProbeCache.config_signature(probe_config=config))

    def test_fixed_export_route_prefers_working_duplicate_in_both_formats(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory):
            with TestClient(app) as client:
                ApiStore.create_singbox_template("test", '{"outbounds":[]}')
                ids = []
                for valid, risk in [(False, 0), (True, 60)]:
                    sub = ApiStore.create_subscription("https://subscription.test")
                    job = ApiStore.create_refresh_job(sub["id"], 0)
                    item = tested_node()
                    item.analyzed_node.is_valid = valid
                    item.analyzed_node.probe.profile.risk_score = risk
                    ApiStore.update_job(job["id"], status="running")
                    self.assertTrue(ApiStore.save_results_if_current(sub["id"], job["id"], sub["url"], [item]))
                    ids.append(sub["id"])
                for order in (ids, ids[::-1]):
                    params = [("subscription_id", id) for id in order]
                    exported = client.get("/subscriptions/singbox", params=params)
                    self.assertEqual(exported.status_code, 200, exported.text)
                    self.assertEqual(sum(out.get("type") == "vless" for out in exported.json()["outbounds"]), 1)
                    plain = client.get("/subscriptions/enhanced", params=params + [("format", "plain")])
                    self.assertEqual(plain.status_code, 200)
                    self.assertIn("vless://uuid@example.test:443#", plain.text)

    def test_report_filenames_handle_ipv6_and_same_domain_suffix(self):
        items = [tested_node(server_ip=host) for host in ("2001:db8::1", "one.example.com", "two.example.com")]
        items[0].analyzed_node.probe.profile.risk_score = 0
        items[1].analyzed_node.probe.profile.risk_score = 20
        with tempfile.TemporaryDirectory() as directory:
            ResultExporter.export_markdown_report(items, directory)
            details = list(Path(directory, "node_details").glob("*.md"))
            self.assertEqual(len(details), 3)
            self.assertTrue(all(":" not in file.name for file in details))
            report = Path(directory, "report.md").read_text(encoding="utf-8")
            self.assertIn("Unknown", report)
            self.assertLess(report.index("0.0"), report.index("20.0"))

    def test_empty_selector_has_a_real_direct_outbound(self):
        template = '{"outbounds":[{"type":"selector","tag":"proxy","use_all_nodes":true}]}'
        config = generate_singbox_config(template, [])
        self.assertEqual(config["outbounds"][0]["outbounds"], ["DIRECT"])
        self.assertIn({"type": "direct", "tag": "DIRECT"}, config["outbounds"])

    def test_probe_and_export_use_identical_protocol_settings(self):
        base = tested_node().analyzed_node.node
        nodes = [
            replace(base, security="tls", alpn="h3, http/1.1", type="ws", path="/socket", host="edge.test"),
            replace(base, security="reality", pbk="key", sid="id", fp="chrome", type="grpc"),
            Hy2Node("hy2://pass@example.test", "example.test", 443, "hy2", "JP", password="pass", obfs="salamander", obfs_password="obfs"),
            SsNode("ss://example.test", "example.test", 443, "ss", "JP", method="aes-128-gcm", password="pass"),
        ]
        for node in nodes:
            with self.subTest(protocol=node.protocol):
                item = tested_node()
                item.analyzed_node.node = node
                exported = generate_singbox_config('{"outbounds":[]}', [item])["outbounds"][0]
                path = Path(TunnelController.generate_singbox_config(node, 10001))
                try:
                    probed = json.loads(path.read_text(encoding="utf-8"))["outbounds"][0]
                finally:
                    path.unlink()
                exported.pop("tag")
                probed.pop("tag")
                self.assertEqual(probed, exported)

    def test_deployment_build_failure_preserves_running_service_and_reports_failure(self):
        ssh = MagicMock()
        commands = []
        def execute(command):
            commands.append(command)
            stdout, stderr = MagicMock(), MagicMock()
            stdout.read.return_value = b""
            stderr.read.return_value = b"build failed"
            stdout.channel.recv_exit_status.return_value = 1 if "compose build" in command else 0
            return None, stdout, stderr
        ssh.exec_command.side_effect = execute
        with patch.dict("sys.modules", {"paramiko": SimpleNamespace(SSHClient=lambda: ssh)}), \
             patch.dict("os.environ", {"DEPLOY_HOST": "server.test", "DEPLOY_USER": "deployer"}), \
             patch.object(deploy, "build_frontend"), patch.object(deploy, "create_archive"):
            with self.assertRaisesRegex(RuntimeError, "Deployment command failed"):
                deploy.deploy()
        self.assertFalse(any("compose up" in command or "compose down" in command or "docker rm" in command for command in commands))
        ssh.close.assert_called_once()

    def test_deployment_archive_excludes_private_data_and_keeps_dockerignore(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            for filename in ("data/config.json", "inputs/sub.txt", "result/report.md", ".env", ".git/config", "frontend/dist/index.html", ".dockerignore"):
                path = Path(filename)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            deploy.create_archive()
            with zipfile.ZipFile("node_checker.zip") as archive:
                self.assertEqual(set(archive.namelist()), {"frontend/dist/index.html", ".dockerignore"})


class AsyncAuditRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_exit_failure_and_bad_metadata_do_not_erase_ttfb(self):
        node = tested_node().analyzed_node.node
        site = {"id": "ipapi", "provider": "ipapi", "enabled": True}
        for exit_value, response, expected in [
            (("", None), ({}, "success"), ("", "Unknown", "")),
            (("1.1.1.1", {"country_code": "JP", "connection": {"org": "Exit ASN"}}), ({"error": "quota"}, "success"), ("1.1.1.1", "JP", "Exit ASN")),
            (("1.1.1.1", {"country_code": "JP"}), ({"company": "text", "country_code": []}, "success"), ("1.1.1.1", "JP", "")),
            (("1.1.1.1", {"country_code": "JP"}), ({"country_code": "US", "company": {"name": "Site ASN"}}, "success"), ("1.1.1.1", "JP", "Site ASN")),
        ]:
            with self.subTest(expected=expected), ExitStack() as stack:
                for name, value in [("tcp_ping", 1), ("test_ttfb", 100), ("detect_ipv6", (False, "")), ("_fetch_exit_ip", exit_value)]:
                    stack.enter_context(patch.object(LightweightProbe, name, new=AsyncMock(return_value=value)))
                fetch = stack.enter_context(patch.object(LightweightProbe, "_fetch_site", new=AsyncMock(return_value=response)))
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1", probe_config={"api_sites": [site], "exit_ip_endpoint": "https://exit.test"})
                self.assertEqual((probe.actual_ip, probe.actual_geo, probe.asn_org), expected)
                self.assertEqual(probe.ttfb_ms, 100)
                self.assertIsNone(probe.is_detour)
                self.assertIsNone(probe.is_backbone)
                if not exit_value[0]: fetch.assert_not_called()
        with patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=1)), \
             patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=100)), \
             patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))), \
             patch.object(LightweightProbe, "_ip_intelligence", new=AsyncMock(side_effect=ValueError("malformed"))):
            probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1", probe_config={})
            self.assertEqual(probe.ttfb_ms, 100)

    async def test_cancel_during_startup_stops_child_and_removes_config(self):
        started = asyncio.Event()
        process = MagicMock()
        process.wait = AsyncMock()
        async def spawn(*args, **kwargs):
            started.set()
            return process
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "config.json")
            path.write_text("secret", encoding="utf-8")
            with patch.object(TunnelController, "generate_config", return_value=str(path)), \
                 patch("module_tunnel.asyncio.create_subprocess_exec", side_effect=spawn), \
                 patch.object(settings, "TUNNEL_START_DELAY", 60):
                task = asyncio.create_task(TunnelController.start_tunnel(tested_node().analyzed_node.node, 10001))
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            process.terminate.assert_called_once()
            process.wait.assert_awaited_once()
            self.assertFalse(path.exists())

    async def test_concurrent_refreshes_share_filter_and_speed_limits(self):
        active = {"filter": 0, "speed": 0}
        peak = active.copy()
        async def work(phase):
            active[phase] += 1
            peak[phase] = max(peak[phase], active[phase])
            await asyncio.sleep(.01)
            active[phase] -= 1
        async def filter_node(node, sem, **kwargs):
            async with sem: await work("filter")
            return tested_node().analyzed_node
        async def speed_node(node):
            await work("speed")
            return TestedNode(node)
        with patch.object(settings, "FILTER_CONCURRENCY", 1), patch.object(settings, "SPEEDTEST_CONCURRENCY", 1), \
             patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=filter_node), \
             patch.object(SubscriptionRefreshService, "run_speed_test", side_effect=speed_node):
            results = await asyncio.gather(*(SubscriptionRefreshService.run_nodes([tested_node().analyzed_node.node] * 2, speedtest_limit=2, probe_config={"api_sites": [], "exit_ip_endpoint": "https://exit.test"}) for _ in range(3)))
        self.assertEqual(peak, {"filter": 1, "speed": 1})
        self.assertEqual([len(batch) for batch in results], [2, 2, 2])

import asyncio
import io
import json
import tempfile
import threading
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import TCPConnector, web
from fastapi.testclient import TestClient

from api_server import app, delete_subscription
from models import ApiVerdict, Hy2Node, LabelEvidence
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_node_identity import make_node_fingerprint
from module_probe import LightweightProbe
from module_setup import setup_singbox, setup_xray
from module_singbox_exporter import generate_singbox_config, strip_comments
from module_singbox_outbound import singbox_outbound
from module_subscription_exporter import SubscriptionExporter, get_visual_width
from module_subscription_service import SubscriptionRefreshService
from module_tunnel import TunnelController
from settings import settings
from test_audit_regressions import tested_node


class AuditFixTests(unittest.TestCase):
    def test_unsupported_transports_fail_instead_of_becoming_tcp(self):
        for transport in ("xhttp", "unknown"):
            item = tested_node(type=transport, path="/path", host="edge.test", mode="auto")
            with self.subTest(transport=transport):
                with self.assertRaisesRegex(ValueError, transport):
                    TunnelController.generate_singbox_config(item.analyzed_node.node, 1080)
                with self.assertRaisesRegex(ValueError, transport):
                    generate_singbox_config('{"outbounds":[]}', [item])

    def test_hy2_hopping_ports_are_preserved_and_change_identity(self):
        node = Hy2Node("hy2://pass@example.test", "example.test", 443, "node", "JP", password="pass", ports="2000-3000, 4000")
        outbound = singbox_outbound(node, "proxy")
        self.assertEqual(outbound["server_ports"], ["2000:3000", "4000:4000"])
        self.assertNotIn("server_port", outbound)
        self.assertNotEqual(make_node_fingerprint(node), make_node_fingerprint(replace(node, ports="5000-6000")))

    def test_xray_rejects_hy2_options_it_cannot_preserve(self):
        node = Hy2Node("hy2://pass@example.test", "example.test", 443, "node", "JP", password="pass")
        for options in ({"ports": "2000-3000"}, {"obfs": "salamander"}, {"obfs_password": "secret"}, {"up_mbps": 10}, {"down_mbps": 20}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "use sing-box"):
                TunnelController.generate_xray_config(replace(node, **options), 1080)

    def test_deduplication_checks_final_names_after_truncation(self):
        for names, width in [
            (["alpha", "alpha #2", "alpha", "alpha #3", "alpha"], 64),
            (["alpha", "alpha", "alpha #2"], 64),
            (["很长的节点名称" * 8] * 12, 16),
            (["a" * 25, "a" * 26, "a" * 25], 16),
        ]:
            with self.subTest(names=names):
                result = SubscriptionExporter.deduplicate_names(names, width)
                self.assertEqual(len(result), len(set(result)))
                self.assertTrue(all(get_visual_width(name) <= width for name in result))

    def test_comments_preserve_escaped_strings_and_token_boundaries(self):
        value = {"path": "C:\\cache\\", "url": "https://example.test", "quote": '\\" /* keep */ // keep'}
        content = "/* first\nsecond */\n" + json.dumps(value) + " // tail"
        self.assertEqual(json.loads(strip_comments(content)), value)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(strip_comments('{"value": 1/* comment */2}'))

    def test_null_updates_preserve_existing_values(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory), TestClient(app) as client:
            sub = ApiStore.create_subscription("https://subscription.test", "original")
            template = ApiStore.create_singbox_template("template", '{"outbounds":[]}')
            original_settings = client.get("/settings").json()
            for url, payload in [
                (f"/subscriptions/{sub['id']}", {"url": None, "name": None}),
                (f"/singbox/templates/{template['id']}", {"content": None, "name": None}),
                ("/settings", {"FILTER_CONCURRENCY": None, "CACHE_ENABLED": None}),
            ]:
                with self.subTest(url=url):
                    self.assertEqual(client.patch(url, json=payload).status_code, 422)
            response = client.patch(f"/subscriptions/{sub['id']}", json={"name": "renamed", "url": None})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["url"], sub["url"])
            site = ApiStore.get_api_sites()[0]
            self.assertEqual(client.patch(f"/api-sites/{site['id']}", json={"weight": None, "column_name": None}).status_code, 200)
            self.assertEqual(ApiStore.get_api_sites()[0], site)
            self.assertEqual(ApiStore.get_singbox_template(template["id"]), template)
            self.assertEqual(client.get("/settings").json(), original_settings)

    def test_singbox_export_reports_unsupported_transport_as_validation_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory), TestClient(app) as client:
            sub = ApiStore.create_subscription("https://subscription.test")
            ApiStore.create_singbox_template("template", '{"outbounds":[]}')
            job = ApiStore.create_refresh_job(sub["id"], 0)
            ApiStore.update_job(job["id"], status="running")
            self.assertTrue(ApiStore.save_results_if_current(sub["id"], job["id"], sub["url"], [tested_node(type="xhttp")]))
            response = client.get("/subscriptions/singbox", params={"subscription_id": sub["id"]})
            self.assertEqual(response.status_code, 422)
            self.assertIn("xhttp", response.json()["detail"])

    def test_core_downloads_use_timeouts_and_the_configured_destination(self):
        for name, setting, setup, asset_name in [
            ("sing-box", "SING_BOX_PATH", setup_singbox, "sing-box-windows-amd64.zip"),
            ("xray", "XRAY_PATH", setup_xray, "Xray-windows-64.zip"),
        ]:
            archive_data = io.BytesIO()
            with zipfile.ZipFile(archive_data, "w") as archive:
                archive.writestr(f"release/{name}.exe", b"executable")
            release = {"assets": [{"name": asset_name, "browser_download_url": "https://download.test/core.zip"}]}
            with tempfile.TemporaryDirectory() as directory, patch.object(settings, setting, str(Path(directory, "nested", f"{name}.exe"))), \
                 patch("module_setup.shutil.which", return_value=None), \
                 patch("module_setup.urllib.request.urlopen", side_effect=[io.BytesIO(json.dumps(release).encode()), io.BytesIO(archive_data.getvalue())]) as request:
                setup()
                self.assertEqual(Path(getattr(settings, setting)).read_bytes(), b"executable")
                self.assertEqual([call.kwargs["timeout"] for call in request.call_args_list], [30, 30])
                setup()
                self.assertEqual(request.call_count, 2)
                self.assertEqual(list(Path(directory).rglob("*.download")), [])

    def test_core_download_failure_leaves_no_partial_executable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "SING_BOX_PATH", str(Path(directory, "core.exe"))), \
             patch("module_setup.shutil.which", return_value=None), \
             patch("module_setup.urllib.request.urlopen", side_effect=TimeoutError("stalled")):
            with self.assertRaisesRegex(RuntimeError, "Failed to prepare sing-box"):
                setup_singbox()
            self.assertEqual(list(Path(directory).iterdir()), [])


class AsyncAuditFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_errors_do_not_discard_a_successful_probe(self):
        item = tested_node().analyzed_node
        config = {"api_sites": [], "exit_ip_endpoint": "https://exit.test"}
        for operation in ("get", "set"):
            with self.subTest(operation=operation), \
                 patch.object(ProbeCache, "get", new=AsyncMock(return_value=None, side_effect=PermissionError("read only") if operation == "get" else None)), \
                 patch.object(ProbeCache, "set", new=AsyncMock(side_effect=PermissionError("read only") if operation == "set" else None)), \
                 patch.object(TunnelController, "start_tunnel", new=AsyncMock(return_value=(None, None))), \
                 patch.object(TunnelController, "stop_tunnel", new=AsyncMock()) as stop, \
                 patch.object(LightweightProbe, "run_probe", new=AsyncMock(return_value=item.probe)):
                result = await SubscriptionRefreshService.process_node_filter(item.node, asyncio.Semaphore(1), probe_config=config)
                self.assertTrue(result.is_valid)
                self.assertEqual(result.probe.ttfb_ms, 100)
                stop.assert_awaited_once()

    async def test_runtime_changes_during_probe_do_not_write_a_cache_entry(self):
        item = tested_node().analyzed_node
        config = {"api_sites": [], "exit_ip_endpoint": "https://exit.test"}
        for attribute, before, after in [("PROXY_CORE", "sing-box", "xray"), ("TTFB_TARGET_URL", "https://old.test", "https://new.test")]:
            async def probe(*args, **kwargs):
                setattr(settings, attribute, after)
                return item.probe
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory() as directory, \
                 patch.object(settings, "DATA_DIR", directory), patch.object(settings, attribute, before), \
                 patch.object(settings, "CACHE_ENABLED", True), \
                 patch.object(TunnelController, "start_tunnel", new=AsyncMock(return_value=(None, None))), \
                 patch.object(TunnelController, "stop_tunnel", new=AsyncMock()), \
                 patch.object(LightweightProbe, "run_probe", side_effect=probe):
                result = await SubscriptionRefreshService.process_node_filter(item.node, asyncio.Semaphore(1), probe_config=config)
                self.assertTrue(result.is_valid)
                self.assertIsNone(await ProbeCache.get(item.node, probe_config=config))
                self.assertEqual(list(Path(directory).rglob("*.json")), [])

    async def test_cache_signature_is_checked_after_waiting_for_writer(self):
        item = tested_node().analyzed_node
        config = {"api_sites": [], "exit_ip_endpoint": "https://exit.test"}
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory), \
             patch.object(settings, "PROXY_CORE", "sing-box"), patch.object(settings, "CACHE_ENABLED", True), \
             patch.object(ProbeCache, "_write_lock", asyncio.Lock()):
            signature = ProbeCache.config_signature(probe_config=config)
            async with ProbeCache._write_lock:
                task = asyncio.create_task(ProbeCache.set(item.node, item.probe, probe_config=config, expected_signature=signature))
                await asyncio.sleep(0)
                settings.PROXY_CORE = "xray"
            await task
            self.assertEqual(list(Path(directory).rglob("*.json")), [])

    async def test_sites_with_the_same_display_name_keep_their_weights(self):
        sites = [{"id": id, "column_name": "Same", "provider": "ipapi", "enabled": True, "weight": weight} for id, weight in [("one", 1), ("two", 9)]]
        verdicts = [ApiVerdict("Same", site_id=id, risk_score=score, risk_labels=[LabelEvidence("clean", 1)]) for id, score in [("one", 0), ("two", 100)]]
        with patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("1.1.1.1", {}))), \
             patch.object(LightweightProbe, "_fetch_site", new=AsyncMock(return_value=({}, "success"))), \
             patch.object(LightweightProbe, "_verdict_for_site", side_effect=verdicts):
            *_, profile = await LightweightProbe._ip_intelligence("socks5://unused", {"api_sites": sites, "exit_ip_endpoint": "https://exit.test"})
        self.assertEqual(profile.risk_score, 90)

    async def test_ttfb_finishes_after_first_byte_while_body_is_open(self):
        release_body = asyncio.Event()
        async def handler(request):
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(b"first byte")
            await release_body.wait()
            return response
        server = web.Application()
        server.router.add_get("/", handler)
        runner = web.AppRunner(server)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with patch("module_probe.ProxyConnector.from_url", side_effect=lambda *args, **kwargs: TCPConnector()), patch.object(settings, "TTFB_TIMEOUT", .2):
                result = await LightweightProbe.test_ttfb("socks5://unused", f"http://127.0.0.1:{port}/", times=1)
            self.assertLess(result, 9999)
            self.assertFalse(release_body.is_set())
        finally:
            release_body.set()
            await runner.cleanup()

    async def test_refresh_prepares_only_selected_core_without_blocking_loop(self):
        loop = asyncio.get_running_loop()
        for core in ("sing-box", "xray"):
            started = asyncio.Event()
            release = threading.Event()
            def setup():
                loop.call_soon_threadsafe(started.set)
                if not release.wait(2):
                    raise AssertionError("event loop blocked during setup")
            with self.subTest(core=core), patch.object(settings, "PROXY_CORE", core), \
                 patch("module_subscription_service.setup_singbox", side_effect=setup if core == "sing-box" else AssertionError("wrong core")) as singbox, \
                 patch("module_subscription_service.setup_xray", side_effect=setup if core == "xray" else AssertionError("wrong core")) as xray, \
                 patch.object(ApiStore, "get_subscription", return_value=None):
                task = asyncio.create_task(SubscriptionRefreshService.run_subscription_refresh("missing", "job", speedtest_limit=0))
                try:
                    await asyncio.wait_for(started.wait(), .5)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                    with self.assertRaisesRegex(ValueError, "Subscription not found"):
                        await task
                self.assertEqual((singbox.call_count, xray.call_count), (1, 0) if core == "sing-box" else (0, 1))

    async def test_deleting_subscription_cancels_running_scan(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "DATA_DIR", directory):
            ApiStore.init_db()
            sub = ApiStore.create_subscription("https://subscription.test")
            started, stopped = asyncio.Event(), asyncio.Event()
            async def scan(*args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            with patch.object(SubscriptionRefreshService, "run_subscription_refresh", side_effect=scan):
                job = SubscriptionRefreshService.schedule_refresh(sub["id"])
                task = SubscriptionRefreshService._running_tasks[job["id"]]
                try:
                    await started.wait()
                    ApiStore.update_subscription(sub["id"], url="https://changed.test")
                    self.assertEqual(ApiStore.get_job(job["id"])["status"], "failed")
                    self.assertTrue((await delete_subscription(sub["id"]))["deleted"])
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertTrue(stopped.is_set())
                self.assertIsNone(ApiStore.get_job(job["id"]))
                self.assertNotIn(job["id"], SubscriptionRefreshService._running_tasks)

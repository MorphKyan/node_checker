import asyncio
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api_server import app
from models import AnalyzedNode, ApiVerdict, NodeProfile, ProbeData, TestedNode, VlessNode
from module_api_store import ApiStore
from module_cache import ProbeCache
from module_analyzer import NodeAnalyzer
from module_profile import NodeProfileAggregator
from module_subscription_exporter import SubscriptionExporter
from module_subscription_service import SubscriptionRefreshService
from settings import settings


def node(risk=None, *, valid=True, name="n") -> TestedNode:
    raw = VlessNode(f"vless://uuid-{name}@example.com:443#{name}", f"uuid-{name}", "example.com", 443, name, "JP")
    profile = NodeProfile(risk_score=risk, evidence=[ApiVerdict(source="ipwho.is", site_id="ipwhois", status="success", risk_score=risk)] if risk is not None else [])
    probe = ProbeData(9999, 120, "203.0.113.1", "JP", "asn", profile=profile)
    return TestedNode(AnalyzedNode(raw, probe, valid, "" if valid else "TTFB timeout"), None, "not_tested")


class JsonRefactorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.DATA_DIR
        settings.DATA_DIR = self.temp.name

    def tearDown(self):
        settings.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def test_default_config_is_json_and_masks_keys(self):
        ApiStore.init_db()
        self.assertTrue((Path(settings.DATA_DIR) / "config.json").exists())
        site = ApiStore.create_api_site({"id": "custom", "column_name": "Custom", "provider": "ipwhois", "url_template": "https://example.test/{ip}?key={key}", "api_key": "secret", "weight": 1, "enabled": False})
        self.assertTrue(site["api_key_configured"])
        self.assertNotIn("api_key", site)
        self.assertIn("secret", (Path(settings.DATA_DIR) / "config.json").read_text(encoding="utf-8"))

    def test_site_crud_key_clear_and_snapshot(self):
        site = ApiStore.create_api_site({"id": "custom", "column_name": "Custom", "provider": "ipwhois", "url_template": "https://example.test/{ip}", "api_key": "secret", "weight": 2, "enabled": False})
        kept = ApiStore.update_api_site("custom", {"column_name": "New"})
        self.assertTrue(kept["api_key_configured"])
        cleared = ApiStore.update_api_site("custom", {"clear_api_key": True})
        self.assertFalse(cleared["api_key_configured"])
        sub = ApiStore.create_subscription("https://example.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0, api_sites_snapshot=ApiStore.get_api_sites(public=False))
        ApiStore.update_job(job["id"], status="running", phase="filter")
        self.assertTrue(ApiStore.save_results_if_current(sub["id"], job["id"], sub["url"], [node(12)]))
        result = ApiStore.get_latest_result(sub["id"])
        self.assertEqual(result["api_sites_snapshot"][0]["id"], "ipwhois")
        self.assertNotIn("api_key", result["api_sites_snapshot"][0])

    def test_enabled_key_template_cannot_be_cleared(self):
        ApiStore.create_api_site({"id": "keyed", "column_name": "Keyed", "provider": "ipwhois", "url_template": "https://example.test/{ip}?key={key}", "api_key": "secret", "weight": 1, "enabled": True})
        with self.assertRaisesRegex(ValueError, "API key"):
            ApiStore.update_api_site("keyed", {"clear_api_key": True})

    def test_corrupt_and_expired_cache_are_removed_and_signature_changes(self):
        async def run():
            item = node(10).analyzed_node
            first = [{"id": "one", "api_key": "a"}]
            second = [{"id": "one", "api_key": "b"}]
            self.assertNotEqual(ProbeCache.config_signature(first), ProbeCache.config_signature(second))
            await ProbeCache.set(item.node, item.probe, first)
            path = ProbeCache._path(item.node, ProbeCache.config_signature(first))
            path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(await ProbeCache.get(item.node, first))
            self.assertFalse(path.exists())
        asyncio.run(run())

    def test_unknown_risk_sorting_and_default_no_speedtest(self):
        ordered = SubscriptionExporter.sort_nodes([node(None), node(5), node(50)], valid_only=False)
        self.assertEqual([item.analyzed_node.probe.profile.risk_score for item in ordered], [5, 50, None])
        self.assertEqual(settings.API_DEFAULT_SPEEDTEST_LIMIT, 0)

    def test_api_site_endpoints(self):
        with TestClient(app) as client:
            listed = client.get("/api-sites")
            self.assertEqual(listed.status_code, 200)
            self.assertIn("sites", listed.json())
            response = client.post("/api-sites", json={"id": "custom", "column_name": "Custom", "provider": "ipwhois", "url_template": "https://example.test/{ip}", "weight": 1, "enabled": False})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["api_key_configured"])

    def test_subscription_url_update_invalidates_result_and_active_job(self):
        sub = ApiStore.create_subscription("https://one.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0)
        ApiStore.update_job(job["id"], status="running", phase="filter")
        self.assertTrue(ApiStore.save_results_if_current(sub["id"], job["id"], sub["url"], [node(4)]))
        ApiStore.update_subscription(sub["id"], url="https://two.test/sub")
        self.assertIsNone(ApiStore.get_latest_result(sub["id"]))

    def test_delete_subscription_removes_result_and_jobs(self):
        sub = ApiStore.create_subscription("https://delete.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0)
        self.assertTrue(ApiStore.delete_subscription(sub["id"]))
        self.assertIsNone(ApiStore.get_job(job["id"]))
        self.assertIsNone(ApiStore.get_latest_result(sub["id"]))

    def test_restart_marks_active_job_failed(self):
        sub = ApiStore.create_subscription("https://restart.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0)
        self.assertEqual(ApiStore.fail_stale_active_jobs("restart"), 1)
        self.assertEqual(ApiStore.get_job(job["id"])["status"], "failed")

    def test_order_requires_exact_site_set(self):
        with self.assertRaises(ValueError):
            ApiStore.order_api_sites(["ipwhois"])

    def test_disabled_key_template_may_be_saved_but_not_enabled_without_key(self):
        created = ApiStore.create_api_site({"id": "disabled-key", "column_name": "Disabled", "provider": "ipwhois", "url_template": "https://example.test/{ip}?key={key}", "weight": 1, "enabled": False})
        self.assertFalse(created["enabled"])
        with self.assertRaises(ValueError):
            ApiStore.update_api_site("disabled-key", {"enabled": True})

    def test_corrupt_config_recovers_to_defaults(self):
        ApiStore.init_db()
        config = Path(settings.DATA_DIR) / "config.json"
        config.write_text("{not json", encoding="utf-8")
        ApiStore.init_db()
        recovered = ApiStore.get_api_sites(public=False)
        self.assertEqual([site["id"] for site in recovered], ["ipwhois", "ipapi", "scamalytics", "proxycheck", "abstract", "ip2location"])

    def test_atomic_write_failure_preserves_previous_config(self):
        ApiStore.init_db()
        config = Path(settings.DATA_DIR) / "config.json"
        previous = config.read_text(encoding="utf-8")
        with patch("module_api_store.os.replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                ApiStore.update_exit_ip_endpoint("https://replacement.example.test")
        self.assertEqual(config.read_text(encoding="utf-8"), previous)
        self.assertFalse(list(Path(settings.DATA_DIR).glob("*.tmp")))

    def test_concurrent_config_job_and_result_writes_remain_readable(self):
        sub = ApiStore.create_subscription("https://concurrent.example.test/sub")
        job = ApiStore.create_refresh_job(sub["id"], 0)
        errors = []

        def work(action):
            try:
                for index in range(8):
                    action(index)
            except Exception as exc:  # pragma: no cover - assertion reports it
                errors.append(exc)

        threads = [
            threading.Thread(target=work, args=(lambda index: ApiStore.update_exit_ip_endpoint(f"https://exit{index}.example.test"),)),
            threading.Thread(target=work, args=(lambda index: ApiStore.update_job(job["id"], phase=f"phase-{index}", processed_nodes=index),)),
            threading.Thread(target=work, args=(lambda index: ApiStore.save_results(sub["id"], [node(index, name=f"result-{index}")]),)),
        ]
        for thread in threads: thread.start()
        for thread in threads: thread.join()

        self.assertEqual(errors, [])
        self.assertTrue(ApiStore.get_exit_ip_endpoint().startswith("https://exit"))
        self.assertEqual(ApiStore.get_job(job["id"])["processed_nodes"], 7)
        self.assertEqual(ApiStore.get_latest_result(sub["id"])["node_count"], 1)

    def test_api_routes_cover_create_update_clear_order_endpoint_and_delete(self):
        with TestClient(app) as client:
            self.assertIn("ipwhois", client.get("/api-sites/providers").json())
            created = client.post("/api-sites", json={"id": "route-site", "column_name": "Route Site", "provider": "ipwhois", "url_template": "https://route.example.test/{ip}?key={key}", "api_key": "secret", "weight": 2, "enabled": True})
            self.assertEqual(created.status_code, 200)
            self.assertTrue(created.json()["api_key_configured"])
            renamed = client.patch("/api-sites/route-site", json={"column_name": "Renamed", "enabled": False})
            self.assertEqual(renamed.status_code, 200)
            self.assertTrue(renamed.json()["api_key_configured"])
            cleared = client.patch("/api-sites/route-site", json={"clear_api_key": True})
            self.assertEqual(cleared.status_code, 200)
            self.assertFalse(cleared.json()["api_key_configured"])
            ids = [site["id"] for site in client.get("/api-sites").json()["sites"]]
            ordered = client.put("/api-sites/order", json={"ids": ["route-site", *[site_id for site_id in ids if site_id != "route-site"]]})
            self.assertEqual(ordered.status_code, 200)
            self.assertEqual(ordered.json()[0]["id"], "route-site")
            endpoint = client.patch("/exit-ip-endpoint", json={"exit_ip_endpoint": "https://exit.example.test"})
            self.assertEqual(endpoint.json()["exit_ip_endpoint"], "https://exit.example.test")
            self.assertEqual(client.delete("/api-sites/route-site").status_code, 200)

    def test_config_changes_produce_cache_miss_for_all_probe_inputs(self):
        async def run():
            item = node(10).analyzed_node
            sites = ApiStore.get_api_sites(public=False)
            await ProbeCache.set(item.node, item.probe, sites)
            self.assertIsNotNone(await ProbeCache.get(item.node, sites))
            changed = deepcopy(sites)
            changed[0].update(url_template="https://changed.example.test/{ip}", api_key="different", weight=2, enabled=False, order=99)
            self.assertNotEqual(ProbeCache.config_signature(sites), ProbeCache.config_signature(changed))
            ApiStore.update_api_site(changed[0]["id"], changed[0])
            self.assertIsNone(await ProbeCache.get(item.node))

            before = ProbeCache.config_signature()
            ApiStore.update_exit_ip_endpoint("https://different-exit.example.test")
            self.assertNotEqual(before, ProbeCache.config_signature())
            original = (settings.TTFB_TARGET_URL, settings.PROBE_TEST_TIMES, settings.TTFB_TIMEOUT, settings.API_TIMEOUT)
            try:
                for attr, value in (("TTFB_TARGET_URL", "https://changed-target.example.test"), ("PROBE_TEST_TIMES", original[1] + 1), ("TTFB_TIMEOUT", original[2] + 1), ("API_TIMEOUT", original[3] + 1)):
                    baseline = ProbeCache.config_signature()
                    setattr(settings, attr, value)
                    self.assertNotEqual(baseline, ProbeCache.config_signature(), attr)
            finally:
                settings.TTFB_TARGET_URL, settings.PROBE_TEST_TIMES, settings.TTFB_TIMEOUT, settings.API_TIMEOUT = original
        asyncio.run(run())

    def test_direct_filter_freezes_probe_config_before_cache_and_probe(self):
        original = ApiStore.get_probe_config_snapshot()
        probe = node(8).analyzed_node.probe

        async def mutate_after_cache(_node, *args, probe_config=None, **kwargs):
            ApiStore.update_api_site("ipwhois", {"weight": 2})
            ApiStore.update_exit_ip_endpoint("https://changed-during-filter.example.test")
            self.assertEqual(probe_config, original)
            return None

        async def run():
            with patch("module_subscription_service.ProbeCache.get", side_effect=mutate_after_cache), \
                 patch("module_subscription_service.ProbeCache.set", new=AsyncMock()) as cache_set, \
                 patch("module_subscription_service.LightweightProbe.run_probe", new=AsyncMock(return_value=probe)) as run_probe, \
                patch("module_subscription_service.TunnelController.start_tunnel", new=AsyncMock(return_value=(None, None))), \
                patch("module_subscription_service.TunnelController.stop_tunnel", new=AsyncMock()):
                await SubscriptionRefreshService.process_node_filter(node(8).analyzed_node.node, asyncio.Semaphore(1))
                self.assertEqual(run_probe.await_args.kwargs["probe_config"], original)
                self.assertEqual(cache_set.await_args.kwargs["probe_config"], original)
        asyncio.run(run())

    def test_batch_endpoint_snapshot_is_stable_during_nodes_and_changes_for_next_job_cache(self):
        async def run():
            ApiStore.update_exit_ip_endpoint("https://old-exit.example.test")
            sub = ApiStore.create_subscription("https://snapshot.example.test/sub")
            current_job = ApiStore.create_refresh_job(sub["id"], 0)
            old_config = current_job["probe_config_snapshot"]
            self.assertEqual(old_config["exit_ip_endpoint"], "https://old-exit.example.test")
            observed = []
            changed = asyncio.Event()

            async def fake_filter(raw_node, _sem, *, probe_config, **_kwargs):
                observed.append(probe_config["exit_ip_endpoint"])
                if raw_node.remark == "first":
                    ApiStore.update_exit_ip_endpoint("https://new-exit.example.test")
                    changed.set()
                else:
                    await changed.wait()
                return node(5, name=raw_node.remark).analyzed_node

            with patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=fake_filter):
                await SubscriptionRefreshService.run_nodes(
                    [node(1, name="first").analyzed_node.node, node(2, name="second").analyzed_node.node],
                    speedtest_limit=0,
                    probe_config=old_config,
                )
            self.assertEqual(observed, ["https://old-exit.example.test", "https://old-exit.example.test"])
            self.assertNotEqual(
                ProbeCache.config_signature(probe_config=old_config),
                ProbeCache.config_signature(probe_config=ApiStore.get_probe_config_snapshot()),
            )

            cache_node = node(5, name="cached").analyzed_node
            await ProbeCache.set(cache_node.node, cache_node.probe, probe_config=old_config)
            self.assertIsNotNone(await ProbeCache.get(cache_node.node, probe_config=old_config))
            self.assertIsNone(await ProbeCache.get(cache_node.node, probe_config=ApiStore.get_probe_config_snapshot()))
            next_job = ApiStore.create_refresh_job(sub["id"], 0)
            self.assertEqual(next_job["exit_ip_endpoint_snapshot"], "https://new-exit.example.test")
            self.assertEqual(next_job["probe_config_snapshot"]["exit_ip_endpoint"], "https://new-exit.example.test")
        asyncio.run(run())

    def test_subscription_routes_stale_task_linkage_and_delete(self):
        sub = ApiStore.create_subscription("https://stale.example.test/sub", "Stale")
        active = ApiStore.create_refresh_job(sub["id"], 0)
        ApiStore.update_job(active["id"], status="running", phase="filter")
        self.assertFalse(ApiStore.save_results_if_current(sub["id"], active["id"], "https://other.example.test/sub", [node(1)]))
        with TestClient(app) as client:
            updated = client.patch(f"/subscriptions/{sub['id']}", json={"url": "https://updated.example.test/sub", "name": "Updated"})
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["name"], "Updated")
            self.assertEqual(ApiStore.get_job(active["id"])["status"], "failed")
            self.assertEqual(client.delete(f"/subscriptions/{sub['id']}").json()["deleted"], True)
        self.assertIsNone(ApiStore.get_job(active["id"]))

    def test_enhanced_export_respects_max_risk_and_valid_only(self):
        sub = ApiStore.create_subscription("https://filters.example.test/sub")
        ApiStore.save_results(sub["id"], [node(10, name="low"), node(90, name="high"), node(15, valid=False, name="invalid")])
        with TestClient(app) as client:
            only_low = client.get(f"/subscriptions/{sub['id']}/enhanced?format=plain&max_risk=20")
            self.assertEqual(only_low.status_code, 200)
            self.assertEqual(len(only_low.text.splitlines()), 1)
            include_invalid = client.get(f"/subscriptions/{sub['id']}/enhanced?format=plain&max_risk=20&valid_only=false")
            self.assertEqual(len(include_invalid.text.splitlines()), 2)

    def test_ttfb_alone_controls_validity_and_all_failed_apis_have_null_risk(self):
        raw = node().analyzed_node.node
        timeout = NodeAnalyzer.analyze(raw, ProbeData(1, 9999, "", "Unknown", "", profile=NodeProfile(risk_score=0)))
        api_failures = NodeProfileAggregator.aggregate([ApiVerdict("one", status="error"), ApiVerdict("two", status="timeout")], {"one": 1, "two": 1})
        success = NodeAnalyzer.analyze(raw, ProbeData(9999, 120, "", "Unknown", "", profile=api_failures))
        self.assertFalse(timeout.is_valid)
        self.assertTrue(success.is_valid)
        self.assertIsNone(api_failures.risk_score)

    def test_default_and_manual_speedtest_limits_are_stored_and_selected(self):
        sub = ApiStore.create_subscription("https://speed.example.test/sub")
        default_job = ApiStore.create_refresh_job(sub["id"], settings.API_DEFAULT_SPEEDTEST_LIMIT)
        manual_job = ApiStore.create_refresh_job(sub["id"], 2, force_probe=True)
        self.assertEqual(default_job["speedtest_limit"], 0)
        self.assertEqual(manual_job["speedtest_limit"], 2)
        selected, skipped = SubscriptionRefreshService.select_speedtest_nodes_per_region([node(1).analyzed_node, node(2, name="other").analyzed_node], 1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(skipped), 1)

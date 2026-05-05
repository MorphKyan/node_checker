import base64
import asyncio
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api_server import app
from models import AnalyzedNode, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode
from module_api_store import ApiStore
from module_subscription_service import SubscriptionRefreshService
from settings import settings


def make_tested_node(valid: bool = True) -> TestedNode:
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
        is_backbone=True,
        backbone_info="CN2",
        profile=NodeProfile(
            network_labels=[LabelEvidence("datacenter", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
            risk_score=35.0,
            confidence="high",
        ),
    )
    analyzed = AnalyzedNode(
        node=node,
        probe=probe,
        is_valid=valid,
        total_score=92.0 if valid else 0.0,
        reject_reason="" if valid else "Timeout",
        score_details="test score",
    )
    return TestedNode(analyzed, 12.34 if valid else 0.0)


async def noop_run_job(job_id: str) -> None:
    return None


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_api_db_path = settings.API_DB_PATH
        self.original_cache_db_path = settings.CACHE_DB_PATH
        self.original_cache_enabled = settings.CACHE_ENABLED
        self.original_runtime_settings_path = settings.RUNTIME_SETTINGS_PATH
        self.original_filter_concurrency = settings.FILTER_CONCURRENCY
        self.original_speedtest_concurrency = settings.SPEEDTEST_CONCURRENCY
        self.original_speedtest_limit = settings.API_DEFAULT_SPEEDTEST_LIMIT
        self.original_subscription_max_bytes = settings.SUBSCRIPTION_MAX_BYTES
        self.original_speedtest_max_bytes = settings.SPEEDTEST_MAX_BYTES
        settings.API_DB_PATH = str(Path(self.tmpdir.name, "api.sqlite3"))
        settings.CACHE_DB_PATH = str(Path(self.tmpdir.name, "probe_cache.sqlite3"))
        settings.RUNTIME_SETTINGS_PATH = str(Path(self.tmpdir.name, "runtime_settings.json"))
        settings.CACHE_ENABLED = True
        ApiStore._initialized_paths.clear()
        self.run_job_patch = patch(
            "module_subscription_service.SubscriptionRefreshService.run_job",
            side_effect=noop_run_job,
        )
        self.run_job_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.run_job_patch.stop()
        settings.API_DB_PATH = self.original_api_db_path
        settings.CACHE_DB_PATH = self.original_cache_db_path
        settings.CACHE_ENABLED = self.original_cache_enabled
        settings.RUNTIME_SETTINGS_PATH = self.original_runtime_settings_path
        settings.FILTER_CONCURRENCY = self.original_filter_concurrency
        settings.SPEEDTEST_CONCURRENCY = self.original_speedtest_concurrency
        settings.API_DEFAULT_SPEEDTEST_LIMIT = self.original_speedtest_limit
        settings.SUBSCRIPTION_MAX_BYTES = self.original_subscription_max_bytes
        settings.SPEEDTEST_MAX_BYTES = self.original_speedtest_max_bytes
        ApiStore._initialized_paths.clear()
        self.tmpdir.cleanup()

    def create_subscription_without_refresh(self) -> dict:
        return ApiStore.create_subscription("https://example.com/sub", "my-sub")

    def save_result(self, subscription_id: str, nodes: list[TestedNode] | None = None) -> None:
        ApiStore.save_results(subscription_id, nodes or [make_tested_node()])

    def test_create_subscription_starts_refresh_job(self):
        response = self.client.post(
            "/subscriptions",
            json={"url": "https://example.com/sub", "name": "my-sub"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["subscription_id"].startswith("sub_"))
        self.assertTrue(payload["job_id"].startswith("job_"))
        self.assertEqual(payload["status"], "queued")
        self.assertIsNotNone(ApiStore.get_subscription(payload["subscription_id"]))

    def test_list_subscriptions_returns_summary(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        response = self.client.get("/subscriptions")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], subscription["id"])
        self.assertEqual(payload[0]["node_count"], 1)
        self.assertEqual(payload[0]["valid_count"], 1)
        self.assertIn("last_job_id", payload[0])

    def test_get_update_and_delete_subscription(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        get_response = self.client.get(f"/subscriptions/{subscription['id']}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["node_count"], 1)

        patch_response = self.client.patch(
            f"/subscriptions/{subscription['id']}",
            json={"name": "renamed", "url": "https://example.com/next"},
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["name"], "renamed")
        self.assertEqual(patch_response.json()["url"], "https://example.com/next")
        self.assertEqual(patch_response.json()["node_count"], 0)
        self.assertEqual(self.client.get(f"/subscriptions/{subscription['id']}/results").status_code, 409)

        delete_response = self.client.delete(f"/subscriptions/{subscription['id']}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["deleted"], True)
        self.assertEqual(self.client.get(f"/subscriptions/{subscription['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/subscriptions/{subscription['id']}/results").status_code, 404)

    def test_update_subscription_name_keeps_existing_results(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        patch_response = self.client.patch(
            f"/subscriptions/{subscription['id']}",
            json={"name": "renamed"},
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["name"], "renamed")
        self.assertEqual(patch_response.json()["node_count"], 1)
        self.assertEqual(self.client.get(f"/subscriptions/{subscription['id']}/results").status_code, 200)

    def test_update_subscription_url_fails_active_jobs(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])
        active_job = ApiStore.create_refresh_job(subscription["id"], 3, False)

        updated = ApiStore.update_subscription(subscription["id"], url="https://example.com/next")

        self.assertEqual(updated["last_status"], "new")
        self.assertIsNone(updated["last_job_id"])
        self.assertIsNone(ApiStore.get_latest_result(subscription["id"]))
        self.assertIsNone(ApiStore.find_active_job(subscription["id"]))
        failed_job = ApiStore.get_job(active_job["id"])
        self.assertEqual(failed_job["status"], "failed")
        self.assertEqual(failed_job["phase"], "failed")
        self.assertIn("Subscription URL changed", failed_job["error"])

    def test_stale_active_jobs_are_marked_failed(self):
        subscription = self.create_subscription_without_refresh()
        active_job = ApiStore.create_refresh_job(subscription["id"], 3, False)

        count = ApiStore.fail_stale_active_jobs("test restart")

        self.assertEqual(count, 1)
        self.assertEqual(ApiStore.get_job(active_job["id"])["status"], "failed")
        self.assertEqual(ApiStore.get_job(active_job["id"])["error"], "test restart")
        self.assertEqual(ApiStore.get_subscription(subscription["id"])["last_status"], "failed")

    def test_old_job_status_update_does_not_overwrite_current_job(self):
        subscription = self.create_subscription_without_refresh()
        old_job = ApiStore.create_refresh_job(subscription["id"], 3, False)
        ApiStore.update_subscription(subscription["id"], url="https://example.com/next")
        new_job = ApiStore.create_refresh_job(subscription["id"], 3, False)

        ApiStore.update_job(
            old_job["id"],
            status="failed",
            phase="failed",
            error="late old job failure",
            finished_at=ApiStore.now(),
        )

        subscription_after_update = ApiStore.get_subscription(subscription["id"])
        self.assertEqual(subscription_after_update["last_job_id"], new_job["id"])
        self.assertEqual(subscription_after_update["last_status"], "queued")

    def test_refresh_supports_speedtest_limit_and_force_probe(self):
        subscription = self.create_subscription_without_refresh()

        response = self.client.post(
            f"/subscriptions/{subscription['id']}/refresh",
            json={"speedtest_limit": 0, "force_probe": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        job = ApiStore.get_job(payload["job_id"])
        self.assertEqual(job["speedtest_limit"], 0)
        self.assertEqual(job["force_probe"], 1)

    def test_schedule_refresh_marks_job_failed_when_no_event_loop_is_running(self):
        subscription = self.create_subscription_without_refresh()

        job = SubscriptionRefreshService.schedule_refresh(subscription["id"])

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["phase"], "failed")
        self.assertIn("Unable to schedule refresh task", job["error"])
        self.assertEqual(
            ApiStore.get_subscription(subscription["id"])["last_status"],
            "failed",
        )

    def test_refresh_discards_results_when_subscription_url_changes_during_run(self):
        async def run_case():
            subscription = self.create_subscription_without_refresh()
            job = ApiStore.create_refresh_job(subscription["id"], 3, False)

            async def run_nodes(*args, **kwargs):
                ApiStore.update_subscription(subscription["id"], url="https://example.com/next")
                return [make_tested_node()]

            with (
                patch("module_subscription_service.setup_singbox"),
                patch("module_subscription_service.ProbeCache.init_db", new=AsyncMock()),
                patch.object(
                    SubscriptionRefreshService,
                    "fetch_subscription_text",
                    new=AsyncMock(return_value="vless://uuid@example.com:443?security=tls#JP"),
                ),
                patch.object(SubscriptionRefreshService, "run_nodes", side_effect=run_nodes),
            ):
                with self.assertRaisesRegex(ValueError, "no longer current"):
                    await SubscriptionRefreshService.run_subscription_refresh(
                        subscription["id"],
                        job["id"],
                        speedtest_limit=3,
                    )

            self.assertIsNone(ApiStore.get_latest_result(subscription["id"]))
            self.assertEqual(ApiStore.get_job(job["id"])["status"], "failed")

        asyncio.run(run_case())

    def test_get_job_returns_status(self):
        subscription = self.create_subscription_without_refresh()
        job = ApiStore.create_refresh_job(subscription["id"], 3, False)

        response = self.client.get(f"/jobs/{job['id']}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_id"], job["id"])
        self.assertEqual(payload["status"], "queued")

    def test_enhanced_defaults_to_base64_subscription(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        response = self.client.get(f"/subscriptions/{subscription['id']}/enhanced")

        self.assertEqual(response.status_code, 200)
        decoded = base64.b64decode(response.text).decode("utf-8")
        self.assertIn("vless://", decoded)
        self.assertIn("JP", decoded)

    def test_enhanced_supports_plain_detailed(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        response = self.client.get(
            f"/subscriptions/{subscription['id']}/enhanced?format=plain&mode=detailed"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("vless://", response.text)
        self.assertIn("Example%20ASN", response.text)

    def test_results_return_latest_node_details(self):
        subscription = self.create_subscription_without_refresh()
        self.save_result(subscription["id"])

        response = self.client.get(f"/subscriptions/{subscription['id']}/results")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subscription_id"], subscription["id"])
        self.assertEqual(payload["subscription_status"], "new")
        self.assertIsNone(payload["last_job_id"])
        self.assertEqual(payload["node_count"], 1)
        node = payload["nodes"][0]
        self.assertEqual(node["probe"]["network_labels"], ["机房"])
        self.assertEqual(node["probe"]["type_labels"], ["Clean"])
        self.assertEqual(node["probe"]["confidence"], "high")
        self.assertIn("机房", node["enhanced_name_compact"])

    def test_missing_result_returns_409(self):
        subscription = self.create_subscription_without_refresh()

        enhanced = self.client.get(f"/subscriptions/{subscription['id']}/enhanced")
        results = self.client.get(f"/subscriptions/{subscription['id']}/results")

        self.assertEqual(enhanced.status_code, 409)
        self.assertEqual(results.status_code, 409)

    def test_missing_resources_return_404(self):
        self.assertEqual(self.client.get("/subscriptions/sub_missing/results").status_code, 404)
        self.assertEqual(self.client.get("/jobs/job_missing").status_code, 404)

    def test_settings_can_be_read_and_updated(self):
        get_response = self.client.get("/settings")
        self.assertEqual(get_response.status_code, 200)
        self.assertIn("FILTER_CONCURRENCY", get_response.json())

        patch_response = self.client.patch(
            "/settings",
            json={
                "FILTER_CONCURRENCY": 7,
                "SPEEDTEST_CONCURRENCY": 3,
                "API_DEFAULT_SPEEDTEST_LIMIT": 0,
                "SUBSCRIPTION_MAX_BYTES": 4096,
                "SPEEDTEST_MAX_BYTES": 2 * 1024 * 1024,
            },
        )
        self.assertEqual(patch_response.status_code, 200)
        payload = patch_response.json()
        self.assertEqual(payload["FILTER_CONCURRENCY"], 7)
        self.assertEqual(payload["SPEEDTEST_CONCURRENCY"], 3)
        self.assertEqual(payload["API_DEFAULT_SPEEDTEST_LIMIT"], 0)
        self.assertEqual(payload["SUBSCRIPTION_MAX_BYTES"], 4096)
        self.assertEqual(payload["SPEEDTEST_MAX_BYTES"], 2 * 1024 * 1024)
        self.assertEqual(settings.FILTER_CONCURRENCY, 7)
        self.assertEqual(settings.SPEEDTEST_CONCURRENCY, 3)
        self.assertEqual(settings.SUBSCRIPTION_MAX_BYTES, 4096)
        self.assertEqual(settings.SPEEDTEST_MAX_BYTES, 2 * 1024 * 1024)

        runtime_file = Path(settings.RUNTIME_SETTINGS_PATH)
        self.assertTrue(runtime_file.exists())

    def test_invalid_setting_value_returns_422(self):
        response = self.client.patch("/settings", json={"FILTER_CONCURRENCY": 0})
        self.assertEqual(response.status_code, 422)

    def test_refresh_rejects_excessive_speedtest_limit(self):
        subscription = self.create_subscription_without_refresh()

        response = self.client.post(
            f"/subscriptions/{subscription['id']}/refresh",
            json={"speedtest_limit": 101},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(ApiStore.find_active_job(subscription["id"]))

    def test_static_frontend_fallback_returns_index_when_dist_exists(self):
        dist = Path("frontend", "dist")
        index = dist / "index.html"
        original_text = index.read_text(encoding="utf-8") if index.exists() else None
        try:
            dist.mkdir(parents=True, exist_ok=True)
            index.write_text("<html><body>frontend-shell</body></html>", encoding="utf-8")
            response = self.client.get("/")
            nested = self.client.get("/nodes/sub_123")
            self.assertEqual(response.status_code, 200)
            self.assertIn("frontend-shell", response.text)
            self.assertEqual(nested.status_code, 200)
            self.assertIn("frontend-shell", nested.text)
        finally:
            if original_text is None:
                if index.exists():
                    index.unlink()
            else:
                index.write_text(original_text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

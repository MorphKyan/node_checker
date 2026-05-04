import base64
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api_server import app
from models import AnalyzedNode, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode
from module_api_store import ApiStore
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
        settings.API_DB_PATH = str(Path(self.tmpdir.name, "api.sqlite3"))
        settings.CACHE_DB_PATH = str(Path(self.tmpdir.name, "probe_cache.sqlite3"))
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


if __name__ == "__main__":
    unittest.main()

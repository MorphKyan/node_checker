import asyncio
import unittest
from unittest.mock import patch

from models import AnalyzedNode, ProbeData, TestedNode, VlessNode
from module_subscription_service import SubscriptionRefreshService
from settings import settings


def make_node(index: int) -> VlessNode:
    return VlessNode(
        raw_uri=f"vless://uuid-{index}@example.com:443?security=tls#JP-{index}",
        uuid=f"uuid-{index}",
        server_ip="example.com",
        server_port=443,
        remark=f"JP-{index}",
        expected_geo="JP",
    )


def make_analyzed_node(node: VlessNode, score: float = 90.0) -> AnalyzedNode:
    return AnalyzedNode(
        node=node,
        probe=ProbeData(
            tcp_ping_ms=80.0,
            ttfb_ms=210.0,
            actual_ip="203.0.113.10",
            actual_geo="JP",
            asn_org="Example ASN",
            fraud_score=20,
        ),
        is_valid=True,
        total_score=score,
        reject_reason="",
    )


class SubscriptionRefreshServiceTests(unittest.TestCase):
    def test_run_nodes_limits_speedtest_concurrency(self):
        async def run_case():
            original_speedtest_concurrency = settings.SPEEDTEST_CONCURRENCY
            original_filter_concurrency = settings.FILTER_CONCURRENCY
            settings.SPEEDTEST_CONCURRENCY = 2
            settings.FILTER_CONCURRENCY = 10
            active = 0
            max_active = 0

            async def fake_filter(node, sem, force_probe=False):
                return make_analyzed_node(node)

            async def fake_speed_test(analyzed_node):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.01)
                active -= 1
                return TestedNode(analyzed_node, 10.0)

            try:
                with (
                    patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=fake_filter),
                    patch.object(SubscriptionRefreshService, "run_speed_test", side_effect=fake_speed_test),
                ):
                    results = await SubscriptionRefreshService.run_nodes(
                        [make_node(index) for index in range(5)],
                        speedtest_limit=5,
                    )
            finally:
                settings.SPEEDTEST_CONCURRENCY = original_speedtest_concurrency
                settings.FILTER_CONCURRENCY = original_filter_concurrency

            return max_active, results

        max_active, results = asyncio.run(run_case())

        self.assertLessEqual(max_active, 2)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(node.download_speed_mbps == 10.0 for node in results))


if __name__ == "__main__":
    unittest.main()

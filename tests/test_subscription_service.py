import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from models import AnalyzedNode, NodeProfile, ProbeData, TestedNode, VlessNode
from module_subscription_service import SubscriptionRefreshService
from settings import settings


def make_node(index: int, expected_geo: str = "JP") -> VlessNode:
    return VlessNode(
        raw_uri=f"vless://uuid-{index}@example.com:443?security=tls#{expected_geo}-{index}",
        uuid=f"uuid-{index}",
        server_ip="example.com",
        server_port=443,
        remark=f"{expected_geo}-{index}",
        expected_geo=expected_geo,
    )


def make_analyzed_node(node: VlessNode, risk: float = 10.0, actual_geo: str | None = None) -> AnalyzedNode:
    return AnalyzedNode(
        node=node,
        probe=ProbeData(
            tcp_ping_ms=80.0,
            ttfb_ms=210.0,
            actual_ip="203.0.113.10",
            actual_geo=actual_geo or node.expected_geo,
            asn_org="Example ASN",
            profile=NodeProfile(risk_score=risk),
        ),
        is_valid=True,
        reject_reason="",
    )


class SubscriptionRefreshServiceTests(unittest.TestCase):
    def test_run_nodes_without_speedtests_preserves_all_nodes(self):
        valid = make_analyzed_node(make_node(1))
        invalid = make_analyzed_node(make_node(2))
        invalid.is_valid = False
        for analyzed in ([], [invalid, valid]):
            with (
                self.subTest(nodes=len(analyzed)),
                patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=analyzed),
                patch.object(SubscriptionRefreshService, "run_speed_test") as speedtest,
                patch("module_subscription_service.ApiStore.get_probe_config_snapshot", return_value={}),
            ):
                result = asyncio.run(SubscriptionRefreshService.run_nodes(
                    [item.node for item in analyzed], speedtest_limit=0,
                ))
                self.assertEqual(result, [TestedNode(item) for item in sorted(analyzed, key=lambda item: not item.is_valid)])
                speedtest.assert_not_called()

    def test_fetch_subscription_text_rejects_large_local_file(self):
        original_max_m = settings.SUBSCRIPTION_MAX_M
        settings.SUBSCRIPTION_MAX_M = 1
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir, "sub.txt")
                path.write_text("A" * (1024 * 1024 + 1), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "exceeds 1048576 bytes"):
                    asyncio.run(SubscriptionRefreshService.fetch_subscription_text(str(path)))
        finally:
            settings.SUBSCRIPTION_MAX_M = original_max_m

    def test_run_nodes_limits_speedtest_concurrency(self):
        async def run_case():
            original_speedtest_concurrency = settings.SPEEDTEST_CONCURRENCY
            original_filter_concurrency = settings.FILTER_CONCURRENCY
            settings.SPEEDTEST_CONCURRENCY = 2
            settings.FILTER_CONCURRENCY = 10
            active = 0
            max_active = 0

            async def fake_filter(node, sem, force_probe=False, api_sites=None, probe_config=None, route_probe=None):
                return make_analyzed_node(node)

            async def fake_speed_test(analyzed_node, *, precise=False):
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

    def test_select_speedtest_nodes_uses_top_nodes_per_region(self):
        analyzed_nodes = [
            make_analyzed_node(make_node(1, "JP"), risk=5),
            make_analyzed_node(make_node(2, "JP"), risk=20),
            make_analyzed_node(make_node(3, "JP"), risk=30),
            make_analyzed_node(make_node(4, "US"), risk=10),
            make_analyzed_node(make_node(5, "US"), risk=15),
            make_analyzed_node(make_node(6, "US"), risk=40),
        ]

        nodes_to_test, nodes_to_skip = SubscriptionRefreshService.select_speedtest_nodes_per_region(
            analyzed_nodes,
            2,
        )

        self.assertEqual(
            {node.node.remark for node in nodes_to_test},
            {"JP-1", "JP-2", "US-4", "US-5"},
        )
        self.assertEqual(
            {node.node.remark for node in nodes_to_skip},
            {"JP-3", "US-6"},
        )

    def test_speedtest_prioritizes_zero_risk_and_puts_unknown_last(self):
        nodes = [make_analyzed_node(make_node(i), risk=risk)
                 for i, risk in enumerate([None, 20, 0, 0, 5])]
        nodes[3].probe.ttfb_ms = 100

        selected, skipped = SubscriptionRefreshService.select_speedtest_nodes_per_region(nodes, 1)
        self.assertEqual(selected, [nodes[3]])
        self.assertEqual(skipped, [nodes[2], nodes[4], nodes[1], nodes[0]])

        nodes[4].node.expected_geo = nodes[4].probe.actual_geo = "US"
        selected, _ = SubscriptionRefreshService.select_speedtest_nodes_per_region(nodes, 1)
        self.assertEqual(selected, [nodes[3], nodes[4]])

    def test_two_stage_speedtest_selects_fastest_per_region_and_keeps_all_nodes(self):
        nodes = [make_analyzed_node(make_node(i, geo)) for i, geo in enumerate(["JP", "JP", "US", "US", "JP"])]
        nodes[-1].is_valid = False
        coarse_speeds = [1, 20, 10, None]
        calls = []
        progress = []

        async def speed(node, *, precise=False):
            index = nodes.index(node)
            calls.append((index, precise))
            value = 99 if precise else coarse_speeds[index]
            return TestedNode(node, value, "success" if value is not None else "failed")

        with (
            patch.object(SubscriptionRefreshService, "process_node_filter", side_effect=nodes),
            patch.object(SubscriptionRefreshService, "run_speed_test", side_effect=speed),
        ):
            results = asyncio.run(SubscriptionRefreshService.run_nodes(
                [node.node for node in nodes], speedtest_limit=1,
                progress_callback=lambda *args: progress.append(args),
            ))
        self.assertEqual(calls, [(0, False), (1, False), (2, False), (3, False), (1, True), (2, True)])
        self.assertEqual(len(results), 5)
        self.assertEqual([item.download_speed_mbps for item in results[:2]], [99, 99])
        self.assertTrue(all(item.download_speed_mbps is None for item in results[2:]))
        self.assertEqual(progress[-1], ("speedtest", 6, 6))

    def test_failed_coarse_test_does_not_run_cloudflare(self):
        node = make_analyzed_node(make_node(1))
        with (
            patch.object(SubscriptionRefreshService, "process_node_filter", return_value=node),
            patch.object(SubscriptionRefreshService, "run_speed_test", return_value=TestedNode(node, None, "failed")) as speed,
        ):
            results = asyncio.run(SubscriptionRefreshService.run_nodes([node.node], speedtest_limit=1))
        speed.assert_awaited_once_with(node, precise=False)
        self.assertEqual(results, [TestedNode(node)])


if __name__ == "__main__":
    unittest.main()

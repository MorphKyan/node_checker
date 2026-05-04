import asyncio
import base64
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from models import AnalyzedNode, LabelEvidence, NodeProfile, ProbeData, TestedNode, VlessNode
from module_cache import ProbeCache
from module_subscription_exporter import SubscriptionExporter, get_visual_width
from settings import settings


def make_tested_node(
    raw_uri: str,
    remark: str,
    score: float,
    ttfb: float,
    speed: float,
    valid: bool = True,
    network_labels: list[LabelEvidence] | None = None,
    risk_labels: list[LabelEvidence] | None = None,
    asn_org: str = "Example ASN",
    actual_geo: str = "JP",
) -> TestedNode:
    node = VlessNode(
        raw_uri=raw_uri,
        uuid="uuid",
        server_ip="example.com",
        server_port=443,
        remark=remark,
        expected_geo="JP",
    )
    profile = NodeProfile(
        network_labels=network_labels or [],
        risk_labels=risk_labels or [],
    )
    probe = ProbeData(
        tcp_ping_ms=80.0,
        ttfb_ms=ttfb,
        actual_ip="203.0.113.10",
        actual_geo=actual_geo,
        asn_org=asn_org,
        fraud_score=20,
        profile=profile,
    )
    return TestedNode(
        AnalyzedNode(node, probe, valid, score, "" if valid else "Timeout", "test score"),
        speed,
    )


class SubscriptionUriRewriteTests(unittest.TestCase):
    def test_rewrite_only_changes_remark_and_preserves_query(self):
        raw_uri = "vless://uuid@example.com:443?security=tls&type=ws&path=%2F#Old"
        renamed = SubscriptionExporter.rewrite_vless_remark(raw_uri, "🇯🇵 日本 节点")

        self.assertTrue(renamed.startswith("vless://uuid@example.com:443?security=tls&type=ws&path=%2F#"))
        self.assertEqual(renamed.split("#", 1)[0], raw_uri.split("#", 1)[0])
        self.assertEqual(urllib.parse.unquote(renamed.split("#", 1)[1]), "🇯🇵 日本 节点")

    def test_rewrite_adds_remark_when_missing(self):
        raw_uri = "vless://uuid@example.com:443?security=tls"
        renamed = SubscriptionExporter.rewrite_vless_remark(raw_uri, "JP | 家宽")

        self.assertEqual(renamed.split("#", 1)[0], raw_uri)
        self.assertEqual(urllib.parse.unquote(renamed.split("#", 1)[1]), "JP | 家宽")


class SubscriptionTemplateTests(unittest.TestCase):
    def test_compact_uses_profile_aliases_for_network_and_type(self):
        tested = make_tested_node(
            "vless://uuid@example.com:443?security=tls#Old",
            "Old",
            92.0,
            210.0,
            0.0,
            network_labels=[LabelEvidence("hosting", 0.9)],
            risk_labels=[LabelEvidence("proxy", 0.9)],
        )

        remark = SubscriptionExporter.build_remark(tested, "compact", 64)

        self.assertIn("🇯🇵 JP", remark)
        self.assertIn("托管机房", remark)
        self.assertIn("Proxy", remark)
        self.assertIn("92分", remark)
        self.assertIn("210ms", remark)
        self.assertNotIn("Old", remark)

    def test_missing_labels_and_empty_asn_use_clean_fallbacks(self):
        tested = make_tested_node(
            "vless://uuid@example.com:443?security=tls#Old",
            "Old",
            88.0,
            220.0,
            0.0,
            asn_org="",
        )

        remark = SubscriptionExporter.build_remark(tested, "detailed", 96)

        self.assertIn("未知网络", remark)
        self.assertIn("未知类型", remark)
        self.assertIn("未测速", remark)
        self.assertIn("Old", remark)
        self.assertNotIn(" |  | ", remark)


class SubscriptionExportBehaviorTests(unittest.TestCase):
    def test_filter_sort_and_skip_invalid_nodes(self):
        raw_uri = "vless://uuid@example.com:443?security=tls#Old"
        slow = make_tested_node(
            raw_uri,
            "Slow",
            90.0,
            300.0,
            10.0,
            network_labels=[LabelEvidence("datacenter", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
        )
        fast = make_tested_node(
            raw_uri,
            "Fast",
            90.0,
            200.0,
            1.0,
            network_labels=[LabelEvidence("datacenter", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
        )
        invalid = make_tested_node(raw_uri, "Bad", 100.0, 100.0, 100.0, valid=False)

        uris = SubscriptionExporter.build_uris(
            [slow, invalid, fast],
            "compact",
            max_name_length=64,
            valid_only=True,
        )
        remarks = [urllib.parse.unquote(uri.split("#", 1)[1]) for uri in uris]

        self.assertEqual(len(uris), 2)
        self.assertIn("200ms", remarks[0])

    def test_dedupe_and_truncate(self):
        raw_uri = "vless://uuid@example.com:443?security=tls#Old"
        first = make_tested_node(
            raw_uri,
            "Same",
            90.0,
            210.0,
            10.0,
            network_labels=[LabelEvidence("likely_residential", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
        )
        second = make_tested_node(
            raw_uri,
            "Same",
            90.0,
            210.0,
            10.0,
            network_labels=[LabelEvidence("likely_residential", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
        )

        uris = SubscriptionExporter.build_uris(
            [first, second],
            "compact",
            max_name_length=28,
            valid_only=True,
        )
        remarks = [urllib.parse.unquote(uri.split("#", 1)[1]) for uri in uris]

        self.assertTrue(remarks[1].endswith(" #2"))
        self.assertLessEqual(get_visual_width(remarks[0]), 28)
        self.assertLessEqual(get_visual_width(remarks[1]), 28)

    def test_export_writes_plain_and_base64_files(self):
        tested = make_tested_node(
            "vless://uuid@example.com:443?security=tls#Old",
            "Old",
            92.0,
            210.0,
            12.34,
            network_labels=[LabelEvidence("likely_residential", 0.9)],
            risk_labels=[LabelEvidence("clean", 0.9)],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            SubscriptionExporter.export_enhanced_subscriptions([tested], tmpdir)
            compact = Path(tmpdir, "enhanced_compact.txt").read_text(encoding="utf-8")
            detailed = Path(tmpdir, "enhanced_detailed.txt").read_text(encoding="utf-8")
            compact_b64 = Path(tmpdir, "enhanced_compact_base64.txt").read_text(encoding="utf-8")
            detailed_b64 = Path(tmpdir, "enhanced_detailed_base64.txt").read_text(encoding="utf-8")

        self.assertIn("vless://", compact)
        self.assertIn("vless://", detailed)
        self.assertEqual(base64.b64decode(compact_b64).decode("utf-8"), compact)
        self.assertEqual(base64.b64decode(detailed_b64).decode("utf-8"), detailed)


class ProbeCacheRestoreTests(unittest.TestCase):
    def test_cache_hit_restores_profile_dataclasses(self):
        async def run_case():
            original_enabled = settings.CACHE_ENABLED
            original_db_path = settings.CACHE_DB_PATH
            original_failure_results = settings.CACHE_FAILURE_RESULTS
            original_initialized = ProbeCache._initialized

            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    settings.CACHE_ENABLED = True
                    settings.CACHE_DB_PATH = str(Path(tmpdir, "probe_cache.sqlite3"))
                    settings.CACHE_FAILURE_RESULTS = True
                    ProbeCache._initialized = False

                    tested = make_tested_node(
                        "vless://uuid@example.com:443?security=tls#Old",
                        "Old",
                        92.0,
                        210.0,
                        0.0,
                        network_labels=[LabelEvidence("hosting", 0.9)],
                        risk_labels=[LabelEvidence("proxy", 0.9)],
                    )

                    await ProbeCache.set(tested.analyzed_node.node, tested.analyzed_node.probe)
                    return await ProbeCache.get(tested.analyzed_node.node)
            finally:
                settings.CACHE_ENABLED = original_enabled
                settings.CACHE_DB_PATH = original_db_path
                settings.CACHE_FAILURE_RESULTS = original_failure_results
                ProbeCache._initialized = original_initialized

        restored = asyncio.run(run_case())

        self.assertIsInstance(restored.profile, NodeProfile)
        self.assertIsInstance(restored.profile.network_labels[0], LabelEvidence)
        self.assertEqual(
            SubscriptionExporter.format_network_labels(restored.profile),
            "托管机房",
        )


if __name__ == "__main__":
    unittest.main()

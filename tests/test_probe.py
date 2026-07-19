import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from models import VlessNode
from module_probe import LightweightProbe


class LightweightProbeTests(unittest.TestCase):
    def test_empty_snapshot_does_not_fallback_to_current_sites(self):
        async def run_case():
            node = VlessNode("vless://uuid@example.com:443#US", "uuid", "example.com", 443, "US", "US")
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=80.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=210.0)),
                patch.object(LightweightProbe, "trace_route", new=AsyncMock(return_value=("", False, False, ""))),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("8.8.8.8", {"country_code": "US"}))),
                patch("module_api_store.ApiStore.get_api_sites", side_effect=AssertionError("must not read current sites")),
            ):
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", api_sites=[])
            self.assertEqual(probe.actual_ip, "8.8.8.8")
            self.assertIsNone(probe.profile.risk_score)
        asyncio.run(run_case())

    def test_registry_status_and_risk_are_aggregated(self):
        async def run_case():
            node = VlessNode("vless://uuid@example.com:443#US", "uuid", "example.com", 443, "US", "US")
            site = {"id": "ipwhois", "column_name": "ipwho.is", "provider": "ipwhois", "url_template": "https://example/{ip}", "weight": 2, "enabled": True}
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=9999.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=110.0)),
                patch.object(LightweightProbe, "trace_route", new=AsyncMock(return_value=("", False, False, ""))),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("1.1.1.1", {"country_code": "US"}))),
                patch.object(LightweightProbe, "_fetch_site", new=AsyncMock(return_value=({"success": True, "security": {"proxy": True}}, "success"))),
            ):
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", [site])
            self.assertEqual(probe.profile.evidence[0].site_id, "ipwhois")
            self.assertEqual(probe.profile.evidence[0].status, "success")
            self.assertLess(probe.ttfb_ms, 9999.0)
        asyncio.run(run_case())

    def test_explicit_probe_config_uses_its_frozen_exit_endpoint(self):
        async def run_case():
            node = VlessNode("vless://uuid@example.com:443#US", "uuid", "example.com", 443, "US", "US")
            snapshot = {"api_sites": [], "exit_ip_endpoint": "https://old-exit.example.test"}
            fetch_exit = AsyncMock(return_value=("9.9.9.9", {"country_code": "US"}))
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=80.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=210.0)),
                patch.object(LightweightProbe, "trace_route", new=AsyncMock(return_value=("", False, False, ""))),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=fetch_exit),
                patch("module_api_store.ApiStore.get_exit_ip_endpoint", side_effect=AssertionError("must use snapshot")),
            ):
                await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", probe_config=snapshot)
            fetch_exit.assert_awaited_once_with("socks5://127.0.0.1:1080", "https://old-exit.example.test")
        asyncio.run(run_case())

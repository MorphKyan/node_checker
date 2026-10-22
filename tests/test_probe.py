import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models import VlessNode
from module_probe import LightweightProbe
from settings import settings


class LightweightProbeTests(unittest.TestCase):
    def test_api_retry_once_and_three_second_timeout(self):
        async def run_case():
            site = {"url_template": "https://example.test/{ip}"}
            for method in ("site", "exit"):
                for outcomes, calls, status in (
                    ([asyncio.TimeoutError(), 200], 2, "success"),
                    ([OSError("connection reset"), 200], 2, "success"),
                    ([503, 200], 2, "success"),
                    ([429, 200], 1, "rate_limited"),
                    ([403, 200], 1, "error"),
                    ([asyncio.TimeoutError(), asyncio.TimeoutError()], 2, "timeout"),
                    ([OSError("connection reset"), OSError("connection reset")], 2, "error"),
                    ([503, 503], 2, "error"),
                ):
                    with self.subTest(method=method, outcomes=outcomes):
                        responses = []
                        for outcome in outcomes:
                            if isinstance(outcome, Exception):
                                responses.append(outcome)
                            else:
                                response = MagicMock(status=outcome)
                                response.json = AsyncMock(return_value={"ip": "1.1.1.1"})
                                response.text = AsyncMock(return_value='{"ip":"1.1.1.1"}')
                                responses.append(response)
                        session = MagicMock()
                        session.get.return_value.__aenter__.side_effect = responses
                        with (
                            patch("module_probe.ProxyConnector.from_url") as connector,
                            patch("module_probe.aiohttp.ClientSession") as client,
                        ):
                            client.return_value.__aenter__.return_value = session
                            result = (
                                await LightweightProbe._fetch_site(site, "1.1.1.1", "socks5://127.0.0.1:1080")
                                if method == "site" else
                                await LightweightProbe._fetch_exit_ip("socks5://127.0.0.1:1080", "https://exit.test")
                            )
                        expected = ({"ip": "1.1.1.1"}, "success") if status == "success" else (None, status)
                        if method == "exit":
                            expected = ("1.1.1.1", {"ip": "1.1.1.1"}) if status == "success" else ("", None)
                        self.assertEqual(result, expected)
                        self.assertEqual(session.get.call_count, calls)
                        self.assertEqual(connector.call_count, calls)
                        for request in session.get.call_args_list:
                            self.assertEqual(request.kwargs["timeout"], 3.0)
                        self.assertEqual(settings.API_TIMEOUT, 3.0)
        asyncio.run(run_case())

    def test_cancelled_site_request_is_not_retried(self):
        async def run_case():
            with patch("module_probe.ProxyConnector.from_url", side_effect=asyncio.CancelledError()) as connector:
                with self.assertRaises(asyncio.CancelledError):
                    await LightweightProbe._fetch_site({"url_template": "https://example.test/{ip}"}, "1.1.1.1", "socks5://127.0.0.1:1080")
            connector.assert_called_once()
        asyncio.run(run_case())

    def test_site_requests_use_node_tunnel(self):
        async def run_case():
            site = {"url_template": "https://example.test/{ip}?key={key}", "api_key": "test key"}
            response = MagicMock(status=200)
            response.json = AsyncMock(return_value={"ip": "1.1.1.1"})
            session = MagicMock()
            session.get.return_value.__aenter__.return_value = response
            with (
                patch("module_probe.ProxyConnector.from_url") as connector,
                patch("module_probe.aiohttp.ClientSession") as client,
            ):
                client.return_value.__aenter__.return_value = session
                result = await LightweightProbe._fetch_site(site, "1.1.1.1", "socks5://127.0.0.1:1080")
            connector.assert_called_once_with("socks5://127.0.0.1:1080", rdns=True)
            client.assert_called_once_with(connector=connector.return_value)
            self.assertEqual(result, ({"ip": "1.1.1.1"}, "success"))
        asyncio.run(run_case())

    def test_empty_snapshot_does_not_fallback_to_current_sites(self):
        async def run_case():
            node = VlessNode(raw_uri="vless://uuid@example.com:443#US", uuid="uuid",
                             server_ip="example.com", server_port=443, remark="US", expected_geo="US")
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=80.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=210.0)),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("8.8.8.8", {"country_code": "US"}))),
                patch("module_api_store.ApiStore.get_api_sites", side_effect=AssertionError("must not read current sites")),
            ):
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", api_sites=[])
            self.assertEqual(probe.actual_ip, "8.8.8.8")
            self.assertIsNone(probe.profile.risk_score)
            self.assertEqual(probe.trace_path, "")
            self.assertIsNone(probe.is_detour)
            self.assertIsNone(probe.is_backbone)
        asyncio.run(run_case())

    def test_netcoffee_supplies_geo_asn_and_risk(self):
        async def run_case():
            site = {"id": "netcoffee", "provider": "netcoffee", "enabled": True}
            data = {"ip": "1.1.1.1", "countryCode": "au", "asOrganization": "Example ASN", "trust_score": 72}
            with (
                patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("1.1.1.1", None))),
                patch.object(LightweightProbe, "_fetch_site", new=AsyncMock(return_value=(data, "success"))),
            ):
                ip, geo, asn, profile = await LightweightProbe._ip_intelligence(
                    "socks5://127.0.0.1:1080", {"api_sites": [site], "exit_ip_endpoint": "https://exit.test"})
            self.assertEqual((ip, geo, asn), ("1.1.1.1", "AU", "Example ASN"))
            self.assertEqual(profile.evidence[0].site_id, "netcoffee")
            self.assertEqual(profile.evidence[0].risk_score, 28)
        asyncio.run(run_case())

    def test_registry_status_and_risk_are_aggregated(self):
        async def run_case():
            node = VlessNode(raw_uri="vless://uuid@example.com:443#US", uuid="uuid",
                             server_ip="example.com", server_port=443, remark="US", expected_geo="US")
            site = {"id": "ipwhois", "column_name": "ipwho.is", "provider": "ipwhois", "url_template": "https://example/{ip}", "weight": 2, "enabled": True}
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=9999.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=110.0)),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=AsyncMock(return_value=("1.1.1.1", {"country_code": "US"}))),
                patch.object(LightweightProbe, "_fetch_site", new=AsyncMock(return_value=({"success": True, "security": {"proxy": True}}, "success"))) as fetch_site,
            ):
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", [site])
            fetch_site.assert_awaited_once_with(site, "1.1.1.1", "socks5://127.0.0.1:1080")
            self.assertEqual(probe.profile.evidence[0].site_id, "ipwhois")
            self.assertEqual(probe.profile.evidence[0].status, "success")
            self.assertLess(probe.ttfb_ms, 9999.0)
        asyncio.run(run_case())

    def test_explicit_probe_config_uses_its_frozen_exit_endpoint(self):
        async def run_case():
            node = VlessNode(raw_uri="vless://uuid@example.com:443#US", uuid="uuid",
                             server_ip="example.com", server_port=443, remark="US", expected_geo="US")
            snapshot = {"api_sites": [], "exit_ip_endpoint": "https://old-exit.example.test"}
            fetch_exit = AsyncMock(return_value=("9.9.9.9", {"country_code": "US"}))
            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=80.0)),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=210.0)),
                patch.object(LightweightProbe, "detect_ipv6", new=AsyncMock(return_value=(False, ""))),
                patch.object(LightweightProbe, "_fetch_exit_ip", new=fetch_exit),
                patch("module_api_store.ApiStore.get_exit_ip_endpoint", side_effect=AssertionError("must use snapshot")),
            ):
                await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080", probe_config=snapshot)
            fetch_exit.assert_awaited_once_with("socks5://127.0.0.1:1080", "https://old-exit.example.test")
        asyncio.run(run_case())

import unittest
from unittest.mock import AsyncMock, patch

from models import VlessNode
from module_probe import LightweightProbe


class LightweightProbeTests(unittest.TestCase):
    def test_run_probe_falls_back_to_direct_ip_intelligence(self):
        async def run_case():
            node = VlessNode(
                raw_uri="vless://uuid@example.com:443?security=tls#US",
                uuid="uuid",
                server_ip="example.com",
                server_port=443,
                remark="US",
                expected_geo="US",
            )

            with (
                patch.object(LightweightProbe, "tcp_ping", new=AsyncMock(return_value=80.0)),
                patch.object(LightweightProbe, "trace_route", new=AsyncMock(return_value=("No trace path", False, False, ""))),
                patch.object(LightweightProbe, "test_ttfb", new=AsyncMock(return_value=210.0)),
                patch.object(LightweightProbe, "fetch_ip_info", new=AsyncMock(side_effect=RuntimeError("proxy failed"))),
                patch.object(LightweightProbe, "resolve_probe_target_ip", new=AsyncMock(return_value="8.8.8.8")),
                patch.object(LightweightProbe, "fetch_ipwhois_direct", new=AsyncMock(return_value=("Clean", {
                    "success": True,
                    "ip": "8.8.8.8",
                    "country_code": "US",
                    "connection": {"org": "Google LLC"},
                    "security": {
                        "proxy": False,
                        "vpn": False,
                        "tor": False,
                        "hosting": False,
                    },
                }))),
                patch.object(LightweightProbe, "fetch_ipapi", new=AsyncMock(return_value=("Clean", {
                    "is_proxy": False,
                    "is_vpn": False,
                    "is_tor": False,
                    "is_datacenter": True,
                }))) as ipapi,
                patch.object(LightweightProbe, "fetch_scamalytics", new=AsyncMock(return_value=("Not configured", None))),
                patch.object(LightweightProbe, "fetch_proxycheck", new=AsyncMock(return_value=("Clean", {
                    "status": "ok",
                    "8.8.8.8": {
                        "detections": {
                            "proxy": False,
                            "vpn": False,
                            "tor": False,
                            "hosting": False,
                        },
                    },
                }))) as proxycheck,
                patch.object(LightweightProbe, "fetch_abstract", new=AsyncMock(return_value=("Not configured", None))),
                patch.object(LightweightProbe, "fetch_ip2location", new=AsyncMock(return_value=("Usage:DCH", {
                    "usage_type": "DCH",
                    "is_proxy": False,
                }))) as ip2location,
            ):
                probe = await LightweightProbe.run_probe(node, "socks5://127.0.0.1:1080")

            self.assertEqual(probe.actual_ip, "8.8.8.8")
            self.assertEqual(probe.actual_geo, "US")
            self.assertEqual(probe.asn_org, "Google LLC")
            ipapi.assert_awaited_once_with("8.8.8.8")
            proxycheck.assert_awaited_once_with("8.8.8.8")
            ip2location.assert_awaited_once_with("8.8.8.8")
            self.assertNotEqual(probe.profile.display_labels, ["未知"])

        import asyncio

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from module_route import EntranceRouteProbe, parse_trace
from settings import settings


class TraceParserTests(unittest.TestCase):
    def test_windows_localized_and_linux_output_with_ipv6_and_gaps(self):
        self.assertEqual(parse_trace("""
Tracing route to 1.1.1.1 over a maximum of 30 hops:
  1    <1 ms     1 ms     1 ms  192.168.1.1
  2     *        *        *     请求超时。
  3  59.43.1.1  12.4 ms  59.43.1.2  13.1 ms
  4  2001:4860::1  24.1 ms
  5     1 ms     1 ms     1 ms  fe80::1%12
"""), [(1, ["192.168.1.1"]), (2, []), (3, ["59.43.1.1", "59.43.1.2"]),
       (4, ["2001:4860::1"]), (5, ["fe80::1"])])


class EntranceRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_entrance_shares_trace_and_annotates_asn_evidence(self):
        probe = EntranceRouteProbe()
        with patch.object(probe, "_trace", new=AsyncMock(return_value=(
            "1 192.168.1.1 1 ms\n2 59.43.1.1 12 ms\n3 1.1.1.1 30 ms", "partial"))) as trace, \
             patch.object(probe, "_lookup_asns", new=AsyncMock(side_effect=lambda ip: [4809] if ip == "59.43.1.1" else [13335])) as lookup:
            first, second = await asyncio.gather(probe.probe("1.1.1.1"), probe.probe("1.1.1.1"))
        self.assertEqual(first, second)
        trace.assert_awaited_once_with("1.1.1.1")
        self.assertEqual(lookup.await_count, 2)
        self.assertEqual(first["route_status"], "completed")
        self.assertTrue(first["is_backbone"])
        self.assertEqual(first["backbone_info"], "电信 CN2 (AS4809)")
        self.assertIn("2: 59.43.1.1 [AS4809 电信 CN2]", first["trace_path"])

    async def test_partial_path_and_unmatched_asns_stay_unknown(self):
        probe = EntranceRouteProbe()
        for output, asns in [("1 8.8.8.8 2 ms\n2 * * *", []),
                             ("1 8.8.8.8 2 ms\n2 * * *", [15169]),
                             ("1 1.1.1.1 2 ms", [4809])]:
            with self.subTest(output=output), \
                 patch.object(probe, "_trace", new=AsyncMock(return_value=(output, "timeout"))), \
                 patch.object(probe, "_lookup_asns", new=AsyncMock(return_value=asns)):
                result = await probe._probe_target("1.1.1.1")
            # The target's own ASN must not count as a transit network.
            self.assertIsNone(result["is_backbone"])
            self.assertEqual(result["backbone_info"], "")
            self.assertTrue(result["trace_path"])
            self.assertEqual(result["route_status"], "completed" if "1 1.1.1.1" in output else "timeout")

    async def test_unannounced_cn2_prefix_is_evidence_without_invented_asn(self):
        probe = EntranceRouteProbe()
        with patch.object(probe, "_trace", new=AsyncMock(return_value=("1 59.43.1.1 2 ms\n2 * * *", "timeout"))), \
             patch.object(probe, "_lookup_asns", new=AsyncMock(return_value=[])):
            result = await probe._probe_target("1.1.1.1")
        self.assertTrue(result["is_backbone"])
        self.assertEqual(result["backbone_info"], "电信 CN2 (IP段 59.43.0.0/16)")
        self.assertIn("IP段 59.43.0.0/16", result["trace_path"])
        self.assertNotIn("AS4809", result["trace_path"])

    async def test_missing_tool_dns_failure_and_spawn_failure_are_nonfatal(self):
        probe = EntranceRouteProbe()
        with patch("module_route.shutil.which", return_value=None):
            result = await probe.probe("1.1.1.1")
            self.assertEqual(result["route_status"], "missing_tool")
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", new=AsyncMock(side_effect=OSError("dns"))):
            self.assertEqual(await probe.probe("invalid.test"), {"route_status": "dns_failed"})
        with patch.object(probe, "_trace", new=AsyncMock(side_effect=OSError("spawn"))):
            self.assertEqual((await probe._probe_target("::1"))["route_status"], "failed")

    async def test_lookup_handles_bad_data_and_does_not_send_private_ips(self):
        probe = EntranceRouteProbe()
        self.assertEqual(await probe._asns_for("192.168.1.1"), [])
        for status, data in [(503, {}), (200, {"status": "error"}),
                             (200, {"status": "ok", "data": {"asns": ["bad"]}}),
                             (200, {"status": "ok", "data": {"asns": ["4809"]}})]:
            response = MagicMock(status=status)
            response.json = AsyncMock(return_value=data)
            session = MagicMock()
            session.get.return_value.__aenter__.return_value = response
            with patch("module_route.aiohttp.ClientSession") as client:
                client.return_value.__aenter__.return_value = session
                result = await probe._lookup_asns("59.43.1.1")
            self.assertEqual(result, [4809] if data.get("data", {}).get("asns") == ["4809"] else [])

    async def test_timeout_kills_child_and_preserves_partial_output(self):
        probe = EntranceRouteProbe()
        killed = asyncio.Event()
        process = MagicMock(returncode=None)
        process.kill.side_effect = killed.set
        process.wait = AsyncMock(return_value=1)
        async def communicate():
            await killed.wait()
            return b"1 192.168.1.1 1 ms\n2 * * *", None
        process.communicate = communicate
        with patch("module_route.shutil.which", return_value="trace"), \
             patch("module_route.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn, \
             patch.object(settings, "ROUTE_TIMEOUT", .01):
            result = await probe._probe_target("1.1.1.1")
        self.assertEqual(result["route_status"], "timeout")
        self.assertEqual(result["trace_path"], "1: 192.168.1.1\n2: *")
        self.assertEqual(spawn.await_args.args[-1], "1.1.1.1")
        process.wait.assert_awaited()

    async def test_linux_command_uses_numeric_target_and_one_udp_probe_per_hop(self):
        process = MagicMock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"1 1.1.1.1 1 ms", None))
        process.wait = AsyncMock(return_value=0)
        with patch("module_route.os.name", "posix"), \
             patch("module_route.shutil.which", return_value="/usr/bin/traceroute"), \
             patch("module_route.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
            await EntranceRouteProbe()._trace("1.1.1.1")
        self.assertEqual(spawn.await_args.args, ("/usr/bin/traceroute", "-n", "-4", "-m", "30", "-q", "1", "-w", "0.5", "1.1.1.1"))
        self.assertNotIn("creationflags", spawn.await_args.kwargs)

    async def test_cancellation_reaps_child(self):
        probe = EntranceRouteProbe()
        reading, killed = asyncio.Event(), asyncio.Event()
        process = MagicMock(returncode=None)
        process.kill.side_effect = killed.set
        process.wait = AsyncMock(return_value=1)
        async def communicate():
            reading.set()
            await killed.wait()
            return b"", None
        process.communicate = communicate
        with patch("module_route.shutil.which", return_value="trace"), \
             patch("module_route.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
            task = asyncio.create_task(probe.probe("1.1.1.1"))
            await reading.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(killed.is_set())
        process.wait.assert_awaited()

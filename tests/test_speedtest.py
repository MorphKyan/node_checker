import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from module_speedtest import BandwidthTester
from settings import settings


class BandwidthTesterTests(unittest.TestCase):
    def test_bytes_to_count_truncates_chunk_at_max_bytes(self):
        self.assertEqual(BandwidthTester.bytes_to_count(0, 8, 10), 8)
        self.assertEqual(BandwidthTester.bytes_to_count(8, 8, 10), 2)
        self.assertEqual(BandwidthTester.bytes_to_count(10, 8, 10), 0)

    def run_download(self, *, precise=False, fail=False, stall=False, partial_timeout=False):
        clock = SimpleNamespace(now=0.0)
        requests = []
        chunks_read = []

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                if stall:
                    await asyncio.sleep(1)
                for index in range(101):
                    if partial_timeout and index == 1:
                        clock.now += 2
                        raise httpx.ReadTimeout("stalled after data")
                    chunks_read.append(index)
                    clock.now += 2
                    yield b"x" * 1_000_000

            async def aclose(self):
                clock.now += 1000

        async def handle(request):
            requests.append(request)
            clock.now += 100  # Connection and response-header delay.
            return httpx.Response(503 if fail else 200, stream=Body())

        node = SimpleNamespace(node=SimpleNamespace(remark="test"))
        with (
            patch("module_speedtest.AsyncProxyTransport.from_url", return_value=httpx.MockTransport(handle)),
            patch("module_speedtest.time", SimpleNamespace(perf_counter=lambda: clock.now)),
            patch.object(settings, "SPEEDTEST_MAX_M", 1),
            patch.object(settings, "SPEEDTEST_TIMEOUT", 0.001 if stall else 10),
        ):
            result = asyncio.run(BandwidthTester.run_speed_test(node, "socks5://localhost:1234", precise=precise))
        return result, requests, chunks_read

    def test_coarse_download_excludes_setup_and_cleanup_and_caps_bytes(self):
        result, requests, chunks = self.run_download()
        self.assertAlmostEqual(result.download_speed_mbps, 1_048_576 * 8 / 1_000_000 / 4)
        self.assertEqual(result.speedtest_status, "success")
        self.assertEqual(str(requests[0].url), settings.SPEEDTEST_URL)
        self.assertEqual(len(chunks), 2)

    def test_precise_download_uses_cloudflare_and_stops_at_100_mb(self):
        result, requests, chunks = self.run_download(precise=True)
        self.assertEqual(str(requests[0].url), "https://speed.cloudflare.com/__down?bytes=100000000")
        self.assertEqual(requests[0].headers["Accept-Encoding"], "identity")
        self.assertEqual(len(chunks), 100)
        self.assertEqual(result.download_speed_mbps, 4)

    def test_http_error_is_failed(self):
        result, _, chunks = self.run_download(fail=True)
        self.assertIsNone(result.download_speed_mbps)
        self.assertEqual(result.speedtest_status, "failed")
        self.assertEqual(chunks, [])

    def test_body_deadline_stops_stalled_download(self):
        result, _, chunks = self.run_download(stall=True)
        self.assertIsNone(result.download_speed_mbps)
        self.assertEqual(result.speedtest_status, "failed")
        self.assertEqual(chunks, [])

    def test_partial_read_timeout_keeps_measured_throughput(self):
        result, _, chunks = self.run_download(partial_timeout=True)
        self.assertEqual(result.download_speed_mbps, 2)
        self.assertEqual(result.speedtest_status, "success")
        self.assertEqual(len(chunks), 1)


if __name__ == "__main__":
    unittest.main()

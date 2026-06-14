import asyncio
import unittest

from aiohttp import web

from module_parser import VlessParser
from settings import settings


class VlessParserTests(unittest.TestCase):
    def test_parse_ipv6_host_with_brackets(self):
        raw = "vless://uuid@[2001:db8::1]:443?security=tls&sni=example.com#IPv6"

        nodes = VlessParser.parse_nodes(raw)

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].server_ip, "2001:db8::1")
        self.assertEqual(nodes[0].server_port, 443)
        self.assertEqual(nodes[0].security, "tls")
        self.assertEqual(nodes[0].sni, "example.com")

    def test_http_source_requires_http_or_https_scheme(self):
        self.assertTrue(VlessParser.is_http_source("https://example.com/sub"))
        self.assertTrue(VlessParser.is_http_source("HTTP://example.com/sub"))
        self.assertFalse(VlessParser.is_http_source("http_subscriptions.txt"))
        self.assertFalse(VlessParser.is_http_source("file:///tmp/subscriptions.txt"))

    def test_fetch_subscription_rejects_large_content_length(self):
        async def run_case():
            original_max_m = settings.SUBSCRIPTION_MAX_M
            settings.SUBSCRIPTION_MAX_M = 1

            async def handler(request):
                return web.Response(body=b"A" * (1024 * 1024 + 1))

            app = web.Application()
            app.router.add_get("/sub", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                with self.assertRaisesRegex(ValueError, "exceeds 1048576 bytes"):
                    await VlessParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
            finally:
                settings.SUBSCRIPTION_MAX_M = original_max_m
                await runner.cleanup()

        asyncio.run(run_case())

    def test_fetch_subscription_rejects_stream_over_limit(self):
        async def run_case():
            original_max_m = settings.SUBSCRIPTION_MAX_M
            settings.SUBSCRIPTION_MAX_M = 1

            async def handler(request):
                response = web.StreamResponse()
                await response.prepare(request)
                await response.write(b"A" * 512 * 1024)
                await response.write(b"B" * 513 * 1024)
                await response.write_eof()
                return response

            app = web.Application()
            app.router.add_get("/sub", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                with self.assertRaisesRegex(ValueError, "exceeds 1048576 bytes"):
                    await VlessParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
            finally:
                settings.SUBSCRIPTION_MAX_M = original_max_m
                await runner.cleanup()

        asyncio.run(run_case())

    def test_fetch_subscription_allows_response_at_limit(self):
        async def run_case():
            original_max_m = settings.SUBSCRIPTION_MAX_M
            settings.SUBSCRIPTION_MAX_M = 1
            payload = "A" * (1024 * 1024)

            async def handler(request):
                return web.Response(body=payload.encode("utf-8"))

            app = web.Application()
            app.router.add_get("/sub", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                text = await VlessParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
            finally:
                settings.SUBSCRIPTION_MAX_M = original_max_m
                await runner.cleanup()
            return text

        self.assertEqual(len(asyncio.run(run_case())), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

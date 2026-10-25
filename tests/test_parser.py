import asyncio
import base64
from contextlib import redirect_stdout
from io import StringIO
import unittest

from aiohttp import web

from module_parser import NodeParser
from settings import settings


class NodeParserTests(unittest.TestCase):
    def test_shared_endpoint_parsing_preserves_credentials_and_uri(self):
        for scheme, parser in (("vless", NodeParser.parse_vless_line),
                               ("hy2", NodeParser.parse_hy2_line),
                               ("hysteria2", NodeParser.parse_hy2_line)):
            for suffix, sni, remark in (("", "", ""),
                                        ("?sni=first&sni=last&path=%2Fa%3Fb#JP%20%23node", "last", "JP #node")):
                raw = f"{scheme}://user%40secret@[2001:db8::1]:8443{suffix}"
                with self.subTest(raw=raw):
                    node = parser(raw)
                    self.assertEqual((node.raw_uri, node.server_ip, node.server_port, node.sni, node.remark),
                                     (raw, "2001:db8::1", 8443, sni, remark))
                    if scheme == "vless":
                        self.assertEqual(node.uuid, "user%40secret")
                        self.assertEqual(node.path, "/a?b" if suffix else "")
                    else:
                        self.assertEqual(node.password, "user@secret")

    def test_shared_endpoint_parsing_rejects_missing_and_invalid_addresses(self):
        for scheme, parser in (("vless", NodeParser.parse_vless_line),
                               ("hy2", NodeParser.parse_hy2_line),
                               ("hysteria2", NodeParser.parse_hy2_line)):
            for address in ("host", ":443", "host:bad", "host:65536", "[invalid]:443"):
                with self.subTest(scheme=scheme, address=address), self.assertRaises(ValueError):
                    parser(f"{scheme}://secret@{address}")

    def test_urlsafe_base64_subscription_with_unicode_remark(self):
        raw = "vless://uuid@example.com:443#测试x😀"
        encoded = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        self.assertTrue("-" in encoded or "_" in encoded)
        self.assertEqual(NodeParser.parse_nodes(encoded), NodeParser.parse_nodes(raw))

    def test_invalid_nodes_do_not_log_credentials(self):
        output = StringIO()
        with redirect_stdout(output):
            nodes = NodeParser.parse_nodes("\n".join([
                "ss://aes-128-gcm:secret-ss@host:bad",
                "vless://secret-uuid@host:bad",
                "hy2://secret-password@host:bad",
                "vless://uuid@host:443",
            ]))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(output.getvalue().count("Failed to parse"), 3)
        self.assertNotIn("secret", output.getvalue())

    def test_parse_ipv6_host_with_brackets(self):
        raw = "vless://uuid@[2001:db8::1]:443?security=tls&sni=example.com#IPv6"

        nodes = NodeParser.parse_nodes(raw)

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].server_ip, "2001:db8::1")
        self.assertEqual(nodes[0].server_port, 443)
        self.assertEqual(nodes[0].security, "tls")
        self.assertEqual(nodes[0].sni, "example.com")

    def test_http_source_requires_http_or_https_scheme(self):
        self.assertTrue(NodeParser.is_http_source("https://example.com/sub"))
        self.assertTrue(NodeParser.is_http_source("HTTP://example.com/sub"))
        self.assertFalse(NodeParser.is_http_source("http_subscriptions.txt"))
        self.assertFalse(NodeParser.is_http_source("file:///tmp/subscriptions.txt"))

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
                    await NodeParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
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
                    await NodeParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
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
                text = await NodeParser.fetch_subscription(f"http://127.0.0.1:{port}/sub")
            finally:
                settings.SUBSCRIPTION_MAX_M = original_max_m
                await runner.cleanup()
            return text

        self.assertEqual(len(asyncio.run(run_case())), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

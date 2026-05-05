import unittest

from module_parser import VlessParser


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


if __name__ == "__main__":
    unittest.main()

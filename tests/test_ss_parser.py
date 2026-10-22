import base64
from dataclasses import asdict, replace
import json
import os
import tempfile
import unittest

from models import SsNode, AnalyzedNode, ProbeData, TestedNode
from module_parser import NodeParser
from module_node_identity import make_node_fingerprint
from module_result_codec import restore_proxy_node, restore_tested_nodes
from module_shadowsocks import singbox_shadowsocks_outbound
from module_singbox_exporter import generate_singbox_config
from module_subscription_exporter import SubscriptionExporter
from module_tunnel import TunnelController
from module_exporter import ResultExporter


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


class ShadowsocksTests(unittest.TestCase):
    def setUp(self):
        self.uri = 'ss://' + b64('aes-128-gcm:p@ss:word') + '@example.com:8388#JP%20Node'
        self.node = NodeParser.parse_ss_line(self.uri)
        self.tested = TestedNode(AnalyzedNode(
            node=self.node,
            probe=ProbeData(tcp_ping_ms=10, ttfb_ms=20, actual_ip='1.1.1.1',
                            actual_geo='JP', asn_org='Test ISP'),
            is_valid=True,
        ))

    def test_sip002_base64_and_geo(self):
        self.assertIsInstance(self.node, SsNode)
        self.assertEqual(self.node.method, 'aes-128-gcm')
        self.assertEqual(self.node.password, 'p@ss:word')
        self.assertEqual(self.node.server_ip, 'example.com')
        self.assertEqual(self.node.server_port, 8388)
        self.assertEqual(self.node.remark, 'JP Node')
        self.assertEqual(self.node.expected_geo, 'JP')

    def test_percent_encoded_ss2022_ipv6(self):
        node = NodeParser.parse_ss_line(
            'ss://2022-blake3-aes-128-gcm:ab%2Bcd%2Fef%3D@[2001:db8::1]:443/#IPv6')
        self.assertEqual(node.password, 'ab+cd/ef=')
        self.assertEqual(node.server_ip, '2001:db8::1')
        self.assertEqual(node.method, '2022-blake3-aes-128-gcm')

    def test_legacy_full_base64(self):
        node = NodeParser.parse_ss_line('ss://' + b64('aes-128-gcm:p@ss:word@example.com:8388') + '#JP')
        self.assertEqual(node.password, self.node.password)
        self.assertEqual(node.server_ip, self.node.server_ip)
        literal = NodeParser.parse_ss_line('ss://' + b64('aes-128-gcm:p%23ss@example.com:8388'))
        self.assertEqual(literal.password, 'p%23ss')

    def test_mixed_base64_subscription_and_invalid_ss(self):
        text = '\n'.join([self.uri, 'vless://uuid@host:443', 'hy2://secret@host:443',
                          'ss://broken', 'ss://aes-128-gcm:secret@host:0'])
        for source in [text, b64(text)]:
            with self.subTest(encoded=source != text):
                self.assertEqual([n.protocol for n in NodeParser.parse_nodes(source)], ['ss', 'vless', 'hy2'])

    def test_plugins_are_preserved_and_xray_rejects_them(self):
        node = NodeParser.parse_ss_line(self.uri.split('#')[0] +
                                       '/?plugin=v2ray-plugin%3Btls%3Bhost%3Dexample.com#JP')
        outbound = singbox_shadowsocks_outbound(node, 'node')
        self.assertEqual(outbound['plugin'], 'v2ray-plugin')
        self.assertEqual(outbound['plugin_opts'], 'tls;host=example.com')
        with self.assertRaisesRegex(ValueError, 'plugins require sing-box'):
            TunnelController.generate_xray_config(node, 10808)

    def test_tunnel_configs(self):
        for generate, core in [(TunnelController.generate_singbox_config, 'sing-box'),
                               (TunnelController.generate_xray_config, 'xray')]:
            with self.subTest(core=core):
                path = generate(self.node, 10808)
                try:
                    with open(path, encoding='utf-8') as stream:
                        config = json.load(stream)
                    outbound = config['outbounds'][0]
                    server = outbound if core == 'sing-box' else outbound['settings']['servers'][0]
                    self.assertEqual(outbound.get('type', outbound.get('protocol')), 'shadowsocks')
                    self.assertEqual(server['method'], self.node.method)
                    self.assertEqual(server['password'], self.node.password)
                finally:
                    os.unlink(path)

    def test_codec_and_connection_fingerprint(self):
        restored = restore_tested_nodes(json.loads(json.dumps([asdict(self.tested)])))[0].analyzed_node.node
        self.assertEqual(restored, self.node)
        data = asdict(self.node)
        del data['protocol']
        self.assertIsInstance(restore_proxy_node(data), SsNode)
        self.assertEqual(make_node_fingerprint(self.node), make_node_fingerprint(replace(self.node, remark='renamed')))
        for changes in [{'password': 'other'}, {'method': 'aes-256-gcm'},
                        {'plugin': 'obfs-local'}, {'plugin_opts': 'obfs=tls'}]:
            self.assertNotEqual(make_node_fingerprint(self.node), make_node_fingerprint(replace(self.node, **changes)))

    def test_export_retains_uri_and_singbox_connection_settings(self):
        uri = SubscriptionExporter.build_uris([self.tested], 'compact', 64)[0]
        self.assertEqual(uri.split('#')[0], self.uri.split('#')[0])
        config = generate_singbox_config('{"outbounds": [{"type": "selector", "tag": "proxy", "use_all_nodes": true}]}', [self.tested])
        outbound = config['outbounds'][-1]
        self.assertEqual(outbound['type'], 'shadowsocks')
        self.assertEqual(outbound['method'], self.node.method)
        self.assertEqual(outbound['password'], self.node.password)
        self.assertEqual(config['outbounds'][0]['outbounds'], [outbound['tag']])

    def test_report_has_ss_method(self):
        with tempfile.TemporaryDirectory() as folder:
            ResultExporter.export_markdown_report([self.tested], base_dir=folder)
            from pathlib import Path
            detail = next((Path(folder) / 'node_details').glob('*.md')).read_text(encoding='utf-8')
            self.assertIn('aes-128-gcm', detail)
            self.assertIn('`SS`', detail)


if __name__ == '__main__':
    unittest.main()

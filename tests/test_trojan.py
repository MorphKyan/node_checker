import base64
from dataclasses import asdict, replace
import json
import os
import unittest

from models import TrojanNode, AnalyzedNode, ProbeData, TestedNode
from module_parser import NodeParser
from module_node_identity import make_node_fingerprint
from module_result_codec import restore_proxy_node, restore_tested_nodes
from module_subscription_exporter import SubscriptionExporter
from module_tunnel import TunnelController


class TrojanTests(unittest.TestCase):
    def setUp(self):
        self.uri = 'trojan://p%40ss%3Aword@[2001:db8::1]:443?security=tls&type=tcp&sni=example.com&peer=ignored&allowInsecure=0#JP%20Node'
        self.node = NodeParser.parse_trojan_line(self.uri)

    def test_plain_base64_and_mixed_subscriptions(self):
        raw = self.uri + '\nvless://uuid@example.com:443\nhy2://password@example.com:443'
        for text in (raw, base64.b64encode(raw.encode()).decode()):
            nodes = NodeParser.parse_nodes(text)
            self.assertEqual([node.protocol for node in nodes], ['trojan', 'vless', 'hy2'])
            self.assertEqual(nodes[0], self.node)
        self.assertEqual((self.node.password, self.node.server_ip, self.node.server_port),
                         ('p@ss:word', '2001:db8::1', 443))
        self.assertEqual((self.node.remark, self.node.expected_geo, self.node.sni, self.node.insecure),
                         ('JP Node', 'JP', 'example.com', False))

    def test_defaults_aliases_and_invalid_input(self):
        node = NodeParser.parse_trojan_line('trojan://secret@example.com:443?peer=tls.example&insecure=true')
        self.assertEqual((node.security, node.type, node.sni, node.insecure), ('tls', 'tcp', 'tls.example', True))
        for uri in ('trojan://@host:443', 'trojan://secret@host:0',
                    'trojan://secret@host:bad', 'trojan://secret@host:443?security=invalid'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                NodeParser.parse_trojan_line(uri)

    def test_tunnels_preserve_tls_password_and_transports(self):
        for transport in ('tcp', 'ws', 'grpc'):
            node = NodeParser.parse_trojan_line(
                f'trojan://p%40ss@example.com:443?type={transport}&path=%2Fsocket&serviceName=svc'
                '&host=ws.example&sni=tls.example&alpn=h2&fp=chrome&allowInsecure=1')
            for generate in (TunnelController.generate_singbox_config, TunnelController.generate_xray_config):
                with self.subTest(transport=transport, core=generate.__name__):
                    path = generate(node, 10808)
                    try:
                        with open(path, encoding='utf-8') as stream:
                            outbound = json.load(stream)['outbounds'][0]
                        self.assertEqual(outbound.get('type', outbound.get('protocol')), 'trojan')
                        if 'type' in outbound:
                            self.assertEqual(outbound['password'], 'p@ss')
                            self.assertNotIn('uuid', outbound)
                            self.assertEqual(outbound['tls']['server_name'], 'tls.example')
                            self.assertTrue(outbound['tls']['insecure'])
                            self.assertEqual(outbound['tls']['alpn'], ['h2'])
                            self.assertEqual(outbound['tls']['utls']['fingerprint'], 'chrome')
                            if transport != 'tcp':
                                self.assertEqual(outbound['transport']['type'], transport)
                                key = 'service_name' if transport == 'grpc' else 'path'
                                self.assertEqual(outbound['transport'][key], 'svc' if transport == 'grpc' else '/socket')
                        else:
                            self.assertEqual(outbound['settings']['servers'][0]['password'], 'p@ss')
                            tls = outbound['streamSettings']['tlsSettings']
                            self.assertEqual((tls['serverName'], tls['allowInsecure'], tls['alpn'], tls['fingerprint']),
                                             ('tls.example', True, ['h2'], 'chrome'))
                            self.assertEqual(outbound['streamSettings']['network'], transport)
                            if transport == 'grpc':
                                self.assertEqual(outbound['streamSettings']['grpcSettings']['serviceName'], 'svc')
                            elif transport == 'ws':
                                self.assertEqual(outbound['streamSettings']['wsSettings'],
                                                 {'path': '/socket', 'headers': {'Host': 'ws.example'}})
                    finally:
                        os.unlink(path)

    def test_storage_fingerprints_and_export(self):
        tested = TestedNode(AnalyzedNode(self.node, ProbeData(10, 20, '1.1.1.1', 'JP', 'Test ISP'), True))
        restored = restore_tested_nodes(json.loads(json.dumps([asdict(tested)])))[0]
        self.assertEqual(restored, tested)
        data = asdict(self.node)
        del data['protocol']
        self.assertIsInstance(restore_proxy_node(data), TrojanNode)
        original = make_node_fingerprint(self.node)
        self.assertEqual(original, make_node_fingerprint(replace(self.node, remark='new', raw_uri='renamed')))
        for changes in ({'password': 'other'}, {'sni': 'other'}, {'insecure': True}, {'path': '/other'}):
            self.assertNotEqual(original, make_node_fingerprint(replace(self.node, **changes)))
        exported = SubscriptionExporter.build_uris([restored], 'compact', 64)[0]
        self.assertEqual(exported.split('#')[0], self.uri.split('#')[0])

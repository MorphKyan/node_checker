import unittest
import json
import os
from models import VlessNode
from module_tunnel import TunnelController

class XrayConfigTests(unittest.TestCase):
    def test_xray_config_generation_basic(self):
        node = VlessNode(
            raw_uri="vless://uuid@example.com:443?type=tcp#test",
            uuid="uuid-vless-test",
            server_ip="example.com",
            server_port=443,
            remark="test",
            expected_geo="US",
            security="none",
            type="tcp"
        )
        config_path = TunnelController.generate_xray_config(node, 10800)
        
        self.assertTrue(os.path.exists(config_path))
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # Cleanup
        os.remove(config_path)
        
        self.assertEqual(config["inbounds"][0]["port"], 10800)
        self.assertEqual(config["inbounds"][0]["protocol"], "socks")
        self.assertEqual(config["outbounds"][0]["protocol"], "vless")
        self.assertEqual(config["outbounds"][0]["settings"]["vnext"][0]["address"], "example.com")
        self.assertEqual(config["outbounds"][0]["settings"]["vnext"][0]["users"][0]["id"], "uuid-vless-test")
        self.assertEqual(config["outbounds"][0]["streamSettings"]["network"], "tcp")
        self.assertEqual(config["outbounds"][0]["streamSettings"]["security"], "none")

    def test_xray_config_generation_reality_grpc(self):
        node = VlessNode(
            raw_uri="vless://uuid@example.com:443?type=grpc&security=reality&sni=sni.com&pbk=publickey&sid=shortid&serviceName=mygrpc#test",
            uuid="uuid-vless-test",
            server_ip="example.com",
            server_port=443,
            remark="test",
            expected_geo="US",
            security="reality",
            sni="sni.com",
            pbk="publickey",
            sid="shortid",
            type="grpc",
            path="mygrpc"
        )
        config_path = TunnelController.generate_xray_config(node, 10801)
        
        self.assertTrue(os.path.exists(config_path))
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # Cleanup
        os.remove(config_path)
        
        stream_settings = config["outbounds"][0]["streamSettings"]
        self.assertEqual(stream_settings["network"], "grpc")
        self.assertEqual(stream_settings["security"], "reality")
        self.assertEqual(stream_settings["realitySettings"]["serverName"], "sni.com")
        self.assertEqual(stream_settings["realitySettings"]["publicKey"], "publickey")
        self.assertEqual(stream_settings["realitySettings"]["shortId"], "shortid")
        self.assertEqual(stream_settings["grpcSettings"]["serviceName"], "mygrpc")

    def test_xray_config_generation_xhttp(self):
        node = VlessNode(
            raw_uri="vless://uuid@example.com:443?type=xhttp&security=tls&sni=sni.com&host=host.com&path=/mypath&mode=auto#test",
            uuid="uuid-vless-test",
            server_ip="example.com",
            server_port=443,
            remark="test",
            expected_geo="US",
            security="tls",
            sni="sni.com",
            type="xhttp",
            path="/mypath",
            host="host.com",
            mode="auto"
        )
        config_path = TunnelController.generate_xray_config(node, 10802)
        
        self.assertTrue(os.path.exists(config_path))
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        # Cleanup
        os.remove(config_path)
        
        stream_settings = config["outbounds"][0]["streamSettings"]
        self.assertEqual(stream_settings["network"], "xhttp")
        self.assertEqual(stream_settings["security"], "tls")
        self.assertEqual(stream_settings["tlsSettings"]["serverName"], "sni.com")
        self.assertEqual(stream_settings["xhttpSettings"]["path"], "/mypath")
        self.assertEqual(stream_settings["xhttpSettings"]["host"], "host.com")
        self.assertEqual(stream_settings["xhttpSettings"]["mode"], "auto")

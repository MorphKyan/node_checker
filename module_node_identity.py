import hashlib
import json

from models import ProxyNode, Hy2Node, VlessNode, SsNode


def make_node_fingerprint(node: ProxyNode) -> str:
    if isinstance(node, SsNode):
        identity = {
            "protocol": "ss", "server_ip": node.server_ip, "server_port": node.server_port,
            "method": node.method, "password": node.password,
            "plugin": node.plugin, "plugin_opts": node.plugin_opts,
        }
    elif isinstance(node, Hy2Node) or getattr(node, "protocol", "vless") in {"hy2", "hysteria2"}:
        identity = {
            "protocol": "hy2",
            "password": node.password,
            "server_ip": node.server_ip,
            "server_port": node.server_port,
            "sni": node.sni,
            "insecure": node.insecure,
            "obfs": node.obfs,
            "obfs_password": node.obfs_password,
            "up_mbps": node.up_mbps,
            "down_mbps": node.down_mbps,
        }
    else:
        identity = {
            "protocol": "vless",
            "uuid": getattr(node, "uuid", ""),
            "server_ip": node.server_ip,
            "server_port": node.server_port,
            "security": getattr(node, "security", ""),
            "sni": getattr(node, "sni", ""),
            "fp": getattr(node, "fp", ""),
            "pbk": getattr(node, "pbk", ""),
            "sid": getattr(node, "sid", ""),
            "type": getattr(node, "type", ""),
            "path": getattr(node, "path", ""),
            "host": getattr(node, "host", ""),
            "flow": getattr(node, "flow", ""),
            "alpn": getattr(node, "alpn", ""),
            "mode": getattr(node, "mode", ""),
        }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_node_identity(node: ProxyNode) -> str:
    identity = {
        "protocol": getattr(node, "protocol", "vless"),
        "server": f"{node.server_ip}:{node.server_port}",
        "sni": getattr(node, "sni", ""),
    }
    return json.dumps(identity, sort_keys=True, ensure_ascii=False)

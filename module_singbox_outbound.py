from models import ProxyNode, Hy2Node, SsNode
from module_shadowsocks import singbox_shadowsocks_outbound


def singbox_outbound(node: ProxyNode, tag: str) -> dict:
    if isinstance(node, SsNode):
        outbound = singbox_shadowsocks_outbound(node, tag)
    elif isinstance(node, Hy2Node) or getattr(node, "protocol", "vless") in {"hy2", "hysteria2"}:
        outbound = {
            "type": "hysteria2",
            "tag": tag,
            "server": node.server_ip,
            "server_port": node.server_port,
            "password": getattr(node, "password", ""),
            "tls": {
                "enabled": True,
                "insecure": getattr(node, "insecure", False),
            }
        }
        if getattr(node, "sni", ""):
            outbound["tls"]["server_name"] = node.sni
        if getattr(node, "obfs", ""):
            outbound["obfs"] = {
                "type": node.obfs,
                "password": getattr(node, "obfs_password", "")
            }
        if getattr(node, "up_mbps", None) is not None:
            outbound["up_mbps"] = node.up_mbps
        if getattr(node, "down_mbps", None) is not None:
            outbound["down_mbps"] = node.down_mbps
    else:
        outbound = {
            "type": "vless",
            "tag": tag,
            "server": node.server_ip,
            "server_port": node.server_port,
            "uuid": getattr(node, "uuid", ""),
        }

        if getattr(node, "flow", ""):
            outbound["flow"] = node.flow

        security = getattr(node, "security", "")
        if security in ["tls", "reality"]:
            tls_config = {
                "enabled": True,
                "insecure": False,
                "alpn": (
                    [item.strip() for item in node.alpn.split(",") if item.strip()]
                    if getattr(node, "alpn", "")
                    else ["h2", "http/1.1"]
                ),
            }
            if getattr(node, "sni", ""):
                tls_config["server_name"] = node.sni
            if getattr(node, "fp", ""):
                tls_config["utls"] = {
                    "enabled": True,
                    "fingerprint": node.fp,
                }
            if security == "reality":
                reality_config = {"enabled": True}
                if getattr(node, "pbk", ""):
                    reality_config["public_key"] = node.pbk
                if getattr(node, "sid", ""):
                    reality_config["short_id"] = node.sid
                tls_config["reality"] = reality_config
            outbound["tls"] = tls_config

        vless_type = getattr(node, "type", "tcp")
        if vless_type == "ws":
            transport = {"type": "ws"}
            if getattr(node, "path", ""):
                transport["path"] = node.path
            if getattr(node, "host", ""):
                transport["headers"] = {"Host": node.host}
            outbound["transport"] = transport
        elif vless_type == "grpc":
            transport = {"type": "grpc"}
            if getattr(node, "path", ""):
                transport["service_name"] = node.path
            outbound["transport"] = transport

    return outbound

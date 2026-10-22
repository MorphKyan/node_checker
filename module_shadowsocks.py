from models import SsNode


def singbox_shadowsocks_outbound(node: SsNode, tag: str) -> dict:
    outbound = {
        "type": "shadowsocks", "tag": tag,
        "server": node.server_ip, "server_port": node.server_port,
        "method": node.method, "password": node.password,
    }
    if node.plugin:
        outbound.update(plugin=node.plugin, plugin_opts=node.plugin_opts)
    return outbound


def xray_shadowsocks_outbound(node: SsNode, tag: str) -> dict:
    if node.plugin:
        raise ValueError("Shadowsocks SIP003 plugins require sing-box; Xray plugin configuration is unsupported")
    return {
        "protocol": "shadowsocks", "tag": tag,
        "settings": {"servers": [{
            "address": node.server_ip, "port": node.server_port,
            "method": node.method, "password": node.password,
        }]},
    }

import json
import os
import subprocess
import tempfile
import asyncio
from models import ProxyNode, Hy2Node, SsNode
from module_shadowsocks import xray_shadowsocks_outbound
from module_singbox_outbound import singbox_outbound
from settings import settings

class TunnelController:
    @staticmethod
    def generate_singbox_config(node: ProxyNode, local_port: int) -> str:
        outbound = singbox_outbound(node, "proxy-out")

        config = {
            "log": {"level": "fatal"},
            "inbounds": [{"type": "socks", "tag": "socks-in",
                          "listen": "127.0.0.1", "listen_port": local_port}],
            "outbounds": [outbound],
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="singbox_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        return path

    @staticmethod
    def generate_xray_config(node: ProxyNode, local_port: int) -> str:
        if isinstance(node, SsNode):
            outbound = xray_shadowsocks_outbound(node, "ss-out")
        elif isinstance(node, Hy2Node) or getattr(node, "protocol", "vless") in {"hy2", "hysteria2"}:
            if node.obfs or node.obfs_password or node.ports or node.up_mbps is not None or node.down_mbps is not None:
                raise ValueError("Xray Hysteria2 options are unsupported: obfs, ports, up/down bandwidth; use sing-box")
            outbound = {
                "protocol": "hysteria",
                "tag": "hy2-out",
                "settings": {
                    "address": node.server_ip,
                    "port": node.server_port,
                    "version": 2
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "tlsSettings": {
                        "allowInsecure": getattr(node, "insecure", False),
                        "serverName": getattr(node, "sni", "")
                    },
                    "hysteriaSettings": {
                        "version": 2,
                        "auth": getattr(node, "password", "")
                    }
                }
            }
        else:
            outbound = {
                "protocol": "vless",
                "tag": "vless-out",
                "settings": {
                    "vnext": [{
                        "address": node.server_ip,
                        "port": node.server_port,
                        "users": [{"id": getattr(node, "uuid", ""), "encryption": "none"}],
                    }],
                },
                "streamSettings": {"network": "tcp", "security": "none"},
            }

            # flow
            if getattr(node, "flow", ""):
                outbound["settings"]["vnext"][0]["users"][0]["flow"] = node.flow

            stream_settings = outbound["streamSettings"]

            # TLS / Reality
            security = getattr(node, "security", "")
            if security == "tls":
                stream_settings["security"] = "tls"
                stream_settings["tlsSettings"] = {
                    "serverName": getattr(node, "sni", ""),
                    "allowInsecure": False
                }
                if getattr(node, "fp", ""):
                    stream_settings["tlsSettings"]["fingerprint"] = node.fp
                if getattr(node, "alpn", ""):
                    alpn_list = [a.strip() for a in node.alpn.split(",") if a.strip()]
                    if alpn_list:
                        stream_settings["tlsSettings"]["alpn"] = alpn_list
            elif security == "reality":
                stream_settings["security"] = "reality"
                stream_settings["realitySettings"] = {
                    "show": False,
                    "serverName": getattr(node, "sni", ""),
                    "publicKey": getattr(node, "pbk", ""),
                    "shortId": getattr(node, "sid", "") or "",
                    "spiderX": ""
                }
                if getattr(node, "fp", ""):
                    stream_settings["realitySettings"]["fingerprint"] = node.fp

            # Transport type
            node_type = getattr(node, "type", "tcp")
            if node_type == "ws":
                stream_settings["network"] = "ws"
                stream_settings["wsSettings"] = {
                    "path": getattr(node, "path", "") or "/",
                    "headers": {
                        "Host": getattr(node, "host", "")
                    } if getattr(node, "host", "") else {}
                }
            elif node_type == "grpc":
                stream_settings["network"] = "grpc"
                stream_settings["grpcSettings"] = {
                    "serviceName": getattr(node, "path", "") or "",
                    "multiMode": False
                }
            elif node_type == "xhttp":
                stream_settings["network"] = "xhttp"
                stream_settings["xhttpSettings"] = {
                    "path": getattr(node, "path", "") or "/",
                    "host": getattr(node, "host", "") or "",
                    "mode": getattr(node, "mode", "") or "auto"
                }
            elif node_type != "tcp":
                raise ValueError(f"Unsupported Xray transport: {node_type}")

        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"protocol": "socks", "listen": "127.0.0.1",
                          "port": local_port, "settings": {"auth": "noauth", "udp": True}}],
            "outbounds": [outbound],
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        return path

    @staticmethod
    async def start_tunnel(node: ProxyNode, local_port: int):
        if settings.PROXY_CORE == "xray":
            config_path = TunnelController.generate_xray_config(node, local_port)
            executable, fallback, arguments = settings.XRAY_PATH, "xray", []
        else:
            config_path = TunnelController.generate_singbox_config(node, local_port)
            executable, fallback, arguments = settings.SING_BOX_PATH, "sing-box", ["run"]
        executable = os.path.join(os.getcwd(), executable)
        if not os.path.exists(executable):
            executable = fallback
        cmd = [executable, *arguments, "-c", config_path]

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(settings.TUNNEL_START_DELAY)
            return process, config_path
        except (Exception, asyncio.CancelledError):
            await TunnelController.stop_tunnel(process, config_path)
            raise

    @staticmethod
    async def stop_tunnel(process, config_path: str):
        if process:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
        if config_path and os.path.exists(config_path):
            try:
                os.remove(config_path)
            except Exception:
                pass

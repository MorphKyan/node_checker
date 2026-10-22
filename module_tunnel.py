import json
import os
import subprocess
import tempfile
import asyncio
from models import ProxyNode, Hy2Node, SsNode
from module_shadowsocks import singbox_shadowsocks_outbound, xray_shadowsocks_outbound
from settings import settings

class TunnelController:
    @staticmethod
    def generate_singbox_config(node: ProxyNode, local_port: int) -> str:
        if isinstance(node, SsNode):
            outbound = singbox_shadowsocks_outbound(node, "ss-out")
        elif isinstance(node, Hy2Node) or getattr(node, "protocol", "vless") in {"hy2", "hysteria2"}:
            outbound = {
                "type": "hysteria2",
                "tag": "hy2-out",
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
                "tag": "vless-out",
                "server": node.server_ip,
                "server_port": node.server_port,
                "uuid": getattr(node, "uuid", ""),
            }
            if getattr(node, "flow", ""):
                outbound["flow"] = node.flow
            
            # TLS / Reality
            security = getattr(node, "security", "")
            if security in ["tls", "reality"]:
                tls_config = {
                    "enabled": True,
                    "server_name": getattr(node, "sni", ""),
                    "insecure": False,
                    "utls": {
                        "enabled": bool(getattr(node, "fp", "")),
                        "fingerprint": getattr(node, "fp", "") or "chrome"
                    }
                }
                if security == "reality":
                    tls_config["reality"] = {
                        "enabled": True,
                        "public_key": getattr(node, "pbk", ""),
                        "short_id": getattr(node, "sid", "")
                    }
                outbound["tls"] = tls_config

            # Transport type
            node_type = getattr(node, "type", "tcp")
            if node_type == "ws":
                outbound["transport"] = {
                    "type": "ws",
                    "path": getattr(node, "path", ""),
                    "headers": {"Host": getattr(node, "host", "")} if getattr(node, "host", "") else {}
                }
            elif node_type == "grpc":
                outbound["transport"] = {
                    "type": "grpc",
                    "service_name": getattr(node, "path", "") or ""
                }

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
    def generate_config(node: ProxyNode, local_port: int) -> str:
        core_type = getattr(settings, "PROXY_CORE", "sing-box")
        if core_type == "xray":
            return TunnelController.generate_xray_config(node, local_port)
        else:
            return TunnelController.generate_singbox_config(node, local_port)

    @staticmethod
    async def start_tunnel(node: ProxyNode, local_port: int):
        config_path = TunnelController.generate_config(node, local_port)
        core_type = getattr(settings, "PROXY_CORE", "sing-box")
        
        if core_type == "xray":
            xray_exe = os.path.join(os.getcwd(), settings.XRAY_PATH)
            if not os.path.exists(xray_exe):
                xray_exe = "xray" # fallback to path
            cmd = [xray_exe, "-c", config_path]
        else:
            sing_box_exe = os.path.join(os.getcwd(), settings.SING_BOX_PATH)
            if not os.path.exists(sing_box_exe):
                sing_box_exe = "sing-box" # fallback to path
            cmd = [sing_box_exe, "run", "-c", config_path]
            
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(settings.TUNNEL_START_DELAY)
            return process, config_path
        except Exception as e:
            if os.path.exists(config_path):
                os.remove(config_path)
            raise e

    @staticmethod
    async def stop_tunnel(process, config_path: str):
        if process:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if config_path and os.path.exists(config_path):
            try:
                os.remove(config_path)
            except Exception:
                pass

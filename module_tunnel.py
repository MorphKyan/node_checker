import json
import os
import subprocess
import tempfile
import asyncio
from models import VlessNode
from settings import settings

class TunnelController:
    @staticmethod
    def generate_singbox_config(node: VlessNode, local_port: int) -> str:
        config = {
            "log": {"level": "fatal"},
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "127.0.0.1",
                    "listen_port": local_port
                }
            ],
            "outbounds": [
                {
                    "type": "vless",
                    "tag": "vless-out",
                    "server": node.server_ip,
                    "server_port": node.server_port,
                    "uuid": node.uuid,
                    "flow": node.flow if node.flow else ""
                }
            ]
        }
        
        # Remove empty flow to avoid sing-box schema error
        if not config["outbounds"][0]["flow"]:
            del config["outbounds"][0]["flow"]
        
        # TLS / Reality
        if node.security in ["tls", "reality"]:
            tls_config = {
                "enabled": True,
                "server_name": node.sni,
                "insecure": False,
                "utls": {
                    "enabled": bool(node.fp),
                    "fingerprint": node.fp or "chrome"
                }
            }
            if node.security == "reality":
                tls_config["reality"] = {
                    "enabled": True,
                    "public_key": node.pbk,
                    "short_id": node.sid
                }
            config["outbounds"][0]["tls"] = tls_config

        # Transport type
        if node.type == "ws":
            config["outbounds"][0]["transport"] = {
                "type": "ws",
                "path": node.path,
                "headers": {"Host": node.host} if node.host else {}
            }
        elif node.type == "grpc":
            config["outbounds"][0]["transport"] = {
                "type": "grpc",
                "service_name": node.path or ""
            }

        fd, path = tempfile.mkstemp(suffix=".json", prefix="singbox_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        return path

    @staticmethod
    def generate_xray_config(node: VlessNode, local_port: int) -> str:
        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "port": local_port,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {
                        "auth": "noauth",
                        "udp": True
                    }
                }
            ],
            "outbounds": [
                {
                    "protocol": "vless",
                    "tag": "vless-out",
                    "settings": {
                        "vnext": [
                            {
                                "address": node.server_ip,
                                "port": node.server_port,
                                "users": [
                                    {
                                        "id": node.uuid,
                                        "encryption": "none"
                                    }
                                ]
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "none"
                    }
                }
            ]
        }

        # flow
        if node.flow:
            config["outbounds"][0]["settings"]["vnext"][0]["users"][0]["flow"] = node.flow

        stream_settings = config["outbounds"][0]["streamSettings"]

        # TLS / Reality
        if node.security == "tls":
            stream_settings["security"] = "tls"
            stream_settings["tlsSettings"] = {
                "serverName": node.sni,
                "allowInsecure": False
            }
            if node.fp:
                stream_settings["tlsSettings"]["fingerprint"] = node.fp
            if node.alpn:
                alpn_list = [a.strip() for a in node.alpn.split(",") if a.strip()]
                if alpn_list:
                    stream_settings["tlsSettings"]["alpn"] = alpn_list
        elif node.security == "reality":
            stream_settings["security"] = "reality"
            stream_settings["realitySettings"] = {
                "show": False,
                "serverName": node.sni,
                "publicKey": node.pbk,
                "shortId": node.sid or "",
                "spiderX": ""
            }
            if node.fp:
                stream_settings["realitySettings"]["fingerprint"] = node.fp

        # Transport type
        if node.type == "ws":
            stream_settings["network"] = "ws"
            stream_settings["wsSettings"] = {
                "path": node.path or "/",
                "headers": {
                    "Host": node.host
                } if node.host else {}
            }
        elif node.type == "grpc":
            stream_settings["network"] = "grpc"
            stream_settings["grpcSettings"] = {
                "serviceName": node.path or "",
                "multiMode": False
            }
        elif node.type == "xhttp":
            stream_settings["network"] = "xhttp"
            stream_settings["xhttpSettings"] = {
                "path": node.path or "/",
                "host": node.host or "",
                "mode": getattr(node, "mode", "") or "auto"
            }

        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        return path

    @staticmethod
    def generate_config(node: VlessNode, local_port: int) -> str:
        core_type = getattr(settings, "PROXY_CORE", "sing-box")
        if core_type == "xray":
            return TunnelController.generate_xray_config(node, local_port)
        else:
            return TunnelController.generate_singbox_config(node, local_port)

    @staticmethod
    async def start_tunnel(node: VlessNode, local_port: int):
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

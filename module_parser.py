import base64
import urllib.parse
from models import VlessNode
import aiohttp
from settings import settings

GEO_MAP = {
    "hk": "HK", "香港": "HK", "hongkong": "HK",
    "tw": "TW", "台湾": "TW", "taiwan": "TW", "台北": "TW", "新北": "TW",
    "jp": "JP", "日本": "JP", "japan": "JP", "东京": "JP", "大阪": "JP",
    "sg": "SG", "新加坡": "SG", "singapore": "SG", "狮城": "SG",
    "us": "US", "美国": "US", "america": "US", "usa": "US", "洛杉矶": "US", "硅谷": "US",
    "kr": "KR", "韩国": "KR", "korea": "KR", "首尔": "KR",
    "uk": "GB", "英国": "GB", "united kingdom": "GB", "伦敦": "GB",
    "de": "DE", "德国": "DE", "germany": "DE", "法兰克福": "DE",
}

class VlessParser:
    @staticmethod
    def is_http_source(source: str) -> bool:
        scheme = urllib.parse.urlparse(source).scheme.lower()
        return scheme in {"http", "https"}

    @staticmethod
    async def fetch_subscription(url: str) -> str:
        timeout = aiohttp.ClientTimeout(total=settings.API_TIMEOUT)
        max_bytes = max(1, int(settings.SUBSCRIPTION_MAX_M)) * 1024 * 1024
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise ValueError(
                                f"Subscription response exceeds {max_bytes} bytes"
                            )
                    except ValueError as e:
                        if "exceeds" in str(e):
                            raise

                chunks = []
                downloaded_bytes = 0
                async for chunk in resp.content.iter_chunked(65536):
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > max_bytes:
                        raise ValueError(
                            f"Subscription response exceeds {max_bytes} bytes"
                        )
                    chunks.append(chunk)

                encoding = resp.charset or "utf-8"
                return b"".join(chunks).decode(encoding)

    @staticmethod
    def parse_nodes(raw_text: str) -> list[VlessNode]:
        raw_text = raw_text.strip()
        padding = 4 - (len(raw_text) % 4)
        if padding != 4:
            raw_text += "=" * padding
            
        try:
            decoded = base64.b64decode(raw_text).decode('utf-8')
        except Exception:
            decoded = raw_text

        nodes = []
        for line in decoded.splitlines():
            line = line.strip()
            if not line.startswith("vless://"):
                continue
            
            try:
                main_part, *remark_part = line.split('#', 1)
                remark = urllib.parse.unquote(remark_part[0]) if remark_part else ""
                
                uri_str = main_part[len("vless://"):]
                creds, server_port_params = uri_str.split('@', 1)
                uuid = creds
                
                if '?' in server_port_params:
                    server_port_str, params_str = server_port_params.split('?', 1)
                else:
                    server_port_str = server_port_params
                    params_str = ""
                    
                parsed_server = urllib.parse.urlsplit(f"//{server_port_str}")
                server_ip = parsed_server.hostname
                server_port = parsed_server.port
                if not server_ip or server_port is None:
                    raise ValueError("Missing server host or port")
                
                params = dict(urllib.parse.parse_qsl(params_str))
                transport_type = params.get("type", "tcp")
                transport_path = (
                    params.get("serviceName") or params.get("path", "")
                    if transport_type == "grpc"
                    else params.get("path", "")
                )
                
                expected_geo = "Unknown"
                remark_lower = remark.lower()
                for key, geo in GEO_MAP.items():
                    if key in remark_lower:
                        expected_geo = geo
                        break
                        
                nodes.append(VlessNode(
                    raw_uri=line,
                    uuid=uuid,
                    server_ip=server_ip,
                    server_port=server_port,
                    remark=remark,
                    expected_geo=expected_geo,
                    flow=params.get("flow", ""),
                    security=params.get("security", ""),
                    sni=params.get("sni", ""),
                    alpn=params.get("alpn", ""),
                    fp=params.get("fp", ""),
                    pbk=params.get("pbk", ""),
                    sid=params.get("sid", ""),
                    type=transport_type,
                    path=transport_path,
                    host=params.get("host", ""),
                    mode=params.get("mode", "")
                ))
            except Exception as e:
                print(f"[Parser] Failed to parse line: {line[:30]}... Error: {e}")
                
        return nodes

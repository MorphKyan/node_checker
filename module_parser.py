import base64
import urllib.parse
from models import ProxyNode, VlessNode, Hy2Node, SsNode
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

class NodeParser:
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
    def _match_geo(remark: str) -> str:
        remark_lower = remark.lower()
        for key, geo in GEO_MAP.items():
            if key in remark_lower:
                return geo
        return "Unknown"

    @staticmethod
    def parse_vless_line(line: str) -> VlessNode:
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
        
        expected_geo = NodeParser._match_geo(remark)
                
        return VlessNode(
            raw_uri=line,
            uuid=uuid,
            server_ip=server_ip,
            server_port=server_port,
            remark=remark,
            expected_geo=expected_geo,
            protocol="vless",
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
        )

    @staticmethod
    def parse_hy2_line(line: str) -> Hy2Node:
        main_part, *remark_part = line.split('#', 1)
        remark = urllib.parse.unquote(remark_part[0]) if remark_part else ""
        
        if main_part.startswith("hysteria2://"):
            uri_str = main_part[len("hysteria2://"):]
        else:
            uri_str = main_part[len("hy2://"):]

        creds, server_port_params = uri_str.split('@', 1)
        password = urllib.parse.unquote(creds)

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
        sni = params.get("sni") or params.get("peer") or ""
        insecure_raw = params.get("insecure") or params.get("allow_insecure") or params.get("allowInsecure") or "0"
        insecure = str(insecure_raw).lower() in {"1", "true", "yes"}
        obfs = params.get("obfs", "")
        obfs_password = params.get("obfs-password") or params.get("obfs_password") or ""
        
        up_val = params.get("up") or params.get("up_mbps")
        up_mbps = int(up_val) if up_val and str(up_val).isdigit() else None
        
        down_val = params.get("down") or params.get("down_mbps")
        down_mbps = int(down_val) if down_val and str(down_val).isdigit() else None

        expected_geo = NodeParser._match_geo(remark)

        return Hy2Node(
            raw_uri=line,
            password=password,
            server_ip=server_ip,
            server_port=server_port,
            remark=remark,
            expected_geo=expected_geo,
            protocol="hy2",
            sni=sni,
            insecure=insecure,
            obfs=obfs,
            obfs_password=obfs_password,
            up_mbps=up_mbps,
            down_mbps=down_mbps,
            ports=params.get("ports", "")
        )

    @staticmethod
    def parse_ss_line(line: str) -> SsNode:
        # SIP002 userinfo (Base64URL or percent-encoded) and legacy full Base64.
        main, _, fragment = line.partition('#')
        authority, _, query = main[len("ss://"):].partition('?')

        def decode_base64(value: str) -> str:
            value = urllib.parse.unquote(value)
            return base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            ).decode("utf-8")

        legacy = '@' not in authority
        if legacy:
            authority = decode_base64(authority)
        credentials, server = authority.rsplit('@', 1)
        if not legacy:
            if ':' in credentials:
                credentials = urllib.parse.unquote(credentials)
            else:
                credentials = decode_base64(credentials)
        method, password = credentials.split(':', 1)
        endpoint = urllib.parse.urlsplit(f"//{server}")
        if not method or not password or not endpoint.hostname or not endpoint.port:
            raise ValueError("Missing Shadowsocks credentials, host or port")
        params = dict(urllib.parse.parse_qsl(query))
        plugin, _, plugin_opts = params.get("plugin", "").partition(';')
        remark = urllib.parse.unquote(fragment)
        return SsNode(
            raw_uri=line, server_ip=endpoint.hostname, server_port=endpoint.port,
            remark=remark, expected_geo=NodeParser._match_geo(remark),
            method=method, password=password, plugin=plugin, plugin_opts=plugin_opts,
        )

    @staticmethod
    def parse_nodes(raw_text: str) -> list[ProxyNode]:
        raw_text = raw_text.strip()
        try:
            decoded = base64.b64decode(raw_text + "=" * (-len(raw_text) % 4), altchars=b"-_").decode('utf-8')
        except ValueError:
            decoded = raw_text

        parsers = {
            "ss": NodeParser.parse_ss_line,
            "vless": NodeParser.parse_vless_line,
            "hy2": NodeParser.parse_hy2_line,
            "hysteria2": NodeParser.parse_hy2_line,
        }
        nodes = []
        for line in decoded.splitlines():
            line = line.strip()
            scheme, _, _ = line.partition("://")
            parser = parsers.get(scheme)
            if parser is None:
                continue
            try:
                nodes.append(parser(line))
            except ValueError:
                print(f"[Parser] Failed to parse {scheme} line (invalid URI)")
                
        return nodes

VlessParser = NodeParser

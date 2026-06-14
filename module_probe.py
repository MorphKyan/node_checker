import asyncio
import ipaddress
import socket
import time
import urllib.parse
from aiohttp_socks import ProxyConnector
import aiohttp
from models import VlessNode, ProbeData
from settings import settings
import json
from module_profile import ProfileAdapters, NodeProfileAggregator

class LightweightProbe:
    _ip_cache = {}
    _ip_cache_lock = asyncio.Lock()

    @staticmethod
    async def tcp_ping(ip: str, port: int, times: int = None) -> float:
        if times is None: times = settings.PROBE_TEST_TIMES
        results = []
        for _ in range(times):
            start_time = time.perf_counter()
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=settings.TCP_PING_TIMEOUT
                )
                writer.close()
                await writer.wait_closed()
                results.append((time.perf_counter() - start_time) * 1000)
            except Exception:
                pass
        if not results:
            return 9999.0
        return sum(results) / len(results)

    @staticmethod
    async def fetch_ip_info(socks5_url: str) -> dict:
        connector = ProxyConnector.from_url(socks5_url, rdns=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(settings.IPWHOIS_API, timeout=settings.API_TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    async def resolve_probe_target_ip(host: str) -> str:
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            pass

        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            if family in {socket.AF_INET, socket.AF_INET6}:
                return str(sockaddr[0])
        return host

    @staticmethod
    def _ipwhois_url(ip: str) -> str:
        return urllib.parse.urljoin(settings.IPWHOIS_API.rstrip("/") + "/", ip)

    @staticmethod
    async def fetch_ipwhois_direct(ip: str) -> tuple[str, dict | None]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(LightweightProbe._ipwhois_url(ip), timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success") is True:
                            security = data.get("security", {})
                            info = []
                            if security.get("proxy"): info.append("Proxy")
                            if security.get("vpn"): info.append("VPN")
                            if security.get("tor"): info.append("Tor")
                            if security.get("hosting"): info.append("Hosting")
                            return ", ".join(info) if info else "Clean", data
                        return "Error", data
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception:
            return "Error", None

    @staticmethod
    async def fetch_ipapi(ip: str) -> tuple[str, dict | None]:
        if not settings.IPAPI_API:
            return "Not configured", None
        url = settings.IPAPI_API.format(ip=ip)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info = []
                        if data.get("is_proxy"): info.append("Proxy")
                        if data.get("is_vpn"): info.append("VPN")
                        if data.get("is_tor"): info.append("Tor")
                        if data.get("is_datacenter"): info.append("Datacenter")
                        if data.get("is_abuser"): info.append("Abuser")
                        company_type = data.get("company", {}).get("type", "")
                        if company_type: info.append(f"Type:{company_type}")
                        return ", ".join(info) if info else "Clean", data
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception as e:
            return "Error", None

    @staticmethod
    async def fetch_scamalytics(ip: str) -> tuple[str, dict | None]:
        if not settings.SCAMALYTICS_API:
            return "Not configured", None
        url = settings.SCAMALYTICS_API.format(ip=ip)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        try:
                            data = json.loads(text)
                            info = []
                            if "scamalytics" in data:
                                scam = data["scamalytics"]
                                score = scam.get("scamalytics_score", "N/A")
                                risk = scam.get("scamalytics_risk", "N/A")
                                info.append(f"Score: {score}")
                                info.append(f"Risk: {risk}")
                                
                                proxy = scam.get("scamalytics_proxy", {})
                                if proxy.get("is_vpn"): info.append("VPN")
                                if proxy.get("is_datacenter"): info.append("Datacenter")
                                if proxy.get("is_tor"): info.append("Tor")
                                if proxy.get("is_public_proxy"): info.append("Proxy")
                                if proxy.get("is_web_proxy"): info.append("WebProxy")
                            else:
                                # Fallback if structure is different
                                score = data.get("score", data.get("fraud_score", "N/A"))
                                risk = data.get("risk", "N/A")
                                info.append(f"Score: {score}")
                                info.append(f"Risk: {risk}")
                                
                            return ", ".join(info), data
                        except json.JSONDecodeError:
                            return text.strip()[:100], None
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception as e:
            return "Error", None

    @staticmethod
    def _format_api_url(template: str, ip: str, key: str = "") -> str:
        return template.format(ip=ip, key=key)

    @staticmethod
    async def fetch_proxycheck(ip: str) -> tuple[str, dict | None]:
        if not settings.PROXYCHECK_API:
            return "Not configured", None
        url = LightweightProbe._format_api_url(settings.PROXYCHECK_API, ip, settings.PROXYCHECK_KEY)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get(ip) if isinstance(data, dict) else None
                        detections = result.get("detections", {}) if isinstance(result, dict) else {}
                        info = []
                        if detections.get("proxy"): info.append("Proxy")
                        if detections.get("vpn"): info.append("VPN")
                        if detections.get("tor"): info.append("Tor")
                        if detections.get("hosting"): info.append("Hosting")
                        if detections.get("compromised"): info.append("Compromised")
                        if "risk" in detections: info.append(f"Risk:{detections.get('risk')}")
                        return ", ".join(info) if info else "Clean", data
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception:
            return "Error", None

    @staticmethod
    async def fetch_abstract(ip: str) -> tuple[str, dict | None]:
        if not settings.ABSTRACT_API_KEY:
            return "Not configured", None
        url = LightweightProbe._format_api_url(settings.ABSTRACT_IP_INTELLIGENCE_API, ip, settings.ABSTRACT_API_KEY)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        security = data.get("security", {}) if isinstance(data, dict) else {}
                        info = []
                        if security.get("is_proxy"): info.append("Proxy")
                        if security.get("is_vpn"): info.append("VPN")
                        if security.get("is_tor"): info.append("Tor")
                        if security.get("is_hosting"): info.append("Hosting")
                        if security.get("is_abuse"): info.append("Abuse")
                        return ", ".join(info) if info else "Clean", data
                    if resp.status == 429:
                        return "Rate limited", None
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception:
            return "Error", None

    @staticmethod
    async def fetch_ip2location(ip: str) -> tuple[str, dict | None]:
        if settings.IP2LOCATION_KEY:
            url = LightweightProbe._format_api_url(settings.IP2LOCATION_API, ip, settings.IP2LOCATION_KEY)
        else:
            url = f"https://api.ip2location.io/?ip={ip}&format=json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict) and data.get("error"):
                            return "Error", data
                        info = []
                        if data.get("is_proxy"): info.append("Proxy")
                        usage_type = data.get("usage_type")
                        if usage_type: info.append(f"Usage:{usage_type}")
                        proxy = data.get("proxy", {}) if isinstance(data.get("proxy"), dict) else {}
                        proxy_type = proxy.get("proxy_type") or data.get("proxy_type")
                        if proxy_type: info.append(f"ProxyType:{proxy_type}")
                        return ", ".join(info) if info else "Clean", data
                    return f"Error: {resp.status}", None
        except asyncio.TimeoutError:
            return "Timeout", None
        except Exception:
            return "Error", None

    @staticmethod
    async def test_ttfb(socks5_url: str, target_url: str, times: int = None) -> float:
        if times is None: times = settings.PROBE_TEST_TIMES
        results = []
        for _ in range(times):
            start_time = time.perf_counter()
            try:
                connector = ProxyConnector.from_url(socks5_url, rdns=True)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(target_url, timeout=settings.TTFB_TIMEOUT) as resp:
                        await resp.read()
                        results.append((time.perf_counter() - start_time) * 1000)
            except Exception:
                pass
        if not results:
            return 9999.0
        return sum(results) / len(results)

    @staticmethod
    async def detect_ipv6(socks5_url: str) -> tuple[bool, str]:
        # Try api6.ipify.org first
        try:
            connector = ProxyConnector.from_url(socks5_url, rdns=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("https://api6.ipify.org?format=json", timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ip = data.get("ip", "").strip()
                        if ip:
                            try:
                                ipaddress.ip_address(ip)
                                return True, ip
                            except ValueError:
                                pass
        except Exception:
            pass

        # Fallback to v6.ident.me
        try:
            connector = ProxyConnector.from_url(socks5_url, rdns=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("http://v6.ident.me", timeout=settings.API_TIMEOUT) as resp:
                    if resp.status == 200:
                        ip = (await resp.text()).strip()
                        if ip:
                            try:
                                ipaddress.ip_address(ip)
                                return True, ip
                            except ValueError:
                                pass
        except Exception:
            pass

        return False, ""

    @staticmethod
    async def trace_route(ip: str) -> tuple[str, bool, bool, str]:
        import re, ipaddress
        try:
            process = await asyncio.create_subprocess_exec(
                "tracert", "-d", "-h", "15", "-w", "500", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            try:
                text = stdout.decode('gbk')
            except:
                text = stdout.decode('utf-8', errors='ignore')
                
            ips = []
            for line in text.split('\n'):
                match = re.search(r'^\s*\d+\s+.*?\s+(\d{1,3}(?:\.\d{1,3}){3})', line)
                if match:
                    ips.append(match.group(1))
                    
            if not ips:
                return ("No trace path", False, False, "")
                
            public_ips = []
            for h_ip in ips:
                try:
                    parsed_ip = ipaddress.ip_address(h_ip)
                    if not parsed_ip.is_private and not parsed_ip.is_loopback:
                        public_ips.append(h_ip)
                except:
                    pass
                    
            if not public_ips:
                return ("Only private IPs", False, False, "")
                
            geo_data = []
            ips_to_query = []
            
            async with LightweightProbe._ip_cache_lock:
                for p_ip in public_ips:
                    if p_ip in LightweightProbe._ip_cache:
                        geo_data.append(LightweightProbe._ip_cache[p_ip])
                    else:
                        ips_to_query.append(p_ip)
                        geo_data.append(None) # placeholder
                        
            if ips_to_query:
                # Group queries into batches of up to 100
                for i in range(0, len(ips_to_query), 100):
                    batch_ips = ips_to_query[i:i+100]
                    batch_req = [{"query": p_ip, "fields": "country,countryCode,city,isp,org,as"} for p_ip in batch_ips]
                    
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.post("http://ip-api.com/batch", json=batch_req, timeout=10) as resp:
                                if resp.status == 200:
                                    batch_resp = await resp.json()
                                    async with LightweightProbe._ip_cache_lock:
                                        for k, p_ip in enumerate(batch_ips):
                                            LightweightProbe._ip_cache[p_ip] = batch_resp[k]
                                            # Replace placeholder
                                            for j, g in enumerate(geo_data):
                                                if g is None and public_ips[j] == p_ip:
                                                    geo_data[j] = batch_resp[k]
                    except:
                        pass
                        
            # In case some queries failed, clean up placeholders
            geo_data = [g if g is not None else {"status": "fail"} for g in geo_data]
                        
            path_str_parts = []
            countries = []
            is_backbone = False
            backbone_info_parts = []
            
            backbone_map = {
                "AS4809": "CN2", "AS9929": "CU9929", "AS58453": "CMI",
                "AS4134": "CT163", "AS4837": "CU169", "AS9808": "CMNET",
                "AS2914": "NTT", "AS6453": "Tata", "AS3356": "Level3",
                "AS1299": "Arelion", "AS174": "Cogent", "AS3257": "GTT",
                "AS6939": "HE", "AS4637": "Telstra", "AS3491": "PCCW"
            }
            
            target_country = geo_data[-1].get("countryCode", "") if geo_data else ""
            local_country = "CN"
            is_detour = False
            
            for i, data in enumerate(geo_data):
                ip = public_ips[i]
                if data.get("status") == "fail":
                    path_str_parts.append(f"{ip}(Unknown)")
                    continue
                    
                cc = data.get("countryCode", "")
                asn_str = data.get("as", "")
                asn_match = re.search(r'(AS\d+)', asn_str)
                asn = asn_match.group(1) if asn_match else ""
                
                if asn in backbone_map:
                    is_backbone = True
                    bb_name = backbone_map[asn]
                    if bb_name not in backbone_info_parts:
                        backbone_info_parts.append(bb_name)
                        
                if cc and cc != "Unknown":
                    if cc not in countries:
                        countries.append(cc)
                    if i < len(geo_data) - 1:
                        if cc != local_country and cc != target_country:
                            is_detour = True
                            
                path_str_parts.append(f"{ip}({cc}, {asn})")
                
            return (" -> ".join(path_str_parts), is_detour, is_backbone, ", ".join(backbone_info_parts))
        except Exception as e:
            return (f"Trace failed: {str(e)}", False, False, "")

    @staticmethod
    async def run_probe(node: VlessNode, socks5_url: str) -> ProbeData:
        tcp_ping_task = asyncio.create_task(LightweightProbe.tcp_ping(node.server_ip, node.server_port))
        trace_task = asyncio.create_task(LightweightProbe.trace_route(node.server_ip))
        ipv6_task = asyncio.create_task(LightweightProbe.detect_ipv6(socks5_url))
        
        ttfb_ms = 9999.0
        actual_ip = ""
        actual_geo = "Unknown"
        asn_org = ""
        fraud_score = 0
        risk_tags = ""
        
        try:
            ttfb_ms = await LightweightProbe.test_ttfb(socks5_url, settings.TTFB_TARGET_URL)
        except Exception as e:
            print(f"[{node.remark}] TTFB Error: {repr(e)}")
            pass
            
        ipwhois_info = ""
        ipapi_info = ""
        scamalytics_info = ""
        proxycheck_info = ""
        abstract_info = ""
        ip2location_info = ""
        ipwhois_data = None
        ipapi_data = None
        scamalytics_data = None
        proxycheck_data = None
        abstract_data = None
        ip2location_data = None

        try:
            ip_info = await LightweightProbe.fetch_ip_info(socks5_url)
            if ip_info.get("success") == True:
                ipwhois_data = ip_info
                actual_ip = ip_info.get("ip", "")
                actual_geo = ip_info.get("country_code", "Unknown")
                connection = ip_info.get("connection", {})
                asn_org = connection.get("org", "")
                
                security = ip_info.get("security", {})
                tags = []
                if security.get("proxy"): 
                    fraud_score += 30
                    tags.append("Proxy")
                if security.get("vpn"): 
                    fraud_score += 30
                    tags.append("VPN")
                if security.get("tor"): 
                    fraud_score += 50
                    tags.append("Tor")
                if security.get("hosting"): 
                    fraud_score += 20
                    tags.append("Hosting")
                risk_tags = ", ".join(tags) if tags else "Clean"
                ipwhois_info = risk_tags
                
                # If we got actual IP, query the other APIs
        except asyncio.TimeoutError:
            print(f"[{node.remark}] IPWhoIs Error: Timeout")
            ipwhois_info = "Timeout"
        except Exception as e:
            print(f"[{node.remark}] IPWhoIs Error: {repr(e)}")
            ipwhois_info = "Error"

        if not actual_ip:
            try:
                actual_ip = await LightweightProbe.resolve_probe_target_ip(node.server_ip)
                ipwhois_info, ipwhois_data = await LightweightProbe.fetch_ipwhois_direct(actual_ip)
                if ipwhois_data and ipwhois_data.get("success") is True:
                    actual_geo = ipwhois_data.get("country_code", "Unknown")
                    connection = ipwhois_data.get("connection", {})
                    asn_org = connection.get("org", "")
            except Exception as e:
                print(f"[{node.remark}] Direct IP intelligence fallback failed: {repr(e)}")

        if actual_ip:
            ipapi_task = asyncio.create_task(LightweightProbe.fetch_ipapi(actual_ip))
            scam_task = asyncio.create_task(LightweightProbe.fetch_scamalytics(actual_ip))
            proxycheck_task = asyncio.create_task(LightweightProbe.fetch_proxycheck(actual_ip))
            abstract_task = asyncio.create_task(LightweightProbe.fetch_abstract(actual_ip))
            ip2location_task = asyncio.create_task(LightweightProbe.fetch_ip2location(actual_ip))

            ipapi_info, ipapi_data = await ipapi_task
            scamalytics_info, scamalytics_data = await scam_task
            proxycheck_info, proxycheck_data = await proxycheck_task
            abstract_info, abstract_data = await abstract_task
            ip2location_info, ip2location_data = await ip2location_task

        tcp_ping_ms = await tcp_ping_task
        
        trace_path, is_detour, is_backbone, backbone_info = await trace_task
        ipv6_support, actual_ipv6 = await ipv6_task
        profile = NodeProfileAggregator.aggregate([
            ProfileAdapters.from_ipwhois(ipwhois_data),
            ProfileAdapters.from_ipapi(ipapi_data),
            ProfileAdapters.from_scamalytics(scamalytics_data),
            ProfileAdapters.from_proxycheck(proxycheck_data, actual_ip),
            ProfileAdapters.from_abstract(abstract_data),
            ProfileAdapters.from_ip2location(ip2location_data),
        ], source_weights={
            "proxycheck.io": 1.3,
            "Abstract API": 0.8,
            "IP2Location.io": 0.6,
        })
        fraud_score = max(fraud_score, int(round(profile.risk_score)))
        
        return ProbeData(
            tcp_ping_ms=tcp_ping_ms,
            ttfb_ms=ttfb_ms,
            actual_ip=actual_ip,
            actual_geo=actual_geo,
            asn_org=asn_org,
            fraud_score=fraud_score,
            risk_tags=risk_tags,
            ipwhois_info=ipwhois_info,
            ipapi_info=ipapi_info,
            scamalytics_info=scamalytics_info,
            proxycheck_info=proxycheck_info,
            abstract_info=abstract_info,
            ip2location_info=ip2location_info,
            trace_path=trace_path,
            is_detour=is_detour,
            is_backbone=is_backbone,
            backbone_info=backbone_info,
            profile=profile,
            ipv6_support=ipv6_support,
            actual_ipv6=actual_ipv6
        )

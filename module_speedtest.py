import asyncio
import time
from httpx_socks import AsyncProxyTransport
import httpx
from models import AnalyzedNode, TestedNode
from settings import settings

class BandwidthTester:
    @staticmethod
    async def run_speed_test(analyzed_node: AnalyzedNode, socks5_url: str, *, precise: bool = False) -> TestedNode:
        download_speed_mbps = 0.0
        transport = AsyncProxyTransport.from_url(socks5_url)
        elapsed = 0.0
        downloaded_bytes = 0
        max_bytes = 100_000_000 if precise else max(1, int(settings.SPEEDTEST_MAX_M)) * 1024 * 1024
        url = "https://speed.cloudflare.com/__down?bytes=100000000" if precise else settings.SPEEDTEST_URL
        
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            headers["Accept-Encoding"] = "identity"
            # Disable http2 as it often causes RemoteProtocolError with some proxies/CDNs
            async with httpx.AsyncClient(transport=transport, headers=headers, http2=False, follow_redirects=True) as client:
                async with client.stream("GET", url, timeout=settings.SPEEDTEST_TIMEOUT) as resp:
                    resp.raise_for_status()
                    # Measure body transfer only, excluding connection setup and cleanup.
                    start_time = time.perf_counter()
                    try:
                        async with asyncio.timeout(settings.SPEEDTEST_TIMEOUT):
                            async for chunk in resp.aiter_raw():
                                downloaded_bytes += min(len(chunk), max(0, max_bytes - downloaded_bytes))
                                if downloaded_bytes >= max_bytes:
                                    break
                    except (httpx.ReadTimeout, asyncio.TimeoutError, httpx.RemoteProtocolError):
                        pass
                    finally:
                        elapsed = time.perf_counter() - start_time
                        
        except Exception as e:
            # Only print error if we didn't download anything significant
            if downloaded_bytes < 1024 * 100:
                print(f"[SpeedTest Error] {analyzed_node.node.remark}: {repr(e)}")
            
        if elapsed > 0:
            download_speed_mbps = (downloaded_bytes * 8) / 1_000_000 / elapsed

        return TestedNode(analyzed_node, download_speed_mbps if downloaded_bytes else None, "success" if downloaded_bytes else "failed")

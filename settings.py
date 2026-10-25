import os
from pathlib import Path

from console_encoding import configure_standard_streams

configure_standard_streams()

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # 代理内核路径
    SING_BOX_PATH = os.getenv("SING_BOX_PATH", "sing-box.exe")
    XRAY_PATH = os.getenv("XRAY_PATH", "xray.exe")
    PROXY_CORE = os.getenv("PROXY_CORE", "sing-box")

    # 并发与超时控制
    FILTER_CONCURRENCY = 10
    SPEEDTEST_CONCURRENCY = 2
    
    PROBE_TEST_TIMES = 3  # TCP ping次数；HTTP验活成功即停，最多尝试两次
    
    TUNNEL_START_DELAY = 1.5  # 启动代理内核后的等待时间(秒)

    TCP_PING_TIMEOUT = 3.0
    TTFB_TIMEOUT = 5.0
    API_TIMEOUT = 3.0
    ROUTE_TIMEOUT = 20.0
    ROUTE_MAX_HOPS = 30
    ROUTE_HOP_TIMEOUT = 0.5
    SPEEDTEST_TIMEOUT = 10.0
    SUBSCRIPTION_MAX_M = 2
    SPEEDTEST_MAX_M = 10

    # 测试目标 URLs
    TTFB_TARGET_URL = "http://www.gstatic.com/generate_204"
    SPEEDTEST_URL = "https://dl.google.com/android/repository/platform-tools_r35.0.0-windows.zip" # ~6MB

    # 本地探测结果缓存
    CACHE_ENABLED = True
    PROBE_CACHE_TTL_SECONDS = 24 * 60 * 60
    CACHE_FAILURE_RESULTS = False

    # 增强订阅导出
    SUBSCRIPTION_EXPORT_ENABLED = True
    SUBSCRIPTION_EXPORT_DIR = "result/subscriptions"
    SUBSCRIPTION_EXPORT_VALID_ONLY = True
    SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH = 64
    SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH = 96

    # 本地 API 服务
    DATA_DIR = os.getenv("DATA_DIR", str(BASE_DIR / "data"))
    API_DEFAULT_SPEEDTEST_LIMIT = 0

settings = Config()

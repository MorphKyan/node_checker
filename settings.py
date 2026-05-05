import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # 代理内核路径
    SING_BOX_PATH = os.getenv("SING_BOX_PATH", "sing-box.exe")

    # 并发与超时控制
    FILTER_CONCURRENCY = 10
    SPEEDTEST_CONCURRENCY = 2
    
    PROBE_TEST_TIMES = 3  # ping和TTFB测试次数
    
    TUNNEL_START_DELAY = 1.5  # 启动代理内核后的等待时间(秒)
    TUNNEL_LOCAL_PORT_START = 10000

    TCP_PING_TIMEOUT = 3.0
    TTFB_TIMEOUT = 5.0
    API_TIMEOUT = 5.0
    SPEEDTEST_TIMEOUT = 10.0
    SUBSCRIPTION_MAX_BYTES = 2 * 1024 * 1024
    SPEEDTEST_MAX_BYTES = 8 * 1024 * 1024

    # 测试目标 URLs
    TTFB_TARGET_URL = "http://www.gstatic.com/generate_204"
    IPWHOIS_API = "http://ipwho.is/"
    IPAPI_KEY = os.getenv("IPAPI_KEY", "")
    IPAPI_API = os.getenv(
        "IPAPI_API",
        f"https://api.ipapi.is?q={{ip}}{'&key=' + IPAPI_KEY if IPAPI_KEY else ''}",
    )
    SCAMALYTICS_API = os.getenv("SCAMALYTICS_API", "")
    PROXYCHECK_KEY = os.getenv("PROXYCHECK_KEY", "")
    PROXYCHECK_API = os.getenv(
        "PROXYCHECK_API",
        "https://proxycheck.io/v3/{ip}" + ("?key={key}" if PROXYCHECK_KEY else ""),
    )
    ABSTRACT_API_KEY = os.getenv("ABSTRACT_API_KEY", "")
    ABSTRACT_IP_INTELLIGENCE_API = os.getenv(
        "ABSTRACT_IP_INTELLIGENCE_API",
        "https://ip-intelligence.abstractapi.com/v1/?api_key={key}&ip_address={ip}",
    )
    IP2LOCATION_KEY = os.getenv("IP2LOCATION_KEY", "")
    IP2LOCATION_API = os.getenv(
        "IP2LOCATION_API",
        "https://api.ip2location.io/?key={key}&ip={ip}&format=json",
    )
    SPEEDTEST_URL = "https://dl.google.com/android/repository/platform-tools_r35.0.0-windows.zip" # ~6MB

    # 评分规则阈值
    FRAUD_SCORE_TOLERANCE = 75
    MIN_TOTAL_SCORE = 50.0

    # 本地探测结果缓存
    CACHE_ENABLED = True
    CACHE_DB_PATH = "cache/probe_cache.sqlite3"
    PROBE_CACHE_TTL_SECONDS = 24 * 60 * 60
    CACHE_FAILURE_RESULTS = False

    # 增强订阅导出
    SUBSCRIPTION_EXPORT_ENABLED = True
    SUBSCRIPTION_EXPORT_DIR = "result/subscriptions"
    SUBSCRIPTION_EXPORT_VALID_ONLY = True
    SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH = 64
    SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH = 96

    # 本地 API 服务
    API_DB_PATH = "data/api.sqlite3"
    API_HOST = "127.0.0.1"
    API_PORT = 8000
    API_DEFAULT_SPEEDTEST_LIMIT = 3
    RUNTIME_SETTINGS_PATH = "data/runtime_settings.json"

    @classmethod
    def load_from_file(cls, filepath="config.json"):
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if hasattr(cls, k):
                        setattr(cls, k, v)

settings = Config()

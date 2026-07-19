import json
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
    
    PROBE_TEST_TIMES = 3  # ping和TTFB测试次数
    
    TUNNEL_START_DELAY = 1.5  # 启动代理内核后的等待时间(秒)
    TUNNEL_LOCAL_PORT_START = 10000

    TCP_PING_TIMEOUT = 3.0
    TTFB_TIMEOUT = 5.0
    API_TIMEOUT = 5.0
    SPEEDTEST_TIMEOUT = 10.0
    SUBSCRIPTION_MAX_M = 2
    SPEEDTEST_MAX_M = 8

    # 测试目标 URLs
    TTFB_TARGET_URL = "http://www.gstatic.com/generate_204"
    SPEEDTEST_URL = "https://dl.google.com/android/repository/platform-tools_r35.0.0-windows.zip" # ~6MB

    # 评分规则阈值
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
    API_HOST = "127.0.0.1"
    API_PORT = 8000
    API_DEFAULT_SPEEDTEST_LIMIT = 0

    @classmethod
    def load_from_file(cls, filepath="config.json"):
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if hasattr(cls, k):
                        setattr(cls, k, v)

settings = Config()

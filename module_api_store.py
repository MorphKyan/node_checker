import os
import sqlite3
import threading
import time
import uuid

from models import TestedNode
from module_result_codec import tested_nodes_from_json, tested_nodes_to_json
from settings import settings


class ApiStore:
    _write_lock = threading.Lock()
    _initialized_paths: set[str] = set()

    @staticmethod
    def now() -> int:
        return int(time.time())

    @staticmethod
    def new_subscription_id() -> str:
        return f"sub_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_job_id() -> str:
        return f"job_{uuid.uuid4().hex[:12]}"

    @classmethod
    def db_path(cls) -> str:
        return settings.API_DB_PATH

    @classmethod
    def default_singbox_template(cls) -> str:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "examples",
            "singbox_template.yaml",
        )
        with open(template_path, "r", encoding="utf-8") as template_file:
            return template_file.read()

    @classmethod
    def connect(cls):
        conn = sqlite3.connect(cls.db_path(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @classmethod
    def init_db(cls) -> None:
        db_path = cls.db_path()
        if db_path in cls._initialized_paths:
            return

        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with cls._write_lock:
            if db_path in cls._initialized_paths:
                return
            conn = cls.connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        last_status TEXT NOT NULL DEFAULT 'new',
                        last_job_id TEXT
                    );

                    CREATE TABLE IF NOT EXISTS refresh_jobs (
                        id TEXT PRIMARY KEY,
                        subscription_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        phase TEXT NOT NULL DEFAULT 'queued',
                        processed_nodes INTEGER NOT NULL DEFAULT 0,
                        total_nodes INTEGER NOT NULL DEFAULT 0,
                        error TEXT,
                        speedtest_limit INTEGER NOT NULL,
                        force_probe INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        started_at INTEGER,
                        finished_at INTEGER,
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
                    );

                    CREATE TABLE IF NOT EXISTS subscription_results (
                        subscription_id TEXT PRIMARY KEY,
                        result_json TEXT NOT NULL,
                        node_count INTEGER NOT NULL,
                        valid_count INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
                    );

                    CREATE TABLE IF NOT EXISTS singbox_templates (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    """
                )
                conn.commit()

                # Pre-populate with default template if table is empty
                count = conn.execute("SELECT count(*) FROM singbox_templates").fetchone()[0]
                if count == 0:
                    tpl_id = f"tpl_{uuid.uuid4().hex[:12]}"
                    default_content = """{
  "experimental": {
    "cache_file": {
      "enabled": true,
      "path": "/etc/sing-box/cache.db",
      "store_fakeip": true
    }
  },
  // 出站
  "outbounds": [
    // 手动选择国家或地区节点；根据“国家或地区出站”的名称对 `outbounds` 值进行增删改，须一一对应
    { "tag": "🚀 节点选择", "type": "selector", "outbounds": [ "♻️ 自动选择", "👉 手动选择", "🇭🇰 香港节点", "🇹🇼 台湾节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点", "🇺🇸 美国节点", "🇺🇸 加州节点" ] },
    // 选择`🎯 全球直连`为测试本地网络（运营商网络速度和 IPv6 支持情况），可选择其它节点用于测试机场节点速度和 IPv6 支持情况
    { "tag": "📈 网络测试", "type": "selector", "outbounds": [ "🎯 全球直连", "🚀 节点选择", "🇭🇰 香港节点", "🇹🇼 台湾节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点", "🇺🇸 美国节点", "🇺🇸 加州节点" ] },
    { "tag": "🕹️ 游戏平台", "type": "selector", "outbounds": [ "🎯 全球直连", "🚀 节点选择" ] },
    { "tag": "🤖 AI 平台", "type": "selector", "outbounds": [ "🇺🇸 加州节点" ] },
    { "tag": "🌍 国外媒体", "type": "selector", "outbounds": [ "🚀 节点选择", "🇭🇰 香港节点", "🇹🇼 台湾节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点", "🇺🇸 美国节点" ] },
    { "tag": "🌎 国外域名", "type": "selector", "outbounds": [ "🚀 节点选择", "🇭🇰 香港节点", "🇹🇼 台湾节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点", "🇺🇸 美国节点" ] },
    { "tag": "📲 电报消息", "type": "selector", "outbounds": [ "🚀 节点选择", "🇭🇰 香港节点", "🇹🇼 台湾节点", "🇯🇵 日本节点", "🇸🇬 新加坡节点", "🇺🇸 美国节点" ] },
    { "tag": "🐟 漏网之鱼", "type": "selector", "outbounds": [ "🎯 全球直连", "🚀 节点选择", "👉 手动选择" ] },
    { "tag": "🎯 全球直连", "type": "selector", "outbounds": [ "DIRECT" ] },
    { "tag": "DIRECT", "type": "direct" },
    { "tag": "GLOBAL", "type": "selector", "outbounds": [ "🚀 节点选择", "DIRECT" ] },
    
    // -------------------- 国家或地区出站 --------------------
    // 自动选择节点，即按照 url 测试结果使用延迟最低的节点；测试后容差大于 50ms 才会切换到延迟低的那个节点；筛选出“香港”节点，支持正则表达式
    { "tag": "🇭🇰 香港节点", "type": "urltest", "include": "(?i)(🇭🇰|港|hk|hongkong|hong kong)" },
    // 节点自动回退，默认选择第一个节点，节点超时后则会按代理顺序选择下一个可用节点，以此类推。也被叫做“故障转移”
    { "tag": "🇹🇼 台湾节点", "type": "urltest", "use_all_nodes": true, "include": "(?i)(🇹🇼|台|tw|taiwan|tai wan)" },
    // 节点负载均衡，即将请求均匀分配到多个节点上，优点是更稳定，速度可能有提升；将相同的目标地址请求分配给该出站内的同一个节点；推荐在节点复用比较多的情况下使用
    { "tag": "🇯🇵 日本节点", "type": "urltest", "include": "(?i)(🇯🇵|日|jp|japan)" },
    // 可使用 `"use_all_nodes": true` 代替，意思为引入所有出站节点
    { "tag": "🇸🇬 新加坡节点", "type": "urltest", "use_all_nodes": true, "include": "(?i)(🇸🇬|新|sg|singapore)" },
    { "tag": "🇺🇸 美国节点", "type": "urltest", "tolerance": 100, "include": "(?i)(🇺🇸|美|us|unitedstates|united states)" },
    { "tag": "🇺🇸 加州节点", "type": "selector", "include": "(?i)(加州|加利福尼亚|California|CA)" },
    { "tag": "♻️ 自动选择", "type": "urltest", "tolerance": 100, "use_all_nodes": true },
    { "tag": "👉 手动选择", "type": "selector", "use_all_nodes": true }
  ],
  // 路由
  "route": {
    // 域名解析器，必须在 `dns.servers` 配置有 `dns_direct`
    "default_domain_resolver": "dns_direct",
    // 规则
    "rules": [
      // 若使用 ShellCrash，可进入 7 → 4 启用域名嗅探后删除此条 `action`
      { "action": "sniff" },
      // 若使用 ShellCrash，可进入 7 → 4 启用域名嗅探后删除此条 `action`
      { "protocol": [ "dns" ], "action": "hijack-dns" },
      // 若使用 ShellCrash，会自动覆写此条，可删除此条 `clash_mode`
      { "clash_mode": "direct", "outbound": "DIRECT" },
      // 若使用 ShellCrash，会自动覆写此条，可删除此条 `clash_mode`
      { "clash_mode": "global", "outbound": "GLOBAL" },
      // 自定义规则优先放前面
      { "rule_set": [ "private" ], "outbound": "🎯 全球直连" },
      { "rule_set": [ "ads" ], "action": "reject" },
      { "rule_set": [ "games" ], "outbound": "🕹️ 游戏平台" },
      { "rule_set": [ "media" ], "outbound": "🌍 国外媒体" },
      { "rule_set": [ "ai" ], "outbound": "🤖 AI 平台" },
      { "rule_set": [ "networktest" ], "outbound": "📈 网络测试" },
      { "rule_set": [ "tld-proxy" ], "outbound": "🌎 国外域名" },
      { "rule_set": [ "gfw" ], "outbound": "🌎 国外域名" },
      { "rule_set": [ "telegramip" ], "outbound": "📲 电报消息" },
      // 将目标域名解析成 IP 后与下方的 IP 规则进行匹配，提高兼容性
      { "action": "resolve" },
      { "rule_set": [ "mediaip" ], "outbound": "🌍 国外媒体" }
    ],
    // 规则集（binary 文件每天自动更新）
    "rule_set": [
      {
        "tag": "ads",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/ads.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "private",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/private.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "games",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/games.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "media",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/media.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "ai",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/ai.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "networktest",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/networktest.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "tld-proxy",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/tld-proxy.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "gfw",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/gfw.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "telegramip",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/telegramip.srs",
        "download_detour": "DIRECT"
      },
      {
        "tag": "mediaip",
        "type": "remote",
        "format": "binary",
        "url": "https://ghproxy.net/https://github.com/DustinWin/ruleset_geodata/releases/download/sing-box-ruleset-compatible/mediaip.srs",
        "download_detour": "DIRECT"
      }
    ],
    // 默认出站，即没有命中规则的域名或 IP 走该规则
    "final": "🐟 漏网之鱼",
    "auto_detect_interface": true
  }
}"""
                    default_content = cls.default_singbox_template()
                    conn.execute(
                        """
                        INSERT INTO singbox_templates (
                            id, name, content, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (tpl_id, "默认模板", default_content, cls.now(), cls.now()),
                    )
                    conn.commit()
                cls._initialized_paths.add(db_path)
            finally:
                conn.close()

    @classmethod
    def create_subscription(cls, url: str, name: str | None = None) -> dict:
        cls.init_db()
        sub_id = cls.new_subscription_id()
        now = cls.now()
        final_name = name or sub_id
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO subscriptions (
                        id, name, url, created_at, updated_at, last_status, last_job_id
                    ) VALUES (?, ?, ?, ?, ?, 'new', NULL)
                    """,
                    (sub_id, final_name, url, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return cls.get_subscription(sub_id)

    @classmethod
    def get_subscription(cls, subscription_id: str) -> dict | None:
        cls.init_db()
        conn = cls.connect()
        try:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def update_subscription(
        cls,
        subscription_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
    ) -> dict | None:
        cls.init_db()
        existing = cls.get_subscription(subscription_id)
        if not existing:
            return None
        url_changed = url is not None and url != existing["url"]
        updates = []
        values = []
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if url is not None:
            updates.append("url = ?")
            values.append(url)
        if not updates:
            return cls.get_subscription(subscription_id)

        now = cls.now()
        if url_changed:
            updates.append("last_status = 'new'")
            updates.append("last_job_id = NULL")
        updates.append("updated_at = ?")
        values.append(now)
        values.append(subscription_id)
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    f"UPDATE subscriptions SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                if url_changed:
                    conn.execute(
                        "DELETE FROM subscription_results WHERE subscription_id = ?",
                        (subscription_id,),
                    )
                    conn.execute(
                        """
                        UPDATE refresh_jobs
                        SET status = 'failed',
                            phase = 'failed',
                            error = ?,
                            finished_at = ?
                        WHERE subscription_id = ?
                          AND status IN ('queued', 'running')
                        """,
                        (
                            "Subscription URL changed before refresh completed",
                            now,
                            subscription_id,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
        return cls.get_subscription(subscription_id)

    @classmethod
    def fail_stale_active_jobs(cls, reason: str) -> int:
        cls.init_db()
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, subscription_id
                    FROM refresh_jobs
                    WHERE status IN ('queued', 'running')
                    """
                ).fetchall()
                if not rows:
                    return 0

                conn.execute(
                    """
                    UPDATE refresh_jobs
                    SET status = 'failed',
                        phase = 'failed',
                        error = ?,
                        finished_at = ?
                    WHERE status IN ('queued', 'running')
                    """,
                    (reason, now),
                )
                for row in rows:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET last_status = 'failed', updated_at = ?
                        WHERE id = ? AND last_job_id = ?
                        """,
                        (now, row["subscription_id"], row["id"]),
                    )
                conn.commit()
                return len(rows)
            finally:
                conn.close()

    @classmethod
    def delete_subscription(cls, subscription_id: str) -> bool:
        cls.init_db()
        with cls._write_lock:
            conn = cls.connect()
            try:
                existing = conn.execute(
                    "SELECT id FROM subscriptions WHERE id = ?",
                    (subscription_id,),
                ).fetchone()
                if not existing:
                    return False
                conn.execute(
                    "DELETE FROM subscription_results WHERE subscription_id = ?",
                    (subscription_id,),
                )
                conn.execute(
                    "DELETE FROM refresh_jobs WHERE subscription_id = ?",
                    (subscription_id,),
                )
                conn.execute(
                    "DELETE FROM subscriptions WHERE id = ?",
                    (subscription_id,),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    @classmethod
    def list_subscriptions(cls) -> list[dict]:
        cls.init_db()
        conn = cls.connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    s.id, s.name, s.url, s.last_status, s.updated_at, s.last_job_id,
                    COALESCE(r.node_count, 0) AS node_count,
                    COALESCE(r.valid_count, 0) AS valid_count
                FROM subscriptions s
                LEFT JOIN subscription_results r ON r.subscription_id = s.id
                ORDER BY s.created_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @classmethod
    def find_active_job(cls, subscription_id: str) -> dict | None:
        cls.init_db()
        conn = cls.connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM refresh_jobs
                WHERE subscription_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (subscription_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def create_refresh_job(
        cls,
        subscription_id: str,
        speedtest_limit: int,
        force_probe: bool = False,
    ) -> dict:
        cls.init_db()
        job_id = cls.new_job_id()
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO refresh_jobs (
                        id, subscription_id, status, phase, speedtest_limit,
                        force_probe, created_at
                    ) VALUES (?, ?, 'queued', 'queued', ?, ?, ?)
                    """,
                    (job_id, subscription_id, speedtest_limit, int(force_probe), now),
                )
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_status = 'queued', last_job_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (job_id, now, subscription_id),
                )
                conn.commit()
            finally:
                conn.close()
        return cls.get_job(job_id)

    @classmethod
    def get_job(cls, job_id: str) -> dict | None:
        cls.init_db()
        conn = cls.connect()
        try:
            row = conn.execute(
                "SELECT * FROM refresh_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def update_job(
        cls,
        job_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        processed_nodes: int | None = None,
        total_nodes: int | None = None,
        error: str | None = None,
        started_at: int | None = None,
        finished_at: int | None = None,
    ) -> None:
        cls.init_db()
        updates = []
        values = []
        for field, value in (
            ("status", status),
            ("phase", phase),
            ("processed_nodes", processed_nodes),
            ("total_nodes", total_nodes),
            ("error", error),
            ("started_at", started_at),
            ("finished_at", finished_at),
        ):
            if value is not None:
                updates.append(f"{field} = ?")
                values.append(value)
        if not updates:
            return

        values.append(job_id)
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    f"UPDATE refresh_jobs SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                job = conn.execute(
                    "SELECT * FROM refresh_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if job and status is not None:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET last_status = ?, updated_at = ?
                        WHERE id = ? AND last_job_id = ?
                        """,
                        (status, cls.now(), job["subscription_id"], job["id"]),
                    )
                conn.commit()
            finally:
                conn.close()

    @classmethod
    def cancel_job(cls, job_id: str, reason: str = "Canceled by user") -> dict | None:
        cls.init_db()
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                job = conn.execute(
                    "SELECT id, subscription_id, status FROM refresh_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if not job:
                    return None
                if job["status"] not in {"queued", "running"}:
                    return dict(job)

                conn.execute(
                    """
                    UPDATE refresh_jobs
                    SET status = 'canceled',
                        phase = 'canceled',
                        error = ?,
                        finished_at = ?
                    WHERE id = ?
                    """,
                    (reason, now, job_id),
                )
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_status = 'canceled', updated_at = ?
                    WHERE id = ? AND last_job_id = ?
                    """,
                    (now, job["subscription_id"], job_id),
                )
                conn.commit()
                return cls.get_job(job_id)
            finally:
                conn.close()

    @classmethod
    def save_results(cls, subscription_id: str, nodes: list[TestedNode]) -> None:
        cls.init_db()
        payload = tested_nodes_to_json(nodes)
        node_count = len(nodes)
        valid_count = sum(1 for node in nodes if node.analyzed_node.is_valid)
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO subscription_results (
                        subscription_id, result_json, node_count, valid_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(subscription_id) DO UPDATE SET
                        result_json = excluded.result_json,
                        node_count = excluded.node_count,
                        valid_count = excluded.valid_count,
                        updated_at = excluded.updated_at
                    """,
                    (subscription_id, payload, node_count, valid_count, now),
                )
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET updated_at = ?
                    WHERE id = ?
                    """,
                    (now, subscription_id),
                )
                conn.commit()
            finally:
                conn.close()

    @classmethod
    def save_results_if_current(
        cls,
        subscription_id: str,
        job_id: str,
        expected_url: str,
        nodes: list[TestedNode],
    ) -> bool:
        cls.init_db()
        payload = tested_nodes_to_json(nodes)
        node_count = len(nodes)
        valid_count = sum(1 for node in nodes if node.analyzed_node.is_valid)
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                subscription = conn.execute(
                    """
                    SELECT id, url, last_job_id
                    FROM subscriptions
                    WHERE id = ?
                    """,
                    (subscription_id,),
                ).fetchone()
                job = conn.execute(
                    """
                    SELECT id, status
                    FROM refresh_jobs
                    WHERE id = ? AND subscription_id = ?
                    """,
                    (job_id, subscription_id),
                ).fetchone()
                if (
                    not subscription
                    or not job
                    or subscription["url"] != expected_url
                    or subscription["last_job_id"] != job_id
                    or job["status"] != "running"
                ):
                    return False

                conn.execute(
                    """
                    INSERT INTO subscription_results (
                        subscription_id, result_json, node_count, valid_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(subscription_id) DO UPDATE SET
                        result_json = excluded.result_json,
                        node_count = excluded.node_count,
                        valid_count = excluded.valid_count,
                        updated_at = excluded.updated_at
                    """,
                    (subscription_id, payload, node_count, valid_count, now),
                )
                conn.execute(
                    """
                    UPDATE refresh_jobs
                    SET status = 'completed',
                        phase = 'completed',
                        processed_nodes = ?,
                        total_nodes = ?,
                        finished_at = ?
                    WHERE id = ?
                    """,
                    (node_count, node_count, now, job_id),
                )
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET last_status = 'completed', updated_at = ?
                    WHERE id = ? AND last_job_id = ?
                    """,
                    (now, subscription_id, job_id),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    @classmethod
    def get_latest_result(cls, subscription_id: str) -> dict | None:
        cls.init_db()
        conn = cls.connect()
        try:
            row = conn.execute(
                """
                SELECT subscription_id, result_json, node_count, valid_count, updated_at
                FROM subscription_results
                WHERE subscription_id = ?
                """,
                (subscription_id,),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            data["nodes"] = tested_nodes_from_json(data.pop("result_json"))
            return data
        finally:
            conn.close()

    @staticmethod
    def new_template_id() -> str:
        return f"tpl_{uuid.uuid4().hex[:12]}"

    @classmethod
    def list_singbox_templates(cls) -> list[dict]:
        cls.init_db()
        conn = cls.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM singbox_templates ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @classmethod
    def get_singbox_template(cls, template_id: str) -> dict | None:
        cls.init_db()
        conn = cls.connect()
        try:
            row = conn.execute(
                "SELECT * FROM singbox_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def create_singbox_template(cls, name: str, content: str) -> dict:
        cls.init_db()
        tpl_id = cls.new_template_id()
        now = cls.now()
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    """
                    INSERT INTO singbox_templates (
                        id, name, content, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (tpl_id, name, content, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return cls.get_singbox_template(tpl_id)

    @classmethod
    def update_singbox_template(
        cls,
        template_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> dict | None:
        cls.init_db()
        existing = cls.get_singbox_template(template_id)
        if not existing:
            return None
        updates = []
        values = []
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if content is not None:
            updates.append("content = ?")
            values.append(content)
        if not updates:
            return existing

        now = cls.now()
        updates.append("updated_at = ?")
        values.append(now)
        values.append(template_id)
        with cls._write_lock:
            conn = cls.connect()
            try:
                conn.execute(
                    f"UPDATE singbox_templates SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                conn.commit()
            finally:
                conn.close()
        return cls.get_singbox_template(template_id)

    @classmethod
    def delete_singbox_template(cls, template_id: str) -> bool:
        cls.init_db()
        with cls._write_lock:
            conn = cls.connect()
            try:
                existing = conn.execute(
                    "SELECT id FROM singbox_templates WHERE id = ?",
                    (template_id,),
                ).fetchone()
                if not existing:
                    return False
                conn.execute(
                    "DELETE FROM singbox_templates WHERE id = ?",
                    (template_id,),
                )
                conn.commit()
                return True
            finally:
                conn.close()

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
                    """
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

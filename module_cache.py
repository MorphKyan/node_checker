import asyncio
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict

from models import ApiVerdict, LabelEvidence, NodeProfile, ProbeData, VlessNode
from settings import settings


class ProbeCache:
    _init_lock = asyncio.Lock()
    _write_lock = asyncio.Lock()
    _initialized = False

    @staticmethod
    def make_node_fingerprint(node: VlessNode) -> str:
        identity = {
            "uuid": node.uuid,
            "server_ip": node.server_ip,
            "server_port": node.server_port,
            "security": node.security,
            "sni": node.sni,
            "fp": node.fp,
            "pbk": node.pbk,
            "sid": node.sid,
            "type": node.type,
            "path": node.path,
            "host": node.host,
            "flow": node.flow,
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def make_node_identity(node: VlessNode) -> str:
        identity = {
            "server": f"{node.server_ip}:{node.server_port}",
            "security": node.security,
            "type": node.type,
            "sni": node.sni,
            "host": node.host,
        }
        return json.dumps(identity, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _restore_label_evidence(items) -> list[LabelEvidence]:
        restored = []
        for item in items or []:
            if isinstance(item, LabelEvidence):
                restored.append(item)
            elif isinstance(item, dict):
                restored.append(LabelEvidence(**item))
        return restored

    @classmethod
    def _restore_api_verdict(cls, data) -> ApiVerdict:
        if isinstance(data, ApiVerdict):
            return data
        return ApiVerdict(
            source=data.get("source", ""),
            network_labels=cls._restore_label_evidence(data.get("network_labels")),
            risk_labels=cls._restore_label_evidence(data.get("risk_labels")),
            risk_score=data.get("risk_score"),
            raw_summary=data.get("raw_summary", ""),
        )

    @classmethod
    def _restore_node_profile(cls, data) -> NodeProfile:
        if isinstance(data, NodeProfile):
            return data
        if not isinstance(data, dict):
            return NodeProfile()
        return NodeProfile(
            display_labels=list(data.get("display_labels") or ["未知"]),
            network_labels=cls._restore_label_evidence(data.get("network_labels")),
            risk_labels=cls._restore_label_evidence(data.get("risk_labels")),
            risk_score=float(data.get("risk_score", 0.0) or 0.0),
            confidence=data.get("confidence", "low"),
            evidence=[
                cls._restore_api_verdict(item)
                for item in data.get("evidence", [])
                if isinstance(item, (ApiVerdict, dict))
            ],
        )

    @classmethod
    def _restore_probe_data(cls, data: dict) -> ProbeData:
        data = dict(data)
        if "profile" in data:
            data["profile"] = cls._restore_node_profile(data["profile"])
        return ProbeData(**data)

    @classmethod
    async def init_db(cls) -> None:
        if cls._initialized:
            return

        async with cls._init_lock:
            if cls._initialized:
                return

            db_path = settings.CACHE_DB_PATH
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS probe_cache (
                        fingerprint TEXT PRIMARY KEY,
                        node_identity TEXT NOT NULL,
                        probe_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            cls._initialized = True

    @classmethod
    async def get(cls, node: VlessNode) -> ProbeData | None:
        if not settings.CACHE_ENABLED:
            return None

        await cls.init_db()
        fingerprint = cls.make_node_fingerprint(node)
        now = int(time.time())

        conn = sqlite3.connect(settings.CACHE_DB_PATH)
        try:
            row = conn.execute(
                "SELECT probe_json, expires_at FROM probe_cache WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None

        probe_json, expires_at = row
        if expires_at < now:
            return None

        try:
            data = json.loads(probe_json)
            return cls._restore_probe_data(data)
        except Exception as e:
            print(f"[Cache Error] Failed to load cache for {node.remark}: {e}")
            return None

    @classmethod
    async def set(cls, node: VlessNode, probe_data: ProbeData) -> None:
        if not settings.CACHE_ENABLED:
            return

        if not settings.CACHE_FAILURE_RESULTS:
            if probe_data.tcp_ping_ms >= 9999.0 or probe_data.ttfb_ms >= 9999.0:
                return

        await cls.init_db()
        fingerprint = cls.make_node_fingerprint(node)
        node_identity = cls.make_node_identity(node)
        probe_json = json.dumps(asdict(probe_data), ensure_ascii=False)
        now = int(time.time())
        expires_at = now + int(settings.PROBE_CACHE_TTL_SECONDS)

        async with cls._write_lock:
            conn = sqlite3.connect(settings.CACHE_DB_PATH)
            try:
                existing = conn.execute(
                    "SELECT created_at FROM probe_cache WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                created_at = existing[0] if existing else now
                conn.execute(
                    """
                    INSERT INTO probe_cache (
                        fingerprint, node_identity, probe_json, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        node_identity = excluded.node_identity,
                        probe_json = excluded.probe_json,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (fingerprint, node_identity, probe_json, created_at, now, expires_at),
                )
                conn.commit()
            finally:
                conn.close()

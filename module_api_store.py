"""JSON-backed persistence for the local API service.

The service intentionally uses one process per data directory.  Files are
written atomically so an interrupted write never leaves a partially written
configuration, job, result, or cache entry behind.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from models import TestedNode
from module_result_codec import restore_tested_nodes
from settings import settings


DEFAULT_API_SITES = [
    {"id": "ipwhois", "column_name": "ipwho.is", "provider": "ipwhois", "url_template": "https://ipwho.is/{ip}", "api_key": "", "weight": 1.0, "enabled": True, "order": 0},
    {"id": "ipapi", "column_name": "ipapi.is", "provider": "ipapi", "url_template": "https://api.ipapi.is?q={ip}", "api_key": "", "weight": 1.0, "enabled": True, "order": 1},
    {"id": "scamalytics", "column_name": "Scamalytics", "provider": "scamalytics", "url_template": "https://api11.scamalytics.com/v3/{ip}?key={key}", "api_key": "", "weight": 1.0, "enabled": False, "order": 2},
    {"id": "proxycheck", "column_name": "proxycheck.io", "provider": "proxycheck", "url_template": "https://proxycheck.io/v3/{ip}", "api_key": "", "weight": 1.3, "enabled": True, "order": 3},
    {"id": "abstract", "column_name": "Abstract API", "provider": "abstract", "url_template": "https://ip-intelligence.abstractapi.com/v1/?api_key={key}&ip_address={ip}", "api_key": "", "weight": 0.8, "enabled": False, "order": 4},
    {"id": "ip2location", "column_name": "IP2Location.io", "provider": "ip2location", "url_template": "https://api.ip2location.io/?ip={ip}&format=json", "api_key": "", "weight": 0.6, "enabled": True, "order": 5},
]


class ApiStore:
    _config_lock = threading.RLock()
    _job_locks: dict[str, threading.RLock] = {}
    _result_locks: dict[str, threading.RLock] = {}

    @staticmethod
    def now() -> int:
        return int(time.time())

    @staticmethod
    def new_subscription_id() -> str:
        return f"sub_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_job_id() -> str:
        return f"job_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_template_id() -> str:
        return f"tpl_{uuid.uuid4().hex[:12]}"

    @classmethod
    def data_dir(cls) -> Path:
        return Path(settings.DATA_DIR)

    @classmethod
    def config_path(cls) -> Path:
        return cls.data_dir() / "config.json"

    @classmethod
    def results_path(cls, subscription_id: str) -> Path:
        return cls.data_dir() / "results" / f"{subscription_id}.json"

    @classmethod
    def jobs_path(cls, job_id: str) -> Path:
        return cls.data_dir() / "jobs" / f"{job_id}.json"

    @staticmethod
    def _atomic_write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(temp, path)
        finally:
            # A failed replacement must leave the previous file intact and
            # must not accumulate abandoned temporary configuration files.
            temp.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path, fallback: Any = None) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return fallback

    @classmethod
    def _default_config(cls) -> dict[str, Any]:
        return {
            "version": 1,
            "runtime_settings": {key: getattr(settings, key) for key in __import__("module_runtime_settings").EDITABLE_SETTINGS},
            "exit_ip_endpoint": "https://ipwho.is/",
            "api_sites": deepcopy(DEFAULT_API_SITES),
            "subscriptions": [],
            "singbox_templates": [],
        }

    @classmethod
    def init_db(cls) -> None:
        """Compatibility name retained for callers; no database is created."""
        with cls._config_lock:
            cls.data_dir().mkdir(parents=True, exist_ok=True)
            config = cls._read_json(cls.config_path())
            if not isinstance(config, dict):
                cls._atomic_write(cls.config_path(), cls._default_config())
            else:
                changed = False
                defaults = cls._default_config()
                for key, value in defaults.items():
                    if key not in config:
                        config[key] = value
                        changed = True
                if changed:
                    cls._atomic_write(cls.config_path(), config)

    @classmethod
    def _config(cls) -> dict[str, Any]:
        cls.init_db()
        config = cls._read_json(cls.config_path(), cls._default_config())
        return config if isinstance(config, dict) else cls._default_config()

    @classmethod
    def _save_config(cls, config: dict[str, Any]) -> None:
        cls._atomic_write(cls.config_path(), config)

    @classmethod
    def default_singbox_template(cls) -> str:
        path = Path(__file__).resolve().parent / "examples" / "singbox_template.yaml"
        return path.read_text(encoding="utf-8")

    @classmethod
    def get_runtime_settings(cls) -> dict[str, Any]:
        return deepcopy(cls._config().get("runtime_settings", {}))

    @classmethod
    def save_runtime_settings(cls, values: dict[str, Any]) -> None:
        with cls._config_lock:
            config = cls._config()
            config["runtime_settings"] = deepcopy(values)
            cls._save_config(config)

    @classmethod
    def get_exit_ip_endpoint(cls) -> str:
        return str(cls._config().get("exit_ip_endpoint") or "https://ipwho.is/")

    @classmethod
    def get_probe_config_snapshot(cls) -> dict[str, Any]:
        """Capture every persisted input used by a probe in one config read."""
        config = cls._config()
        sites = sorted(config.get("api_sites", []), key=lambda s: (s.get("order", 0), s.get("id", "")))
        return {
            "api_sites": deepcopy(sites),
            "exit_ip_endpoint": str(config.get("exit_ip_endpoint") or "https://ipwho.is/"),
        }

    @classmethod
    def update_exit_ip_endpoint(cls, endpoint: str) -> str:
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("exit_ip_endpoint must be an HTTP(S) URL")
        with cls._config_lock:
            config = cls._config(); config["exit_ip_endpoint"] = endpoint; cls._save_config(config)
        return endpoint

    @classmethod
    def _public_site(cls, site: dict[str, Any]) -> dict[str, Any]:
        public = {k: v for k, v in site.items() if k != "api_key"}
        public["api_key_configured"] = bool(site.get("api_key"))
        return public

    @classmethod
    def get_api_sites(cls, *, public: bool = True) -> list[dict[str, Any]]:
        sites = sorted(cls._config().get("api_sites", []), key=lambda s: (s.get("order", 0), s.get("id", "")))
        return [cls._public_site(s) if public else deepcopy(s) for s in sites]

    @staticmethod
    def provider_types() -> list[str]:
        return ["ipwhois", "ipapi", "scamalytics", "proxycheck", "abstract", "ip2location"]

    @classmethod
    def _validate_site(cls, data: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
        site = deepcopy(existing or {})
        site.update({k: v for k, v in data.items() if k not in {"clear_api_key", "api_key_configured"}})
        site_id = str(site.get("id", "")).strip()
        if not site_id or not site_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError("site id must contain only letters, digits, '-' or '_'")
        if site.get("provider") not in cls.provider_types():
            raise ValueError("unsupported provider")
        if not str(site.get("column_name", "")).strip():
            raise ValueError("column_name is required")
        template = str(site.get("url_template", ""))
        if "{ip}" not in template or not template.startswith(("http://", "https://")):
            raise ValueError("url_template must be an HTTP(S) URL containing {ip}")
        try:
            site["weight"] = float(site.get("weight", 1.0))
        except (TypeError, ValueError):
            raise ValueError("weight must be a number")
        if site["weight"] <= 0:
            raise ValueError("weight must be greater than zero")
        site["enabled"] = bool(site.get("enabled", False))
        if site["enabled"] and "{key}" in template and not str(site.get("api_key", "")):
            raise ValueError("an API key is required before enabling this site")
        site["id"] = site_id
        site["column_name"] = str(site["column_name"]).strip()
        return site

    @classmethod
    def create_api_site(cls, data: dict[str, Any]) -> dict[str, Any]:
        with cls._config_lock:
            config = cls._config(); sites = config["api_sites"]
            if any(s.get("id") == data.get("id") for s in sites):
                raise ValueError("site id already exists")
            site = cls._validate_site(data)
            site["order"] = len(sites)
            site["api_key"] = str(data.get("api_key") or "")
            sites.append(site); cls._save_config(config)
            return cls._public_site(site)

    @classmethod
    def update_api_site(cls, site_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        with cls._config_lock:
            config = cls._config()
            for index, old in enumerate(config["api_sites"]):
                if old.get("id") != site_id: continue
                if "id" in data and data["id"] != site_id:
                    raise ValueError("site id cannot be changed")
                # Apply key semantics before validation: an enabled `{key}`
                # template must be validated against the final stored key.
                candidate = deepcopy(old)
                candidate.update({k: v for k, v in data.items() if k not in {"clear_api_key", "api_key_configured", "id", "api_key"}})
                if data.get("clear_api_key"):
                    candidate["api_key"] = ""
                elif "api_key" in data and data["api_key"]:
                    candidate["api_key"] = str(data["api_key"])
                site = cls._validate_site(candidate, existing=None)
                config["api_sites"][index] = site; cls._save_config(config)
                return cls._public_site(site)
        return None

    @classmethod
    def delete_api_site(cls, site_id: str) -> bool:
        with cls._config_lock:
            config = cls._config(); sites = config["api_sites"]
            kept = [s for s in sites if s.get("id") != site_id]
            if len(kept) == len(sites): return False
            for index, site in enumerate(kept): site["order"] = index
            config["api_sites"] = kept; cls._save_config(config); return True

    @classmethod
    def order_api_sites(cls, ordered_ids: list[str]) -> list[dict[str, Any]]:
        with cls._config_lock:
            config = cls._config(); sites = config["api_sites"]
            ids = [s.get("id") for s in sites]
            if set(ids) != set(ordered_ids) or len(ids) != len(ordered_ids):
                raise ValueError("order must include every site exactly once")
            mapping = {s["id"]: s for s in sites}
            config["api_sites"] = [mapping[id_] for id_ in ordered_ids]
            for index, site in enumerate(config["api_sites"]): site["order"] = index
            cls._save_config(config)
            return cls.get_api_sites()

    @classmethod
    def create_subscription(cls, url: str, name: str | None = None) -> dict:
        with cls._config_lock:
            config = cls._config(); now = cls.now(); sub_id = cls.new_subscription_id()
            sub = {"id": sub_id, "name": name or f"Subscription {sub_id[-6:]}", "url": url, "created_at": now, "updated_at": now, "last_status": "new", "last_job_id": None}
            config["subscriptions"].append(sub); cls._save_config(config); return deepcopy(sub)

    @classmethod
    def get_subscription(cls, subscription_id: str) -> dict | None:
        for sub in cls._config().get("subscriptions", []):
            if sub.get("id") == subscription_id: return deepcopy(sub)
        return None

    @classmethod
    def update_subscription(cls, subscription_id: str, *, name: str | None = None, url: str | None = None) -> dict | None:
        with cls._config_lock:
            config = cls._config()
            for sub in config["subscriptions"]:
                if sub.get("id") != subscription_id: continue
                url_changed = url is not None and url != sub.get("url")
                if name is not None: sub["name"] = name
                if url is not None: sub["url"] = url
                sub["updated_at"] = cls.now()
                if url_changed:
                    sub.update(last_status="new", last_job_id=None)
                    cls.results_path(subscription_id).unlink(missing_ok=True)
                    for path in (cls.data_dir() / "jobs").glob("*.json"):
                        job = cls._read_json(path, {})
                        if job.get("subscription_id") == subscription_id and job.get("status") in {"queued", "running"}:
                            job.update(status="failed", phase="failed", error="Subscription URL changed before refresh completed", finished_at=cls.now())
                            cls._atomic_write(path, job)
                cls._save_config(config); return deepcopy(sub)
        return None

    @classmethod
    def delete_subscription(cls, subscription_id: str) -> bool:
        with cls._config_lock:
            config = cls._config(); old = config["subscriptions"]
            config["subscriptions"] = [s for s in old if s.get("id") != subscription_id]
            if len(old) == len(config["subscriptions"]): return False
            cls.results_path(subscription_id).unlink(missing_ok=True)
            for path in (cls.data_dir() / "jobs").glob("*.json"):
                job = cls._read_json(path, {})
                if job.get("subscription_id") == subscription_id: path.unlink(missing_ok=True)
            cls._save_config(config); return True

    @classmethod
    def list_subscriptions(cls) -> list[dict]:
        rows = []
        for sub in sorted(cls._config().get("subscriptions", []), key=lambda s: s.get("created_at", 0), reverse=True):
            result = cls.get_latest_result(sub["id"])
            rows.append({**deepcopy(sub), "node_count": result["node_count"] if result else 0, "valid_count": result["valid_count"] if result else 0})
        return rows

    @classmethod
    def _job_lock(cls, job_id: str) -> threading.RLock:
        with cls._config_lock: return cls._job_locks.setdefault(job_id, threading.RLock())

    @classmethod
    def _result_lock(cls, subscription_id: str) -> threading.RLock:
        with cls._config_lock: return cls._result_locks.setdefault(subscription_id, threading.RLock())

    @classmethod
    def find_active_job(cls, subscription_id: str) -> dict | None:
        jobs = [cls._read_json(p, {}) for p in (cls.data_dir() / "jobs").glob("*.json")]
        active = [j for j in jobs if j.get("subscription_id") == subscription_id and j.get("status") in {"queued", "running"}]
        return deepcopy(max(active, key=lambda j: j.get("created_at", 0))) if active else None

    @classmethod
    def create_refresh_job(
        cls,
        subscription_id: str,
        speedtest_limit: int,
        force_probe: bool = False,
        api_sites_snapshot: list[dict] | None = None,
        exit_ip_endpoint_snapshot: str | None = None,
        probe_config_snapshot: dict[str, Any] | None = None,
    ) -> dict:
        with cls._config_lock:
            if not cls.get_subscription(subscription_id): raise KeyError(subscription_id)
            config_snapshot = deepcopy(probe_config_snapshot) if probe_config_snapshot is not None else cls.get_probe_config_snapshot()
            if api_sites_snapshot is not None:
                config_snapshot["api_sites"] = deepcopy(api_sites_snapshot)
            if exit_ip_endpoint_snapshot is not None:
                config_snapshot["exit_ip_endpoint"] = str(exit_ip_endpoint_snapshot)
            config_snapshot.setdefault("api_sites", [])
            config_snapshot.setdefault("exit_ip_endpoint", "https://ipwho.is/")
            now = cls.now(); job_id = cls.new_job_id()
            job = {"id": job_id, "subscription_id": subscription_id, "status": "queued", "phase": "queued", "processed_nodes": 0, "total_nodes": 0, "error": None, "speedtest_limit": int(speedtest_limit), "force_probe": bool(force_probe), "created_at": now, "started_at": None, "finished_at": None, "probe_config_snapshot": config_snapshot, "api_sites_snapshot": deepcopy(config_snapshot["api_sites"]), "exit_ip_endpoint_snapshot": config_snapshot["exit_ip_endpoint"]}
            cls._atomic_write(cls.jobs_path(job_id), job)
            config = cls._config()
            for sub in config["subscriptions"]:
                if sub["id"] == subscription_id: sub.update(last_status="queued", last_job_id=job_id, updated_at=now)
            cls._save_config(config); return deepcopy(job)

    @classmethod
    def get_job(cls, job_id: str) -> dict | None:
        job = cls._read_json(cls.jobs_path(job_id))
        return deepcopy(job) if isinstance(job, dict) else None

    @classmethod
    def update_job(cls, job_id: str, **updates: Any) -> None:
        with cls._job_lock(job_id):
            job = cls._read_json(cls.jobs_path(job_id))
            if not isinstance(job, dict): return
            for key, value in updates.items():
                if value is not None: job[key] = value
            cls._atomic_write(cls.jobs_path(job_id), job)
            if updates.get("status") is not None:
                with cls._config_lock:
                    config = cls._config()
                    for sub in config["subscriptions"]:
                        if sub["id"] == job["subscription_id"] and sub.get("last_job_id") == job_id:
                            sub.update(last_status=job["status"], updated_at=cls.now())
                    cls._save_config(config)

    @classmethod
    def cancel_job(cls, job_id: str, reason: str = "Canceled by user") -> dict | None:
        job = cls.get_job(job_id)
        if not job: return None
        if job.get("status") in {"queued", "running"}:
            cls.update_job(job_id, status="canceled", phase="canceled", error=reason, finished_at=cls.now())
        return cls.get_job(job_id)

    @classmethod
    def fail_stale_active_jobs(cls, reason: str) -> int:
        count = 0
        for path in (cls.data_dir() / "jobs").glob("*.json"):
            job = cls._read_json(path, {})
            if job.get("status") in {"queued", "running"}:
                cls.update_job(job["id"], status="failed", phase="failed", error=reason, finished_at=cls.now()); count += 1
        return count

    @classmethod
    def _result_payload(cls, subscription_id: str, nodes: list[TestedNode], api_sites_snapshot: list[dict] | None = None, exit_ip_endpoint_snapshot: str | None = None) -> dict:
        now = cls.now()
        return {"subscription_id": subscription_id, "nodes": [__import__("dataclasses").asdict(n) for n in nodes], "node_count": len(nodes), "valid_count": sum(n.analyzed_node.is_valid for n in nodes), "updated_at": now, "api_sites_snapshot": [cls._public_site(s) for s in (api_sites_snapshot or [])], "exit_ip_endpoint_snapshot": exit_ip_endpoint_snapshot}

    @classmethod
    def save_results(cls, subscription_id: str, nodes: list[TestedNode], api_sites_snapshot: list[dict] | None = None) -> None:
        with cls._result_lock(subscription_id): cls._atomic_write(cls.results_path(subscription_id), cls._result_payload(subscription_id, nodes, api_sites_snapshot))

    @classmethod
    def save_results_if_current(cls, subscription_id: str, job_id: str, expected_url: str, nodes: list[TestedNode]) -> bool:
        with cls._result_lock(subscription_id):
            sub = cls.get_subscription(subscription_id); job = cls.get_job(job_id)
            if not sub or not job or sub.get("url") != expected_url or sub.get("last_job_id") != job_id or job.get("status") != "running": return False
            cls._atomic_write(cls.results_path(subscription_id), cls._result_payload(subscription_id, nodes, job.get("api_sites_snapshot", []), job.get("exit_ip_endpoint_snapshot")))
            cls.update_job(job_id, status="completed", phase="completed", processed_nodes=len(nodes), total_nodes=len(nodes), finished_at=cls.now())
            return True

    @classmethod
    def get_latest_result(cls, subscription_id: str) -> dict | None:
        data = cls._read_json(cls.results_path(subscription_id))
        if not isinstance(data, dict): return None
        try: data["nodes"] = restore_tested_nodes(data.get("nodes", []))
        except (TypeError, ValueError, KeyError): return None
        return data

    @classmethod
    def list_singbox_templates(cls) -> list[dict]:
        return sorted(deepcopy(cls._config().get("singbox_templates", [])), key=lambda t: t.get("created_at", 0), reverse=True)

    @classmethod
    def get_singbox_template(cls, template_id: str) -> dict | None:
        return next((t for t in cls.list_singbox_templates() if t.get("id") == template_id), None)

    @classmethod
    def create_singbox_template(cls, name: str, content: str) -> dict:
        with cls._config_lock:
            config = cls._config(); now = cls.now(); tpl = {"id": cls.new_template_id(), "name": name, "content": content, "created_at": now, "updated_at": now}; config["singbox_templates"].append(tpl); cls._save_config(config); return deepcopy(tpl)

    @classmethod
    def update_singbox_template(cls, template_id: str, *, name: str | None = None, content: str | None = None) -> dict | None:
        with cls._config_lock:
            config = cls._config()
            for tpl in config["singbox_templates"]:
                if tpl["id"] == template_id:
                    if name is not None: tpl["name"] = name
                    if content is not None: tpl["content"] = content
                    tpl["updated_at"] = cls.now(); cls._save_config(config); return deepcopy(tpl)
        return None

    @classmethod
    def delete_singbox_template(cls, template_id: str) -> bool:
        with cls._config_lock:
            config = cls._config(); old = config["singbox_templates"]; config["singbox_templates"] = [t for t in old if t["id"] != template_id]
            if len(old) == len(config["singbox_templates"]): return False
            cls._save_config(config); return True

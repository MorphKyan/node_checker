import json
import os
from typing import Any

from settings import settings


EDITABLE_SETTINGS: dict[str, type] = {
    "FILTER_CONCURRENCY": int,
    "API_DEFAULT_SPEEDTEST_LIMIT": int,
    "CACHE_ENABLED": bool,
    "PROBE_CACHE_TTL_SECONDS": int,
    "CACHE_FAILURE_RESULTS": bool,
    "SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH": int,
    "SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH": int,
    "TTFB_TARGET_URL": str,
    "SPEEDTEST_URL": str,
}


class RuntimeSettings:
    @staticmethod
    def path() -> str:
        return settings.RUNTIME_SETTINGS_PATH

    @classmethod
    def get_editable(cls) -> dict[str, Any]:
        return {key: getattr(settings, key) for key in EDITABLE_SETTINGS}

    @classmethod
    def load(cls) -> None:
        path = cls.path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cls.apply(data, persist=False)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"[RuntimeSettings] Failed to load {path}: {e}")

    @staticmethod
    def validate_value(key: str, value: Any) -> Any:
        expected_type = EDITABLE_SETTINGS[key]
        if expected_type is bool:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            return value
        if expected_type is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{key} must be an integer")
            return value
        if expected_type is str:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            return value
        return value

    @classmethod
    def apply(cls, data: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
        for key, value in data.items():
            if key not in EDITABLE_SETTINGS:
                continue
            setattr(settings, key, cls.validate_value(key, value))

        current = cls.get_editable()
        if persist:
            path = cls.path()
            path_dir = os.path.dirname(path)
            if path_dir:
                os.makedirs(path_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
        return current

from typing import Any

from settings import settings


EDITABLE_SETTINGS: dict[str, type] = {
    "FILTER_CONCURRENCY": int,
    "SPEEDTEST_CONCURRENCY": int,
    "API_DEFAULT_SPEEDTEST_LIMIT": int,
    "CACHE_ENABLED": bool,
    "PROBE_CACHE_TTL_SECONDS": int,
    "CACHE_FAILURE_RESULTS": bool,
    "SUBSCRIPTION_MAX_M": int,
    "SPEEDTEST_MAX_M": int,
    "SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH": int,
    "SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH": int,
    "TTFB_TARGET_URL": str,
    "SPEEDTEST_URL": str,
    "PROXY_CORE": str,
}

SETTING_LIMITS: dict[str, dict[str, Any]] = {
    "FILTER_CONCURRENCY": {"min": 1, "max": 100},
    "SPEEDTEST_CONCURRENCY": {"min": 1, "max": 20},
    "API_DEFAULT_SPEEDTEST_LIMIT": {"min": 0, "max": 100},
    "PROBE_CACHE_TTL_SECONDS": {"min": 60},
    "SUBSCRIPTION_MAX_M": {"min": 1, "max": 50},
    "SPEEDTEST_MAX_M": {"min": 1, "max": 256},
    "SUBSCRIPTION_COMPACT_MAX_NAME_LENGTH": {"min": 16, "max": 160},
    "SUBSCRIPTION_DETAILED_MAX_NAME_LENGTH": {"min": 32, "max": 240},
    "TTFB_TARGET_URL": {"min_length": 1},
    "SPEEDTEST_URL": {"min_length": 1},
    "PROXY_CORE": {"options": ["sing-box", "xray"]},
}


class RuntimeSettings:
    @staticmethod
    def get_editable() -> dict[str, Any]:
        return {key: getattr(settings, key) for key in EDITABLE_SETTINGS}

    @classmethod
    def get_metadata(cls) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "type": value_type.__name__,
                **SETTING_LIMITS.get(key, {}),
            }
            for key, value_type in EDITABLE_SETTINGS.items()
        }

    @classmethod
    def load(cls) -> None:
        try:
            from module_api_store import ApiStore
            data = ApiStore.get_runtime_settings()
            cls.apply(data, persist=False)
        except (OSError, ValueError) as e:
            print(f"[RuntimeSettings] Failed to load JSON config: {e}")

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
            limits = SETTING_LIMITS.get(key, {})
            min_value = limits.get("min")
            max_value = limits.get("max")
            if min_value is not None and value < min_value:
                raise ValueError(f"{key} must be greater than or equal to {min_value}")
            if max_value is not None and value > max_value:
                raise ValueError(f"{key} must be less than or equal to {max_value}")
            return value
        if expected_type is str:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            limits = SETTING_LIMITS.get(key, {})
            min_length = limits.get("min_length")
            if min_length is not None and len(value) < min_length:
                raise ValueError(f"{key} must not be empty")
            options = limits.get("options")
            if options is not None and value not in options:
                raise ValueError(f"{key} must be one of {options}")
            return value
        return value

    @classmethod
    def apply(cls, data: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
        validated = {}
        for key, value in data.items():
            if key not in EDITABLE_SETTINGS:
                continue
            validated[key] = cls.validate_value(key, value)

        for key, value in validated.items():
            setattr(settings, key, value)

        current = cls.get_editable()
        if persist:
            from module_api_store import ApiStore
            ApiStore.save_runtime_settings(current)
        return current

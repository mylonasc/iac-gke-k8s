import os


def normalized_public_base_path(raw: str | None = None) -> str:
    value = raw
    if value is None:
        value = os.getenv("APP_PUBLIC_BASE_PATH", "")
    normalized = str(value or "").strip()
    if not normalized or normalized == "/":
        return ""
    return "/" + normalized.strip("/")


def with_public_base(path: str, raw_base_path: str | None = None) -> str:
    base_path = normalized_public_base_path(raw_base_path)
    if not base_path:
        return path
    return f"{base_path}{path}"

import os
from dotenv import load_dotenv



load_dotenv()

def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v is not None and v != "" else default

def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default

def _env_bool(name: str, default: bool) -> bool:
    v = _env(name)
    if v is None:
        return default
    v = v.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default

OUTPUT_MODE = (_env("OUTPUT_MODE", "console") or "console").strip().lower()
COLLECTOR   = (_env("COLLECTOR", "simulated") or "simulated").strip().lower()

POLL_SECONDS = _env_int("POLL_SECONDS", 10)
STATE_PATH   = _env("STATE_PATH", "./state.json") or "./state.json"
META_MAX_KB  = _env_int("META_MAX_KB", 256)

TXDXAI_INGEST_URL = _env("TXDXAI_INGEST_URL", "console://stdout") or "console://stdout"
TXDXAI_COMPANY_ID = _env_int("TXDXAI_COMPANY_ID", 0)
TXDXAI_API_KEY    = _env("TXDXAI_API_KEY", "") or ""

GVM_HOST = _env("GVM_HOST", "127.0.0.1") or "127.0.0.1"
GVM_PORT = _env_int("GVM_PORT", 9390)
GVM_USERNAME = _env("GVM_USERNAME", _env("GVM_USER", "admin")) or "admin"
GVM_PASSWORD = _env("GVM_PASSWORD", _env("GVM_PASS", "")) or ""
GVM_SOCKET = _env("GVM_SOCKET", "") or ""

DEBUG = _env_bool("DEBUG", False)
MAX_ERROR_REPEAT = _env_int("MAX_ERROR_REPEAT", 3)

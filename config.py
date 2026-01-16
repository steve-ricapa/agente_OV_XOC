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


# =========================
# Modo de salida
# =========================
# console  -> imprime payload
# backend  -> POST HTTPS con Authorization Bearer
OUTPUT_MODE = _env("OUTPUT_MODE", "console").strip().lower()

# =========================
# Backend (solo si OUTPUT_MODE=backend)
# =========================
TXDXAI_INGEST_URL = _env("TXDXAI_INGEST_URL", "console://stdout")
TXDXAI_COMPANY_ID = _env_int("TXDXAI_COMPANY_ID", 0)
TXDXAI_API_KEY = _env("TXDXAI_API_KEY", "")

# =========================
# Agent config
# =========================
COLLECTOR = _env("COLLECTOR", "gmp")
POLL_SECONDS = _env_int("POLL_SECONDS", 60)
STATE_PATH = _env("STATE_PATH", "state.json")
META_MAX_KB = _env_int("META_MAX_KB", 256)

# =========================
# OpenVAS / GVM
# =========================
GVM_HOST = _env("GVM_HOST", "127.0.0.1")
GVM_PORT = _env_int("GVM_PORT", 9390)

# soporta ambos nombres por compatibilidad
GVM_USERNAME = _env("GVM_USERNAME", _env("GVM_USER", "admin"))
GVM_PASSWORD = _env("GVM_PASSWORD", _env("GVM_PASS", ""))

# ⚠️ default seguro: True
GVM_TLS_VERIFY = _env_bool("GVM_TLS_VERIFY", True)

import json
import os
import time
import traceback
from typing import Any, Optional

# XML: intenta usar defusedxml si está disponible (más seguro)
try:
    from defusedxml import ElementTree as SafeET  # type: ignore
except Exception:
    SafeET = None  # fallback

import xml.etree.ElementTree as StdET

# HTTP (solo si OUTPUT_MODE=backend)
import requests


# =========================
# Utilidades de logging de errores
# =========================

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


DEBUG = _bool_env("DEBUG", False)


def format_exception(step: str, e: BaseException, context: Optional[dict[str, Any]] = None) -> str:
    """
    Devuelve un mensaje de error rico en contexto:
    - punto exacto (step)
    - tipo de excepción
    - mensaje
    - contexto clave-valor
    - stacktrace si DEBUG=1
    """
    parts = []
    parts.append(f"[{_now()}] ERROR @ {step}")
    parts.append(f"Tipo: {type(e).__name__}")
    parts.append(f"Motivo: {str(e) if str(e) else '(sin mensaje)'}")

    if context:
        parts.append("Contexto:")
        for k, v in context.items():
            parts.append(f"  - {k}: {v}")

    if DEBUG:
        parts.append("Stacktrace:")
        parts.append(traceback.format_exc())

    return "\n".join(parts)


# =========================
# Lock simple best-effort (cross-platform)
# =========================
class FileLock:
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self.f = None

    def __enter__(self):
        self.f = open(self.lock_path, "a+", encoding="utf-8")
        try:
            import fcntl  # type: ignore
            fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Windows / fallback best effort
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            import fcntl  # type: ignore
            fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self.f.close()
        except Exception:
            pass


# =========================
# Estado (deduplicación)
# =========================

def load_state(path: str) -> dict[str, Any]:
    step = "services.load_state"
    try:
        if not os.path.exists(path):
            return {"sent": []}

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("state.json no es un objeto JSON (dict)")
        if "sent" not in data:
            data["sent"] = []
        if not isinstance(data["sent"], list):
            raise ValueError("state.json['sent'] no es una lista")

        # normaliza a strings y evita basura
        data["sent"] = [str(x) for x in data["sent"] if x is not None]
        return data

    except json.JSONDecodeError as e:
        # state corrupto: arranca limpio (laboratorio)
        print(format_exception(step, e, {"path": path, "accion": "Se reinicia estado limpio"}))
        return {"sent": []}
    except Exception as e:
        print(format_exception(step, e, {"path": path, "accion": "Se reinicia estado limpio"}))
        return {"sent": []}


def save_state(path: str, data: dict[str, Any]) -> None:
    step = "services.save_state"
    tmp = f"{path}.tmp"
    try:
        # valida estructura
        if not isinstance(data, dict):
            raise ValueError("data debe ser dict")
        if "sent" not in data or not isinstance(data["sent"], list):
            raise ValueError("data debe contener 'sent' como lista")

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        os.replace(tmp, path)

    except PermissionError as e:
        print(format_exception(step, e, {"path": path, "tmp": tmp, "sugerencia": "Revisar permisos"}))
        raise
    except Exception as e:
        print(format_exception(step, e, {"path": path, "tmp": tmp}))
        raise
    finally:
        # best effort cleanup
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


# =========================
# Procesamiento XML
# =========================

def _xml_parser():
    return SafeET if SafeET is not None else StdET


def extract_severities(xml_text: str, max_kb: int = 256) -> dict[str, int]:
    step = "services.extract_severities"
    try:
        if xml_text is None:
            raise ValueError("XML es None")
        if not isinstance(xml_text, str):
            raise TypeError(f"XML debe ser str, recibido: {type(xml_text).__name__}")

        max_bytes = int(max_kb) * 1024
        size = len(xml_text.encode("utf-8", errors="ignore"))
        if size > max_bytes:
            raise ValueError(f"XML excede limite: {size} bytes > {max_bytes} bytes ({max_kb} KB)")

        ET = _xml_parser()
        root = ET.fromstring(xml_text)  # type: ignore

        result = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for r in root.findall(".//result"):
            try:
                sev_raw = r.findtext("severity", "0")
                sev = float(sev_raw or "0")
            except Exception:
                continue

            if sev >= 9.0:
                result["critical"] += 1
            elif sev >= 7.0:
                result["high"] += 1
            elif sev >= 4.0:
                result["medium"] += 1
            else:
                result["low"] += 1

        return result

    except (StdET.ParseError,) as e:
        print(format_exception(step, e, {"max_kb": max_kb, "hint": "XML mal formado"}))
        raise
    except Exception as e:
        print(format_exception(step, e, {"max_kb": max_kb}))
        raise


def map_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s in {"running", "in progress", "in_progress"}:
        return "running"
    if s in {"pending", "queued", "wait", "waiting"}:
        return "pending"
    if s in {"completed", "done", "finished", "success"}:
        return "completed"
    return s


# =========================
# Emisión (console-only o backend seguro)
# =========================

def emit_payload(
    *,
    output_mode: str,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: int = 15,
    require_https: bool = True,
) -> bool:
    step = "services.emit_payload"
    mode = (output_mode or "console").strip().lower()

    try:
        if mode == "console":
            print("\n" + "=" * 90)
            print(f"[{_now()}] TXDXAI INGEST (console-only)")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("=" * 90 + "\n")
            return True

        # backend mode
        if not url:
            raise ValueError("TXDXAI_INGEST_URL vacío")

        if require_https and not url.startswith("https://"):
            raise ValueError("Backend URL debe ser HTTPS (o usa OUTPUT_MODE=console)")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        r = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if 200 <= r.status_code < 300:
            print(f"[{_now()}] OK -> enviado al backend ({r.status_code})")
            return True

        # intenta dar info sin volcar todo el body
        snippet = ""
        try:
            snippet = (r.text or "")[:300]
        except Exception:
            snippet = ""

        raise RuntimeError(f"Backend rechazó: HTTP {r.status_code}. Respuesta: {snippet}")

    except requests.exceptions.SSLError as e:
        print(format_exception(step, e, {"url": url, "hint": "Problema TLS/certificado"}))
        return False
    except requests.exceptions.ConnectionError as e:
        print(format_exception(step, e, {"url": url, "hint": "No conecta a backend (DNS/ruta/firewall)"}))
        return False
    except requests.exceptions.Timeout as e:
        print(format_exception(step, e, {"url": url, "timeout": timeout, "hint": "Backend lento o caído"}))
        return False
    except requests.exceptions.RequestException as e:
        print(format_exception(step, e, {"url": url, "hint": "Fallo HTTP genérico"}))
        return False
    except Exception as e:
        print(format_exception(step, e, {"mode": mode, "url": url}))
        return False

import json
import os
import requests
import time
import traceback
from typing import Any, Optional

try:
    from defusedxml import ElementTree as SafeET  # type: ignore
except Exception:
    SafeET = None

import xml.etree.ElementTree as StdET
import requests


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


DEBUG = _bool_env("DEBUG", False)


def _root_cause(e: BaseException) -> str:
    """Devuelve una causa raíz legible (si existe)."""
    # __cause__ se setea con `raise X from Y`
    if getattr(e, "__cause__", None) is not None:
        c = e.__cause__
        return f"{type(c).__name__}: {c}"
    # __context__ puede existir si hubo una excepción previa
    if getattr(e, "__context__", None) is not None:
        c = e.__context__
        return f"{type(c).__name__}: {c}"
    return ""


def format_exception(step: str, e: BaseException, context: Optional[dict[str, Any]] = None) -> str:
    """
    Mensaje ultra detallado:
    - step (punto exacto)
    - tipo/motivo
    - causa raíz (si existe)
    - contexto clave/valor
    - stacktrace (DEBUG=1)
    """
    parts = []
    parts.append(f"[{_now()}] ERROR @ {step}")
    parts.append(f"Tipo: {type(e).__name__}")
    parts.append(f"Motivo: {str(e) if str(e) else '(sin mensaje)'}")

    rc = _root_cause(e)
    if rc:
        parts.append(f"Causa raíz: {rc}")

    if context:
        parts.append("Contexto:")
        for k, v in context.items():
            parts.append(f"  - {k}: {v}")

    if DEBUG:
        parts.append("Stacktrace:")
        parts.append(traceback.format_exc())

    return "\n".join(parts)


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


def load_state(path: str) -> dict[str, Any]:
    step = "services.load_state"
    try:
        if not os.path.exists(path):
            return {"sent": []}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("state.json no es dict")
        sent = data.get("sent", [])
        if not isinstance(sent, list):
            raise ValueError("state.json['sent'] no es lista")
        data["sent"] = [str(x) for x in sent if x is not None]
        return data
    except json.JSONDecodeError as e:
        print(format_exception(step, e, {"path": path, "accion": "estado reiniciado"}))
        return {"sent": []}
    except Exception as e:
        print(format_exception(step, e, {"path": path, "accion": "estado reiniciado"}))
        return {"sent": []}


def save_state(path: str, data: dict[str, Any]) -> None:
    step = "services.save_state"
    tmp = f"{path}.tmp"
    try:
        if "sent" not in data or not isinstance(data["sent"], list):
            raise ValueError("data debe contener sent:list")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(format_exception(step, e, {"path": path, "tmp": tmp}))
        raise
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def extract_severities(xml_text: str, max_kb: int = 256) -> dict[str, int]:
    step = "services.extract_severities"
    try:
        if not isinstance(xml_text, str) or not xml_text:
            raise ValueError("XML vacío o no str")

        max_bytes = int(max_kb) * 1024
        size = len(xml_text.encode("utf-8", errors="ignore"))
        if size > max_bytes:
            raise ValueError(f"XML excede límite: {size} bytes > {max_bytes} bytes")

        ET = SafeET if SafeET is not None else StdET
        root = ET.fromstring(xml_text)  # type: ignore

        out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in root.findall(".//result"):
            try:
                sev = float(r.findtext("severity", "0") or "0")
            except Exception:
                continue

            if sev >= 9.0:
                out["critical"] += 1
            elif sev >= 7.0:
                out["high"] += 1
            elif sev >= 4.0:
                out["medium"] += 1
            else:
                out["low"] += 1

        return out

    except (StdET.ParseError,) as e:
        print(format_exception(step, e, {"hint": "XML mal formado"}))
        raise
    except Exception as e:
        print(format_exception(step, e, {"max_kb": max_kb}))
        raise


def emit_payload(
    *,
    output_mode: str,
    url: str,
    api_key: str,
    payload: dict,
    timeout: int = 15,
    require_https: bool = True
) -> bool:
    step = "services.emit_payload"
    mode = (output_mode or "console").strip().lower()

    tls_verify_env = os.getenv("BACKEND_TLS_VERIFY", "true").strip().lower()
    tls_verify = tls_verify_env in {"1", "true", "yes", "y", "on"}

    try:
        if mode == "console":
            print("\n" + "=" * 90)
            print("TXDXAI INGEST (console-only)")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("=" * 90 + "\n")
            return True

        if not url:
            raise ValueError("TXDXAI_INGEST_URL vacío")

        if require_https and not url.startswith("https://"):
            raise ValueError("Backend URL debe ser HTTPS (o usa OUTPUT_MODE=console)")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 🔻 Ignorar warnings cuando verify=False (modo laboratorio)
        if not tls_verify:
            try:
                import urllib3  # type: ignore
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

        r = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            verify=tls_verify,  # ✅ aquí se ignora el certificado
        )

        if 200 <= r.status_code < 300:
            print(f"OK backend ({r.status_code})")
            return True

        snippet = (r.text or "")[:300]
        raise RuntimeError(f"Backend rechazó: HTTP {r.status_code}. Respuesta: {snippet}")

    except requests.exceptions.SSLError as e:
        # ✅ no crashea
        print(format_exception(step, e, {"url": url, "tls_verify": tls_verify, "accion": "se ignora SSL y se continúa"}))
        return False
    except requests.exceptions.RequestException as e:
        print(format_exception(step, e, {"url": url, "tls_verify": tls_verify}))
        return False
    except Exception as e:
        print(format_exception(step, e, {"mode": mode, "url": url}))
        return False
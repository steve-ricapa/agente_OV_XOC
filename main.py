import os
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import time
import traceback

from config import (
    OUTPUT_MODE,
    TXDXAI_INGEST_URL,
    TXDXAI_COMPANY_ID,
    TXDXAI_API_KEY,
    COLLECTOR,
    POLL_SECONDS,
    STATE_PATH,
    META_MAX_KB,
    GVM_HOST,
    GVM_PORT,
    GVM_USERNAME,
    GVM_PASSWORD,
    GVM_TLS_VERIFY,
)

from gvm_client import GVMClient
from services import FileLock, load_state, save_state, extract_severities, emit_payload

# XML parser best-effort
try:
    from defusedxml import ElementTree as ET  # type: ignore
except Exception:
    import xml.etree.ElementTree as ET


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


DEBUG = _bool_env("DEBUG", False)
MAX_ERROR_REPEAT = int(os.getenv("MAX_ERROR_REPEAT", "3"))


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


_error_counts = {}


def handle_exception(step: str, e: BaseException, context: dict):
    """
    Reporte ultra descriptivo con anti-spam:
    - step: punto exacto
    - tipo/motivo
    - contexto
    - sugerencia
    - stacktrace si DEBUG=1
    """
    sig = (step, type(e).__name__, str(e))
    _error_counts[sig] = _error_counts.get(sig, 0) + 1
    count = _error_counts[sig]

    if count > MAX_ERROR_REPEAT:
        if count == MAX_ERROR_REPEAT + 1:
            print(f"[{now()}] ERROR @ {step} repetido >{MAX_ERROR_REPEAT} veces. Se silenciará.")
        return

    print("\n" + "!" * 90)
    print(f"[{now()}] ERROR @ {step}")
    print(f"Tipo: {type(e).__name__}")
    print(f"Motivo: {str(e) if str(e) else '(sin mensaje)'}")
    print("Contexto:")
    for k, v in context.items():
        print(f"  - {k}: {v}")

    suggestion = "Revisa variables de entorno, conectividad y logs."
    if isinstance(e, PermissionError):
        suggestion = "Revisa permisos de archivos/rutas."
    elif isinstance(e, FileNotFoundError):
        suggestion = "Revisa rutas/archivos. Si es state.json, se crea al guardar."
    elif isinstance(e, ValueError) and "HTTPS" in str(e):
        suggestion = "Usa OUTPUT_MODE=console o cambia el backend a https://"
    elif isinstance(e, ET.ParseError):
        suggestion = "El XML está mal formado o incompleto."
    print(f"Sugerencia: {suggestion}")

    if DEBUG:
        print("Stacktrace:")
        print(traceback.format_exc())

    print("!" * 90 + "\n")


def validate_config():
    if POLL_SECONDS <= 0:
        raise ValueError("POLL_SECONDS debe ser > 0")
    if not STATE_PATH:
        raise ValueError("STATE_PATH vacío")
    if META_MAX_KB <= 0:
        raise ValueError("META_MAX_KB debe ser > 0")
    if COLLECTOR != "gmp":
        raise ValueError("COLLECTOR no soportado (usa 'gmp')")

    if (OUTPUT_MODE or "console").lower() == "backend":
        if not TXDXAI_INGEST_URL:
            raise ValueError("TXDXAI_INGEST_URL vacío (modo backend)")
        if not TXDXAI_INGEST_URL.startswith("https://"):
            raise ValueError("Backend URL debe ser HTTPS (modo backend)")
        if not TXDXAI_API_KEY:
            print(f"[{now()}] WARN: TXDXAI_API_KEY vacío (modo backend). Puede fallar auth.")


def safe_sleep(seconds: int):
    try:
        time.sleep(seconds)
    except Exception as e:
        handle_exception("sleep", e, {"seconds": seconds})


def main_loop():
    print("=== AGENTE GMP (LAB) ===")
    print(f"[{now()}] OUTPUT_MODE={OUTPUT_MODE} | COLLECTOR={COLLECTOR} | POLL_SECONDS={POLL_SECONDS}s")
    print(f"[{now()}] STATE_PATH={STATE_PATH} | META_MAX_KB={META_MAX_KB}KB")
    print(f"[{now()}] GVM_HOST={GVM_HOST}:{GVM_PORT} | TLS_VERIFY={GVM_TLS_VERIFY}")

    try:
        validate_config()
    except Exception as e:
        handle_exception("startup.validate_config", e, {
            "OUTPUT_MODE": OUTPUT_MODE,
            "COLLECTOR": COLLECTOR,
            "POLL_SECONDS": POLL_SECONDS,
            "STATE_PATH": STATE_PATH,
            "META_MAX_KB": META_MAX_KB
        })
        raise SystemExit(1)

    lock_path = f"{STATE_PATH}.lock"

    while True:
        print(f"\n[{now()}] Nuevo ciclo")

        try:
            # ===== STEP A: estado con lock =====
            with FileLock(lock_path):
                try:
                    state = load_state(STATE_PATH)
                    sent = set(state.get("sent", []))
                except Exception as e:
                    handle_exception("cycle.load_state", e, {"STATE_PATH": STATE_PATH})
                    sent = set()

                # ===== STEP B: obtener tasks XML =====
                try:
                    with GVMClient(GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD, GVM_TLS_VERIFY) as client:
                        tasks_xml = client.get_tasks()
                except Exception as e:
                    handle_exception("cycle.gvm.get_tasks", e, {
                        "GVM_HOST": GVM_HOST,
                        "GVM_PORT": GVM_PORT,
                        "TLS_VERIFY": GVM_TLS_VERIFY
                    })
                    # sin tasks no seguimos este ciclo
                    raise

                # ===== STEP C: parse tasks =====
                try:
                    if len(tasks_xml.encode("utf-8", errors="ignore")) > (META_MAX_KB * 1024):
                        raise ValueError("XML de tasks excede META_MAX_KB")

                    root = ET.fromstring(tasks_xml)
                    tasks = root.findall(".//task")
                    print(f"[{now()}] Tareas detectadas: {len(tasks)}")
                except Exception as e:
                    handle_exception("cycle.parse_tasks_xml", e, {"META_MAX_KB": META_MAX_KB})
                    raise

                # ===== STEP D: procesar tasks/reportes =====
                try:
                    with GVMClient(GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD, GVM_TLS_VERIFY) as client:
                        for idx, task in enumerate(tasks):
                            last = task.find("last_report/report")
                            if last is None:
                                continue

                            report_id = last.get("id")
                            if not report_id:
                                continue

                            if report_id in sent:
                                continue

                            print(f"[{now()}] Procesando reporte {report_id}")

                            # D1) get report XML
                            try:
                                report_xml = client.get_report(report_id)
                            except Exception as e:
                                handle_exception(f"cycle.task[{idx}].gvm.get_report", e, {"report_id": report_id})
                                continue

                            # D2) extract severities
                            try:
                                severities = extract_severities(report_xml, max_kb=META_MAX_KB)
                            except Exception as e:
                                handle_exception(f"cycle.task[{idx}].extract_severities", e, {
                                    "report_id": report_id,
                                    "META_MAX_KB": META_MAX_KB
                                })
                                continue

                            # D3) build payload
                            payload = {
                                "companyId": TXDXAI_COMPANY_ID,
                                "scanId": report_id,
                                "scannerType": "openvas",
                                "collector": COLLECTOR,
                                "results": severities,
                            }

                            # D4) emit
                            ok = emit_payload(
                                output_mode=OUTPUT_MODE,
                                url=TXDXAI_INGEST_URL,
                                api_key=TXDXAI_API_KEY,
                                payload=payload,
                                timeout=15,
                                require_https=True,
                            )

                            if ok:
                                sent.add(report_id)
                                try:
                                    save_state(STATE_PATH, {"sent": sorted(list(sent))})
                                except Exception as e:
                                    handle_exception(f"cycle.task[{idx}].save_state", e, {"STATE_PATH": STATE_PATH})
                            else:
                                print(f"[{now()}] WARN: Emisión falló, no se marca sent: {report_id}")

                except Exception as e:
                    handle_exception("cycle.process_tasks_loop", e, {})
                    # no abortamos el agente; continuamos al sleep

        except KeyboardInterrupt:
            print(f"\n[{now()}] Detenido por usuario (Ctrl+C).")
            break
        except Exception as e:
            handle_exception("cycle.top_level", e, {"accion": "Se continuará el siguiente ciclo"})

        print(f"[{now()}] Esperando {POLL_SECONDS}s")
        safe_sleep(POLL_SECONDS)


if __name__ == "__main__":
    main_loop()

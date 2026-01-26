import os
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import time
import socket
import xml.etree.ElementTree as ET

from config import (
    OUTPUT_MODE, TXDXAI_INGEST_URL, TXDXAI_COMPANY_ID, TXDXAI_API_KEY,
    COLLECTOR, POLL_SECONDS, STATE_PATH, META_MAX_KB,
    GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD, GVM_SOCKET,
    DEBUG, MAX_ERROR_REPEAT
)

from services import FileLock, load_state, save_state, extract_severities, emit_payload, format_exception


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


_error_counts = {}


def _signature(step: str, e: BaseException) -> tuple:
    return (step, type(e).__name__, str(e))


def _is_win_error(e: BaseException, code: int) -> bool:
    s = str(e)
    return f"WinError {code}" in s or f"[WinError {code}]" in s


def _suggestion(step: str, e: BaseException, context: dict) -> str:
    if isinstance(e, ModuleNotFoundError):
        if "gvm" in str(e).lower():
            return "Falta python-gvm en ESTE entorno/venv. Instala deps o usa COLLECTOR=simulated."
        return "Falta un módulo. Verifica requirements y que el venv esté activo."

    if isinstance(e, socket.gaierror):
        return "Error DNS (no resuelve host). Revisa nombre, DNS, o usa IP."
    if isinstance(e, TimeoutError):
        if _is_win_error(e, 10060):
            return "Host/puerto no responde (WinError 10060). Verifica IP/puerto/firewall/gvmd."
        return "Timeout: el host/servicio no respondió."

    if isinstance(e, ConnectionRefusedError):
        return "Conexión rechazada: puerto cerrado o servicio caído."
    if _is_win_error(e, 10061):
        return "WinError 10061: conexión rechazada."

    if "ssl" in type(e).__name__.lower() or "certificate" in str(e).lower():
        return "Problema TLS/certificado."

    if isinstance(e, ET.ParseError) or "ParseError" in type(e).__name__:
        return "XML inválido. Revisa META_MAX_KB o reporte."

    if isinstance(e, PermissionError):
        return "Permiso denegado: revisa permisos."

    return "Revisa logs, variables y servicio gvmd."


def handle_exception(step: str, e: BaseException, context: dict):
    sig = _signature(step, e)
    _error_counts[sig] = _error_counts.get(sig, 0) + 1
    n = _error_counts[sig]

    if n > MAX_ERROR_REPEAT:
        if n == MAX_ERROR_REPEAT + 1:
            print(f"[{now()}] ERROR @ {step} repetido >{MAX_ERROR_REPEAT} veces. Se silenciará.")
        return

    print("\n" + "!" * 90)
    print(format_exception(step, e, context))
    print(f"Sugerencia: {_suggestion(step, e, context)}")
    if step.startswith("cycle.gvm"):
        if GVM_SOCKET:
            print(f"Tip: usando socket GMP: {GVM_SOCKET}")
        else:
            print("Tip: valida conectividad al puerto GMP (9390 típicamente).")
    print("!" * 90 + "\n")


def simulated_tasks_xml() -> str:
    return """
    <get_tasks_response>
      <tasks>
        <task><last_report><report id="sim-report-1"/></last_report></task>
        <task><last_report><report id="sim-report-2"/></last_report></task>
      </tasks>
    </get_tasks_response>
    """.strip()


def simulated_report_xml(report_id: str) -> str:
    return f"""
    <get_report_response>
      <report id="{report_id}">
        <results>
          <result><severity>9.3</severity></result>
          <result><severity>7.5</severity></result>
          <result><severity>5.0</severity></result>
          <result><severity>3.2</severity></result>
        </results>
      </report>
    </get_report_response>
    """.strip()


def _parse_result_count(task_node: ET.Element) -> dict[str, int] | None:
    """
    Intenta leer el resumen directo del task XML:
      <last_report>...<result_count><high>..</high>...</result_count>...</last_report>
    Si está, devuelve dict critical/high/medium/low.
    """
    rc = task_node.find(".//last_report//result_count")
    if rc is None:
        return None

    def _get(tag: str) -> int:
        try:
            return int((rc.findtext(tag, "0") or "0").strip())
        except Exception:
            return 0

    # GVM puede usar critical/high/medium/low o equivalentes viejos.
    out = {
        "critical": _get("critical"),
        "high": _get("high"),
        "medium": _get("medium"),
        "low": _get("low"),
    }
    # Si todo es 0 pero hay "hole/warning/info/log", igual devolvemos None
    # para permitir fallback a get_report.
    if out["critical"] == 0 and out["high"] == 0 and out["medium"] == 0 and out["low"] == 0:
        return None
    return out


print("=== AGENTE GMP (LAB) ===")
print(f"[{now()}] OUTPUT_MODE={OUTPUT_MODE} | COLLECTOR={COLLECTOR} | POLL_SECONDS={POLL_SECONDS}s")
print(f"[{now()}] STATE_PATH={STATE_PATH} | META_MAX_KB={META_MAX_KB}KB")
print(f"[{now()}] GVM_HOST={GVM_HOST}:{GVM_PORT}")
if GVM_SOCKET:
    print(f"[{now()}] GVM_SOCKET={GVM_SOCKET}")

lock_path = f"{STATE_PATH}.lock"

while True:
    print(f"\n[{now()}] Nuevo ciclo")

    try:
        with FileLock(lock_path):
            # load state
            state = load_state(STATE_PATH)
            sent = set(state.get("sent", []))

            # get tasks
            tasks_xml = None
            active_collector = (COLLECTOR or "simulated").strip().lower()

            if active_collector == "gmp":
                from gvm_client import GVMClient
                with GVMClient(
                    GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD,
                    socket_path=GVM_SOCKET
                ) as client:
                    tasks_xml = client.get_tasks()

            elif active_collector == "simulated":
                tasks_xml = simulated_tasks_xml()
            else:
                raise ValueError("COLLECTOR inválido. Usa 'gmp' o 'simulated'.")

            # parse tasks
            if len(tasks_xml.encode("utf-8", errors="ignore")) > (META_MAX_KB * 1024):
                raise ValueError("XML de tasks excede META_MAX_KB")

            root = ET.fromstring(tasks_xml)
            tasks = root.findall(".//task")
            print(f"[{now()}] Tareas detectadas: {len(tasks)}")

            for idx, task in enumerate(tasks):
                try:
                    last = task.find(".//last_report//report")
                    if last is None:
                        if DEBUG:
                            print(f"[{now()}] task[{idx}] sin last_report")
                        continue

                    report_id = last.get("id")
                    if not report_id:
                        if DEBUG:
                            print(f"[{now()}] task[{idx}] last_report sin id")
                        continue

                    if report_id in sent:
                        continue

                    # ✅ FAST PATH: usa result_count si existe
                    severities = _parse_result_count(task)

                    # fallback: descargar reporte y parsear
                    if severities is None:
                        if active_collector == "simulated":
                            report_xml = simulated_report_xml(report_id)
                        else:
                            from gvm_client import GVMClient
                            with GVMClient(
                                GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD,
                                socket_path=GVM_SOCKET
                            ) as client:
                                report_xml = client.get_report(report_id)

                        severities = extract_severities(report_xml, max_kb=META_MAX_KB)

                    payload = {
                        "companyId": TXDXAI_COMPANY_ID,
                        "scanId": report_id,
                        "scannerType": "openvas",
                        "collector": active_collector,
                        "results": severities,
                    }

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
                        save_state(STATE_PATH, {"sent": sorted(list(sent))})

                except Exception as e:
                    handle_exception(f"cycle.task[{idx}].process", e, {"hint": "Fallo procesando task/report"})
                    continue

    except KeyboardInterrupt:
        print(f"\n[{now()}] Detenido por usuario (Ctrl+C).")
        break
    except Exception as e:
        handle_exception("cycle.top_level", e, {"accion": "Se continuará el siguiente ciclo"})

    print(f"[{now()}] Esperando {POLL_SECONDS}s")
    time.sleep(POLL_SECONDS)

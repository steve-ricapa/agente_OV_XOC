import os
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import time
import traceback
import socket
import xml.etree.ElementTree as ET

from config import (
    OUTPUT_MODE, TXDXAI_INGEST_URL, TXDXAI_COMPANY_ID, TXDXAI_API_KEY,
    COLLECTOR, POLL_SECONDS, STATE_PATH, META_MAX_KB,
    GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD,
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
    """
    Sugerencias con cobertura alta: red, DNS, TLS, permisos, XML, JSON, módulos, auth.
    """
    # 1) Módulos faltantes
    if isinstance(e, ModuleNotFoundError):
        if "gvm" in str(e).lower():
            return "Falta python-gvm en ESTE entorno/venv. Instala deps en ese venv o usa COLLECTOR=simulated."
        return "Falta un módulo. Verifica requirements y que el venv esté activo."

    # 2) DNS / socket / red
    if isinstance(e, socket.gaierror):
        return "Error DNS (no resuelve host). Revisa nombre, DNS, o usa IP."
    if isinstance(e, TimeoutError):
        # Windows 10060 / Linux timeout
        if _is_win_error(e, 10060):
            return "El host/puerto no responde (WinError 10060). Verifica IP, puerto, firewall, que gvmd esté escuchando y red/VLAN."
        return "Timeout: el host/servicio no respondió a tiempo. Verifica conectividad y carga del servidor."

    # 3) Conexión rechazada / no route
    if isinstance(e, ConnectionRefusedError):
        return "Conexión rechazada: puerto cerrado o servicio caído. Verifica que gvmd escuche en ese puerto (9390 típicamente)."
    if _is_win_error(e, 10061):
        return "WinError 10061: conexión rechazada. Puerto cerrado o firewall en destino."
    if _is_win_error(e, 10065):
        return "WinError 10065: no route to host. Revisa gateway/rutas/VLAN."
    if _is_win_error(e, 10051):
        return "WinError 10051: red inalcanzable. Revisa Wi-Fi/VLAN/rutas."

    # 4) SSL/TLS (si se manifiesta en el stack)
    if "ssl" in type(e).__name__.lower() or "certificate" in str(e).lower():
        return "Problema TLS/certificado. Usa certificados válidos, CA correcta o prueba en lab con config TLS adecuada."

    # 5) XML
    if isinstance(e, ET.ParseError) or "ParseError" in type(e).__name__:
        return "XML inválido/mal formado. Verifica que el reporte esté completo y que META_MAX_KB no lo corte."

    # 6) JSON / state
    if isinstance(e, ValueError) and "state" in step:
        return "State corrupto o estructura inesperada. Borra state.json para reiniciar deduplicación."

    # 7) Permisos / FS
    if isinstance(e, PermissionError):
        return "Permiso denegado: revisa permisos en la carpeta/archivo (state.json, lock, etc.)."
    if isinstance(e, FileNotFoundError):
        return "Archivo no encontrado: revisa rutas/working directory y STATE_PATH."

    # 8) Auth / credenciales (heurístico)
    msg = str(e).lower()
    if "unauthorized" in msg or "authentication" in msg or "not authorized" in msg or "login" in msg:
        return "Falló autenticación. Revisa GVM_USERNAME/GVM_PASSWORD y permisos del usuario en gvmd."

    return "Revisa variables de entorno, conectividad, puertos, servicio gvmd y logs del agente/servidor."


def handle_exception(step: str, e: BaseException, context: dict):
    """
    Handler central:
    - Paso exacto + razón
    - Contexto completo
    - Sugerencia altamente específica
    - Stacktrace si DEBUG=1
    - Anti-spam por firma (MAX_ERROR_REPEAT)
    """
    sig = _signature(step, e)
    _error_counts[sig] = _error_counts.get(sig, 0) + 1
    n = _error_counts[sig]

    if n > MAX_ERROR_REPEAT:
        if n == MAX_ERROR_REPEAT + 1:
            print(f"[{now()}] ERROR @ {step} repetido >{MAX_ERROR_REPEAT} veces. Se silenciará.")
        return

    print("\n" + "!" * 90)
    # Mensaje principal ultra detallado (incluye causa raíz y stacktrace si DEBUG)
    # reutilizamos format_exception de services para consistencia
    print(format_exception(step, e, context))

    # Sugerencia de alta cobertura
    print(f"Sugerencia: {_suggestion(step, e, context)}")

    # Extra: tips por step
    if step.startswith("cycle.gvm"):
        print("Tip: valida conectividad con Test-NetConnection (Windows) o nc/telnet (Linux) al puerto GMP (9390 típicamente).")

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


print("=== AGENTE GMP (LAB) ===")
print(f"[{now()}] OUTPUT_MODE={OUTPUT_MODE} | COLLECTOR={COLLECTOR} | POLL_SECONDS={POLL_SECONDS}s")
print(f"[{now()}] STATE_PATH={STATE_PATH} | META_MAX_KB={META_MAX_KB}KB")
print(f"[{now()}] GVM_HOST={GVM_HOST}:{GVM_PORT}")

lock_path = f"{STATE_PATH}.lock"

while True:
    print(f"\n[{now()}] Nuevo ciclo")

    try:
        with FileLock(lock_path):
            # STEP: load state
            try:
                state = load_state(STATE_PATH)
                sent = set(state.get("sent", []))
            except Exception as e:
                handle_exception("cycle.state.load", e, {"STATE_PATH": STATE_PATH, "accion": "sent=set()"})
                sent = set()

            # STEP: get tasks
            tasks_xml = None
            active_collector = COLLECTOR

            if active_collector == "gmp":
                try:
                    from gvm_client import GVMClient
                    with GVMClient(GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD) as client:
                        tasks_xml = client.get_tasks()
                except ModuleNotFoundError as e:
                    # fallback automático
                    handle_exception("cycle.gvm.missing_module", e, {"accion": "fallback a simulated"})
                    active_collector = "simulated"
                    tasks_xml = simulated_tasks_xml()
                except Exception as e:
                    handle_exception("cycle.gvm.get_tasks", e, {"GVM_HOST": GVM_HOST, "GVM_PORT": GVM_PORT})
                    raise  # sin tasks no seguimos este ciclo

            elif active_collector == "simulated":
                tasks_xml = simulated_tasks_xml()
            else:
                raise ValueError("COLLECTOR inválido. Usa 'gmp' o 'simulated'.")

            # STEP: parse tasks
            try:
                if len(tasks_xml.encode("utf-8", errors="ignore")) > (META_MAX_KB * 1024):
                    raise ValueError("XML de tasks excede META_MAX_KB")
                root = ET.fromstring(tasks_xml)
                tasks = root.findall(".//task")
                print(f"[{now()}] Tareas detectadas: {len(tasks)}")
            except Exception as e:
                handle_exception("cycle.xml.parse_tasks", e, {"META_MAX_KB": META_MAX_KB})
                raise

            # STEP: process tasks
            for idx, task in enumerate(tasks):
                step_prefix = f"cycle.task[{idx}]"

                try:
                    last = task.find("last_report/report")
                    if last is None:
                        continue

                    report_id = last.get("id")
                    if not report_id:
                        continue

                    if report_id in sent:
                        continue

                    # get report
                    if active_collector == "simulated":
                        report_xml = simulated_report_xml(report_id)
                    else:
                        from gvm_client import GVMClient
                        with GVMClient(GVM_HOST, GVM_PORT, GVM_USERNAME, GVM_PASSWORD) as client:
                            report_xml = client.get_report(report_id)

                    # extract severities
                    severities = extract_severities(report_xml, max_kb=META_MAX_KB)

                    # build payload
                    payload = {
                        "companyId": TXDXAI_COMPANY_ID,
                        "scanId": report_id,
                        "scannerType": "openvas",
                        "collector": active_collector,
                        "results": severities,
                    }

                    # emit payload
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
                            handle_exception(f"{step_prefix}.state.save", e, {"STATE_PATH": STATE_PATH})

                except Exception as e:
                    handle_exception(f"{step_prefix}.process", e, {"hint": "Fallo procesando task/report"})
                    continue

    except KeyboardInterrupt:
        print(f"\n[{now()}] Detenido por usuario (Ctrl+C).")
        break
    except Exception as e:
        handle_exception("cycle.top_level", e, {"accion": "Se continuará el siguiente ciclo"})

    print(f"[{now()}] Esperando {POLL_SECONDS}s")
    time.sleep(POLL_SECONDS)

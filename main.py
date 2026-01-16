import time
import xml.etree.ElementTree as ET

from config import *
from services import *
from gvm_client import GVMClient

print("=== AGENTE GMP ===")

state = load_state(STATE_PATH)
sent = set(state["sent"])

while True:

    print("Nuevo ciclo")

    try:
        if COLLECTOR != "gmp":
            print("COLLECTOR no soportado")
            break

        with GVMClient(
            GVM_HOST,
            GVM_PORT,
            GVM_USERNAME,
            GVM_PASSWORD,
            GVM_TLS_VERIFY
        ) as client:

            tasks_xml = client.get_tasks()
            root = ET.fromstring(tasks_xml)
            tasks = root.findall(".//task")

            print(f"Tareas: {len(tasks)}")

            for task in tasks:

                last = task.find("last_report/report")

                if last is None:
                    continue

                report_id = last.get("id")

                if report_id in sent:
                    continue

                print(f"Procesando reporte {report_id}")

                report_xml = client.get_report(report_id)
                severities = extract_severities(report_xml)

                payload = {
                    "companyId": TXDXAI_COMPANY_ID,
                    "apiKey": TXDXAI_API_KEY,
                    "scanId": report_id,
                    "scannerType": "openvas",
                    "results": severities
                }

                ok = send_to_backend(
                    TXDXAI_INGEST_URL,
                    payload
                )

                if ok:
                    sent.add(report_id)
                    save_state(
                        STATE_PATH,
                        {"sent": list(sent)}
                    )

    except Exception as e:
        print("ERROR GENERAL:", e)

    print(f"Esperando {POLL_SECONDS}s")
    time.sleep(POLL_SECONDS)

import os
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

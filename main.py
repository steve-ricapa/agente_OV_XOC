#!/usr/bin/env python3
import os
import time
import json
import traceback
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import requests

load_dotenv()

# =========================
# Helpers
# =========================
def env(name, required=True, default=None):
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise RuntimeError(f"Missing env var: {name}")
    return v

# =========================
# Config
# =========================
POLL_SECONDS = 15
STATE_FILE = env("STATE_PATH", default="./state.json")

TXDXAI_INGEST_URL = env("TXDXAI_INGEST_URL")
TXDXAI_COMPANY_ID = int(env("TXDXAI_COMPANY_ID"))
TXDXAI_API_KEY = env("TXDXAI_API_KEY")

GVM_SOCKET_PATH = env("GVM_SOCKET_PATH")
GVM_USERNAME = env("GVM_USERNAME")
GVM_PASSWORD = env("GVM_PASSWORD")

# =========================
# python-gvm
# =========================
from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp

print("=== OpenVAS Agent v3 (SEND TO BACKEND) ===")
print(f"Polling cada {POLL_SECONDS}s")
print("=========================================\n")

# =========================
# Estado (dedupe)
# =========================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"sent_reports": []}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

state = load_state()
sent_reports = set(state.get("sent_reports", []))

# =========================
# Lógica
# =========================
def map_status(raw: str) -> str:
    s = raw.lower()
    if "done" in s or "completed" in s:
        return "completed"
    if "run" in s:
        return "running"
    return "pending"

def extract_severities(report_xml: str) -> dict:
    root = ET.fromstring(report_xml)
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for result in root.findall(".//result"):
        sev_text = result.findtext("severity")
        if not sev_text:
            continue
        try:
            sev = float(sev_text)
        except ValueError:
            continue

        if sev >= 9.0:
            counts["critical"] += 1
        elif sev >= 7.0:
            counts["high"] += 1
        elif sev >= 4.0:
            counts["medium"] += 1
        else:
            counts["low"] += 1

    return counts

def send_to_backend(payload: dict):
    try:
        r = requests.post(
            TXDXAI_INGEST_URL,
            json=payload,
            timeout=20
        )
        if r.status_code >= 200 and r.status_code < 300:
            print("✅ Enviado correctamente al backend")
            return True
        else:
            print("❌ Error backend:", r.status_code, r.text)
            return False
    except Exception as e:
        print("❌ Error enviando al backend:", e)
        return False

# =========================
# Loop principal
# =========================
while True:
    print("\n🔄 Nuevo ciclo de chequeo...\n")

    try:
        connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
        with Gmp(connection=connection) as gmp:
            gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

            tasks_xml = gmp.get_tasks()
            root = ET.fromstring(tasks_xml)
            tasks = root.findall(".//task")

            print(f"Scans detectados: {len(tasks)}\n")

            for task in tasks:
                task_id = task.get("id")
                name = task.findtext("name") or ""
                raw_status = task.findtext("status") or ""
                status = map_status(raw_status)

                last_report = task.find("last_report/report")
                report_id = last_report.get("id") if last_report is not None else None
                scan_start = last_report.findtext("scan_start") if last_report is not None else None

                print(f"Scan: {name} | status={status}")

                if status != "completed" or not report_id:
                    print("  ↳ Scan no finalizado, se ignora\n")
                    continue

                if report_id in sent_reports:
                    print("  ↳ Scan ya enviado, se omite\n")
                    continue

                print("  ↳ Scan COMPLETADO, leyendo reporte...")

                report_xml = gmp.get_report(report_id=report_id, details=True)
                severities = extract_severities(report_xml)

                payload = {
                    "companyId": TXDXAI_COMPANY_ID,
                    "apiKey": TXDXAI_API_KEY,
                    "scanId": report_id,
                    "scannerType": "openvas",
                    "scanName": name,
                    "status": "completed",
                    "scannedAt": scan_start,
                    "totalHosts": 0,
                    "results": severities,
                    "meta": {
                        "source": "openvas",
                        "taskId": task_id
                    }
                }

                print("📤 Enviando payload al backend...")
                success = send_to_backend(payload)

                if success:
                    sent_reports.add(report_id)
                    save_state({"sent_reports": list(sent_reports)})

    except Exception as e:
        print("❌ Error en ciclo principal:")
        print(type(e).__name__, e)
        traceback.print_exc()

    print(f"⏱ Esperando {POLL_SECONDS}s...\n")
    time.sleep(POLL_SECONDS)

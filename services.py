import os
import json
import time
import xml.etree.ElementTree as ET

# =========================
# Estado
# =========================

def load_state(path):
    if not os.path.exists(path):
        return {"sent": []}

    with open(path) as f:
        return json.load(f)


def save_state(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# =========================
# Procesamiento
# =========================

def extract_severities(xml_text):
    root = ET.fromstring(xml_text)

    result = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0
    }

    for r in root.findall(".//result"):
        try:
            sev = float(r.findtext("severity", "0"))
        except:
            continue

        if sev >= 9:
            result["critical"] += 1
        elif sev >= 7:
            result["high"] += 1
        elif sev >= 4:
            result["medium"] += 1
        else:
            result["low"] += 1

    return result


# =========================
# Backend (console-only)
# =========================

def send_to_backend(url, payload):
    """Modo consola: no envía nada por red.

    `url` se mantiene solo para compatibilidad con el flujo actual de `main.py`.
    """
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print("\n" + "=" * 90)
    print(f"[{ts}] TXDXAI INGEST (console-only) -> {url}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("=" * 90 + "\n")
    return True


def map_status(status: str) -> str:
    """Normaliza estados típicos (soporta los tests incluidos)."""
    s = (status or "").strip().lower()
    if s in {"running", "in progress", "in_progress"}:
        return "running"
    if s in {"pending", "queued", "wait", "waiting"}:
        return "pending"
    if s in {"completed", "done", "finished", "success"}:
        return "completed"
    return s

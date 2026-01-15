import os
import json
import xml.etree.ElementTree as ET
import requests

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
# Backend
# =========================

def send_to_backend(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=15)

        if 200 <= r.status_code < 300:
            print("OK -> enviado al backend")
            return True

        print(
            f"ERROR HTTP {r.status_code} "
            f"-> backend rechazó la petición"
        )
        return False

    except requests.exceptions.ConnectionError:
        print("ERROR -> no se pudo conectar al backend")
        return False

    except requests.exceptions.Timeout:
        print("ERROR -> timeout del backend")
        return False

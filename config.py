import os
from dotenv import load_dotenv

load_dotenv()

# =========================
# Backend
# =========================
TXDXAI_INGEST_URL = os.getenv("TXDXAI_INGEST_URL", "console://stdout")
TXDXAI_COMPANY_ID = int(os.getenv("TXDXAI_COMPANY_ID", "0"))
TXDXAI_API_KEY = os.getenv("TXDXAI_API_KEY", "")

# =========================
# Agent config
# =========================
COLLECTOR = os.getenv("COLLECTOR")
POLL_SECONDS = int(os.getenv("POLL_SECONDS"))
STATE_PATH = os.getenv("STATE_PATH")
META_MAX_KB = int(os.getenv("META_MAX_KB"))

# =========================
# OpenVAS / GVM
# =========================
GVM_HOST = os.getenv("GVM_HOST")
GVM_PORT = int(os.getenv("GVM_PORT"))
GVM_USERNAME = os.getenv("GVM_USERNAME")
GVM_PASSWORD = os.getenv("GVM_PASSWORD")
GVM_TLS_VERIFY = os.getenv("GVM_TLS_VERIFY") == "true"

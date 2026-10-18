"""Environment variables and repository paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logging_config import configure_logging, get_log_file_path, get_logger

configure_logging()
logger = get_logger(__name__)

DATA_RAW_DIR = Path(os.environ.get("HIL_DATA_RAW_DIR", PROJECT_ROOT / "data" / "raw"))
VEHICLE_PROGRAM_ECUS_CSV = DATA_RAW_DIR / "vehicle_program_ecus.csv"
RIG_CAPABILITIES_CSV = DATA_RAW_DIR / "rig_capabilities.csv"
FEATURE_REQUIREMENTS_CSV = DATA_RAW_DIR / "feature_requirements.csv"
CIARA_BOOKINGS_CSV = DATA_RAW_DIR / "ciara_bookings.csv"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
if not GEMINI_MODEL:
    raise ValueError("GEMINI_MODEL must not be empty.")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().casefold()
if LLM_PROVIDER not in {"gemini", "ollama"}:
    raise ValueError("LLM_PROVIDER must be either 'gemini' or 'ollama'.")
OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://localhost:11434"
).strip().rstrip("/")
if not OLLAMA_BASE_URL.startswith(("http://", "https://")):
    raise ValueError("OLLAMA_BASE_URL must be an HTTP or HTTPS URL.")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b").strip()
if not OLLAMA_MODEL:
    raise ValueError("OLLAMA_MODEL must not be empty.")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "180"))
OLLAMA_MAX_TOOL_ROUNDS = int(os.environ.get("OLLAMA_MAX_TOOL_ROUNDS", "8"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
if min(OLLAMA_TIMEOUT_SECONDS, OLLAMA_MAX_TOOL_ROUNDS, OLLAMA_NUM_CTX) <= 0:
    raise ValueError(
        "OLLAMA_TIMEOUT_SECONDS, OLLAMA_MAX_TOOL_ROUNDS, and OLLAMA_NUM_CTX "
        "must be positive integers."
    )
ACTIVE_MODEL = GEMINI_MODEL if LLM_PROVIDER == "gemini" else OLLAMA_MODEL

logger.info(
    "Settings loaded: project_root=%s data_raw_dir=%s llm_provider=%s "
    "active_model=%s api_key_configured=%s ollama_base_url=%s log_file=%s",
    PROJECT_ROOT,
    DATA_RAW_DIR,
    LLM_PROVIDER,
    ACTIVE_MODEL,
    bool(GEMINI_API_KEY),
    OLLAMA_BASE_URL,
    get_log_file_path(),
)

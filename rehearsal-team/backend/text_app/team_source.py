"""Load the actual teammate backend from the sibling repository, never a copy."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

REPOSITORY = Path(__file__).resolve().parents[3]
UPSTREAM = REPOSITORY / "backend"
if not (UPSTREAM / "app/bot.py").is_file():
    raise RuntimeError("Clone the complete AiProductHack repository; rehearsal-team uses ../backend/app.")
load_dotenv(os.getenv("REHEARSAL_CONFIG_FILE", str(REPOSITORY / "rehearsal-team/.env.local")), override=False)
os.environ.setdefault("WHISPER_MODEL", "small")
os.environ.setdefault("WHISPER_DEVICE", "cpu")
os.environ.setdefault("WHISPER_COMPUTE_TYPE", "int8")
sys.path.insert(0, str(UPSTREAM))

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://jobs.ge/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

IT_CATEGORY_ID = int(os.getenv("IT_CATEGORY_ID", "6"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
JOB_LIMIT = int(os.getenv("JOB_LIMIT", "15"))
TIMESTAMP_FORMAT = os.getenv("TIMESTAMP_FORMAT", "%d/%m/%Y")

EXCLUDE_KEYWORDS = tuple(k.strip() for k in os.getenv("EXCLUDE_KEYWORDS", "senior,.net,Java,UX/UI,PHP").split(","))

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "seen_jobs.json"
CSV_FILE = BASE_DIR / "seen_jobs.csv"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("telegram_bot_token", os.getenv("telegram_bot")))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("telegram_chat_id"))


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
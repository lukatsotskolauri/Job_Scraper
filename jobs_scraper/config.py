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
JOB_LIMIT = int(os.getenv("JOB_LIMIT", "15"))  # max jobs sent per category per run; the rest wait for the next run
MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "3"))  # only jobs posted within this many days count as new
TIMESTAMP_FORMAT = os.getenv("TIMESTAMP_FORMAT", "%d/%m/%Y")

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "seen_jobs.json"
CSV_FILE = BASE_DIR / "seen_jobs.csv"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("telegram_bot_token", os.getenv("telegram_bot")))
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", os.getenv("telegram_chat_id"))

# Private chat (usually your own user ID) that is told when the health check fails.
# Kept separate from the job chats so subscribers never see maintenance alerts.
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID")


def _parse_chat_categories(raw: str) -> list[tuple[str, int]]:
    """Parse "chat_id:category_id,chat_id:category_id" into a list of pairs."""
    chats: list[tuple[str, int]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        chat_id, sep, cid = item.rpartition(":")
        chat_id, cid = chat_id.strip(), cid.strip()
        if not sep or not chat_id or not cid.isdigit():
            raise ValueError(
                f"Invalid CHAT_CATEGORIES entry {item!r}; expected chat_id:category_id"
            )
        chats.append((chat_id, int(cid)))
    return chats


# Extra chats, each with its own jobs.ge category: "chat_id:cid,chat_id:cid".
# TELEGRAM_CHAT_ID keeps receiving IT jobs (IT_CATEGORY_ID) as before.
CHAT_CATEGORIES = _parse_chat_categories(os.getenv("CHAT_CATEGORIES", ""))
if TELEGRAM_CHAT_ID and all(chat != TELEGRAM_CHAT_ID for chat, _ in CHAT_CATEGORIES):
    CHAT_CATEGORIES.insert(0, (TELEGRAM_CHAT_ID, IT_CATEGORY_ID))


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
import json
import logging
from typing import List, Set, TYPE_CHECKING

from .config import STATE_FILE

if TYPE_CHECKING:
    from .models import JobListing

logger = logging.getLogger(__name__)


def load_seen_ids() -> Set[str]:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: Set[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def get_new_listings(listings: List["JobListing"]) -> List["JobListing"]:
    seen_ids = load_seen_ids()
    current_ids = {job.job_id for job in listings}

    new_listings = [job for job in listings if job.job_id not in seen_ids]

    save_seen_ids(seen_ids | current_ids)
    return new_listings
import json
import logging
from typing import Dict, List, Set, TYPE_CHECKING

from .config import STATE_FILE, IT_CATEGORY_ID

if TYPE_CHECKING:
    from .models import JobListing

logger = logging.getLogger(__name__)

# Seen job IDs, keyed by jobs.ge category ID (as a string): {"6": {"766959", ...}}
SeenState = Dict[str, Set[str]]


def load_seen() -> SeenState:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            logger.warning("State file is empty or corrupt, starting fresh.")
            return {}

        if isinstance(data, list):
            # Old format: a flat list of IT job IDs.
            return {str(IT_CATEGORY_ID): set(data)}
        if isinstance(data, dict):
            return {str(cid): set(ids) for cid, ids in data.items()}
        logger.warning("State file has unexpected format, starting fresh.")
    return {}


def save_seen(seen: SeenState) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {cid: sorted(ids) for cid, ids in sorted(seen.items())},
            f,
            ensure_ascii=False,
            indent=2,
        )


def get_new_listings(listings: List["JobListing"], seen_ids: Set[str]) -> List["JobListing"]:
    return [job for job in listings if job.job_id not in seen_ids]

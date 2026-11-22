import csv
import logging
from typing import List

import requests

from .config import TELEGRAM_BOT_TOKEN, REQUEST_TIMEOUT, CSV_FILE, IT_CATEGORY_ID
from .models import JobListing

logger = logging.getLogger(__name__)


def format_jobs_message(jobs: List[JobListing]) -> str:
    return "\n\n".join(f"[{job.timestamp}] {job.title}\n{job.url}" for job in jobs)


def send_telegram_message(jobs: List[JobListing], chat_id: str, cid: int = IT_CATEGORY_ID) -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram not sent. Set TELEGRAM_BOT_TOKEN.")
        return

    label = "IT job(s)" if cid == IT_CATEGORY_ID else f"job(s) in category {cid}"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"{len(jobs)} new {label} on jobs.ge\n\n{format_jobs_message(jobs)}",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Telegram request failed.") from exc

    if not response.ok:
        raise RuntimeError(f"Telegram API returned HTTP {response.status_code}: {response.text}")


def save_to_csv(jobs: List[JobListing]) -> None:
    file_exists = CSV_FILE.exists()

    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["job_id", "title", "url", "timestamp"])

        for job in jobs:
            writer.writerow([job.job_id, job.title, job.url, job.timestamp])

    logger.info("Saved %d job(s) to %s", len(jobs), CSV_FILE)
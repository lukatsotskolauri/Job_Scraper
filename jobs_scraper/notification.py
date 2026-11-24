import csv
import logging
from html import escape
from typing import List

import requests

from .config import TELEGRAM_BOT_TOKEN, ALERT_CHAT_ID, REQUEST_TIMEOUT, CSV_FILE, IT_CATEGORY_ID
from .models import JobListing

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096


def format_job(job: JobListing) -> str:
    """One job as Telegram HTML: a clickable title, then company and deadline."""
    lines = [f'<a href="{escape(job.url)}">{escape(job.title)}</a>']
    details = []
    if job.company:
        details.append(f"🏢 {escape(job.company)}")
    if job.deadline:
        details.append(f"⏳ {escape(job.deadline)}")
    if details:
        lines.append(" · ".join(details))
    return "\n".join(lines)


def format_jobs_message(jobs: List[JobListing]) -> str:
    return "\n\n".join(format_job(job) for job in jobs)


def build_messages(jobs: List[JobListing], header: str) -> List[str]:
    """Split jobs into as few messages as possible under Telegram's length limit."""
    messages: List[str] = []
    current = f"<b>{escape(header)}</b>"
    for job in jobs:
        entry = format_job(job)
        if len(current) + 2 + len(entry) > TELEGRAM_MAX_LENGTH:
            messages.append(current)
            current = entry
        else:
            current = f"{current}\n\n{entry}"
    messages.append(current)
    return messages


def send_telegram_message(jobs: List[JobListing], chat_id: str, cid: int = IT_CATEGORY_ID) -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram not sent. Set TELEGRAM_BOT_TOKEN.")
        return

    label = "IT job(s)" if cid == IT_CATEGORY_ID else f"job(s) in category {cid}"
    header = f"{len(jobs)} new {label} on jobs.ge"

    for text in build_messages(jobs, header):
        _post_message(chat_id, text)


def send_alert(problem: str) -> None:
    """Tell ALERT_CHAT_ID that the scraper is broken. Never raises."""
    if not TELEGRAM_BOT_TOKEN or not ALERT_CHAT_ID:
        logger.warning("Alert not sent. Set TELEGRAM_BOT_TOKEN and ALERT_CHAT_ID.")
        return

    text = (
        "<b>⚠️ jobs.ge scraper health check failed</b>\n\n"
        f"{escape(problem)}\n\n"
        "No jobs were sent this run. Check the workflow logs."
    )
    try:
        _post_message(ALERT_CHAT_ID, text)
        logger.info("Alert sent to %s.", ALERT_CHAT_ID)
    except RuntimeError:
        # The run is already failing; don't hide the real problem behind this one.
        logger.exception("Could not send the alert.")


def _post_message(chat_id: str, text: str) -> None:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
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
            writer.writerow(["job_id", "title", "url", "timestamp", "company", "posted", "deadline"])

        for job in jobs:
            writer.writerow(
                [job.job_id, job.title, job.url, job.timestamp, job.company, job.posted, job.deadline]
            )

    logger.info("Saved %d job(s) to %s", len(jobs), CSV_FILE)

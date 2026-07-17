from __future__ import annotations

import csv
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Set

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


load_dotenv()

BASE_URL = "https://jobs.ge/"
STATE_FILE = Path(__file__).parent / "seen_jobs.json"
CSV_FILE = Path(__file__).parent / "seen_jobs.csv"
IT_CATEGORY_ID = int(os.getenv("IT_CATEGORY_ID", "6"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
JOB_LIMIT = int(os.getenv("JOB_LIMIT", "15"))
TIMESTAMP_FORMAT = os.getenv("TIMESTAMP_FORMAT", "%d/%m/%Y")
EXCLUDE_KEYWORDS = tuple(k.strip() for k in os.getenv("EXCLUDE_KEYWORDS", "senior,.net,Java,UX/UI,PHP").split(","))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN", "telegram_bot_token", "telegram_bot")
TELEGRAM_CHAT_ID = get_env("TELEGRAM_CHAT_ID", "telegram_chat_id")


@dataclass
class JobListing:
    job_id: str
    title: str
    url: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_page(page: int = 1, cid: int = IT_CATEGORY_ID) -> str:
    params = {"page": page, "cid": cid}
    headers = {"User-Agent": USER_AGENT}

    response = requests.get(BASE_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_job_listings(html: str) -> List[JobListing]:
    soup = BeautifulSoup(html, "html.parser")
    job_link_pattern = re.compile(r"view=jobs&id=(\d+)")

    listings: List[JobListing] = []
    seen_ids: Set[str] = set()
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)

    for link in soup.find_all("a", href=job_link_pattern):
        title = link.get_text(strip=True)
        if not title:
            continue

        job_id = job_link_pattern.search(link["href"]).group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        listings.append(
            JobListing(
                job_id=job_id,
                title=title,
                url=f"https://jobs.ge/ge/?view=jobs&id={job_id}",
                timestamp=timestamp,
            )
        )

    return listings


def health_check() -> bool:
    try:
        html = fetch_page(page=1, cid=IT_CATEGORY_ID)
        soup = BeautifulSoup(html, "html.parser")
        
        job_link_pattern = re.compile(r"view=jobs&id=(\d+)")
        job_links = soup.find_all("a", href=job_link_pattern)
        
        if not job_links:
            logger.warning("Health check failed: No job links found. Site structure may have changed.")
            return False
        
        logger.info("Health check passed: Found %d job links on first page.", len(job_links))
        return True
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return False


def scrape_all_pages(
    max_pages: int = 3,
    cid: int = IT_CATEGORY_ID,
) -> List[JobListing]:
    all_listings: List[JobListing] = []
    for page in range(1, max_pages + 1):
        logger.info("Fetching page %d ...", page)
        html = fetch_page(page=page, cid=cid)
        page_listings = parse_job_listings(html)
        if not page_listings:
            logger.info("No listings on page %d, stopping.", page)
            break
        all_listings.extend(page_listings)
    return all_listings



def load_seen_ids() -> Set[str]:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: Set[str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def save_to_csv(jobs: List[JobListing]) -> None:
    file_exists = CSV_FILE.exists()
    
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        
        if not file_exists:
            writer.writerow(["job_id", "title", "url", "timestamp"])
        
        for job in jobs:
            writer.writerow([job.job_id, job.title, job.url, job.timestamp])
    
    logger.info("Saved %d job(s) to %s", len(jobs), CSV_FILE)


def get_new_listings(listings: List[JobListing]) -> List[JobListing]:
    seen_ids = load_seen_ids()
    current_ids = {job.job_id for job in listings}

    new_listings = [job for job in listings if job.job_id not in seen_ids]

    save_seen_ids(seen_ids | current_ids)
    return new_listings


def exclude_listings(listings: List[JobListing]) -> List[JobListing]:
    excluded_terms = tuple(term.lower() for term in EXCLUDE_KEYWORDS)
    return [
        job
        for job in listings
        if not any(term in job.title.lower() for term in excluded_terms)
    ]


def format_jobs_message(jobs: List[JobListing]) -> str:
    return "\n\n".join(f"[{job.timestamp}] {job.title}\n{job.url}" for job in jobs)


def send_telegram_message(jobs: List[JobListing]) -> None:
    if not all((TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)):
        logger.warning(
            "Telegram not sent. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
        )
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"{len(jobs)} new IT job(s) on jobs.ge\n\n{format_jobs_message(jobs)}",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Telegram request failed.") from exc

    if not response.ok:
        raise RuntimeError(f"Telegram API returned HTTP {response.status_code}.")

def main() -> None:
    if not health_check():
        logger.error("Aborting due to failed health check.")
        return
    
    listings = exclude_listings(scrape_all_pages(max_pages=MAX_PAGES))[:JOB_LIMIT]
    logger.info("Scraped %d total listings.", len(listings))

    new_listings = get_new_listings(listings)
    logger.info("%d new listing(s) since last run.", len(new_listings))

    if not new_listings:
        print("No new listings found.")
        return

    for job in new_listings:
        print(f"- [{job.timestamp}] {job.title}  ({job.url})")

    save_to_csv(new_listings)
    send_telegram_message(new_listings)


if __name__ == "__main__":
    main()

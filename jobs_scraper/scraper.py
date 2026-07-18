import logging
import re
from datetime import datetime
from typing import List

import requests
from bs4 import BeautifulSoup

from .config import BASE_URL, USER_AGENT, IT_CATEGORY_ID, REQUEST_TIMEOUT, TIMESTAMP_FORMAT
from .models import JobListing

logger = logging.getLogger(__name__)


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
    seen_ids: set = set()
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


def scrape_all_pages(max_pages: int = 3, cid: int = IT_CATEGORY_ID) -> List[JobListing]:
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
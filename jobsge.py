import logging

from jobs_scraper.config import MAX_PAGES, JOB_LIMIT
from jobs_scraper.scraper import health_check, scrape_all_pages
from jobs_scraper.filter import exclude_listings
from jobs_scraper.state import get_new_listings, load_seen_ids, save_seen_ids
from jobs_scraper.notification import save_to_csv, send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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

    send_telegram_message(new_listings)   # raises on failure, so nothing below runs
    save_to_csv(new_listings)
    save_seen_ids(load_seen_ids() | {job.job_id for job in new_listings})


if __name__ == "__main__":
    main()
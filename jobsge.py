import logging
import sys
from collections import defaultdict

from jobs_scraper.config import MAX_PAGES, JOB_LIMIT, CHAT_CATEGORIES, IT_CATEGORY_ID
from jobs_scraper.scraper import health_check, scrape_all_pages
from jobs_scraper.filter import exclude_listings
from jobs_scraper.state import get_new_listings, load_seen, save_seen
from jobs_scraper.notification import save_to_csv, send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_category(cid: int, chat_ids: list[str], seen: dict[str, set[str]]) -> None:
    listings = exclude_listings(scrape_all_pages(max_pages=MAX_PAGES, cid=cid), cid)[:JOB_LIMIT]
    logger.info("[category %d] Scraped %d listings.", cid, len(listings))

    new_listings = get_new_listings(listings, seen.get(str(cid), set()))
    logger.info("[category %d] %d new listing(s) since last run.", cid, len(new_listings))

    if not new_listings:
        return

    for job in new_listings:
        print(f"- [cat {cid}] [{job.timestamp}] {job.title}  ({job.url})")

    for chat_id in chat_ids:
        send_telegram_message(new_listings, chat_id, cid)  # raises on failure

    save_to_csv(new_listings)
    seen.setdefault(str(cid), set()).update(job.job_id for job in new_listings)
    save_seen(seen)


def main() -> None:
    if not health_check():
        logger.error("Aborting due to failed health check.")
        sys.exit(1)

    # Group chats by category so each category is scraped only once.
    categories: dict[int, list[str]] = defaultdict(list)
    for chat_id, cid in CHAT_CATEGORIES:
        categories[cid].append(chat_id)
    if not categories:
        logger.warning("No chats configured. Set TELEGRAM_CHAT_ID and/or CHAT_CATEGORIES.")
        categories[IT_CATEGORY_ID] = []

    seen = load_seen()
    failed = []
    for cid, chat_ids in categories.items():
        try:
            process_category(cid, chat_ids, seen)
        except Exception:
            logger.exception("[category %d] Failed; will retry next run.", cid)
            failed.append(cid)

    if failed:
        sys.exit(f"Failed categories: {failed}")


if __name__ == "__main__":
    main()

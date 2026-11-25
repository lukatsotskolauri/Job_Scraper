import logging
import sys
from collections import defaultdict

from jobs_scraper.config import MAX_PAGES, JOB_LIMIT, MAX_AGE_DAYS, CHAT_CATEGORIES, IT_CATEGORY_ID
from jobs_scraper.scraper import find_health_problem, scrape_all_pages
from jobs_scraper.filter import filter_recent
from jobs_scraper.state import get_new_listings, load_seen, save_seen
from jobs_scraper.notification import save_to_csv, send_alert, send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_category(cid: int, chat_ids: list[str], seen: dict[str, set[str]]) -> None:
    listings = scrape_all_pages(max_pages=MAX_PAGES, cid=cid)
    listings = filter_recent(listings, MAX_AGE_DAYS)
    logger.info("[category %d] %d listing(s) from the last %d day(s).", cid, len(listings), MAX_AGE_DAYS)

    # Find new jobs first, then cap, so a busy day can't push jobs out of view.
    # Jobs over the cap stay unseen and go out on the next run.
    first_run = str(cid) not in seen
    unseen = get_new_listings(listings, seen.get(str(cid), set()))
    new_listings = unseen[:JOB_LIMIT]
    logger.info(
        "[category %d] %d new listing(s), sending %d.", cid, len(unseen), len(new_listings)
    )

    if not new_listings:
        return

    for job in new_listings:
        print(f"- [cat {cid}] [{job.timestamp}] {job.title}  ({job.url})")

    for chat_id in chat_ids:
        send_telegram_message(new_listings, chat_id, cid)  # raises on failure

    save_to_csv(new_listings)
    # On a category's first run, send only the newest batch and mark the
    # rest as seen too, instead of working through the backlog over many runs.
    marked = unseen if first_run else new_listings
    seen.setdefault(str(cid), set()).update(job.job_id for job in marked)
    save_seen(seen)


def main() -> None:
    problem = find_health_problem()
    if problem:
        send_alert(problem)
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

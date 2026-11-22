import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from .config import EXCLUDE_KEYWORDS, IT_CATEGORY_ID
from .models import JobListing

logger = logging.getLogger(__name__)

# Georgia is UTC+4 all year (no daylight saving time).
TBILISI_TZ = timezone(timedelta(hours=4))

GEORGIAN_MONTHS = {
    "იანვარი": 1,
    "თებერვალი": 2,
    "მარტი": 3,
    "აპრილი": 4,
    "მაისი": 5,
    "ივნისი": 6,
    "ივლისი": 7,
    "აგვისტო": 8,
    "სექტემბერი": 9,
    "ოქტომბერი": 10,
    "ნოემბერი": 11,
    "დეკემბერი": 12,
}


def exclude_listings(listings: List[JobListing], cid: int = IT_CATEGORY_ID) -> List[JobListing]:
    # The keyword list is tuned for IT jobs, so other categories are left unfiltered.
    if cid != IT_CATEGORY_ID:
        return listings

    excluded_terms = tuple(term.lower() for term in EXCLUDE_KEYWORDS)
    return [
        job
        for job in listings
        if not any(term in job.title.lower() for term in excluded_terms)
    ]


def parse_posted_date(text: str, today: date) -> Optional[date]:
    """Parse a jobs.ge date like "21 ნოემბერი" (no year) into a date."""
    parts = text.split()
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in GEORGIAN_MONTHS:
        return None

    day, month = int(parts[0]), GEORGIAN_MONTHS[parts[1]]
    for year in (today.year, today.year - 1):
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue
        # A date "in the future" belongs to last year (e.g. "30 დეკემბერი" seen in January).
        if parsed <= today + timedelta(days=1):
            return parsed
    return None


def filter_recent(
    listings: List[JobListing], max_age_days: int, today: Optional[date] = None
) -> List[JobListing]:
    """Keep jobs posted within max_age_days. Jobs with an unreadable date are kept."""
    today = today or datetime.now(TBILISI_TZ).date()
    cutoff = today - timedelta(days=max_age_days)

    recent = []
    for job in listings:
        posted = parse_posted_date(job.posted, today)
        if posted is None or posted >= cutoff:
            recent.append(job)
    return recent

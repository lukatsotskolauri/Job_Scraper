import logging
from typing import List

from .config import EXCLUDE_KEYWORDS, IT_CATEGORY_ID
from .models import JobListing

logger = logging.getLogger(__name__)


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

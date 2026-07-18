import logging
from typing import List

from .config import EXCLUDE_KEYWORDS
from .models import JobListing

logger = logging.getLogger(__name__)


def exclude_listings(listings: List[JobListing]) -> List[JobListing]:
    excluded_terms = tuple(term.lower() for term in EXCLUDE_KEYWORDS)
    return [
        job
        for job in listings
        if not any(term in job.title.lower() for term in excluded_terms)
    ]
from dataclasses import dataclass, asdict
from typing import List


@dataclass
class JobListing:
    job_id: str
    title: str
    url: str
    timestamp: str
    company: str = ""
    posted: str = ""     # as shown on jobs.ge, e.g. "21 ნოემბერი"
    deadline: str = ""   # as shown on jobs.ge, e.g. "21 დეკემბერი"

    def to_dict(self) -> dict:
        return asdict(self)

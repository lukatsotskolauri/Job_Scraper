from dataclasses import dataclass, asdict
from typing import List


@dataclass
class JobListing:
    job_id: str
    title: str
    url: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)
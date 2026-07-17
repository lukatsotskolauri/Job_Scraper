from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import os
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).parent
RESUME_FILE = BASE_DIR / "resume.typ"
VACANCY_JSON_FILE = BASE_DIR / "vacancy_analysis.json"
GENERATED_PROMPT_FILE = BASE_DIR / "generated_prompt.txt"
DEBUG_HTML_FILE = BASE_DIR / "debug.html"
DEBUG_TEXT_FILE = BASE_DIR / "debug_vacancy_text.txt"
CONFIG_FILE = BASE_DIR / "config.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))
MIN_VACANCY_TEXT_LENGTH = 100
MAX_VACANCY_TEXT_LENGTH = 24000


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


_config = load_config()

SOFT_SKILL_TERMS = tuple(_config["soft_skill_terms"])
RESPONSIBILITY_SECTION_MARKERS = tuple(_config["responsibility_section_markers"])
REQUIREMENT_SECTION_MARKERS = tuple(_config["requirement_section_markers"])
SOFT_SKILL_SECTION_MARKERS = tuple(_config["soft_skill_section_markers"])
BENEFIT_SECTION_MARKERS = tuple(_config["benefit_section_markers"])
APPLY_SECTION_MARKERS = tuple(_config["apply_section_markers"])
PREFERRED_ITEM_MARKERS = tuple(_config["preferred_item_markers"])
SOFT_SKILL_ITEM_MARKERS = tuple(_config["soft_skill_item_markers"])
TITLE_LABELS = tuple(_config["title_labels"])
COMPANY_LABELS = tuple(_config["company_labels"])
EMPLOYMENT_TYPE_LABELS = tuple(_config["employment_type_labels"])
LOCATION_LABELS = tuple(_config["location_labels"])
TECH_KEYWORDS = tuple(_config["tech_keywords"])


OLLAMA_SYSTEM_PROMPT = """You are a job vacancy information extractor.

Convert the supplied job vacancy text into valid JSON.

Return exactly these fields:

{
  "job_title": "string",
  "company": "string or null",
  "location": "string or null",
  "employment_type": "string or null",
  "responsibilities": ["string"],
  "required_skills": ["string"],
  "preferred_skills": ["string"],
  "soft_skills": ["string"],
  "important_keywords": ["string"],
  "seniority": "string or null"
}

Rules:

- Return JSON only.
- Do not use Markdown.
- Use the exact English field names shown above.
- Do not translate JSON field names.
- Do not invent missing information.
- Support Georgian and English vacancy descriptions.
- Keep extracted values in the original vacancy language unless translation is obvious.
- Keep every list item short and clear.
- Put technical requirements in required_skills.
- Put optional technical requirements in preferred_skills.
- Requirements containing "preferred," "desirable," or "სასურველია"
  normally belong in preferred_skills.
- Put teamwork, communication, organization, analytical thinking,
  responsibility and willingness to learn in soft_skills.
- Extract ATS-relevant terms into important_keywords.
- Do not include website menus, unrelated company information,
  cookie messages, advertisements or other vacancies.
- In Georgian vacancies, "ძირითადი ფუნქცია-მოვალეობები" means responsibilities.
- In Georgian vacancies, "საკვალიფიკაციო მოთხოვნები და უნარები" means required and preferred skills.
"""


class VacancyData(BaseModel):
    job_title: str
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    important_keywords: list[str] = Field(default_factory=list)
    seniority: str | None = None

    @field_validator(
        "job_title",
        "company",
        "location",
        "employment_type",
        "seniority",
        mode="before",
    )
    @classmethod
    def clean_optional_strings(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator(
        "responsibilities",
        "required_skills",
        "preferred_skills",
        "soft_skills",
        "important_keywords",
        mode="before",
    )
    @classmethod
    def coerce_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = clean_list_item(value)
            return [value] if value else []
        if isinstance(value, list):
            return [
                cleaned
                for item in value
                if (cleaned := clean_list_item(str(item)))
            ]
        return []

    @model_validator(mode="after")
    def move_soft_skills_to_soft_skill_field(self) -> VacancyData:
        soft_skills = list(self.soft_skills)
        required_skills = []
        preferred_skills = []

        for skill in self.required_skills:
            if is_soft_skill(skill):
                soft_skills.append(skill)
            else:
                required_skills.append(skill)

        for skill in self.preferred_skills:
            if is_soft_skill(skill):
                soft_skills.append(skill)
            else:
                preferred_skills.append(skill)

        self.required_skills = deduplicate(required_skills)
        self.preferred_skills = deduplicate(preferred_skills)
        self.soft_skills = deduplicate(soft_skills)
        self.important_keywords = deduplicate(self.important_keywords)
        return self


def is_soft_skill(value: str) -> bool:
    normalized = value.lower()
    return any(term in normalized for term in SOFT_SKILL_TERMS)


def deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)

    return result


def get_args_from_terminal() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a job vacancy URL and generate a CV-tailoring prompt."
    )
    parser.add_argument("url", help="Job vacancy URL to analyze.")
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use Ollama to refine the locally extracted vacancy data.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug files (HTML and text) for troubleshooting.",
    )
    return parser.parse_args()


async def scrape_vacancy(url: str, debug: bool = False) -> str:
    """Download the page and extract clean vacancy text."""
    vacancy_text, html = await scrape_vacancy_content(url, seen=set())

    if debug:
        DEBUG_TEXT_FILE.write_text(vacancy_text, encoding="utf-8")
        DEBUG_HTML_FILE.write_text(html, encoding="utf-8")

    if len(vacancy_text) < MIN_VACANCY_TEXT_LENGTH:
        print(f"Warning: Only extracted {len(vacancy_text)} characters. Proceeding anyway.")

    return vacancy_text[:MAX_VACANCY_TEXT_LENGTH]


async def scrape_vacancy_content(url: str, seen: set[str]) -> tuple[str, str]:
    from bs4 import BeautifulSoup

    validate_url(url)

    if url in seen:
        raise ValueError(f"Detected a circular vacancy redirect while scraping {url}")
    seen.add(url)

    if is_helio_apply_url(url):
        return await scrape_helio_apply_vacancy(url)

    html = await download_html(url)
    soup = BeautifulSoup(html, "html.parser")
    vacancy_text = extract_relevant_text(soup)
    embedded_url = extract_embedded_jobs_ge_vacancy_url(soup, url, vacancy_text)

    if embedded_url:
        try:
            embedded_text, embedded_html = await scrape_vacancy_content(embedded_url, seen)
        except (httpx.HTTPError, ValueError):
            return vacancy_text, html

        if is_better_vacancy_text(embedded_text, vacancy_text):
            return embedded_text, embedded_html

    return vacancy_text, html


def extract_embedded_jobs_ge_vacancy_url(soup: Any, page_url: str, vacancy_text: str) -> str | None:
    if not is_jobs_ge_vacancy_url(page_url):
        return None

    content = soup.select_one("table.dtable")
    if not content:
        return None

    anchors = list(content.find_all("a", href=True))

    if looks_like_jobs_ge_external_stub(vacancy_text):
        for anchor in anchors:
            href = urljoin(page_url, anchor["href"])
            if is_external_vacancy_url(href):
                return href

    for anchor in anchors:
        href = urljoin(page_url, anchor["href"])
        if is_jobs_ge_vacancy_url(href) and is_full_text_link(anchor.get_text(" ", strip=True)):
            return href

    return None


def is_jobs_ge_vacancy_url(url: str) -> bool:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.netloc.endswith("jobs.ge") and query.get("view") == ["jobs"] and "id" in query


def looks_like_jobs_ge_external_stub(text: str) -> bool:
    normalized = text.lower()
    return any(
        marker in normalized
        for marker in (
            "ვაკანსიის შესახებ დეტალური ინფორმაციის",
            "ვაკანსიის დეტალურად სანახავად",
            "დეტალური ინფორმაციის გასაცნობად",
            "აპლიკაციის გამოსაგზავნად",
            "მიჰყევით ბმულს",
            "ეწვიეთ მოცემულ ბმულს",
            "გადადით მითითებულ ბმულზე",
            "გაგვიზიარეთ რეზიუმე",
            "იხილეთ ამ განცხადების სრული ტექსტი",
            "see full text",
            "for further details",
            "refer to the link",
            "full text",
            "please visit",
        )
    )


def is_external_vacancy_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if parsed.scheme not in {"http", "https"}:
        return False
    if hostname.endswith("jobs.ge"):
        return False

    ignored_hosts = (
        "facebook.com",
        "www.facebook.com",
        "counter.top.ge",
        "taya.ge",
        "www.taya.ge",
    )
    return hostname not in ignored_hosts


def is_full_text_link(text: str) -> bool:
    normalized = text.lower()
    return "სრული ტექსტ" in normalized or "ინგლისურ" in normalized or "full text" in normalized


def is_better_vacancy_text(candidate: str, current: str) -> bool:
    if looks_like_blocked_or_inactive_page(candidate):
        return False
    if len(candidate) >= len(current) + 200:
        return True
    return looks_like_vacancy_text(candidate) and not looks_like_vacancy_text(current)


def looks_like_blocked_or_inactive_page(text: str) -> bool:
    normalized = text.lower()
    return any(
        marker in normalized
        for marker in (
            "too many times",
            "please try again later",
            "this position has been filled",
            "sorry, this position has been filled",
            "404 not found",
            "page not found",
            "access denied",
        )
    )


def is_helio_apply_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return hostname in {"hel-ai.com", "www.hel-ai.com", "app.helio-ai.com", "www.app.helio-ai.com"} and parsed.path.startswith("/apply/")


async def scrape_helio_apply_vacancy(url: str) -> tuple[str, str]:
    token = await resolve_helio_apply_token(url)
    api_url = f"https://api.helio-ai.com/apply/{token}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://www.app.helio-ai.com",
        "Referer": f"https://www.app.helio-ai.com/apply/{token}",
    }

    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(api_url)
        response.raise_for_status()

    data = response.json()
    return format_helio_apply_text(data), json.dumps(data, ensure_ascii=False, indent=2)


async def resolve_helio_apply_token(url: str) -> str:
    parsed = urlparse(url)
    token = parsed.path.rstrip("/").split("/")[-1]
    hostname = parsed.hostname or ""

    if hostname not in {"hel-ai.com", "www.hel-ai.com"}:
        return token

    html = await download_html_without_js_redirect(url)
    redirect_url = extract_js_redirect(html)
    if not redirect_url:
        return token

    redirect_url = urljoin(url, redirect_url)
    return urlparse(redirect_url).path.rstrip("/").split("/")[-1]


async def download_html_without_js_redirect(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(follow_redirects=True, headers=headers, timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def format_helio_apply_text(data: dict[str, Any]) -> str:
    from bs4 import BeautifulSoup

    parts: list[str] = []
    title = data.get("job_title_local") or data.get("job_title_en")
    company = data.get("company_name") or data.get("company_business_name_en")
    working_schedules = data.get("working_schedules") or []
    cities = data.get("cities") or []
    description = data.get("description") or ""

    if title:
        parts.append(f"Job title: {title}")
    if company:
        parts.append(f"Company name: {company}")

    location = ", ".join(
        city["city_name"]
        for city in cities
        if isinstance(city, dict) and city.get("city_name") and city.get("is_visible", True)
    )
    if location:
        parts.append(f"Location: {location}")

    employment_type = ", ".join(
        schedule["job_type_name"]
        for schedule in working_schedules
        if isinstance(schedule, dict) and schedule.get("job_type_name") and schedule.get("is_visible", True)
    )
    if employment_type:
        parts.append(f"Employment type: {employment_type}")

    if description:
        description_text = BeautifulSoup(str(description), "html.parser").get_text("\n", strip=True)
        parts.append(clean_text(description_text))

    return clean_text("\n\n".join(parts))


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    if parsed.netloc.endswith("jobs.ge") and query.get("view") == ["jobs"] and "id" not in query:
        raise ValueError(
            "jobs.ge vacancy URL is missing the id query parameter. "
            "Your shell probably treated '&id=...' as a separate command. "
            "Wrap URLs containing '&' in quotes, for example: "
            'uv run python main.py "https://jobs.ge/ge/?view=jobs&id=738174"'
        )


def extract_js_redirect(html: str) -> str | None:
    """Extract JavaScript redirect URL from HTML."""
    patterns = [
        r'location\.href\s*=\s*["\']([^"\']+)["\']',
        r'window\.location\s*=\s*["\']([^"\']+)["\']',
        r'window\.location\.replace\s*\(\s*["\']([^"\']+)["\']\s*\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


async def download_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def extract_relevant_text(soup: Any) -> str:
    from bs4 import BeautifulSoup
    import json

    soup = BeautifulSoup(str(soup), "html.parser") if not isinstance(soup, BeautifulSoup) else soup

    # Special handling for jobs.ge table structure
    job_div = soup.select_one("#job")
    if job_div:
        # Remove script tags from job div
        for script in job_div.find_all("script"):
            script.decompose()
        text = clean_text(job_div.get_text("\n", strip=True))
        if len(text) >= 200:
            return text

    # Try to extract JSON-LD structured data first
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                if isinstance(item, dict):
                    # Extract from JobPosting schema
                    if item.get("@type") == "JobPosting":
                        parts = []
                        for field in ["description", "title", "responsibilities", "qualifications", "skills"]:
                            if field in item and item[field]:
                                parts.append(str(item[field]))
                        if parts:
                            return clean_text("\n".join(parts))
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    script_text_candidate = extract_script_text_candidate(soup)

    for element in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "noscript",
            "aside",
            "iframe",
            "svg",
            "button",
            "input",
            "select",
            "textarea",
        ]
    ):
        element.decompose()

    selectors = [
        ".pub-vac-text",
        ".pub_vac_text_detail",
        ".inner-vac-content-container",
        ".vac-public-form-container",
        ".jobs-page-container .pub-vac-text",
        "main",
        "article",
        ".vacancy",
        ".job-description",
        ".job-details",
        ".description",
        "#vacancy",
        "#job-description",
        "#job",
        ".dtable",
    ]

    for selector in selectors:
        element = soup.select_one(selector)

        if element:
            for unwanted in element.select(
                ".jobs-share-buttons-container, .brand-info-container, "
                ".inner-vac-form-container, .pub-vac-form, .vac-cover, "
                ".jobs-application-toolbar"
            ):
                unwanted.decompose()

            text = clean_text(element.get_text("\n", strip=True))

            if len(text) >= 300:
                return text

    for div in soup.find_all(["section", "div", "td"]):
        for unwanted in div.select(
            ".jobs-share-buttons-container, .brand-info-container, "
            ".inner-vac-form-container, .pub-vac-form, .vac-cover, "
            ".jobs-application-toolbar"
        ):
            unwanted.decompose()

        text = clean_text(div.get_text("\n", strip=True))
        if looks_like_vacancy_text(text):
            return text

    page_text = clean_text(soup.get_text("\n", strip=True))
    if len(page_text) < 300 and script_text_candidate:
        return script_text_candidate

    return page_text


def extract_script_text_candidate(soup: Any) -> str | None:
    for script in soup.find_all("script"):
        if not script.string or ("{" not in script.string and "job" not in script.string.lower()):
            continue

        try:
            content = script.string
            if "application/json" not in content and "job" not in content.lower():
                continue

            text = re.sub(r'[{}"\[\]:,]', " ", content)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 200:
                return text
        except Exception:
            continue

    return None


def looks_like_vacancy_text(text: str) -> bool:
    if len(text) < 500:
        return False

    markers = (
        "responsibilities",
        "requirements",
        "qualification",
        "skills",
        "job title",
        "employment",
        "vacancy",
        "ფუნქცია",
        "მოვალეობ",
        "მოთხოვნ",
        "უნარ",
        "ვაკანს",
        "სამუშაო",
        "საკვალიფიკაციო",
    )
    lower_text = text.lower()
    return sum(marker in lower_text for marker in markers) >= 2


def clean_text(text: str) -> str:
    text = html_lib.unescape(text)
    if looks_like_embedded_html(text):
        from bs4 import BeautifulSoup

        text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def looks_like_embedded_html(text: str) -> bool:
    return bool(re.search(r"</?(?:p|br|ul|ol|li|strong|span|div|h[1-6])\b", text, flags=re.IGNORECASE))


def clean_list_item(text: str) -> str:
    return re.sub(r"^(?:[*•·-]+\s*)+", "", text).strip(" ;")


async def analyze_vacancy(text: str, use_ollama: bool = False) -> VacancyData:
    """Structure extracted vacancy text and optionally refine it with Ollama."""
    fallback = parse_vacancy_sections(text)

    if not use_ollama:
        validate_vacancy_data(fallback)
        return fallback

    try:
        content = await call_ollama(
            [
                {"role": "system", "content": OLLAMA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract the vacancy data from this text. "
                        "Ignore application forms, share buttons, headers, and footers. "
                        "Keep extracted values in the same language as the vacancy text.\n\n"
                        f"{text}"
                    ),
                },
            ]
        )
        vacancy = parse_vacancy_response(content)
    except (httpx.HTTPError, ValueError) as exc:
        if not has_minimum_vacancy_data(fallback):
            raise RuntimeError(
                "Ollama failed and the local parser could not extract enough vacancy data. "
                "Check debug_vacancy_text.txt."
            ) from exc
        return fallback

    if needs_repair(vacancy):
        vacancy = merge_vacancy_data(vacancy, fallback)

    validate_vacancy_data(vacancy)
    return vacancy


async def call_ollama(messages: list[dict[str, str]]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": VacancyData.model_json_schema(),
        "options": {"temperature": 0},
        "messages": messages,
    }

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(f"{OLLAMA_URL.rstrip('/')}/api/chat", json=payload)
        response.raise_for_status()

    data = response.json()
    content = data.get("message", {}).get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Ollama returned an empty response.")

    return content


def parse_vacancy_response(content: str) -> VacancyData:
    try:
        vacancy_json = json.loads(extract_json_object(content))
        return VacancyData.model_validate(vacancy_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ollama did not return valid JSON: {content}") from exc
    except ValidationError as exc:
        raise ValueError(f"Ollama returned JSON with the wrong structure: {exc}") from exc


def extract_json_object(content: str) -> str:
    content = content.strip()
    if content.startswith("{") and content.endswith("}"):
        return content

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return content
    return content[start : end + 1]


def validate_vacancy_data(vacancy: VacancyData) -> None:
    if has_minimum_vacancy_data(vacancy):
        return

    print("Warning: Limited vacancy data extracted. Results may be incomplete.")


def has_minimum_vacancy_data(vacancy: VacancyData) -> bool:
    extracted_items = (
        len(vacancy.responsibilities)
        + len(vacancy.required_skills)
        + len(vacancy.preferred_skills)
        + len(vacancy.important_keywords)
    )
    return bool(vacancy.job_title) or extracted_items >= 1


def needs_repair(vacancy: VacancyData) -> bool:
    return len(vacancy.responsibilities) < 2 or len(vacancy.required_skills) < 2


def merge_vacancy_data(primary: VacancyData, fallback: VacancyData) -> VacancyData:
    return VacancyData(
        job_title=primary.job_title or fallback.job_title,
        company=primary.company or fallback.company,
        location=primary.location or fallback.location,
        employment_type=primary.employment_type or fallback.employment_type,
        responsibilities=choose_list(primary.responsibilities, fallback.responsibilities, minimum=2),
        required_skills=choose_list(primary.required_skills, fallback.required_skills, minimum=2),
        preferred_skills=choose_list(primary.preferred_skills, fallback.preferred_skills),
        soft_skills=choose_list(primary.soft_skills, fallback.soft_skills),
        important_keywords=choose_list(primary.important_keywords, fallback.important_keywords),
        seniority=primary.seniority or fallback.seniority,
    )


def choose_list(
    primary: list[str],
    fallback: list[str],
    minimum: int = 1,
) -> list[str]:
    if len(primary) >= minimum:
        return deduplicate(primary)
    return deduplicate(fallback or primary)


def parse_vacancy_sections(text: str) -> VacancyData:
    lines = [line.strip(" ;") for line in text.splitlines() if line.strip(" ;")]
    responsibilities = section_between(
        lines,
        RESPONSIBILITY_SECTION_MARKERS,
        REQUIREMENT_SECTION_MARKERS
        + SOFT_SKILL_SECTION_MARKERS
        + BENEFIT_SECTION_MARKERS
        + APPLY_SECTION_MARKERS
        + ("vacancy application deadline",),
    )
    requirements = section_between(
        lines,
        REQUIREMENT_SECTION_MARKERS,
        PREFERRED_ITEM_MARKERS
        + SOFT_SKILL_SECTION_MARKERS
        + BENEFIT_SECTION_MARKERS
        + APPLY_SECTION_MARKERS
        + ("vacancy application deadline",),
    )
    preferred_skills = section_between(
        lines,
        PREFERRED_ITEM_MARKERS,
        SOFT_SKILL_SECTION_MARKERS
        + BENEFIT_SECTION_MARKERS
        + APPLY_SECTION_MARKERS
        + ("vacancy application deadline",),
    )
    soft_skill_items = section_between(
        lines,
        SOFT_SKILL_SECTION_MARKERS,
        BENEFIT_SECTION_MARKERS + APPLY_SECTION_MARKERS,
    )

    required_skills: list[str] = []
    soft_skills: list[str] = soft_skill_items

    for item in requirements:
        lower_item = item.lower()

        if contains_any(lower_item, PREFERRED_ITEM_MARKERS):
            preferred_skills.append(item)
        elif is_soft_skill(item) or contains_any(lower_item, SOFT_SKILL_ITEM_MARKERS):
            soft_skills.append(item)
        else:
            required_skills.append(item)

    title = first_label_value(lines, TITLE_LABELS) or lines[0]
    company = first_label_value(lines, COMPANY_LABELS) or guess_company_from_lines(lines)
    employment_type = first_label_value(lines, EMPLOYMENT_TYPE_LABELS)
    location = first_label_value(lines, LOCATION_LABELS)
    extracted_items = responsibilities + required_skills + preferred_skills
    keyword_source = extracted_items or fallback_keyword_source(lines, title)

    return VacancyData(
        job_title=title,
        company=company,
        location=location,
        employment_type=employment_type,
        responsibilities=responsibilities,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        soft_skills=soft_skills,
        important_keywords=extract_keywords(keyword_source),
        seniority=guess_seniority(requirements),
    )


def fallback_keyword_source(lines: list[str], title: str) -> list[str]:
    source = [title]

    for line in lines:
        cleaned = clean_list_item(line.strip(" :;"))
        if is_fallback_keyword_line(cleaned):
            source.append(cleaned)

    return deduplicate(source)


def is_fallback_keyword_line(line: str) -> bool:
    if not line or len(line) > 90 or is_noise_line(line):
        return False
    if "http://" in line.lower() or "https://" in line.lower():
        return False

    normalized = line.lower()
    if any(keyword.lower() in normalized for keyword in TECH_KEYWORDS):
        return True

    return bool(
        re.search(
            r"\b(?:it|qa|ui/ux|ux/ui|seo|sap|d365|\.net|devops|backend|back-end|"
            r"front-end|frontend|full-stack|full stack|architect|developer|support|"
            r"operations|network|data|analytics|python|java|php|ios|android)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def is_noise_line(line: str) -> bool:
    normalized = line.lower().strip(" :;")
    return normalized in {
        "ყველა ვაკანსია",
        "ამ ორგანიზაციის ყველა განცხადება",
        "ამოსაბეჭდი ვერსია",
        "all jobs",
        "all ads by this client",
        "printer friendly",
        "published",
        "deadline",
        "გამოქვეყნდა",
        "ბოლო ვადა",
        "დასახელება",
        "მომწოდებელი",
        "provided by",
        "ad title",
    }


def section_between(
    lines: list[str],
    start_markers: tuple[str, ...],
    end_markers: tuple[str, ...],
) -> list[str]:
    start_index: int | None = None

    for index, line in enumerate(lines):
        if is_section_heading(line, start_markers):
            start_index = index + 1
            break

    if start_index is None:
        return []

    result: list[str] = []
    for line in lines[start_index:]:
        if is_section_heading(line, end_markers):
            break
        result.append(line)

    return result


def first_label_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    for label in labels:
        value = line_after_label(lines, label)
        if value:
            return value
    return None


def line_after_label(lines: list[str], label: str) -> str | None:
    label = label.lower()
    for index, line in enumerate(lines):
        cleaned_line = clean_list_item(line)
        normalized = cleaned_line.lower()
        if normalized == label or normalized.startswith(f"{label}:"):
            value = cleaned_line.split(":", 1)[1].strip(" :;") if ":" in cleaned_line else ""
            if value:
                return clean_list_item(value)
            if index + 1 < len(lines):
                return clean_list_item(lines[index + 1].strip(" :;"))
    return None


def guess_company_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        if "აცხადებს ვაკანსიას" in line:
            return line.split("აცხადებს ვაკანსიას", 1)[0].strip(" :;")

        lowered = line.lower()
        for marker in (" is hiring", " announces a vacancy", " has an opening"):
            if marker in lowered:
                return line[: lowered.index(marker)].strip(" :;")

    return None


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(marker.lower() in normalized for marker in markers)


def is_section_heading(text: str, markers: tuple[str, ...]) -> bool:
    normalized = text.lower().strip(" :;.*-")
    for marker in markers:
        marker = marker.lower()
        if normalized == marker or normalized.startswith(f"{marker}:") or normalized.endswith(marker):
            return True

        if normalized.startswith(marker) and is_marker_prefix_heading(normalized, marker):
            return True

    return False


def is_marker_prefix_heading(text: str, marker: str) -> bool:
    if not marker.isascii():
        return True

    if len(text) == len(marker):
        return True

    if marker == "apply":
        return text[len(marker)] in ":;-"

    return text[len(marker)] in " :;-"


def guess_seniority(requirements: list[str]) -> str | None:
    joined = "\n".join(requirements)
    year_match = re.search(r"(\d+)\s*(?:\+?\s*years?|წლ)", joined, flags=re.IGNORECASE)
    if year_match:
        return f"{year_match.group(1)}+ years experience"
    return None


def extract_keywords(items: list[str]) -> list[str]:
    known_keywords = TECH_KEYWORDS

    text = "\n".join(items)
    lower_text = text.lower()
    keywords = [keyword for keyword in known_keywords if keyword.lower() in lower_text]

    for item in items:
        for keyword in extract_keyword_phrases(item):
            keywords.append(keyword)

    return deduplicate(keywords)[:18]


def extract_keyword_phrases(text: str) -> list[str]:
    normalized = clean_text(text).strip(" .;:")
    if not normalized:
        return []

    phrases: list[str] = []
    parenthesized_terms = re.findall(r"\(([^)]+)\)", normalized)
    for terms in parenthesized_terms:
        phrases.extend(term.strip() for term in re.split(r"[,;/]", terms) if term.strip())

    if len(normalized) <= 45:
        phrases.append(normalized)
    else:
        words = re.findall(r"[\w\u10A0-\u10FF.+#-]+", normalized)
        if 1 < len(words) <= 5:
            phrases.append(" ".join(words))

    return phrases


def generate_cv_prompt(vacancy: VacancyData, original_cv: str) -> str:
    """Create the prompt that will tailor the CV."""
    vacancy_json = vacancy.model_dump_json(indent=2)

    return f"""You are an expert CV editor.

Tailor the CV below for this job vacancy.

Rules:
- Keep the CV truthful.
- Do not invent experience, education, certifications, employers, dates, or tools.
- Preserve the Typst structure and syntax.
- Prioritize the vacancy's technical requirements and ATS keywords.
- Emphasize matching responsibilities, required skills, preferred skills, and soft skills.
- Keep the result concise and suitable for an entry-level or junior application when applicable.
- Return only the updated Typst CV.

Vacancy data:
{vacancy_json}

Original CV:
{original_cv}
"""


def save_vacancy_json(vacancy: VacancyData) -> None:
    VACANCY_JSON_FILE.write_text(
        vacancy.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def read_resume() -> str:
    if not RESUME_FILE.exists():
        raise FileNotFoundError(
            f"Resume file not found: {RESUME_FILE}. Create resume.typ first."
        )
    return RESUME_FILE.read_text(encoding="utf-8")


def save_generated_prompt(prompt: str) -> None:
    GENERATED_PROMPT_FILE.write_text(prompt, encoding="utf-8")


async def main() -> None:
    args = get_args_from_terminal()

    vacancy_text = await scrape_vacancy(args.url, debug=args.debug)
    print(f"Scraped {len(vacancy_text)} characters from vacancy")
    
    vacancy_data = await analyze_vacancy(vacancy_text, use_ollama=args.ollama)

    save_vacancy_json(vacancy_data)

    original_cv = read_resume()
    prompt = generate_cv_prompt(vacancy_data, original_cv)

    save_generated_prompt(prompt)

    print(f"Saved {VACANCY_JSON_FILE}")
    print(f"Saved {GENERATED_PROMPT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from None

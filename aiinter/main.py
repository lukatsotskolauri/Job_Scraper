from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from config import (
    BASE_DIR,
    RESUME_FILE,
    VACANCY_JSON_FILE,
    USER_PROFILE_FILE,
    VACANCY_MATCH_FILE,
    CONFIG_FILE,
    OLLAMA_URL,
    OLLAMA_MODEL,
    REQUEST_TIMEOUT,
    OLLAMA_TIMEOUT,
    PROFILE_MATCH_TIMEOUT,
    MIN_VACANCY_TEXT_LENGTH,
    MAX_VACANCY_TEXT_LENGTH,
    load_config,
)
from scraping import scrape_vacancy
from vacancy_parser import (
    VacancyData,
    parse_vacancy_sections,
    validate_vacancy_data,
    has_minimum_vacancy_data,
    needs_repair,
    merge_vacancy_data,
    parse_vacancy_response,
)
from profile_matcher import (
    UserProfile,
    ProfileVacancyMatch,
    load_or_extract_user_profile,
    compare_profile_to_vacancy,
    detect_non_viable_job,
    build_non_viable_match,
    save_vacancy_match,
    read_resume,
)


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
    parser.add_argument(
        "--refresh-profile",
        action="store_true",
        help="Re-extract resume profile with Ollama instead of using user_profile.json.",
    )
    parser.add_argument(
        "--skip-profile-match",
        action="store_true",
        help="Skip Ollama resume profile extraction and semantic vacancy matching.",
    )
    return parser.parse_args()


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
            ],
            response_model=VacancyData,
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


async def call_ollama(
    messages: list[dict[str, str]],
    response_model: type[BaseModel],
) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": response_model.model_json_schema(),
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


def save_vacancy_json(vacancy: VacancyData) -> None:
    VACANCY_JSON_FILE.write_text(
        vacancy.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


async def main() -> None:
    args = get_args_from_terminal()

    vacancy_text = await scrape_vacancy(args.url, debug=args.debug)
    print(f"Scraped {len(vacancy_text)} characters from vacancy")

    vacancy_data = await analyze_vacancy(vacancy_text, use_ollama=args.ollama)

    save_vacancy_json(vacancy_data)

    original_cv = read_resume()
    vacancy_match: ProfileVacancyMatch | None = None

    if not args.skip_profile_match:
        try:
            user_profile, used_cache = await load_or_extract_user_profile(
                original_cv,
                refresh=args.refresh_profile,
            )
            print(
                f"{'Loaded cached' if used_cache else 'Saved'} user profile: "
                f"{USER_PROFILE_FILE}"
            )
            non_viable_reason = detect_non_viable_job(user_profile, vacancy_data)
            if non_viable_reason:
                vacancy_match = build_non_viable_match(
                    user_profile,
                    vacancy_data,
                    non_viable_reason,
                )
                print(f"Job is not viable for me: {non_viable_reason}")
            else:
                vacancy_match = await compare_profile_to_vacancy(
                    user_profile,
                    vacancy_data,
                    vacancy_text,
                )
            save_vacancy_match(vacancy_match)
            print(f"Saved {VACANCY_MATCH_FILE}")
        except (httpx.HTTPError, ValueError) as exc:
            print(f"Warning: Profile matching skipped because Ollama failed: {exc}")

    print(f"Saved {VACANCY_JSON_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled by user.") from None
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from None


__all__ = [
    "get_args_from_terminal",
    "analyze_vacancy",
    "call_ollama",
    "save_vacancy_json",
    "main",
]

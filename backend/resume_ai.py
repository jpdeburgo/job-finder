"""Read a resume's skills and years of experience with a language model.

The model does the reading: it lists the jobs in your work history (title,
company, start and end month, the skills each one used) and every technical
skill on the resume, with how well you know each (1-5 stars, and why). The
arithmetic stays in code: years are added up from those dates by
``resume_parser.build_analysis``, exactly like the parser's, with overlapping
jobs counted once. (Models are good at reading a messy resume and judging
"led the migration" against "some exposure to", and bad at adding up months.)
A skill the model doesn't rate gets the parser's level (skill_levels.py).
Skills on your own list are always included when the resume names them: the
model can pass over a tool the resume doesn't explain ("Backstage"), but you've
said it's yours.

Configure it in ``backend/.env`` with an API key for either provider::

    ANTHROPIC_API_KEY=sk-ant-...        # Claude (used when both keys are set)
    OPENAI_API_KEY=sk-...               # or OpenAI
    RESUME_AI_PROVIDER=openai           # optional: pick one when both are set
    RESUME_AI_MODEL=...                 # optional: a different model

The resume's text is sent to that provider; nothing else is. Both are called
over plain HTTPS with ``requests``, and both are asked for JSON matching
``RESPONSE_SCHEMA`` (Claude through a forced tool call, OpenAI through
structured outputs), which is then checked here anyway.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import requests

from resume_parser import Position, ResumeAnalysis, build_analysis, parse_month, parse_resume
from search_skills import MAX_PROFICIENCY, MIN_PROFICIENCY
from skill_catalog import CATEGORIES, Vocabulary

PROVIDER_ENV_VAR = "RESUME_AI_PROVIDER"
MODEL_ENV_VAR = "RESUME_AI_MODEL"
API_KEY_ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
DEFAULT_MODELS = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4.1-mini"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# A resume is a few pages; the answer lists each job and skill once.
MAX_RESUME_CHARS = 40_000
MAX_OUTPUT_TOKENS = 8192
TIMEOUT_SECONDS = 120

TOOL_NAME = "record_resume"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["positions", "skills"],
    "properties": {
        "positions": {
            "type": "array",
            "description": "Every job in the work history, most recent first.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "company", "start", "end", "skills"],
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string", "description": 'The employer, or "" if not given.'},
                    "start": {"type": "string", "description": "YYYY-MM"},
                    "end": {
                        "type": ["string", "null"],
                        "description": "YYYY-MM, or null if the candidate is still in this job.",
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technical skills this job's entry says were used.",
                    },
                },
            },
        },
        "skills": {
            "type": "array",
            "description": "Every technical skill on the resume, once each.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "category", "level", "level_reason"],
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "level": {
                        "type": "integer",
                        "enum": list(range(MIN_PROFICIENCY, MAX_PROFICIENCY + 1)),
                        "description": "1 Beginner, 2 Familiar, 3 Proficient, 4 Advanced, 5 Expert",
                    },
                    "level_reason": {
                        "type": "string",
                        "description": "The evidence for the level, in a few words.",
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You read resumes for a personal job-search tool. Record the candidate's work history and "
    "technical skills exactly as the resume gives them. Never invent employers, dates, or skills."
)
INSTRUCTIONS = """Today is {today}. Read the resume below and record:

1. positions: every job in the candidate's work history (employment, contract, freelance, and internships), \
but not education, coursework, personal projects, or volunteering. For each, give the title, the company \
("" if not given), and the start and end as "YYYY-MM", with end null if the candidate is still there. When \
only a year is given, use "YYYY-01" for a start and "YYYY-12" for an end. Leave out a job with no dates. \
Under skills, list the technical skills that job's entry says were used.
2. skills: every technical skill anywhere on the resume, once each, with a category: languages, frameworks, \
libraries, databases, cloud services, tools, platforms, and engineering practices such as CI/CD or TDD. \
Leave out soft skills (communication, leadership) and spoken languages.
3. For each skill, how well the candidate knows it, from 1 to 5, and the evidence in a few words (level_reason, e.g. "6 years across two jobs; led the migration"):
   1 Beginner: coursework, learning it, or a brief mention.
   2 Familiar: used a little, long ago, or only listed with nothing showing it was used.
   3 Proficient: used in a job for a year or more.
   4 Advanced: several years, recently, and central to the work.
   5 Expert: many years, central to the work, and leading, designing, or teaching with it.
   If the resume rates a skill itself ("Expert: ...", "familiar with ..."), use that. Judge by what the work shows, not by how often a word appears; a skill used through another counts (React work is JavaScript work).

Name each skill by its usual name ("JavaScript", "Node.js", "PostgreSQL").{your_skills}

<resume>
{resume}
</resume>"""


class AiNotConfiguredError(RuntimeError):
    """No API key for a provider (see the module docstring)."""


class AiReadError(RuntimeError):
    """The model couldn't be reached, refused, or answered with something unusable."""

    def __init__(self, message: str, timed_out: bool = False) -> None:
        super().__init__(message)
        self.timed_out = timed_out


@dataclass(frozen=True)
class AiConfig:
    provider: str  # "anthropic" or "openai"
    model: str
    api_key: str = ""

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAMES[self.provider]


def ai_config(env: Mapping[str, str] | None = None) -> AiConfig:
    """The provider and model to use, from the environment. Raises
    ``AiNotConfiguredError`` when there's no API key for it."""
    env = os.environ if env is None else env
    keys = {provider: env.get(var, "").strip() for provider, var in API_KEY_ENV_VARS.items()}
    chosen = env.get(PROVIDER_ENV_VAR, "").strip().lower()
    if chosen and chosen not in API_KEY_ENV_VARS:
        raise AiNotConfiguredError(
            f"{PROVIDER_ENV_VAR}={chosen!r} isn't a provider; use "
            f"{' or '.join(API_KEY_ENV_VARS)}."
        )
    provider = chosen or next((p for p in API_KEY_ENV_VARS if keys[p]), "")
    if not provider or not keys[provider]:
        wanted = API_KEY_ENV_VARS[provider] if provider else " or ".join(API_KEY_ENV_VARS.values())
        raise AiNotConfiguredError(
            f"AI isn't set up: add {wanted} to backend/.env and restart the API "
            "(see backend/README.md). Parsing works without it."
        )
    model = env.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODELS[provider]
    return AiConfig(provider, model, keys[provider])


def ai_status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Whether AI reading is set up, and with what (never the key)."""
    try:
        config = ai_config(env)
    except AiNotConfiguredError as error:
        return {"configured": False, "provider": None, "model": None, "problem": str(error)}
    return {"configured": True, "provider": config.provider, "model": config.model, "problem": None}


def build_prompt(text: str, your_skills: Iterable[str], today: datetime) -> str:
    names = [name for name in your_skills if name.strip()]
    spelling = (
        " These are skills the candidate lists as theirs: include each one the resume mentions, even if it "
        "doesn't say what it is, and spell it exactly this way: " + ", ".join(names) + "."
        if names else ""
    )
    return INSTRUCTIONS.format(
        today=today.strftime("%B %Y"), your_skills=spelling, resume=text[:MAX_RESUME_CHARS]
    )


# --- Providers -----------------------------------------------------------------------


def _post(session: Any, config: AiConfig, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    try:
        response = session.post(url, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
    except requests.Timeout as error:
        raise AiReadError(
            f"{config.provider_name} didn't answer within {TIMEOUT_SECONDS}s; try again.", timed_out=True
        ) from error
    except requests.RequestException as error:
        raise AiReadError(f"Couldn't reach {config.provider_name}: {error}") from error
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200:
        detail = ""
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            detail = str(data["error"].get("message") or "")
        raise AiReadError(
            f"{config.provider_name} answered {response.status_code}"
            + (f": {detail}" if detail else "")
        )
    if not isinstance(data, dict):
        raise AiReadError(f"{config.provider_name} sent an answer that isn't JSON.")
    return data


def _ask_anthropic(config: AiConfig, prompt: str, session: Any) -> Any:
    data = _post(
        session,
        config,
        ANTHROPIC_URL,
        {"x-api-key": config.api_key, "anthropic-version": ANTHROPIC_VERSION},
        {
            "model": config.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{
                "name": TOOL_NAME,
                "description": "Record the work history and skills read from the resume.",
                "input_schema": RESPONSE_SCHEMA,
            }],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        },
    )
    if data.get("stop_reason") == "max_tokens":
        raise AiReadError("The AI's answer was cut off (the resume may be too long); try parsing instead.")
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
            return block.get("input")
    raise AiReadError(f"{config.provider_name} didn't return the resume's details.")


def _ask_openai(config: AiConfig, prompt: str, session: Any) -> Any:
    data = _post(
        session,
        config,
        OPENAI_URL,
        {"Authorization": f"Bearer {config.api_key}"},
        {
            "model": config.model,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": TOOL_NAME, "strict": True, "schema": RESPONSE_SCHEMA},
            },
        },
    )
    choices = data.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    if message.get("refusal"):
        raise AiReadError(f"{config.provider_name} declined to read the resume: {message['refusal']}")
    if choice.get("finish_reason") == "length":
        raise AiReadError("The AI's answer was cut off (the resume may be too long); try parsing instead.")
    try:
        return json.loads(message.get("content") or "")
    except ValueError as error:
        raise AiReadError(f"{config.provider_name} sent an answer that isn't JSON.") from error


_ASK = {"anthropic": _ask_anthropic, "openai": _ask_openai}


# --- Reading the answer -------------------------------------------------------------


def _text(value: Any, limit: int = 200) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _names(values: Any) -> list[str]:
    return [name for value in (values if isinstance(values, list) else []) if (name := _text(value, 60))]


def positions_from_answer(answer: dict[str, Any], today: int) -> tuple[list[Position], list[str]]:
    """The answer's positions, leaving out (with a note) any whose dates don't make sense."""
    positions, skipped = [], []
    for item in answer.get("positions") or []:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        start = parse_month(_text(item.get("start")))
        end_text = _text(item.get("end"))
        # null is asked for, but "Present" is what resumes say.
        if end_text.lower() in ("present", "current", "now", "ongoing"):
            end_text = ""
        end = parse_month(end_text) if end_text else None
        if start is None or start > today or (end_text and end is None) or (end is not None and end < start):
            skipped.append(title or "a job")
            continue
        positions.append(Position(
            title=title,
            company=_text(item.get("company")),
            start=start,
            end=end if end is not None and end < today else None,
            skills=tuple(_names(item.get("skills"))),
        ))
    notes = [f"Left out jobs whose dates don't make sense: {', '.join(skipped)}."] if skipped else []
    return positions, notes


def _your_skills_it_missed(
    text: str, your_skills: list[str], named: list[str], positions: list[Position], vocabulary: Vocabulary
) -> list[str]:
    """Skills on your list the resume names that the model left out."""
    yours = {vocabulary.resolve(name).name for name in your_skills if name.strip()}
    given = {vocabulary.resolve(name).name.lower() for name in named if name}
    given |= {vocabulary.resolve(name).name.lower() for p in positions for name in p.skills}
    return [name for name in vocabulary.find(text) if name in yours and name.lower() not in given]


def _with_skills_from_parsing(
    text: str, your_skills: list[str], missed: list[str], positions: list[Position], now: datetime
) -> list[Position]:
    """The model's jobs, with each missed skill added to the jobs whose
    entries parsing found it in (matched by their dates), so its years count."""
    parsed = parse_resume(text, your_skills, now=now).positions
    dates = {name: {(p.start, p.end) for p in parsed if name in p.skills} for name in missed}
    return [
        replace(p, skills=p.skills + tuple(name for name in missed if (p.start, p.end) in dates[name]))
        for p in positions
    ]


def read_resume_with_ai(
    text: str,
    your_skills: Iterable[str] = (),
    now: datetime | None = None,
    config: AiConfig | None = None,
    session: Any = None,
) -> ResumeAnalysis:
    """Read a resume's skills and years of experience with the configured model."""
    now = now or datetime.now(timezone.utc)
    config = config or ai_config()
    your_skills = list(your_skills)
    answer = _ASK[config.provider](config, build_prompt(text, your_skills, now), session or requests)
    if not isinstance(answer, dict) or not isinstance(answer.get("positions"), list) \
            or not isinstance(answer.get("skills"), list):
        raise AiReadError(f"{config.provider_name}'s answer isn't in the expected shape.")

    today = now.year * 12 + now.month - 1
    positions, notes = positions_from_answer(answer, today)
    skills = [item for item in answer["skills"] if isinstance(item, dict)]
    categories = {
        name.lower(): str(item.get("category"))
        for item in skills
        if (name := _text(item.get("name"), 60)) and item.get("category") in CATEGORIES
    }
    vocabulary = Vocabulary.with_your_skills(your_skills)
    # Keyed like build_analysis keys skills: the catalog's name for it.
    levels = {
        vocabulary.resolve(name).name.lower(): (level, _text(item.get("level_reason"), 200) or "Rated by the AI")
        for item in skills
        if (name := _text(item.get("name"), 60))
        and type(level := item.get("level")) is int and MIN_PROFICIENCY <= level <= MAX_PROFICIENCY
    }
    if len(text) > MAX_RESUME_CHARS:
        notes.append(f"Only the first {MAX_RESUME_CHARS:,} characters of the resume were sent to the AI.")
    named = [_text(item.get("name"), 60) for item in skills]
    missed = _your_skills_it_missed(text, your_skills, named, positions, vocabulary)
    if missed:
        positions = _with_skills_from_parsing(text, your_skills, missed, positions, now)
        notes.append(
            f"The AI didn't name {', '.join(missed)}, which {'is' if len(missed) == 1 else 'are'} on your "
            f"skill list; {'it was' if len(missed) == 1 else 'they were'} added because the resume mentions "
            f"{'it' if len(missed) == 1 else 'them'}."
        )
    return build_analysis(
        "ai",
        text,
        positions,
        named + missed,
        vocabulary,
        notes=notes,
        now=now,
        provider=config.provider,
        model=config.model,
        categories=categories,
        levels=levels,
    )

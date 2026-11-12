"""Reading a resume with a language model (resume_ai.py). No real API is
called: a fake session answers the way Anthropic and OpenAI do."""

import json
from datetime import datetime, timezone

import pytest
import requests

import resume_ai
from resume_ai import (
    AiConfig,
    AiNotConfiguredError,
    AiReadError,
    ai_config,
    ai_status,
    read_resume_with_ai,
)
from resume_parser import month_index

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
CLAUDE = AiConfig("anthropic", "claude-test", "sk-ant-test")
GPT = AiConfig("openai", "gpt-test", "sk-test")
RESUME = "Senior Engineer at Acme, 2021 - Present. Python, ReactJS, Kubernetes.\nEngineer at Beta 2018-2020: Java."
ANSWER = {
    "positions": [
        {"title": "Senior Engineer", "company": "Acme", "start": "2021-01", "end": None,
         "skills": ["Python", "ReactJS", "Kubernetes"]},
        {"title": "Engineer", "company": "Beta", "start": "2018-01", "end": "2020-12", "skills": ["Java"]},
    ],
    "skills": [
        {"name": "Python", "category": "Language"},
        {"name": "React.js", "category": "Frontend"},
        {"name": "Kubernetes", "category": "DevOps"},
        {"name": "Java", "category": "Language"},
        {"name": "Microsoft Excel", "category": "Tools"},
    ],
}


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("not JSON")
        return self._body


class FakeSession:
    """Records each request and answers with ``response`` (or raises it)."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def claude_answers(answer, stop_reason="tool_use"):
    return FakeResponse(body={
        "content": [{"type": "text", "text": "Here you go."},
                    {"type": "tool_use", "id": "t1", "name": "record_resume", "input": answer}],
        "stop_reason": stop_reason,
    })


def gpt_answers(answer, finish_reason="stop", refusal=None):
    message = {"role": "assistant", "content": json.dumps(answer) if answer is not None else None, "refusal": refusal}
    return FakeResponse(body={"choices": [{"message": message, "finish_reason": finish_reason}]})


# --- Configuration -------------------------------------------------------------------


def test_not_configured_without_a_key():
    with pytest.raises(AiNotConfiguredError, match="add ANTHROPIC_API_KEY or OPENAI_API_KEY to backend/.env"):
        ai_config({})
    assert ai_status({})["configured"] is False


def test_the_provider_follows_the_key_anthropic_first():
    assert ai_config({"OPENAI_API_KEY": "sk-1"}) == AiConfig("openai", "gpt-4.1-mini", "sk-1")
    assert ai_config({"OPENAI_API_KEY": "sk-1", "ANTHROPIC_API_KEY": "sk-ant"}).provider == "anthropic"


def test_provider_and_model_can_be_chosen():
    env = {"OPENAI_API_KEY": "sk-1", "ANTHROPIC_API_KEY": "sk-ant", "RESUME_AI_PROVIDER": "OpenAI",
           "RESUME_AI_MODEL": "gpt-x"}
    assert ai_config(env) == AiConfig("openai", "gpt-x", "sk-1")
    with pytest.raises(AiNotConfiguredError, match="add OPENAI_API_KEY"):
        ai_config({"ANTHROPIC_API_KEY": "sk-ant", "RESUME_AI_PROVIDER": "openai"})
    with pytest.raises(AiNotConfiguredError, match="isn't a provider"):
        ai_config({"RESUME_AI_PROVIDER": "gemini"})


def test_status_never_shows_the_key():
    status = ai_status({"ANTHROPIC_API_KEY": "sk-ant-secret"})
    assert status == {"configured": True, "provider": "anthropic", "model": "claude-sonnet-4-5", "problem": None}
    assert "secret" not in json.dumps(status)


# --- Asking --------------------------------------------------------------------------


def test_claude_is_asked_for_a_forced_tool_call():
    session = FakeSession(claude_answers(ANSWER))
    read_resume_with_ai(RESUME, ["Python", "ReactJS"], now=NOW, config=CLAUDE, session=session)

    [call] = session.calls
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"] == {"x-api-key": "sk-ant-test", "anthropic-version": "2023-06-01"}
    body = call["json"]
    assert body["model"] == "claude-test"
    assert body["tool_choice"] == {"type": "tool", "name": "record_resume"}
    assert body["tools"][0]["input_schema"] == resume_ai.RESPONSE_SCHEMA
    prompt = body["messages"][0]["content"]
    assert "Today is November 2026." in prompt
    assert "spell it exactly this way: Python, ReactJS." in prompt
    assert f"<resume>\n{RESUME}\n</resume>" in prompt
    assert call["timeout"] == resume_ai.TIMEOUT_SECONDS


def test_openai_is_asked_for_strict_structured_output():
    session = FakeSession(gpt_answers(ANSWER))
    read_resume_with_ai(RESUME, [], now=NOW, config=GPT, session=session)

    [call] = session.calls
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer sk-test"}
    body = call["json"]
    assert body["response_format"]["json_schema"] == {
        "name": "record_resume", "strict": True, "schema": resume_ai.RESPONSE_SCHEMA,
    }
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "spell it exactly" not in body["messages"][1]["content"]  # no skills of yours to spell


def test_schema_is_strict_mode_compatible():
    """OpenAI's strict mode needs every property required and no extras, at every level."""

    def check(schema):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) == set(schema["properties"])
            for child in schema["properties"].values():
                check(child)
        if "items" in schema:
            check(schema["items"])

    check(resume_ai.RESPONSE_SCHEMA)


def test_a_long_resume_is_cut_and_that_is_noted():
    session = FakeSession(claude_answers(ANSWER))
    text = RESUME + " x" * resume_ai.MAX_RESUME_CHARS
    analysis = read_resume_with_ai(text, [], now=NOW, config=CLAUDE, session=session)
    assert len(session.calls[0]["json"]["messages"][0]["content"]) < resume_ai.MAX_RESUME_CHARS + 3000
    assert any("Only the first 40,000 characters" in note for note in analysis.notes)


# --- The answer ----------------------------------------------------------------------


@pytest.mark.parametrize(("config", "response"), [(CLAUDE, claude_answers(ANSWER)), (GPT, gpt_answers(ANSWER))])
def test_years_are_added_up_in_code_not_by_the_model(config, response):
    analysis = read_resume_with_ai(RESUME, ["ReactJS"], now=NOW, config=config, session=FakeSession(response))

    assert analysis.method == "ai"
    assert (analysis.provider, analysis.model) == (config.provider, config.model)
    # Jan 2021 - Nov 2026 (71 months) and 2018-2020 (36 months).
    assert analysis.years_experience == round(107 / 12, 1)
    assert analysis.years_basis == "positions"
    assert [(p.title, p.company) for p in analysis.positions] == [("Senior Engineer", "Acme"), ("Engineer", "Beta")]
    assert analysis.positions[0].end is None and analysis.positions[1].end == month_index(2020, 12)

    skills = {skill.name: skill for skill in analysis.skills}
    # ReactJS and React.js are the catalog's React; years from Acme.
    assert skills["React"].years == 5.9 and skills["React"].mentions == 1
    assert skills["Java"].years == 3.0 and skills["Java"].last_used == "2020-12"
    # Not in the catalog: the AI's category, and 0 mentions (not in the text).
    assert skills["Microsoft Excel"].category == "Tools"
    assert skills["Microsoft Excel"].mentions == 0 and skills["Microsoft Excel"].years is None


def test_positions_with_bad_dates_are_left_out_with_a_note():
    answer = {"skills": [], "positions": [
        {"title": "Good", "company": "", "start": "2020-01", "end": "2020-06", "skills": []},
        {"title": "Backwards", "company": "", "start": "2020-06", "end": "2020-01", "skills": []},
        {"title": "Garbled", "company": "", "start": "sometime", "end": None, "skills": []},
        {"title": "Future", "company": "", "start": "2030-01", "end": None, "skills": []},
        {"title": "Bad end", "company": "", "start": "2020-01", "end": "soon", "skills": []},
        {"title": "Said present", "company": "", "start": "2026-05", "end": "Present", "skills": []},
        "not a position",
    ]}
    analysis = read_resume_with_ai(RESUME, [], now=NOW, config=CLAUDE, session=FakeSession(claude_answers(answer)))
    assert [p.title for p in analysis.positions] == ["Said present", "Good"]
    assert analysis.positions[0].end is None  # current, though the schema asks for null
    assert analysis.years_experience == round((6 + 7) / 12, 1)  # Jan-Jun 2020, and May-Nov 2026 (inclusive)
    assert "Left out jobs whose dates don't make sense: Backwards, Garbled, Future, Bad end." in analysis.notes


# --- When it goes wrong --------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "response", "message"),
    [
        (CLAUDE, FakeResponse(401, {"type": "error", "error": {"type": "authentication_error",
                                                                "message": "invalid x-api-key"}}),
         "Anthropic answered 401: invalid x-api-key"),
        (GPT, FakeResponse(429, {"error": {"message": "Rate limit reached"}}), "OpenAI answered 429: Rate limit reached"),
        (GPT, FakeResponse(500, text="<html>"), "OpenAI answered 500$"),
        (CLAUDE, FakeResponse(200, text="<html>"), "isn't JSON"),
        (CLAUDE, claude_answers(ANSWER, stop_reason="max_tokens"), "cut off"),
        (CLAUDE, FakeResponse(200, {"content": [{"type": "text", "text": "Sorry"}]}), "didn't return"),
        (GPT, gpt_answers(ANSWER, finish_reason="length"), "cut off"),
        (GPT, gpt_answers(None, refusal="I can't help with that."), "declined to read the resume: I can't help"),
        (GPT, FakeResponse(200, {"choices": [{"message": {"content": "{oops"}}]}), "isn't JSON"),
        (CLAUDE, claude_answers({"positions": "none"}), "isn't in the expected shape"),
    ],
)
def test_failures_say_what_happened(config, response, message):
    with pytest.raises(AiReadError, match=message) as caught:
        read_resume_with_ai(RESUME, [], now=NOW, config=config, session=FakeSession(response))
    assert not caught.value.timed_out


def test_a_timeout_is_marked_as_one():
    session = FakeSession(requests.Timeout("read timed out"))
    with pytest.raises(AiReadError, match="didn't answer within 120s") as caught:
        read_resume_with_ai(RESUME, [], now=NOW, config=CLAUDE, session=session)
    assert caught.value.timed_out


def test_an_unreachable_provider():
    session = FakeSession(requests.ConnectionError("no route to host"))
    with pytest.raises(AiReadError, match="Couldn't reach OpenAI: no route to host"):
        read_resume_with_ai(RESUME, [], now=NOW, config=GPT, session=session)


# --- Levels --------------------------------------------------------------------------


def test_the_ai_rates_each_skill_and_the_rules_fill_in_the_rest():
    answer = {**ANSWER, "skills": [
        {"name": "ReactJS", "category": "Frontend", "level": 4, "level_reason": "Led the dashboard rewrite"},
        {"name": "Python", "category": "Language", "level": 0, "level_reason": "out of range"},
        {"name": "Kubernetes", "category": "DevOps", "level": "5", "level_reason": "not a number"},
        {"name": "Java", "category": "Language", "level": True, "level_reason": "not a number either"},
    ]}
    analysis = read_resume_with_ai(RESUME, [], now=NOW, config=CLAUDE, session=FakeSession(claude_answers(answer)))
    skills = {skill.name: skill for skill in analysis.skills}
    # "ReactJS" is the catalog's React, so the rating lands on it.
    assert (skills["React"].level, skills["React"].level_reason) == (4, "Led the dashboard rewrite")
    # Unusable ratings: the parser's rules instead.
    assert skills["Python"].level_reason.startswith("5.9 years across 1 job")
    assert skills["Kubernetes"].level_reason.startswith("5.9 years")
    assert skills["Java"].level_reason.startswith("3 years")


def test_the_prompt_explains_the_scale():
    session = FakeSession(claude_answers(ANSWER))
    read_resume_with_ai(RESUME, [], now=NOW, config=CLAUDE, session=session)
    prompt = session.calls[0]["json"]["messages"][0]["content"]
    assert "1 Beginner" in prompt and "5 Expert" in prompt
    assert "React work is JavaScript work" in prompt
    level = resume_ai.RESPONSE_SCHEMA["properties"]["skills"]["items"]["properties"]["level"]
    assert level == {"type": "integer", "enum": [1, 2, 3, 4, 5],
                     "description": "1 Beginner, 2 Familiar, 3 Proficient, 4 Advanced, 5 Expert"}



# --- Your own skills -----------------------------------------------------------------

BACKSTAGE_RESUME = """EXPERIENCE
Platform Engineer, Initech
Jan 2022 - Present
- Built the open-source developer portal on Backstage with TypeScript plugins
Developer, Initrode
2019 - 2021
- Python services
"""
BACKSTAGE_ANSWER = {
    # The model passes over Backstage: nothing on the resume says what it is.
    "positions": [
        {"title": "Platform Engineer", "company": "Initech", "start": "2022-01", "end": None, "skills": ["TypeScript"]},
        {"title": "Developer", "company": "Initrode", "start": "2019-01", "end": "2021-12", "skills": ["Python"]},
    ],
    "skills": [{"name": "TypeScript", "category": "Language", "level": 4, "level_reason": "Plugins"},
               {"name": "Python", "category": "Language", "level": 3, "level_reason": "Services"}],
}


def test_the_prompt_asks_for_your_skills_by_name():
    session = FakeSession(claude_answers(BACKSTAGE_ANSWER))
    read_resume_with_ai(BACKSTAGE_RESUME, ["Backstage", "Python"], now=NOW, config=CLAUDE, session=session)
    prompt = session.calls[0]["json"]["messages"][0]["content"]
    assert ("skills the candidate lists as theirs: include each one the resume mentions, even if it doesn't "
            "say what it is, and spell it exactly this way: Backstage, Python.") in prompt


def test_your_skills_the_ai_misses_are_added_with_their_years():
    analysis = read_resume_with_ai(BACKSTAGE_RESUME, ["Backstage", "Python"], now=NOW, config=CLAUDE,
                                   session=FakeSession(claude_answers(BACKSTAGE_ANSWER)))
    skills = {skill.name: skill for skill in analysis.skills}
    backstage = skills["Backstage"]
    # Put on the Initech job (where parsing found it), so its years count: Jan 2022 - Nov 2026.
    assert analysis.positions[0].skills == ("TypeScript", "Backstage")
    assert (backstage.years, backstage.last_used, backstage.category) == (4.9, "present", "DevOps")
    assert backstage.level_reason.startswith("4.9 years across 1 job")
    assert ("The AI didn't name Backstage, which is on your skill list; it was added because the resume "
            "mentions it.") in analysis.notes


def test_only_your_own_skills_are_added_back():
    # Backstage is in the catalog, but not on this list: the AI's judgment stands.
    analysis = read_resume_with_ai(BACKSTAGE_RESUME, ["Python"], now=NOW, config=CLAUDE,
                                   session=FakeSession(claude_answers(BACKSTAGE_ANSWER)))
    assert "Backstage" not in {skill.name for skill in analysis.skills}
    assert not any("didn't name" in note for note in analysis.notes)

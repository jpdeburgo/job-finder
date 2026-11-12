"""Your resume (resume.py): reading PDF, Word, and text files, saving it with
its readings, and the command line."""

import json
import os
from pathlib import Path

import pytest

import resume
from job_store import FirestoreJobStore
from resume import ResumeError, extract_text
from resume_ai import AiNotConfiguredError
from resume_parser import parse_resume
from search_skills import SearchSkills
from tests.resume_files import SAMPLE_RESUME, make_docx, make_pdf, paragraph, table, text_box


@pytest.fixture
def store(tmp_path):
    return FirestoreJobStore.local(tmp_path / "local_firestore.json", verbose=False)


def fake_ai(text, your_skills):
    """Stands in for resume_ai.read_resume_with_ai: a parse, labelled as AI."""
    parsed = parse_resume(text, your_skills)
    return type(parsed)(**{**parsed.__dict__, "method": "ai", "provider": "anthropic", "model": "fake"})


# --- Reading files -------------------------------------------------------------------


def test_pdf_text_is_read():
    text, kind = extract_text("jane.pdf", make_pdf(SAMPLE_RESUME.splitlines()))
    assert kind == "pdf"
    # PDFs lose blank lines; the rest comes through, dashes and all.
    assert text == "\n".join(line for line in SAMPLE_RESUME.splitlines() if line.strip())
    assert parse_resume(text).years_experience == parse_resume(SAMPLE_RESUME).years_experience


def test_the_contents_decide_not_the_name():
    assert extract_text("resume", make_pdf(["Python"]))[1] == "pdf"
    assert extract_text("resume.txt", make_pdf(["Python"]))[1] == "pdf"


def test_a_pdf_without_text_is_probably_a_scan():
    with pytest.raises(ResumeError, match="No text found in scan.pdf. It may be a scanned image"):
        extract_text("scan.pdf", make_pdf([]))


def test_a_password_protected_pdf():
    with pytest.raises(ResumeError, match="password-protected"):
        extract_text("locked.pdf", make_pdf(["Python"], encrypt=True))


def test_a_damaged_pdf():
    with pytest.raises(ResumeError, match="This PDF couldn't be read"):
        extract_text("broken.pdf", b"%PDF-1.4\nnot really a pdf")


def test_docx_paragraphs_tabs_and_breaks():
    docx = make_docx(paragraph("EXPERIENCE") + paragraph("Engineer, Acme\tJan 2020 - Present") + paragraph("a\nb"))
    assert extract_text("cv.docx", docx) == ("EXPERIENCE\nEngineer, Acme\tJan 2020 - Present\na\nb", "docx")


def test_docx_table_rows_keep_a_title_beside_its_dates():
    docx = make_docx(table([
        [["Senior Engineer, Acme"], ["Jan 2020 – Present"]],
        [["Engineer", "Beta LLC"], ["2017 – 2019"]],  # a cell of two paragraphs: one after another
    ]))
    text, _kind = extract_text("cv.docx", docx)
    assert text == "Senior Engineer, Acme | Jan 2020 – Present\nEngineer\nBeta LLC\n2017 – 2019"


def test_docx_text_boxes_are_read_once():
    text, _kind = extract_text("cv.docx", make_docx(paragraph("Jane") + text_box(["Skills: Python"])))
    assert text == "Jane\nSkills: Python"


def test_a_zip_that_isnt_a_word_document():
    import io
    import zipfile

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ResumeError, match="isn't a Word document"):
        extract_text("cv.docx", data.getvalue())


def test_text_files_in_utf8_or_windows_encodings():
    assert extract_text("cv.txt", "\ufeffJosé – Python\r\n".encode("utf-8")) == ("José – Python", "text")
    assert extract_text("cv.md", "José – Python".encode("cp1252")) == ("José – Python", "text")


@pytest.mark.parametrize(
    ("filename", "data", "message"),
    [
        ("cv.pdf", b"", "The file is empty"),
        ("cv.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", r"\(.doc\) files can't be read; save it as .docx or PDF"),
        ("cv.pages", b"whatever", ".pages files can't be read; upload a PDF, Word"),
        ("cv.docx", b"plain text", "doesn't look like a .docx file"),
        ("cv.bin", b"\x00\x01", ".bin files can't be read"),
        ("cv", b"\x00\x01\x02", "This isn't a text file"),
        ("cv.txt", b"   \n\n ", "No text found in cv.txt.$"),
    ],
)
def test_files_that_cant_be_read(filename, data, message):
    with pytest.raises(ResumeError, match=message):
        extract_text(filename, data)


def test_size_limits(monkeypatch):
    monkeypatch.setattr(resume, "MAX_RESUME_BYTES", 10)
    with pytest.raises(ResumeError, match="too big"):
        extract_text("cv.txt", b"x" * 11)
    monkeypatch.setattr(resume, "MAX_RESUME_BYTES", 10_000)
    monkeypatch.setattr(resume, "MAX_RESUME_CHARS", 5)
    with pytest.raises(ResumeError, match="too much text"):
        extract_text("cv.txt", b"Python SQL")


# --- Saving --------------------------------------------------------------------------


def test_an_upload_is_saved_and_parsed(store):
    document = resume.save_resume(store, "/home/jane/Documents/jane.pdf", make_pdf(SAMPLE_RESUME.splitlines()))

    assert document["filename"] == "jane.pdf"  # never a path
    assert document["file_type"] == "pdf"
    assert list(document["analyses"]) == ["parse"]
    assert document["analyses"]["parse"]["years_experience"] == parse_resume(SAMPLE_RESUME).years_experience
    saved = store.load_resume()
    assert saved["text"] == document["text"] and saved["fingerprint"] == resume.fingerprint(document["text"])
    # Stored like the rest of the database: ISO timestamps, read back as datetimes at the top level.
    assert saved["uploaded_at"] == document["uploaded_at"]
    raw = json.loads(store._client.path.read_text())["settings"]["resume"]
    assert isinstance(raw["analyses"]["parse"]["analyzed_at"], str)


def test_pasted_text(store):
    document = resume.save_resume(store, text="  Python and SQL  ")
    assert (document["filename"], document["file_type"], document["text"]) == ("Pasted text", "text", "Python and SQL")
    with pytest.raises(ResumeError, match="Paste your resume's text first"):
        resume.save_resume(store, text="   ")


def test_your_saved_skills_are_looked_for(store):
    store.save_search_skills(SearchSkills(("Ignition", "Python"), ("Python",)))
    document = resume.save_resume(store, text="EXPERIENCE\nControls Engineer  2020 - 2021\n- Ignition and Python")
    names = [skill["name"] for skill in document["analyses"]["parse"]["skills"]]
    assert names == ["Python", "Ignition"]


def test_reading_it_again_with_ai_keeps_both_readings(store):
    resume.save_resume(store, text=SAMPLE_RESUME)
    document = resume.analyze_saved_resume(store, "ai", ai_reader=fake_ai)

    assert sorted(document["analyses"]) == ["ai", "parse"]
    assert document["analyses"]["ai"]["model"] == "fake"
    assert sorted(store.load_resume()["analyses"]) == ["ai", "parse"]


def test_a_new_upload_drops_the_old_readings(store):
    resume.save_resume(store, text=SAMPLE_RESUME)
    resume.analyze_saved_resume(store, "ai", ai_reader=fake_ai)
    resume.save_resume(store, text="Python")
    assert list(store.load_resume()["analyses"]) == ["parse"]


def test_a_reading_isnt_saved_over_a_newer_resume(store):
    resume.save_resume(store, text=SAMPLE_RESUME)

    def slow_ai(text, skills):
        resume.save_resume(store, text="A different resume: Go")  # uploaded meanwhile
        return fake_ai(text, skills)

    with pytest.raises(resume.ResumeChangedError):
        resume.analyze_saved_resume(store, "ai", ai_reader=slow_ai)
    saved = store.load_resume()
    assert saved["text"] == "A different resume: Go" and list(saved["analyses"]) == ["parse"]


def test_analyzing_without_a_resume(store):
    with pytest.raises(resume.NoResumeError, match="upload one first"):
        resume.analyze_saved_resume(store, "parse")


def test_ai_without_a_key(store, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESUME_AI_PROVIDER", raising=False)
    resume.save_resume(store, text=SAMPLE_RESUME)
    with pytest.raises(AiNotConfiguredError):
        resume.analyze_saved_resume(store, "ai")


def test_deleting_leaves_your_skills_alone(store):
    store.save_search_skills(SearchSkills(("Python",), ("Python",)))
    resume.save_resume(store, text=SAMPLE_RESUME)
    store.delete_resume()
    store.delete_resume()  # nothing to delete: fine, like Firestore
    assert store.load_resume() is None
    assert store.load_search_skills()["skills"] == ["Python"]


def test_an_unknown_method():
    with pytest.raises(ValueError, match="Unknown method 'guess'"):
        resume.analyze_text("Python", "guess")


# --- Command line --------------------------------------------------------------------


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "local_firestore.json"
    monkeypatch.setenv("IG_LOCAL_DB_PATH", str(path))
    return path


def test_cli_prints_what_it_found(tmp_path, local_db, capsys):
    cv = tmp_path / "jane.pdf"
    cv.write_bytes(make_pdf(SAMPLE_RESUME.splitlines()))

    assert resume.cli([str(cv), "--local"]) == 0

    out = capsys.readouterr().out
    assert "Read by parsing." in out
    assert "Experience: " in out and "(from the dates of your jobs)" in out
    assert "Senior Software Engineer · Acme Corp · Austin, TX" in out
    assert "AWS" in out and "listed" in out  # Go, say, is only listed
    assert not local_db.exists()  # nothing saved without --save


def test_cli_save(tmp_path, local_db, capsys):
    cv = tmp_path / "jane.txt"
    cv.write_text(SAMPLE_RESUME)
    assert resume.cli([str(cv), "--local", "--save"]) == 0
    assert "Resume page" in capsys.readouterr().out
    saved = FirestoreJobStore.local(local_db, verbose=False).load_resume()
    assert saved["filename"] == "jane.txt" and list(saved["analyses"]) == ["parse"]


def test_cli_problems(tmp_path, local_db, capsys, monkeypatch):
    assert resume.cli([str(tmp_path / "missing.pdf"), "--local"]) == 2
    assert "No such file" in capsys.readouterr().err

    bad = tmp_path / "cv.doc"
    bad.write_bytes(b"\xd0\xcf\x11\xe0rest")
    assert resume.cli([str(bad), "--local"]) == 1
    assert ".doc) files can't be read" in capsys.readouterr().err

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "RESUME_AI_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # ignore a real backend/.env
    good = tmp_path / "cv.txt"
    good.write_text("Python")
    assert resume.cli([str(good), "--local", "--ai"]) == 1
    assert "AI isn't set up" in capsys.readouterr().err


# --- The document the dashboard reads ------------------------------------------------

FRONTEND_FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures" / "resume.json"


def stored_resume_document(tmp_path):
    """settings/resume as the local store writes it: a parsed reading and an
    AI one (a fake Claude answering), at a fixed time."""
    from datetime import datetime, timezone

    from resume_ai import read_resume_with_ai
    from resume_parser import parse_resume as parse
    from tests.test_resume_ai import CLAUDE, FakeSession, claude_answers

    now = datetime(2026, 11, 11, 9, 30, tzinfo=timezone.utc)
    answer = {
        "positions": [
            {"title": "Senior Software Engineer", "company": "Acme Corp", "start": "2021-01", "end": None,
             "skills": ["Python", "Django", "React", "TypeScript", "AWS", "Kubernetes", "Terraform"]},
            {"title": "Software Engineer", "company": "Beta LLC", "start": "2018-03", "end": "2020-12",
             "skills": ["Node.js", "Express", "AWS Lambda", "PostgreSQL", "Redis"]},
        ],
        # Python and ReactJS rated by the AI; the others get the parser's levels.
        "skills": [{"name": "Python", "category": "Language", "level": 5, "level_reason": "6 years; led the API work"},
                   {"name": "ReactJS", "category": "Frontend", "level": 4, "level_reason": "Led the dashboard rewrite"},
                   {"name": "Express", "category": "Backend"}, {"name": "Code review", "category": "Practice"}],
    }
    skills = ["Python", "ReactJS", "Full Stack"]
    document = resume.resume_document("jane-doe.pdf", "pdf", SAMPLE_RESUME.strip(), now)
    document["analyses"] = {
        "parse": parse(document["text"], skills, now=now).as_document(),
        "ai": read_resume_with_ai(document["text"], skills, now=now, config=CLAUDE,
                                  session=FakeSession(claude_answers(answer))).as_document(),
    }
    store = FirestoreJobStore.local(tmp_path / "db.json", verbose=False)
    store.save_resume(document)
    return json.loads((tmp_path / "db.json").read_text())["settings"]["resume"]


def test_the_dashboards_fixture_is_what_the_python_store_writes(tmp_path):
    """frontend/src/test/fixtures/resume.json is what the dashboard's tests
    read; it must match what this side writes. After changing the document,
    regenerate it with UPDATE_RESUME_FIXTURE=1 pytest tests/test_resume.py."""
    written = stored_resume_document(tmp_path)
    if os.environ.get("UPDATE_RESUME_FIXTURE"):
        FRONTEND_FIXTURE.write_text(json.dumps(written, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    assert json.loads(FRONTEND_FIXTURE.read_text()) == written, (
        "The resume document changed; regenerate the dashboard's fixture with "
        "UPDATE_RESUME_FIXTURE=1 pytest tests/test_resume.py"
    )

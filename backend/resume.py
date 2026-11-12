"""Your resume: read it from a file, work out your skills and years of
experience, and keep it in the database.

Two ways to read it, both giving the same kind of ``ResumeAnalysis``:

* ``parse`` (``resume_parser.py``): rules, no AI. Instant and free; runs on
  every upload.
* ``ai`` (``resume_ai.py``): a language model (Claude or OpenAI). Better at
  unusual layouts and at telling an employer from a skill; needs an API key.

The resume is kept in the ``settings`` collection, with each reading::

    settings/resume
        filename      "jane-doe.pdf"
        file_type     pdf | docx | text
        text          the text read from the file
        fingerprint   identifies the text (a reading is only saved for the text it read)
        uploaded_at
        analyses      {"parse": {...}, "ai": {...}}: see ResumeAnalysis.as_document

Uploading a new resume replaces the old one and its readings. The dashboard's
Resume page (``../frontend``) uploads through ``api.py`` and shows the
readings; from there you can add the skills it found to your skill list.

From the command line::

    python resume.py path/to/resume.pdf            # parse it and print what it found
    python resume.py path/to/resume.pdf --ai       # read it with AI instead
    python resume.py path/to/resume.pdf --save     # also save it (what the dashboard shows)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable
from xml.etree import ElementTree

from resume_parser import METHODS, ResumeAnalysis, parse_resume

if TYPE_CHECKING:  # pragma: no cover - typing only
    from job_store import FirestoreJobStore

RESUME_DOCUMENT = "resume"
MAX_RESUME_BYTES = 5 * 1024 * 1024
# Far more than any resume; keeps a stray huge file out of the database.
MAX_RESUME_CHARS = 100_000
# A .docx is a zip; its text part can't be bigger than this unpacked.
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
FILE_TYPES = {".pdf": "pdf", ".docx": "docx", ".txt": "text", ".md": "text", ".text": "text"}
SUPPORTED_FILES = "PDF, Word (.docx), or plain text"


class ResumeError(ValueError):
    """A resume that can't be read (wrong kind of file, no text, too big)."""


class NoResumeError(LookupError):
    """There's no saved resume to analyze."""


class ResumeChangedError(RuntimeError):
    """A new resume was uploaded while the old one was being analyzed."""


# --- Reading files -------------------------------------------------------------------


def file_type(filename: str, data: bytes) -> str:
    """"pdf", "docx", or "text", from the file's contents first and its name second."""
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "docx"
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise ResumeError("Word 97-2003 (.doc) files can't be read; save it as .docx or PDF and upload that.")
    suffix = Path(filename or "").suffix.lower()
    if suffix in FILE_TYPES and FILE_TYPES[suffix] != "text":
        raise ResumeError(f"This doesn't look like a {suffix} file; it may be damaged.")
    if suffix and suffix not in FILE_TYPES:
        raise ResumeError(f"{suffix} files can't be read; upload a {SUPPORTED_FILES} file.")
    if b"\x00" in data[:4096]:
        raise ResumeError(f"This isn't a text file; upload a {SUPPORTED_FILES} file.")
    return "text"


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ResumeError("This PDF is password-protected; save a copy without a password and upload that.")
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ResumeError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise ResumeError(f"This PDF couldn't be read ({error}).") from error


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _docx_paragraph(paragraph: ElementTree.Element) -> list[str]:
    """A paragraph's text, then the lines of any text box inside it."""
    text: list[str] = []
    boxes: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            if child.tag == f"{_W}t":
                text.append(child.text or "")
            elif child.tag == f"{_W}tab":
                text.append("\t")
            elif child.tag in (f"{_W}br", f"{_W}cr"):
                text.append("\n")
            elif child.tag == f"{_W}txbxContent":
                boxes.extend(_docx_lines(child))
            elif child.tag != _FALLBACK:  # the same text box again, for old Word versions
                walk(child)

    walk(paragraph)
    own = "".join(text)
    # A paragraph that only anchors a text box isn't a blank line of its own.
    return (own.split("\n") if own or not boxes else []) + boxes


def _docx_lines(element: ElementTree.Element) -> list[str]:
    """The text of a document body (or table cell, or text box), a line per paragraph.

    A table row whose cells are one line each becomes one line, "a | b": many
    resume templates put the job title and its dates side by side in a table.
    """
    lines: list[str] = []
    for child in element:
        if child.tag == f"{_W}p":
            lines.extend(_docx_paragraph(child))
        elif child.tag == f"{_W}tbl":
            for row in child.iter(f"{_W}tr"):
                cells = [[line for line in _docx_lines(cell) if line.strip()] for cell in row.findall(f"{_W}tc")]
                if all(len(cell) <= 1 for cell in cells):
                    lines.append(" | ".join(cell[0] for cell in cells if cell))
                else:
                    lines.extend(line for cell in cells for line in cell)
        elif child.tag != f"{_W}sectPr":
            lines.extend(_docx_lines(child))  # content controls and the like
    return lines


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError:
                raise ResumeError("This isn't a Word document; upload a .docx or PDF.") from None
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ResumeError("This Word document is too big to be a resume.")
            root = ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise ResumeError(f"This Word document couldn't be read ({error}).") from error
    body = root.find(f"{_W}body")
    return "\n".join(_docx_lines(body if body is not None else root))


def _plain_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def clean_text(text: str) -> str:
    """Tidy extracted text: one kind of line break, no trailing spaces or runs of blank lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").replace("\u00a0", " ")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """The text of a resume file, and its type ("pdf", "docx", or "text").
    Raises ``ResumeError`` when it can't be read or has no text."""
    if not data:
        raise ResumeError("The file is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise ResumeError(f"The file is too big: a resume can be at most {MAX_RESUME_BYTES // (1024 * 1024)} MB.")
    kind = file_type(filename, data)
    raw = {"pdf": _pdf_text, "docx": _docx_text, "text": _plain_text}[kind](data)
    text = clean_text(raw)
    if not text:
        hint = " It may be a scanned image; export a PDF with real text, or paste the text instead." \
            if kind == "pdf" else ""
        raise ResumeError(f"No text found in {filename or 'the file'}.{hint}")
    if len(text) > MAX_RESUME_CHARS:
        raise ResumeError(f"That's too much text for a resume (over {MAX_RESUME_CHARS:,} characters).")
    return text, kind


# --- Analysing and saving ------------------------------------------------------------

AiReader = Callable[[str, list[str]], ResumeAnalysis]


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read_with_ai(text: str, your_skills: list[str]) -> ResumeAnalysis:
    from resume_ai import read_resume_with_ai

    return read_resume_with_ai(text, your_skills)


def analyze_text(
    text: str, method: str, your_skills: Iterable[str] = (), ai_reader: AiReader | None = None
) -> ResumeAnalysis:
    """Read a resume's text with ``method`` ("parse" or "ai")."""
    if method not in METHODS:
        raise ValueError(f"Unknown method {method!r}; expected one of {', '.join(METHODS)}")
    if method == "ai":
        return (ai_reader or _read_with_ai)(text, list(your_skills))
    return parse_resume(text, your_skills)


def your_skill_names(store: "FirestoreJobStore") -> list[str]:
    """Your skill list (the defaults until you save one): skills on it are
    looked for in your resume as well as the catalog's."""
    import job_search

    return list((job_search.saved_search_skills(store) or job_search.default_search_skills()).skills)


def resume_document(filename: str, kind: str, text: str, now: datetime | None = None) -> dict[str, Any]:
    return {
        "filename": filename,
        "file_type": kind,
        "text": text,
        "fingerprint": fingerprint(text),
        "uploaded_at": now or datetime.now(timezone.utc),
        "analyses": {},
    }


def read_resume(filename: str = "", data: bytes | None = None, text: str | None = None) -> tuple[str, str, str]:
    """(file name, file type, text) for an uploaded file's bytes or pasted
    ``text``. Raises ``ResumeError`` when there's nothing usable."""
    filename = Path(filename or "").name[:255]
    if text is None:
        text, kind = extract_text(filename, data or b"")
        return filename or "Resume", kind, text
    text = clean_text(text)
    if not text:
        raise ResumeError("Paste your resume's text first.")
    if len(text) > MAX_RESUME_CHARS:
        raise ResumeError(f"That's too much text for a resume (over {MAX_RESUME_CHARS:,} characters).")
    return filename or "Pasted text", "text", text


def save_resume(
    store: "FirestoreJobStore",
    filename: str = "",
    data: bytes | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    """Read a resume (a file's bytes, or pasted ``text``), parse it, and save
    both, replacing any resume saved before. Returns the saved document."""
    filename, kind, text = read_resume(filename, data, text)
    document = resume_document(filename, kind, text)
    document["analyses"] = {"parse": analyze_text(text, "parse", your_skill_names(store)).as_document()}
    store.save_resume(document)
    return document


def analyze_saved_resume(
    store: "FirestoreJobStore", method: str, ai_reader: AiReader | None = None
) -> dict[str, Any]:
    """Read the saved resume again with ``method`` (say, with AI after the
    upload parsed it, or parse it again after changing your skills), save
    that reading next to the others, and return the document."""
    saved = store.load_resume()
    if not saved or not saved.get("text"):
        raise NoResumeError("No resume saved yet; upload one first.")
    text = str(saved["text"])
    analysis = analyze_text(text, method, your_skill_names(store), ai_reader)
    updated = store.save_resume_analysis(method, analysis.as_document(), saved.get("fingerprint") or fingerprint(text))
    if updated is None:
        raise ResumeChangedError("A new resume was uploaded while this one was being read; try again.")
    return updated


# --- Command line --------------------------------------------------------------------


def describe(analysis: ResumeAnalysis) -> list[str]:
    """What a reading found, as lines for the terminal."""
    how = f"AI ({analysis.provider}, {analysis.model})" if analysis.method == "ai" else "parsing"
    years = (f"{analysis.years_experience:g} years" if analysis.years_experience is not None else "unknown")
    basis = {"positions": " (from the dates of your jobs)", "stated": " (as the resume states)"}.get(
        analysis.years_basis or "", ""
    )
    lines = [f"Read by {how}.", f"Experience: {years}{basis}", "", f"Jobs ({len(analysis.positions)}):"]
    today = analysis.analyzed_at.year * 12 + analysis.analyzed_at.month - 1
    for position in analysis.positions:
        document = position.as_document(today)
        where = " · ".join(part for part in (position.title, position.company) if part) or "(untitled)"
        lines.append(f"  {document['start']} to {document['end'] or 'present'} "
                     f"({document['months']} months)  {where}")
    lines += ["", f"Skills ({len(analysis.skills)}):"]
    for skill in analysis.skills:
        years_text = f"{skill.years:g} yrs" if skill.years is not None else "listed"
        mentions = f"{skill.mentions}x" if skill.mentions else "inferred"
        lines.append(f"  {skill.name:<24} {years_text:<8} {mentions:<9} {skill.category}")
    if analysis.notes:
        lines += ["", *(f"Note: {note}" for note in analysis.notes)]
    return lines


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resume.py", description="Work out your skills and years of experience from your resume."
    )
    parser.add_argument("file", type=Path, help=f"your resume: {SUPPORTED_FILES}")
    parser.add_argument("--ai", action="store_true", help="read it with AI (needs ANTHROPIC_API_KEY or OPENAI_API_KEY)")
    parser.add_argument("--save", action="store_true", help="save it for the dashboard's Resume page")
    parser.add_argument("--local", action="store_true", help="use local_firestore.json even if Firebase is configured")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    from job_store import FirestoreJobStore, get_job_store
    from resume_ai import AiNotConfiguredError, AiReadError

    load_dotenv()
    store = FirestoreJobStore.local(verbose=False) if args.local else get_job_store(verbose=False)
    method = "ai" if args.ai else "parse"
    try:
        filename, kind, text = read_resume(args.file.name, args.file.read_bytes())
        skills = your_skill_names(store)
        # Saving always keeps the parsed reading, like an upload on the dashboard.
        analyses = {name: analyze_text(text, name, skills) for name in dict.fromkeys(["parse", method])}
        if args.save:
            document = resume_document(filename, kind, text)
            document["analyses"] = {name: analysis.as_document() for name, analysis in analyses.items()}
            store.save_resume(document)
    except OSError as error:
        print(f"resume.py: error: {error}", file=sys.stderr)
        return 2
    except (ResumeError, AiNotConfiguredError, AiReadError) as error:
        print(f"resume.py: {error}", file=sys.stderr)
        return 1
    print("\n".join(describe(analyses[method])))
    if args.save:
        print(f"\nSaved to {store.description}; see the dashboard's Resume page.")
    return 0


if __name__ == "__main__":
    sys.exit(cli())

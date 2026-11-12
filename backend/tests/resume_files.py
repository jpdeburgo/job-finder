"""Small resume files for the tests, built by hand so the suite needs no PDF
or Word library of its own: a one-page PDF with real text (what pypdf reads
in a resume exported from Word or Google Docs) and a minimal .docx."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

_W_NAMESPACE = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_MC_NAMESPACE = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'


def make_pdf(lines: list[str], encrypt: bool = False) -> bytes:
    """A one-page PDF showing ``lines`` in Helvetica (WinAnsi, so "–" works)."""

    def literal(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = ("BT /F1 10 Tf 50 760 Td 13 TL\n"
               + "".join(f"({literal(line)}) Tj T*\n" for line in lines) + "ET").encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    if not encrypt:
        return out.getvalue()
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(out.getvalue())))
    writer.encrypt("secret", algorithm="RC4-128")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    return encrypted.getvalue()


def paragraph(text: str) -> str:
    """A Word paragraph; a "\\t" in the text is a tab, a "\\n" a line break."""
    runs = []
    for number, line in enumerate(text.split("\n")):
        if number:
            runs.append("<w:r><w:br/></w:r>")
        for part_number, part in enumerate(line.split("\t")):
            if part_number:
                runs.append("<w:r><w:tab/></w:r>")
            runs.append(f'<w:r><w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return f"<w:p>{''.join(runs)}</w:p>"


def table(rows: list[list[list[str]]]) -> str:
    """A Word table: rows of cells, each cell a list of paragraphs."""
    body = "".join(
        "<w:tr>" + "".join("<w:tc>" + "".join(paragraph(p) for p in cell) + "</w:tc>" for cell in row) + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl>{body}</w:tbl>"


def text_box(lines: list[str]) -> str:
    """A paragraph holding a text box, the way Word saves one: the box, then
    the same box again as a fallback for old versions (which must be skipped)."""
    box = "<w:txbxContent>" + "".join(paragraph(line) for line in lines) + "</w:txbxContent>"
    return (f"<w:p><w:r><mc:AlternateContent><mc:Choice><w:drawing>{box}</w:drawing></mc:Choice>"
            f"<mc:Fallback><w:pict>{box}</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>")


def make_docx(body_xml: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document {_W_NAMESPACE} {_MC_NAMESPACE}>'
            f"<w:body>{body_xml}<w:sectPr/></w:body></w:document>",
        )
    return out.getvalue()


# A resume with the things that make years tricky: overlapping jobs, an
# education section and a project that mustn't count, a range given in years
# only, and dates inside a bullet point.
SAMPLE_RESUME = """Jane Doe
Cypress, TX | jane@example.com | (555) 201-9988

SUMMARY
Full stack engineer with 8+ years of experience building web apps in Python and React.

TECHNICAL SKILLS
Languages: Python, TypeScript, JavaScript, Go, SQL
Frameworks: React, Django, Node.js, Express
Cloud & DevOps: AWS, Docker, Kubernetes, Terraform, GitHub Actions

PROFESSIONAL EXPERIENCE
Senior Software Engineer | Acme Corp | Austin, TX
Jan 2021 – Present
- Built REST APIs in Python/Django serving 2M users; migrated services 2019–2020 to AWS
- Led the React + TypeScript rewrite of the customer dashboard
- Ran services on Kubernetes with Terraform-managed infrastructure

Software Engineer
Beta LLC, Remote
03/2018 - 12/2020
- Node.js and Express microservices on AWS Lambda
- PostgreSQL schema design, Redis caching

Freelance Web Developer          2019 - 2020
- WordPress and React sites for local businesses

Junior Developer, Gamma Inc.     June 2016 – February 2018
- Java and Spring Boot; jQuery front end

EDUCATION
B.S. Computer Science, State University     2012 – 2016

PROJECTS
Side project in Rust    2022 - 2023
"""

"""Text normalisation, contact-detail detection and section parsing."""

import os
import shutil

import pytest

from engine.extractor import (
    clean_resume_text,
    extract_candidate_metadata,
    extract_text_from_bytes,
    extract_text_from_pdf,
    parse_resume_sections,
)

_TESSERACT_AVAILABLE = shutil.which("tesseract") is not None or bool(os.environ.get("TESSERACT_CMD"))


def _make_pdf_page_image(lines):
    """A PDF page rendered purely as a raster image - no text objects at all, the same
    shape as a scanned or photographed resume."""
    import io

    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (850, 1100), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((50, 50 + i * 30), line, fill="black")
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)

    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=letter)
    c.drawImage(ImageReader(img_buffer), 0, 0, width=letter[0], height=letter[1])
    c.save()
    return pdf_buffer.getvalue()


class TestCleanResumeText:
    def test_normalises_bullet_glyphs(self):
        assert "•" in clean_resume_text("‣ item")

    def test_collapses_runs_of_blank_lines(self):
        assert clean_resume_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_normalises_windows_line_endings(self):
        assert "\r" not in clean_resume_text("a\r\nb\r\nc")

    def test_collapses_internal_whitespace(self):
        assert clean_resume_text("a     b\t\tc") == "a b c"

    def test_empty_input_is_safe(self):
        assert clean_resume_text("") == ""


class TestCandidateMetadata:
    def test_extracts_the_full_contact_set(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        assert meta["name"] == "JANE DOE"
        assert meta["email"] == "jane.doe@example.org"
        assert "555" in meta["phone"]
        assert "linkedin.com/in/janedoe" in meta["linkedin"]

    def test_phone_detection_ignores_body_numbers(self):
        """
        Scanning the whole document used to return a CGPA, a date range or an equipment
        rating before ever reaching the real phone number in the header.
        """
        resume = """JANE DOE
+1-555-987-6543 | jane@example.org

EDUCATION
B.Tech 2019 - 2023, CGPA 8.5 / 10
Worked on 132/33 kV substations and 48V battery packs.
"""
        meta = extract_candidate_metadata(resume)
        digits = "".join(c for c in meta["phone"] if c.isdigit())
        assert digits.endswith("5559876543")

    def test_no_phone_reported_when_there_is_none(self):
        meta = extract_candidate_metadata("JANE DOE\njane@example.org\n\nSUMMARY\nEngineer.")
        assert meta["phone"] == ""

    def test_profile_links_are_not_mistaken_for_the_name(self):
        meta = extract_candidate_metadata("linkedin.com/in/janedoe\nJANE DOE\njane@example.org")
        assert meta["name"] == "JANE DOE"

    def test_contact_line_joins_available_details(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        assert "jane.doe@example.org" in meta["contact_line"]
        assert "|" in meta["contact_line"]

    def test_github_is_detected(self):
        meta = extract_candidate_metadata("JANE DOE\ngithub.com/janedoe | jane@example.org")
        assert "github.com/janedoe" in meta["github"]


class TestSectionParsing:
    def test_splits_into_recognised_sections(self, sample_resume):
        sections = parse_resume_sections(sample_resume)
        assert "Backend engineer" in sections["summary"]
        assert "Python" in sections["skills"]
        assert "Acme Corp" in sections["experience"]
        assert "State University" in sections["education"]
        assert "Telemetry Pipeline" in sections["projects"]

    def test_content_before_the_first_heading_lands_in_contact(self, sample_resume):
        assert "JANE DOE" in parse_resume_sections(sample_resume)["contact"]

    def test_unknown_input_does_not_raise(self):
        sections = parse_resume_sections("just one line of text")
        assert isinstance(sections, dict)
        assert "just one line" in sections["contact"]


class TestExtractFromBytes:
    def test_reads_plain_text(self):
        assert "Hello" in extract_text_from_bytes(b"Hello world", "resume.txt")

    def test_falls_back_on_undecodable_bytes(self):
        """A latin-1 CV must not raise; it degrades to a lossy decode."""
        assert extract_text_from_bytes(b"caf\xe9 resume", "resume.txt")


@pytest.mark.skipif(not _TESSERACT_AVAILABLE, reason="tesseract binary not found on PATH or TESSERACT_CMD")
class TestOcrFallback:
    """
    A scanned or photographed PDF has no embedded text objects - only a picture of
    text - so pypdf's extraction (which reads text objects, not pixels) finds nothing.
    This used to surface as a misleading "Extracted 0 words" success message; OCR is
    the actual fix, this just confirms it still works.
    """

    def test_recovers_text_from_an_image_only_pdf(self):
        pdf_bytes = _make_pdf_page_image(["Jane Doe", "jane.doe@example.com"])
        extracted = extract_text_from_pdf(pdf_bytes)
        assert "jane" in extracted.lower()

    def test_does_not_run_on_a_normal_text_pdf(self):
        """A real text layer must be used as-is - OCR is a fallback, not a first resort."""
        import io

        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.drawString(72, 750, "Jane Doe")
        c.drawString(72, 730, "jane.doe@example.com")
        c.save()

        extracted = extract_text_from_pdf(buf.getvalue())
        # A real text layer round-trips exactly; OCR output has enough character-level
        # noise (spacing, ligatures) that an exact match here would be unlikely if OCR
        # had run instead.
        assert extracted == "Jane Doe\njane.doe@example.com"

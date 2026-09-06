"""Text normalisation, contact-detail detection and section parsing."""

from engine.extractor import (
    clean_resume_text,
    extract_candidate_metadata,
    extract_text_from_bytes,
    parse_resume_sections,
)


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

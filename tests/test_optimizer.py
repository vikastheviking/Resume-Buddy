"""
Optimizer behaviour.

The two properties worth guarding hardest are that scores are never inflated toward a
target, and that no code path invents content the candidate did not supply.
"""

import pytest

from engine.optimizer import clean_llm_markdown, optimize_resume, _format_resume_structurally
from engine.extractor import extract_candidate_metadata
from engine.scorer import evaluate_resume_ats


class FakeLLM:
    """Stands in for a live provider. `response` is returned verbatim from call_chat."""

    def __init__(self, response="", api_key="test-key", raises=None):
        self.response = response
        self.api_key = api_key
        self.model = "fake-model"
        self.raises = raises
        self.calls = 0

    def call_chat(self, system_prompt, user_prompt, temperature=0.2):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.response


class TestCleanLlmMarkdown:
    def test_strips_chain_of_thought_blocks(self):
        out = clean_llm_markdown("<think>reasoning here</think>\n# Jane Doe\n\n## PROFESSIONAL SUMMARY\nText.")
        assert "reasoning here" not in out
        assert "<think>" not in out

    def test_strips_dangling_think_tag(self):
        out = clean_llm_markdown("</think>\n# Jane Doe\n\n## PROFESSIONAL SUMMARY\nText.")
        assert "think" not in out.lower()

    def test_strips_code_fences(self):
        out = clean_llm_markdown("```markdown\n# Jane Doe\n\n## PROFESSIONAL SUMMARY\nText.\n```")
        assert "```" not in out
        assert out.startswith("# Jane Doe")

    def test_cuts_trailing_self_critique(self):
        raw = "# Jane Doe\n\n## PROFESSIONAL SUMMARY\nReal content.\n\nCheck against constraints:\nExact name? Yes."
        out = clean_llm_markdown(raw)
        assert "Check against constraints" not in out
        assert "Exact name?" not in out
        assert "Real content." in out

    def test_canonicalises_section_headings(self):
        out = clean_llm_markdown("# Jane Doe\n\nProfessional Summary\nText.\n\nKey Projects\n- A project.")
        assert "## PROFESSIONAL SUMMARY" in out
        assert "## KEY PROJECTS" in out

    def test_normalises_bullet_markers(self):
        out = clean_llm_markdown("# Jane\n\n## KEY PROJECTS\n• First\n* Second\n- Third")
        assert out.count("\n- ") == 3
        assert "•" not in out

    def test_normalises_smart_typography(self):
        out = clean_llm_markdown("# Jane\n\n## PROFESSIONAL SUMMARY\n2020 – 2024, the team’s “goal”.")
        assert "–" not in out and "’" not in out and "“" not in out

    def test_prepends_real_identity_when_the_model_omits_it(self):
        meta = {"name": "JANE DOE", "contact_line": "jane@example.org"}
        out = clean_llm_markdown("## PROFESSIONAL SUMMARY\nSome text.", meta=meta)
        assert out.startswith("# JANE DOE\njane@example.org")

    def test_replaces_a_hallucinated_identity_header(self):
        meta = {"name": "JANE DOE", "contact_line": "jane@example.org"}
        out = clean_llm_markdown("# Alexander Chen\nfake@nowhere.com\n\n## PROFESSIONAL SUMMARY\nText.", meta=meta)
        assert out.startswith("# JANE DOE")
        assert "Alexander Chen" not in out
        assert "fake@nowhere.com" not in out

    def test_is_idempotent(self):
        """The optimizer used to run this twice; running twice must not change the result."""
        meta = {"name": "JANE DOE", "contact_line": "jane@example.org"}
        once = clean_llm_markdown("# JANE DOE\njane@example.org\n\n## KEY PROJECTS\n- A project.", meta=meta)
        twice = clean_llm_markdown(once, meta=meta)
        assert once == twice

    def test_empty_input_returns_empty(self):
        assert clean_llm_markdown("") == ""


class TestStructuralFormatter:
    def test_preserves_identity_and_contact(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        out = _format_resume_structurally(sample_resume, meta)
        assert out.startswith("# JANE DOE")
        assert "jane.doe@example.org" in out

    def test_preserves_every_real_employer_and_institution(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        out = _format_resume_structurally(sample_resume, meta)
        for fact in ["Acme Corp", "State University", "Telemetry Pipeline", "2M requests/day", "40%"]:
            assert fact in out, f"lost real content: {fact}"

    def test_invents_no_content(self, sample_resume):
        """
        The previous implementation emitted invented bullets and metrics for any resume.
        Every number in the output must come from the input.
        """
        import re

        meta = extract_candidate_metadata(sample_resume)
        out = _format_resume_structurally(sample_resume, meta)

        source_numbers = set(re.findall(r"\d+", sample_resume))
        output_numbers = set(re.findall(r"\d+", out))
        assert output_numbers <= source_numbers, f"invented figures: {output_numbers - source_numbers}"

    def test_emits_canonical_section_headings(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        out = _format_resume_structurally(sample_resume, meta)
        assert "## PROFESSIONAL SUMMARY" in out
        assert "## PROFESSIONAL & INTERNSHIP EXPERIENCE" in out
        assert "## EDUCATION & CERTIFICATIONS" in out


class TestOptimizeResume:
    def test_scores_are_not_inflated_toward_a_target(self, sample_resume, sample_jd):
        """
        A weak rewrite must report its real score.

        The engine previously overwrote any score below 90 with a hardcoded 92-98,
        so the headline number was manufactured rather than measured.
        """
        weak = "# JANE DOE\njane.doe@example.org\n\n## PROFESSIONAL SUMMARY\nI make pastries all day long."
        _, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=weak), evaluate_resume_ats(sample_resume, sample_jd))

        expected = evaluate_resume_ats(clean_llm_markdown(weak, meta=extract_candidate_metadata(sample_resume)), sample_jd)
        assert audit["overall_score"] == expected["overall_score"]
        assert audit["overall_score"] < 90, "a pastry resume should not score as a backend engineer"

    def test_falls_back_structurally_without_an_api_key(self, sample_resume, sample_jd):
        llm = FakeLLM(api_key="")
        text, audit = optimize_resume(sample_resume, sample_jd, llm, evaluate_resume_ats(sample_resume, sample_jd))
        assert llm.calls == 0, "must not call a provider with no key"
        assert audit["engine_used"].startswith("structural")
        assert "JANE DOE" in text

    def test_falls_back_structurally_when_the_provider_fails(self, sample_resume, sample_jd):
        llm = FakeLLM(raises=RuntimeError("provider exploded"))
        text, audit = optimize_resume(sample_resume, sample_jd, llm, evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("structural")
        assert "Acme Corp" in text

    def test_falls_back_when_the_provider_returns_almost_nothing(self, sample_resume, sample_jd):
        text, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response="# J"), evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("structural")
        assert "Acme Corp" in text

    def test_injected_keywords_reports_only_genuine_gains(self, sample_resume, sample_jd):
        baseline = evaluate_resume_ats(sample_resume, sample_jd)
        rewritten = (
            "# JANE DOE\njane.doe@example.org | +1-555-123-4567\n\n"
            "## CORE COMPETENCIES & TECHNICAL SKILLS\nPython, Docker, Kubernetes, AWS, CI/CD, PostgreSQL\n"
        )
        _, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=rewritten), baseline)

        assert "kubernetes" in baseline["missing_keywords"]
        assert "kubernetes" in audit["injected_keywords"]
        # Nothing already present at baseline is reported as newly gained.
        assert not (set(audit["injected_keywords"]) & set(baseline["matched_keywords"]))

    def test_engine_used_identifies_the_llm_path(self, sample_resume, sample_jd):
        good = "# JANE DOE\njane.doe@example.org\n\n## PROFESSIONAL SUMMARY\n" + ("Solid experience. " * 20)
        _, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=good), evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("llm:")


class TestNoHardcodedIdentity:
    """
    The engine used to name one real person's employers in the system prompt and in
    several regexes, so every user's output was contaminated by their details.
    """

    @pytest.mark.parametrize(
        "leaked",
        ["SL Lumax", "APTRANSCO", "Indian Railways", "Retrofitted", "MANDA", "CHAKRADEV"],
    )
    def test_no_real_person_is_referenced_in_the_module(self, leaked):
        import engine.optimizer as optimizer_module
        from pathlib import Path

        source = Path(optimizer_module.__file__).read_text(encoding="utf-8")
        assert leaked.lower() not in source.lower()

    def test_structural_output_contains_only_the_candidates_employers(self, sample_resume):
        meta = extract_candidate_metadata(sample_resume)
        out = _format_resume_structurally(sample_resume, meta)
        for foreign in ["SL Lumax", "APTRANSCO", "Indian Railways"]:
            assert foreign not in out

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
    def test_discards_a_rewrite_that_scores_worse_than_the_baseline(self, sample_resume, sample_jd):
        """
        A weak rewrite must never be shipped as "the optimized resume".

        The engine previously overwrote any score below 90 with a hardcoded 92-98
        (score fabrication). The fix for that must not stop at "report the real score
        honestly" — a rewrite that honestly scores worse than the original is still a
        worse resume than the one the user started with, so it's discarded in favor of
        the unmodified original rather than handed back as "optimized".
        """
        baseline = evaluate_resume_ats(sample_resume, sample_jd)
        weak = "# JANE DOE\njane.doe@example.org\n\n## PROFESSIONAL SUMMARY\nI make pastries all day long."
        text, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=weak), baseline)

        assert audit["overall_score"] >= baseline["overall_score"], "must never end up below the honest baseline"
        # The structural reformat of the real resume ties-or-beats baseline (same real
        # content, just reorganized), so the fallback stops there rather than needing to
        # go all the way back to the literal, unreformatted original.
        assert audit["engine_used"].startswith("structural")
        assert "pastries" not in text
        assert "JANE DOE" in text
        assert "Acme Corp" in text
        # rewrite_status must say "discarded" (a rewrite ran and lost to a stronger
        # candidate), never "no_key"/"llm_failed" — those would tell the frontend to
        # show a wrong notice ("add an API key") when a key was configured and used.
        assert audit["rewrite_status"] == "discarded"

    def test_falls_back_structurally_without_an_api_key(self, sample_resume, sample_jd):
        llm = FakeLLM(api_key="")
        text, audit = optimize_resume(sample_resume, sample_jd, llm, evaluate_resume_ats(sample_resume, sample_jd))
        assert llm.calls == 0, "must not call a provider with no key"
        assert audit["engine_used"].startswith("structural")
        assert audit["rewrite_status"] == "no_key"
        assert "JANE DOE" in text

    def test_falls_back_structurally_when_the_provider_fails(self, sample_resume, sample_jd):
        llm = FakeLLM(raises=RuntimeError("provider exploded"))
        text, audit = optimize_resume(sample_resume, sample_jd, llm, evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("structural")
        assert audit["rewrite_status"] == "llm_failed"
        assert "Acme Corp" in text

    def test_falls_back_when_the_provider_returns_almost_nothing(self, sample_resume, sample_jd):
        text, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response="# J"), evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("structural")
        assert audit["rewrite_status"] == "llm_failed"
        assert "Acme Corp" in text

    def test_injected_keywords_reports_only_genuine_gains(self, sample_resume, sample_jd):
        baseline = evaluate_resume_ats(sample_resume, sample_jd)
        # A full rewrite that keeps every real fact from sample_resume and adds the one
        # genuinely-missing keyword — it must score at or above baseline, or the new
        # non-regression safety net discards it before injected_keywords is even computed.
        rewritten = (
            "# JANE DOE\njane.doe@example.org | +1-555-123-4567 | Austin, Texas | linkedin.com/in/janedoe\n\n"
            "## PROFESSIONAL SUMMARY\nBackend engineer with five years building and testing distributed services.\n\n"
            "## CORE COMPETENCIES & TECHNICAL SKILLS\n- Python\n- Docker\n- Kubernetes\n- PostgreSQL\n- AWS\n- CI/CD\n\n"
            "## PROFESSIONAL & INTERNSHIP EXPERIENCE\n\n### Senior Engineer | Acme Corp | 2020 - 2024\n"
            "- Built REST APIs serving 2M requests/day.\n"
            "- Reduced p99 latency by 40% through query optimization on Kubernetes clusters.\n\n"
            "## KEY PROJECTS\n\n### Telemetry Pipeline | Python, Kafka\n"
            "- Designed an ingestion pipeline processing 500 events/second.\n\n"
            "## EDUCATION & CERTIFICATIONS\n- B.S. Computer Science, State University, 2020\n"
        )
        _, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=rewritten), baseline)

        assert "kubernetes" in baseline["missing_keywords"]
        assert "kubernetes" in audit["injected_keywords"]
        # Nothing already present at baseline is reported as newly gained.
        assert not (set(audit["injected_keywords"]) & set(baseline["matched_keywords"]))

    def test_engine_used_identifies_the_llm_path(self, sample_resume, sample_jd):
        # Must score at or above baseline, or the non-regression safety net discards it
        # in favor of the original before engine_used is ever set to "llm:...".
        good = (
            "# JANE DOE\njane.doe@example.org | +1-555-123-4567 | Austin, Texas | linkedin.com/in/janedoe\n\n"
            "## PROFESSIONAL SUMMARY\nBackend engineer with five years building and testing distributed services.\n\n"
            "## CORE COMPETENCIES & TECHNICAL SKILLS\n- Python\n- Docker\n- PostgreSQL\n- AWS\n- CI/CD\n\n"
            "## PROFESSIONAL & INTERNSHIP EXPERIENCE\n\n### Senior Engineer | Acme Corp | 2020 - 2024\n"
            "- Built REST APIs serving 2M requests/day.\n- Reduced p99 latency by 40% through query optimization.\n\n"
            "## KEY PROJECTS\n\n### Telemetry Pipeline | Python, Kafka\n"
            "- Designed an ingestion pipeline processing 500 events/second.\n\n"
            "## EDUCATION & CERTIFICATIONS\n- B.S. Computer Science, State University, 2020\n"
        )
        _, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=good), evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("llm:")
        assert audit["rewrite_status"] == "llm"

    def test_json_schema_parsing_and_output(self, sample_resume, sample_jd):
        # optimized_resume must carry enough of the real content (plus key_projects, the
        # section the JSON schema used to have no field for) to score at or above
        # baseline — otherwise the non-regression safety net discards it before any of
        # the JSON-derived fields below are ever set.
        json_payload = """
        {
          "ats_score": 92,
          "score_breakdown": {
            "hard_skill_keyword_coverage": 46,
            "job_title_domain_alignment": 14,
            "structure_format_compliance": 14,
            "soft_skill_qualification_coverage": 9,
            "formatting_parseability": 9
          },
          "matched_keywords": ["python", "docker", "gcp"],
          "gap_keywords": ["kubernetes"],
          "revision_log": ["Pass 1: 78% → integrated 5 implicit matches", "Pass 2: 92% → achieved high match"],
          "optimized_resume": {
            "contact_information": "# JANE DOE\\njane.doe@example.org | +1-555-123-4567 | Austin, Texas | linkedin.com/in/janedoe",
            "professional_summary": "Senior Backend Engineer with five years building and testing distributed services on GCP.",
            "core_skills": ["Python", "Docker", "GCP", "PostgreSQL", "AWS", "CI/CD"],
            "professional_experience": [
              {
                "title": "Senior Backend Engineer",
                "company": "Acme Corp",
                "dates": "2021 - Present",
                "bullets": [
                  "Architected Python REST APIs on GCP with 99.9% uptime.",
                  "Reduced p99 latency by 40% through query optimization."
                ]
              }
            ],
            "key_projects": [
              {
                "name": "Telemetry Pipeline",
                "dates": "2020",
                "bullets": ["Designed an ingestion pipeline processing 500 events/second."]
              }
            ],
            "education": ["BS Computer Science, State University, 2020"],
            "certifications": ["GCP Cloud Architect"]
          }
        }
        """
        text, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=json_payload), evaluate_resume_ats(sample_resume, sample_jd))

        # The model's self-reported ats_score (92) and score_breakdown must be ignored —
        # audit reflects the scorer's own honest measurement of the actual rewritten text,
        # not whatever the LLM claims about its own output.
        expected = evaluate_resume_ats(text, sample_jd)
        assert audit["ats_score"] == expected["overall_score"]
        assert audit["ats_score"] != 92
        assert audit["score_breakdown"] == expected["score_breakdown"]
        assert audit["gap_keywords"] == expected["missing_keywords"]
        assert len(audit["revision_log"]) == 2
        assert "JANE DOE" in text
        assert "GCP Cloud Architect" in text

    def test_unparseable_json_falls_back_structurally(self, sample_resume, sample_jd):
        """
        A truncated JSON response (e.g. the model hit its output-token limit mid-object)
        must never be shipped as-is — that ships raw braces and schema field names as
        the "resume". It must fall back to the honest structural reformatting instead.
        """
        truncated = (
            '{"ats_score": 95, "optimized_resume": {"contact_information": "# JANE DOE",'
            ' "professional_summary": "Senior engineer with GCP and Python exp'
        )
        text, audit = optimize_resume(sample_resume, sample_jd, FakeLLM(response=truncated), evaluate_resume_ats(sample_resume, sample_jd))
        assert audit["engine_used"].startswith("structural")
        assert '"optimized_resume"' not in text
        assert "Acme Corp" in text


class TestJsonResumeToMarkdown:
    def test_does_not_duplicate_name_when_contact_information_already_leads_with_it(self):
        from engine.optimizer import json_resume_to_markdown

        resume_obj = {
            "contact_information": "AARAV NARAYAN VENKATA SRINIVASAN\n+91-9000000000 | aarav@example.com",
            "professional_summary": "Engineer.",
        }
        out = json_resume_to_markdown(resume_obj, candidate_name="AARAV NARAYAN VENKATA SRINIVASAN")
        assert out.count("AARAV NARAYAN VENKATA SRINIVASAN") == 1
        assert out.startswith("# AARAV NARAYAN VENKATA SRINIVASAN")

    def test_preserves_key_projects_and_achievements(self):
        from engine.optimizer import json_resume_to_markdown

        resume_obj = {
            "contact_information": "Jane Doe",
            "key_projects": [{"name": "Retrofitted Electric Bike", "dates": "2025", "bullets": ["Converted a bike to EV."]}],
            "achievements": ["Overall Champion — EBDC 2024"],
        }
        out = json_resume_to_markdown(resume_obj, candidate_name="Jane Doe")
        assert "## KEY PROJECTS" in out
        assert "Retrofitted Electric Bike" in out
        assert "## ACHIEVEMENTS & AWARDS" in out
        assert "Overall Champion" in out


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


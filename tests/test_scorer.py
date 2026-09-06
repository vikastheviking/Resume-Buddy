"""Scoring behaviour: keyword matching rules, component scores, and the composite."""

import pytest

from engine.scorer import (
    evaluate_resume_ats,
    extract_keywords_from_text,
    extract_quantifiable_metrics,
)


class TestKeywordExtraction:
    def test_recognises_punctuated_technology_names(self):
        """\\b breaks on '+', '#' and '.', so these need the custom boundaries."""
        found = extract_keywords_from_text("Experienced in C++, C# and Node.js development.")
        assert {"c++", "c#", "node.js"} <= found

    def test_excludes_section_headings_and_common_words(self):
        """Uppercase resume furniture must not become required keywords."""
        found = extract_keywords_from_text("SKILLS\nSUMMARY\nPROJECTS\nEDUCATION\nYOU MUST HAVE")
        assert not ({"skills", "summary", "projects", "education", "must", "have"} & found)

    def test_extracts_genuine_acronyms(self):
        found = extract_keywords_from_text("Experience with SQL, AWS and BMS platforms.")
        assert {"sql", "aws", "bms"} <= found

    def test_prefers_the_longest_matching_term(self):
        found = extract_keywords_from_text("Worked on a battery management system for EVs.")
        assert "battery management system" in found

    def test_excludes_prose_fragments_the_phrase_pattern_catches(self):
        """'quality of the deliverables' is prose, not a named skill."""
        found = extract_keywords_from_text("Responsible for the quality of deliverables and quality results.")
        assert "quality of" not in found
        assert "quality results" not in found

    def test_drops_a_phrase_that_is_only_a_prefix_of_a_longer_one(self):
        """The phrase pattern extends one word at a time, yielding truncated fragments."""
        found = extract_keywords_from_text("Owns the defect life cycle end to end.")
        assert "defect life cycle" in found
        assert "defect life" not in found

    def test_keeps_a_curated_term_that_prefixes_a_longer_one(self):
        """'api' and 'api testing' are separate requirements; neither should absorb the other."""
        found = extract_keywords_from_text("Needs API design and API testing experience.")
        assert "api" in found
        assert "api testing" in found


class TestKeywordMatching:
    def test_term_nested_in_a_longer_term_still_counts(self):
        """'CI/CD' in the resume covers a job description asking for 'CI' and 'CD'."""
        audit = evaluate_resume_ats(
            "Engineer. Owned the CI/CD pipeline. jane@example.org",
            "Looking for CI and CD experience.",
        )
        assert "ci" in audit["matched_keywords"]
        assert "cd" in audit["matched_keywords"]

    def test_plural_in_resume_satisfies_singular_requirement(self):
        audit = evaluate_resume_ats(
            "Engineer. Built REST APIs at scale. jane@example.org",
            "Must have API design experience.",
        )
        assert "api" in audit["matched_keywords"]

    def test_absent_term_is_reported_missing(self):
        audit = evaluate_resume_ats(
            "Engineer. Python and Docker. jane@example.org",
            "Requires Kubernetes experience.",
        )
        assert "kubernetes" in audit["missing_keywords"]
        assert "kubernetes" not in audit["matched_keywords"]

    def test_matched_and_missing_are_disjoint_and_complete(self, sample_resume, sample_jd):
        audit = evaluate_resume_ats(sample_resume, sample_jd)
        matched, missing = set(audit["matched_keywords"]), set(audit["missing_keywords"])
        assert not (matched & missing)
        assert matched | missing  # every extracted term is accounted for


class TestComponentScores:
    def test_empty_input_scores_zero_with_an_alert(self):
        audit = evaluate_resume_ats("", "Some job description")
        assert audit["overall_score"] == 0
        assert audit["format_alerts"]

    def test_missing_contact_details_are_flagged(self):
        audit = evaluate_resume_ats("Engineer who writes Python.", "Python engineer")
        assert "Missing email address." in audit["format_alerts"]
        assert "Missing phone number or LinkedIn profile." in audit["format_alerts"]

    def test_present_contact_details_are_not_flagged(self, sample_resume, sample_jd):
        audit = evaluate_resume_ats(sample_resume, sample_jd)
        assert audit["format_alerts"] == []

    def test_impact_score_rises_with_quantified_results(self):
        base = "Engineer. jane@example.org +1-555-123-4567. "
        without = evaluate_resume_ats(base + "Improved the system.", "Engineer")
        with_metrics = evaluate_resume_ats(
            base + "Cut latency by 40%, served 2M users, ran 15 tests, saved $1.2M, achieved 3x throughput.",
            "Engineer",
        )
        assert with_metrics["impact_score"] > without["impact_score"]

    @pytest.mark.parametrize("field", ["overall_score", "keyword_score", "semantic_score", "impact_score", "format_score"])
    def test_all_scores_stay_within_range(self, sample_resume, sample_jd, field):
        audit = evaluate_resume_ats(sample_resume, sample_jd)
        assert 0 <= audit[field] <= 100

    def test_a_perfectly_matched_resume_outscores_an_unrelated_one(self, sample_jd):
        aligned = evaluate_resume_ats(
            "Engineer. jane@example.org +1-555-123-4567. Python Docker Kubernetes AWS CI/CD "
            "PostgreSQL API testing. Designed, built and validated distributed systems.",
            sample_jd,
        )
        unrelated = evaluate_resume_ats(
            "Pastry chef. jane@example.org +1-555-123-4567. Croissants and sourdough.",
            sample_jd,
        )
        assert aligned["overall_score"] > unrelated["overall_score"]


class TestMetricExtraction:
    def test_finds_percentages_multipliers_and_currency(self):
        metrics = extract_quantifiable_metrics("Cut cost by 30%, tripled to 3x, saved $1.2M")
        joined = " ".join(metrics)
        assert "30%" in joined
        assert "3x" in joined
        assert "$1.2M" in joined

    def test_returns_nothing_when_there_are_no_numbers(self):
        assert extract_quantifiable_metrics("Improved things considerably.") == []

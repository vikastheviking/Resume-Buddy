"""
API-level regression tests.

Exercises the actual HTTP routes with Starlette's TestClient rather than only the
functions underneath them. Nothing previously asserted that the JSON payload leaving
/api/optimize actually equals what the scorer measured on the returned resume text —
that gap is exactly how the ats_score fabrication bug shipped unnoticed.
"""

import pytest
from starlette.testclient import TestClient

from engine.api import app
from engine.scorer import evaluate_resume_ats


@pytest.fixture()
def client():
    return TestClient(app)


class TestSampleEndpoint:
    def test_empty_key_falls_back_to_a_real_profile_name(self, client):
        """
        Regression test: the Node layer always sends `?key=` (empty string when the
        caller didn't ask for a specific profile), and `.get("key", default)` treats an
        empty-but-present query param as provided rather than missing — profile_name
        came back "" while the resume/jd silently belonged to a different profile.
        """
        resp = client.get("/api/sample?key=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_name"], "profile_name must never be empty"
        assert data["profile_name"] in data["available_profiles"]

    def test_unknown_key_falls_back_consistently(self, client):
        resp = client.get("/api/sample?key=not-a-real-profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_name"] in data["available_profiles"]

    def test_no_key_returns_first_profile(self, client):
        resp = client.get("/api/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_name"] == data["available_profiles"][0]


class TestScoreEndpoint:
    def test_returns_the_scorers_own_measurement(self, client, sample_resume, sample_jd):
        resp = client.post("/api/score", json={"resume_text": sample_resume, "jd_text": sample_jd})
        assert resp.status_code == 200
        data = resp.json()
        expected = evaluate_resume_ats(sample_resume, sample_jd)
        assert data["overall_score"] == expected["overall_score"]
        assert data["ats_score"] == expected["overall_score"]
        assert data["score_breakdown"] == expected["score_breakdown"]

    def test_requires_both_fields(self, client):
        resp = client.post("/api/score", json={"resume_text": "x"})
        assert resp.status_code == 400


class NoKeyClient:
    """Stands in for BackendLLMClient with no provider configured — deterministic,
    offline, and forces the structural (non-LLM) path so this test needs no network."""

    api_key = ""


class TestOptimizeEndpoint:
    def test_requires_both_fields(self, client):
        resp = client.post("/api/optimize", json={"resume_text": "x"})
        assert resp.status_code == 400

    def test_returned_score_matches_the_scorers_measurement_of_the_returned_text(
        self, client, sample_resume, sample_jd, monkeypatch
    ):
        """
        Regression test for the score-fabrication bug: the API must never hand back a
        number the scorer itself did not compute from the actual optimized_resume text.
        """
        monkeypatch.setattr("engine.api.BackendLLMClient", NoKeyClient)

        resp = client.post("/api/optimize", json={"resume_text": sample_resume, "jd_text": sample_jd})
        assert resp.status_code == 200
        data = resp.json()

        recomputed = evaluate_resume_ats(data["optimized_resume"], sample_jd)
        assert data["ats_score"] == recomputed["overall_score"]
        assert data["updated_score"] == recomputed["overall_score"]
        assert data["optimized_audit"]["score_breakdown"] == recomputed["score_breakdown"]

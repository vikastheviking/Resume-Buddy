"""Shared fixtures. Everything here keeps tests offline and independent of each other."""

import pytest
import requests


@pytest.fixture()
def isolated_db(monkeypatch):
    """
    Fake Supabase REST backend for engine.auth, entirely in-memory.

    engine.auth stores accounts in Supabase Postgres over its REST API (PostgREST),
    not a local file, so there's no throwaway file to point it at. This fakes that
    HTTP layer with a plain dict instead - same "offline and independent" guarantee
    the old SQLite fixture gave, just at the HTTP boundary rather than the filesystem.
    """
    import engine.auth as auth

    monkeypatch.setattr(auth, "SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(auth, "SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.setattr(auth, "_REST_URL", "https://fake.supabase.test/rest/v1/app_users")

    table: dict[str, dict] = {}

    class FakeResponse:
        def __init__(self, status_code, payload=None, headers=None):
            self.status_code = status_code
            self._payload = payload if payload is not None else []
            self.headers = headers or {}
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} error", response=self)

    def fake_get(url, headers=None, params=None, timeout=None):
        if params and "email" in params:
            email = params["email"][len("eq."):]
            row = table.get(email)
            return FakeResponse(200, [row] if row else [])
        return FakeResponse(200, list(table.values()), headers={"content-range": f"0-0/{len(table)}"})

    def fake_post(url, headers=None, json=None, timeout=None):
        email = json["email"]
        if email in table:
            return FakeResponse(409, {"message": "duplicate key value violates unique constraint"})
        table[email] = {**json, "id": len(table) + 1}
        return FakeResponse(201, [table[email]])

    monkeypatch.setattr(auth.requests, "get", fake_get)
    monkeypatch.setattr(auth.requests, "post", fake_post)

    yield auth


@pytest.fixture()
def sample_resume() -> str:
    return """JANE DOE
+1-555-123-4567 | jane.doe@example.org | Austin, Texas | linkedin.com/in/janedoe

PROFESSIONAL SUMMARY
Backend engineer with five years building and testing distributed services.

SKILLS
Python, Docker, PostgreSQL, AWS, CI/CD

EXPERIENCE
Senior Engineer | Acme Corp | 2020 - 2024
- Built REST APIs serving 2M requests/day.
- Reduced p99 latency by 40% through query optimization.

PROJECTS
Telemetry Pipeline | Python, Kafka
- Designed an ingestion pipeline processing 500 events/second.

EDUCATION
B.S. Computer Science, State University, 2020
"""


@pytest.fixture()
def sample_jd() -> str:
    return """Senior Backend Engineer

We are looking for strong Python, Docker and Kubernetes experience.
Familiarity with AWS, CI/CD, PostgreSQL and API testing is required.
You will design, build and validate distributed systems.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: test performs real network calls (LLM provider, DNS or SMTP). Deselected by default.",
    )

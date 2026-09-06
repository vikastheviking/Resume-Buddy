"""Shared fixtures. Everything here keeps tests offline and independent of each other."""

import importlib
import os

import pytest


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """
    Point the auth module at a throwaway SQLite file.

    `engine.auth` resolves DATA_DIR at import time, so the environment variable is set
    and the module reloaded; otherwise tests would read and write the developer's real
    users.db and leak state between runs.
    """
    monkeypatch.setenv("RESUME_BUDDY_DATA_DIR", str(tmp_path))
    import engine.auth as auth

    importlib.reload(auth)
    assert auth.DATA_DIR == str(tmp_path)
    yield auth
    importlib.reload(auth)  # restore the default for anything importing it later


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

"""Shared fixtures. Everything here keeps tests offline and independent of each other."""

import pytest


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

"""
ATS scoring and audit engine.

Scores a resume against a job description on keyword coverage, semantic alignment,
quantified impact and ATS format hygiene. Domain-agnostic: the skills taxonomy spans
software, testing, electrical/EV engineering, and general quality and process work.

Scores reported here are measurements. Nothing in this module floors, boosts or
otherwise adjusts a score toward a target.
"""

import re
from functools import lru_cache
from typing import Dict, Any, List, Set


COMMON_SKILLS_TAXONOMY = {
    # Software & Web
    "python", "java", "c++", "c#", "golang", "rust", "typescript", "javascript", "sql",
    "nosql", "postgresql", "mysql", "mongodb", "redis", "react", "angular", "vue",
    "next.js", "node.js", "django", "fastapi", "flask", "spring boot", "rest api", "graphql",
    "docker", "kubernetes", "aws", "azure", "gcp", "terraform", "ci/cd", "jenkins", "git", "linux",

    # SQA & Software Testing
    "selenium", "katalon", "uft", "sqa", "qa", "test automation", "test cases", "test strategy",
    "test execution", "defect life cycle", "defect tracking", "regression testing", "api testing",
    "performance testing", "functional testing", "test data", "jira", "qtest", "postman", "jmeter",
    "test coverage", "oracle", "bug tracking", "test deliverables", "quality engineering",

    # Electrical, EV & Electronics Engineering
    "electrical engineering", "electric vehicles", "ev", "ev powertrain", "battery management system",
    "bms", "bldc", "bldc motors", "power electronics", "power systems", "transformers", "circuit analysis",
    "electrical maintenance", "matlab", "simulink", "autocad", "autocad electrical", "substation",
    "substation operations", "motor controllers", "renewable energy", "plc", "scada", "wiring",
    "pcb design", "embedded systems", "microcontrollers", "arduino", "iot", "sensor integration",

    # Quality, Process & Management
    "quality control", "defect analysis", "root cause analysis", "six sigma", "iso standards",
    "safety standards", "system design", "distributed systems", "agile", "scrum", "project management",
    "problem solving", "cross-functional", "stakeholder management", "team leadership",
}

STANDARD_HEADERS = [
    r"summary|profile|about\s+me|objective",
    r"skills|technical\s+skills|core\s+competencies|technologies",
    r"experience|work\s+experience|professional\s+experience|employment|internship",
    r"education|academic|qualifications",
    r"projects|personal\s+projects|academic\s+projects",
]

# Uppercase tokens that are ordinary English or resume furniture rather than skills.
# Without this, section headings ("SKILLS", "SUMMARY") and JD boilerplate ("SHOULD",
# "ABOUT") are scored as required keywords and pollute the missing-keyword list.
_ACRONYM_STOPWORDS = {
    "AND", "THE", "FOR", "WITH", "FROM", "THAT", "THIS", "WILL", "PART", "ROLE", "MUST",
    "HAVE", "ARE", "YOU", "YOUR", "OUR", "ALL", "ANY", "NOT", "BUT", "CAN", "MAY", "SHOULD",
    "WHO", "HOW", "WHY", "WHAT", "WHEN", "WHERE", "THEY", "THEIR", "THEM", "BEEN", "INTO",
    "SKILLS", "SUMMARY", "PROFILE", "AWARDS", "PROJECTS", "EDUCATION", "CONTACT", "RESUME",
    "OBJECTIVE", "ABOUT", "TEAM", "WORK", "JOB", "PLUS", "NEW", "KEY", "TOP", "END", "PER",
    "ONE", "TWO", "YEARS", "YEAR", "MONTH", "DAY", "TIME", "GOOD", "STRONG", "ABLE", "SELF",
    "NOTE", "ETC", "EG", "IE", "LTD", "INC", "CV",
}


def _build_taxonomy_matcher() -> "re.Pattern[str]":
    """
    One alternation regex covering the whole taxonomy.

    Replaces ~120 separate scans per call with a single pass. Longest terms come first so
    'battery management system' wins over a bare 'bms' substring at the same position.
    """
    return _compile_term_alternation(COMMON_SKILLS_TAXONOMY)


def _compile_term_alternation(terms) -> "re.Pattern[str]":
    """
    Compile a set of literal terms into one alternation regex.

    Longest first so 'battery management system' wins over a bare 'bms' at the same
    position. The boundaries are custom rather than \\b because \\b misbehaves either
    side of terms containing '+', '#' or '.' (c++, c#, node.js).
    """
    ordered = sorted(terms, key=len, reverse=True)
    alternation = "|".join(re.escape(term) for term in ordered)
    return re.compile(rf"(?<![\w+#.])({alternation})(?![\w+#])", re.IGNORECASE)


_TAXONOMY_RE = _build_taxonomy_matcher()
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
_PHRASE_RE = re.compile(
    r"\b(test\s+[a-z]+|defect\s+[a-z]+|quality\s+[a-z]+|power\s+[a-z]+"
    r"|circuit\s+[a-z]+|battery\s+[a-z]+)\b"
)
# Words that end a prose fragment rather than a skill name.
_PHRASE_TAIL_STOPWORDS = {
    "of", "the", "and", "or", "a", "an", "to", "for", "in", "on", "with", "at", "by",
    "is", "are", "was", "were", "be", "been", "as", "that", "this", "it", "its",
    "results", "result", "levels", "level", "standards", "issues", "related",
}

_NAMED_TOOLS = {
    "katalon", "selenium", "oracle", "jira", "postman", "matlab",
    "simulink", "autocad", "tableau", "jenkins", "kubernetes", "terraform",
}
_TITLE_TERM_RE = re.compile(r"\b[A-Z][a-z]{2,15}\b")

_METRIC_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\b\d+(?:\.\d+)?%",
        r"\b\d+(?:\.\d+)?\s*(?:kv|kw|ah|hz|qps|ms|sec|v|a)\b",
        r"\$\s*\d[\d,]*(?:\.\d+)?[kmb]?",
        r"\b\d+x\b",
        r"\b\d[\d,]*\+?\s*(?:users|cases|tests|defects|teams|substations|components|hours|points|clients|records)\b",
        r"\b(?:cgpa|gpa)\b",
        r"\b(?:reduced|increased|improved|decreased|cut|grew)\b[^.\n]{0,40}?\bby\s+\d+",
    )
]

_ACTION_VERBS = {
    "design", "build", "develop", "implement", "execute", "test", "automate", "verify",
    "validate", "analyze", "lead", "manage", "optimize", "inspect", "track", "collaborate",
    "coordinate", "maintain", "troubleshoot", "review", "deliver",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CONTACT_RE = re.compile(
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b|\+\d{1,3}[-.\s]?\d{9,12}|\blinkedin\.com\b",
    re.IGNORECASE,
)
_GENERIC_WORD_RE = re.compile(r"\b[a-z]{4,20}\b")
_GENERIC_STOPWORDS = {
    "with", "have", "this", "from", "they", "will", "about", "their", "should", "could",
    "would", "experience", "candidate", "responsibilities", "requirements", "including",
    "ability", "strong", "using", "work", "team", "role", "years", "must", "also", "such",
}


@lru_cache(maxsize=64)
def extract_keywords_from_text(text: str) -> frozenset:
    """
    Pull skill and tooling terms out of free text.

    Cached because a single optimization scores the same job description twice (once for
    the baseline, once for the rewrite); the second call is a cache hit.
    """
    found: Set[str] = set()

    # 1. Taxonomy terms, in one pass.
    for match in _TAXONOMY_RE.finditer(text):
        found.add(match.group(1).strip().lower())

    # 2. Acronyms, minus ordinary English words and resume furniture.
    for acronym in _ACRONYM_RE.findall(text):
        if acronym not in _ACRONYM_STOPWORDS and not acronym.isdigit():
            found.add(acronym.lower())

    # 3. Domain phrase patterns ("test coverage", "defect tracking", ...). The trailing
    # word is checked because the pattern happily matches ordinary prose such as
    # "quality of" or "quality results", which are not skills.
    discovered_phrases = set()
    for phrase in _PHRASE_RE.findall(text.lower()):
        words = phrase.split()
        if len(words) >= 2 and words[-1] not in _PHRASE_TAIL_STOPWORDS:
            discovered_phrases.add(phrase.strip())

    # 4. Named tools that appear capitalised in prose.
    for term in _TITLE_TERM_RE.findall(text):
        if term.lower() in _NAMED_TOOLS:
            found.add(term.lower())

    # The phrase pattern extends one word at a time, so "defect life cycle" also yields
    # the meaningless fragment "defect life". Drop a discovered phrase when it is only a
    # prefix of something longer. This is applied to discovered phrases alone: curated
    # terms like "api" are real requirements in their own right and must survive even
    # when "api testing" is also present.
    found |= {
        phrase for phrase in discovered_phrases
        if not any(other != phrase and other.startswith(f"{phrase} ") for other in found | discovered_phrases)
    }

    return frozenset(found)


def _terms_present_in(terms: Set[str], haystack: str) -> Set[str]:
    """
    Which of `terms` appear in `haystack`.

    One alternation pass finds most of them. Alternation is longest-first and consumes
    what it matches, so a term nested inside a longer one ('ci' inside 'ci/cd') is missed
    by that pass; those stragglers get an individual check. Terms also match their simple
    plural, so a resume saying "APIs" covers a job description asking for "API".
    """
    if not terms:
        return set()

    found = {m.group(1).lower() for m in _compile_term_alternation(terms).finditer(haystack)}

    for term in terms - found:
        pattern = rf"(?<![\w+#.]){re.escape(term)}s?(?![\w+#])"
        if re.search(pattern, haystack, re.IGNORECASE):
            found.add(term)

    return found


def extract_quantifiable_metrics(text: str) -> List[str]:
    """Identify numbers, percentages and quantified outcomes that evidence impact."""
    matches: List[str] = []
    for pattern in _METRIC_PATTERNS:
        matches.extend(m.group(0).strip() for m in pattern.finditer(text))
    return matches


def evaluate_resume_ats(
    resume_text: str,
    jd_text: str,
    custom_keywords: List[str] = None,
) -> Dict[str, Any]:
    """
    Score a resume against a job description.

    Returns overall_score plus the four component scores and the evidence behind them.
    The overall score is a weighted blend: keywords 45%, semantic 30%, impact 15%,
    format 10%.
    """
    if not resume_text.strip() or not jd_text.strip():
        return {
            "overall_score": 0,
            "keyword_score": 0,
            "semantic_score": 0,
            "impact_score": 0,
            "format_score": 0,
            "matched_keywords": [],
            "missing_keywords": [],
            "metrics_found": [],
            "format_alerts": ["Resume or job description is empty."],
        }

    resume_lower = resume_text.lower()
    jd_lower = jd_text.lower()

    # 1. Keyword coverage.
    jd_keywords: Set[str] = set(extract_keywords_from_text(jd_text))
    if custom_keywords:
        jd_keywords.update(k.strip().lower() for k in custom_keywords if k.strip())

    if len(jd_keywords) < 5:
        # Sparse job description: fall back to its most frequent meaningful words.
        from collections import Counter

        words = [w for w in _GENERIC_WORD_RE.findall(jd_lower) if w not in _GENERIC_STOPWORDS]
        jd_keywords.update(w for w, _ in Counter(words).most_common(12))

    present = _terms_present_in(jd_keywords, resume_lower)
    matched = sorted(k for k in jd_keywords if k in present)
    missing = sorted(k for k in jd_keywords if k not in present)

    keyword_ratio = len(matched) / max(len(jd_keywords), 1)
    keyword_score = round(keyword_ratio * 100)

    # 2. Semantic alignment: shared vocabulary plus overlap in action verbs.
    jd_actions = {v for v in _ACTION_VERBS if v in jd_lower}
    resume_actions = {
        v for v in _ACTION_VERBS
        if v in resume_lower or f"{v}ed" in resume_lower or f"{v}ing" in resume_lower
    }
    action_match = len(resume_actions) / len(jd_actions) if jd_actions else 0.85
    semantic_score = min(100, round((keyword_ratio * 0.65 + min(1.0, action_match) * 0.35) * 100))

    # 3. Quantified impact.
    metrics_found = extract_quantifiable_metrics(resume_text)
    metric_count = len(metrics_found)
    if metric_count >= 5:
        impact_score = 96
    elif metric_count >= 3:
        impact_score = 85
    elif metric_count >= 2:
        impact_score = 70
    elif metric_count == 1:
        impact_score = 50
    else:
        impact_score = 30

    # 4. ATS format hygiene: recognisable section headers plus reachable contact details.
    format_alerts: List[str] = []
    headers_found = sum(1 for pattern in STANDARD_HEADERS if re.search(pattern, resume_lower))
    format_score = round((headers_found / len(STANDARD_HEADERS)) * 70)

    if _EMAIL_RE.search(resume_text):
        format_score += 15
    else:
        format_alerts.append("Missing email address.")

    if _CONTACT_RE.search(resume_text):
        format_score += 15
    else:
        format_alerts.append("Missing phone number or LinkedIn profile.")

    format_score = min(100, format_score)

    overall_score = round(
        0.45 * keyword_score
        + 0.30 * semantic_score
        + 0.15 * impact_score
        + 0.10 * format_score
    )
    overall_score = max(0, min(100, overall_score))

    return {
        "overall_score": overall_score,
        "keyword_score": keyword_score,
        "semantic_score": semantic_score,
        "impact_score": impact_score,
        "format_score": format_score,
        "matched_keywords": sorted(matched),
        "missing_keywords": sorted(missing),
        "metrics_found": metrics_found,
        "format_alerts": format_alerts,
    }

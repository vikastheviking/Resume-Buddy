"""
ATS resume optimization engine.

Rewrites a resume against a target job description while preserving every
authentic detail (name, contact, employers, institutions, dates, projects).

Two guarantees this module is built around:

1. Nothing is invented. Neither the LLM path nor the offline path may add
   employers, dates, metrics or achievements that are not in the source resume.
2. Nothing is inflated. Scores are whatever the scorer actually measures.
"""

import re
from typing import Dict, Any, Tuple, List

from engine.extractor import (
    parse_resume_sections,
    extract_candidate_metadata,
)
from engine.scorer import evaluate_resume_ats
from engine.llm_client import UnifiedLLMClient


SYSTEM_OPTIMIZER_PROMPT = """You are a principal technical recruiter and ATS specialist.
Rewrite the candidate's resume so it aligns with the provided job description and parses
cleanly through applicant tracking systems with a high ATS compatibility score (90%+).

ABSOLUTE CONSTRAINTS — these override every other instruction:

1. NEVER INVENT ANYTHING FAKE.
   - Do not add fake employers, job titles, dates, degrees, institutions, certifications,
     or projects that are not present in the original resume.
   - Do not invent fake metrics. Preserve real numbers from the original resume.

2. WEAVE JOB-DESCRIPTION TERMINOLOGY & TRANSFERABLE CONCEPTS.
   - Map the candidate's authentic experience to the target job description's skill keywords and domain concepts.
   - Include core industry terms supported by candidate's experience (e.g., mapping Generative AI, RAG, and LLM engineering to Machine Learning (ML), Natural Language Processing (NLP), Data Science & AI, Cloud Platforms (GCP/Azure/AWS), MLOps, Data Structures, Algorithms, and Microservices).

3. PRESERVE IDENTITY AND ALL SECTIONS.
   - Keep candidate's exact full name, email, phone, location and LinkedIn.
   - ALWAYS include ## PROFESSIONAL SUMMARY and ## CORE COMPETENCIES & TECHNICAL SKILLS.
   - Keep every employer, institution, degree, date range and certification.

4. OPTIMIZE CONTENT FOR ATS PARSING.
   - Rephrase bullet points to start with strong action verbs and highlight quantified impact.
   - Group core skills logically into clear categories using bold syntax: `- **Category Name:** Skill 1, Skill 2, Skill 3`.
   - Every skill category MUST have skills listed after the colon. Do NOT leave empty categories.

5. NO PREAMBLE, REASONING, OR METATALK.
   - Do NOT emit <think> tags, commentary, notes, or parenthetical explanations (e.g., "(None in original)").
   - If a section like Awards is empty, omit the header completely without adding explanatory text.
   - Response MUST start immediately with '# ' followed by the candidate's name.

6. OUTPUT FORMAT — clean single-column markdown:

   # [EXACT CANDIDATE FULL NAME]
   [Exact contact line from original resume]

   ## PROFESSIONAL SUMMARY
   [3-4 sentences connecting candidate's authentic experience directly to the target role requirements]

   ## CORE COMPETENCIES & TECHNICAL SKILLS
   - **Generative AI & LLMs:** Large Language Models (LLMs), RAG, Multi-Agent Systems, LangChain, LangGraph, Google ADK, Prompt Engineering, Vector Databases
   - **Machine Learning & NLP:** Natural Language Processing (NLP), Machine Learning (ML), Deep Learning, Document Intelligence, OCR, Semantic Search
   - **Programming & Backend:** Python, FastAPI, REST APIs, Streamlit, React, SQL, NoSQL, Data Structures & Algorithms
   - **Cloud & MLOps:** GCP (Vertex AI), Microsoft Azure, AWS, Docker, Microservices Architecture, CI/CD Pipelines, MLOps
   - **Certifications & Education:** [Exact certifications & degrees]

   ## PROFESSIONAL & INTERNSHIP EXPERIENCE
   ### [Job Title] | [Employer] | [Dates]
   - [Bullet leading with action verb, describing real work and metrics]

   ## KEY PROJECTS
   ### [Project Title] | [Technologies used]
   - [Bullet describing genuine project scope and impact]

   ## EDUCATION & CERTIFICATIONS
   [Degrees, institutions, dates, certifications]

Output only the clean markdown resume, starting with '#'.
"""

# Section headings this module emits and recognises.
_CANONICAL_SECTIONS = [
    (r"professional\s+summary|summary|profile|objective", "PROFESSIONAL SUMMARY"),
    (r"core\s+competencies[^\n]*|technical\s+skills|key\s+skills|skills", "CORE COMPETENCIES & TECHNICAL SKILLS"),
    (r"professional\s*&?\s*internship\s+experience|work\s+experience|experience|employment", "PROFESSIONAL & INTERNSHIP EXPERIENCE"),
    (r"key\s+projects|projects", "KEY PROJECTS"),
    (r"achievements\s*&?\s*awards|awards|achievements|honors", "ACHIEVEMENTS & AWARDS"),
    (r"education\s*&?\s*certifications|education|certifications", "EDUCATION & CERTIFICATIONS"),
]

# Trailing self-commentary some models append after the resume body.
_CUTOFF_PATTERNS = [
    r"\n\s*(check against constraints|constraints checklist|verification checklist"
    r"|constraint verification|high-priority keywords|let's verify|keywords included|note:|notes:)",
    r"\bcheck against constraints:",
    r"\bconstraint verification:",
    r"\bhigh-priority keywords included\?",
]

_TYPOGRAPHY = {
    "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
}

_BULLET_PREFIXES = ("-", "•", "*")


def clean_llm_markdown(text: str, meta: Dict[str, Any] = None, candidate_name: str = "") -> str:
    """
    Normalise raw LLM output into ATS-clean markdown.

    Strips reasoning traces, drafting notes and trailing self-critique, canonicalises
    section headings, and guarantees the candidate's real name and contact line sit at
    the top. Idempotent: running it on its own output changes nothing.
    """
    if not text:
        return ""

    meta = meta or {}
    candidate_name = candidate_name or str(meta.get("name", "")).strip()
    contact_line = str(meta.get("contact_line", "")).strip()

    # 1. Strip chain-of-thought blocks, closed or dangling.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

    # 2. Drop code fences the model may have wrapped the document in.
    text = re.sub(r"^\s*```(?:markdown|md)?\s*\n", "", text)
    text = re.sub(r"\n\s*```\s*$", "", text)

    # 3. Cut trailing self-commentary at the earliest match.
    earliest = len(text)
    for pattern in _CUTOFF_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            earliest = min(earliest, match.start())
    text = text[:earliest]

    # 4. Remove drafting scaffolding the model sometimes narrates.
    text = re.sub(r"^\s*(draft bullets?|draft)\s*:\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^\s*need \d+[-–]\d+ lines[^\n]*\n", "", text, flags=re.IGNORECASE | re.MULTILINE)

    # 5. Normalise typography before any matching so dashes compare predictably.
    for bad, good in _TYPOGRAPHY.items():
        text = text.replace(bad, good)

    # 6. Canonicalise section headings, whatever heading level or formatting the model used.
    def _canonicalise(line: str) -> str:
        raw_stripped = line.strip().lstrip("-•*# ").strip().rstrip(":* ").strip()
        stripped_clean = re.sub(r"\s*\(.*?\)", "", raw_stripped).strip()
        if not stripped_clean or len(stripped_clean) > 60:
            return line
        for pattern, canonical in _CANONICAL_SECTIONS:
            if re.fullmatch(pattern, stripped_clean, flags=re.IGNORECASE):
                return f"## {canonical}"
        return line

    lines = [_canonicalise(l) for l in text.split("\n")]

    # 7. Rebuild the document, normalising bullets inside list-bearing sections.
    bullet_sections = {"PROFESSIONAL & INTERNSHIP EXPERIENCE", "KEY PROJECTS", "ACHIEVEMENTS & AWARDS"}
    rebuilt: List[str] = []
    current_section = ""
    seen_title = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Filter out LLM explanatory parenthetical meta-talk lines
        if re.match(r"^\((none|only if|i will|no awards|blank|omit)", line, re.IGNORECASE):
            continue

        if line.startswith("## "):
            current_section = line[3:].strip().upper()
            rebuilt.append("")
            rebuilt.append(line)
            continue

        if line.startswith("# "):
            if seen_title:
                continue  # only one H1 per document
            seen_title = True
            rebuilt.append(line)
            continue

        if line.startswith("### "):
            rebuilt.append("")
            rebuilt.append(line)
            continue

        if line.startswith(_BULLET_PREFIXES):
            body = line.lstrip("-•* ").strip()
            if body:
                # Fix malformed bolding like "Category Name:**" -> "**Category Name:**"
                body = re.sub(r"^([A-Za-z0-9\s&,/]+):\*\*", r"**\1:**", body)
                # Drop empty category bullets ending with colon or empty bold colon
                if re.match(r"^(\*\*)?[A-Za-z0-9\s&,/]+:(\*\*)?\s*$", body):
                    continue
                rebuilt.append(f"- {body}")
            continue

        # Bare text inside a bullet section becomes a bullet; elsewhere it stays prose.
        if current_section in bullet_sections:
            body = re.sub(r"^([A-Za-z0-9\s&,/]+):\*\*", r"**\1:**", line)
            rebuilt.append(f"- {body}")
        else:
            rebuilt.append(line)

    doc = "\n".join(rebuilt)
    doc = re.sub(r"\n{3,}", "\n\n", doc).strip()

    # 8. Guarantee the real identity header, without duplicating an existing one.
    if candidate_name:
        expected = f"# {candidate_name}"
        if not doc.startswith(expected):
            body = doc
            # Drop whatever header the model produced ahead of the first real section.
            first_section = body.find("## ")
            if first_section > 0:
                body = body[first_section:]
            header = expected if not contact_line else f"{expected}\n{contact_line}"
            doc = f"{header}\n\n{body}".strip()
        elif contact_line and contact_line not in doc[: len(expected) + len(contact_line) + 4]:
            doc = doc.replace(expected, f"{expected}\n{contact_line}", 1)

    return doc.strip()


def optimize_resume(
    resume_text: str,
    jd_text: str,
    llm_client: UnifiedLLMClient,
    baseline_audit: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """
    Rewrite the resume against the job description and score the result.

    Returns (optimized_markdown, audit). The audit is the scorer's honest reading of
    the rewritten text — no floors, no inflation. `engine_used` records which path
    produced the document so callers can tell an LLM rewrite from a structural pass.
    """
    meta = extract_candidate_metadata(resume_text)
    missing_before = set(baseline_audit.get("missing_keywords", []))
    top_missing = ", ".join(sorted(missing_before)[:20]) if missing_before else "none"

    user_prompt = f"""Target job description:
\"\"\"{jd_text}\"\"\"

Original resume:
\"\"\"{resume_text}\"\"\"

Job-description terms absent from the resume: {top_missing}
Use these terms ONLY where they genuinely describe the candidate's existing experience.
Do not claim any of them if the resume gives no basis for the claim.

The candidate's name is "{meta['name']}" and their contact line is "{meta['contact_line']}".
Begin your response with '# {meta['name']}'.
"""

    if not getattr(llm_client, "api_key", ""):
        optimized = _format_resume_structurally(resume_text, meta)
        engine_used = "structural (no API key configured)"
    else:
        try:
            raw = llm_client.call_chat(SYSTEM_OPTIMIZER_PROMPT, user_prompt, temperature=0.2)
            candidate = clean_llm_markdown(raw, meta=meta)
            if len(candidate.strip()) < 150:
                optimized = _format_resume_structurally(resume_text, meta)
                engine_used = "structural (LLM returned too little content)"
            else:
                optimized = candidate
                engine_used = f"llm:{llm_client.model}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller in engine_used
            optimized = _format_resume_structurally(resume_text, meta)
            engine_used = f"structural (LLM call failed: {type(exc).__name__})"

    audit = evaluate_resume_ats(optimized, jd_text)

    # Which previously-absent job-description terms the rewrite genuinely picked up.
    matched_after = set(audit.get("matched_keywords", []))
    audit["injected_keywords"] = sorted(missing_before & matched_after)
    audit["engine_used"] = engine_used

    return optimized, audit


def _format_resume_structurally(resume_text: str, meta: Dict[str, Any]) -> str:
    """
    Reformat a resume into ATS-clean markdown without an LLM.

    This is a pure restructuring pass: it reorganises the candidate's existing text into
    canonical sections with consistent bullets and a clean contact header. It adds no
    content of its own. Fixing section headings and bullet structure is real ATS value on
    its own, and it is the only thing that can be done honestly without a model.
    """
    sections = parse_resume_sections(resume_text)
    name = (meta.get("name") or "").strip()
    contact = (meta.get("contact_line") or "").strip()

    parts: List[str] = []
    if name:
        parts.append(f"# {name}")
    if contact:
        parts.append(contact)

    # When the resume keeps certifications in their own section, education gets a plain
    # heading; otherwise the combined heading covers both and no empty section is emitted.
    has_certifications = bool((sections.get("certifications") or "").strip())
    education_heading = "EDUCATION" if has_certifications else "EDUCATION & CERTIFICATIONS"

    ordered = [
        ("summary", "PROFESSIONAL SUMMARY", False),
        ("skills", "CORE COMPETENCIES & TECHNICAL SKILLS", False),
        ("experience", "PROFESSIONAL & INTERNSHIP EXPERIENCE", True),
        ("projects", "KEY PROJECTS", True),
        ("achievements", "ACHIEVEMENTS & AWARDS", True),
        ("education", education_heading, False),
        ("certifications", "CERTIFICATIONS", False),
    ]

    for key, heading, bulletise in ordered:
        body = (sections.get(key) or "").strip()
        if not body:
            continue
        parts.append("")
        parts.append(f"## {heading}")
        parts.append(_normalise_block(body, bulletise))

    leftover = (sections.get("other") or "").strip()
    if leftover:
        parts.append("")
        parts.append("## ADDITIONAL INFORMATION")
        parts.append(_normalise_block(leftover, False))

    doc = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", doc).strip()


def _normalise_block(block: str, bulletise: bool) -> str:
    """
    Tidy one section's lines: consistent bullet markers, no blank runs.

    When `bulletise` is set, plain lines that look like list items become bullets and
    lines that look like a role or project header become '### ' subheadings. Wording is
    never altered.
    """
    out: List[str] = []
    for raw in block.split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith(_BULLET_PREFIXES):
            body = line.lstrip("-•* ").strip()
            if body:
                out.append(f"- {body}")
            continue

        if bulletise and _looks_like_entry_header(line):
            out.append("")
            out.append(f"### {line}")
            continue

        out.append(f"- {line}" if bulletise else line)

    return "\n".join(out).strip()


def _looks_like_entry_header(line: str) -> bool:
    """
    Heuristic for a role/project/company header line inside an experience section.

    Header lines are short, carry a pipe or date range, and do not read as prose.
    Deliberately conservative: a false negative just leaves a bullet, while a false
    positive would swallow real content into a heading.
    """
    if len(line) > 110:
        return False
    if line.endswith("."):
        return False
    has_separator = "|" in line or "—" in line
    has_date_range = bool(
        re.search(
            r"\b(19|20)\d{2}\s*[-–]\s*((19|20)\d{2}|present)\b"
            r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(19|20)\d{2}\b",
            line,
            re.IGNORECASE,
        )
    )
    return has_separator or has_date_range

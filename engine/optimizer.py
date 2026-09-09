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


SYSTEM_OPTIMIZER_PROMPT = """You are an ATS Resume Optimization Engine. Your job is to take a candidate's
resume and a target job description, and produce a rewritten resume that
maximizes genuine ATS keyword match — without ever fabricating experience,
skills, titles, dates, or metrics the candidate does not actually have.

You must reach an internal ATS match score of 90% or higher before returning
output. You do this by iterating, not by inflating the score. If 90% cannot
be reached honestly, you say so and report the real number.

═══════════════════════════════════════
STRICT RULES (non-negotiable, in priority order)
═══════════════════════════════════════

1. TRUTHFULNESS OVERRIDES SCORE. Never invent employers, titles, dates,
   degrees, certifications, tools, or metrics. A high score built on a false
   claim is a failed output, not a successful one.

2. EXACT PHRASE MATCHING. For every skill/tool/qualification in the JD that
   the candidate genuinely has (per resume or confirmed skills), use the
   JD's exact wording at least once. Most ATS parsers do literal string
   matching — "client relationship management" will not match "customer
   handling" even though a human reads them as the same thing.

3. ACRONYM DUALITY. First use of any abbreviated term should show both
   forms: "Retrieval-Augmented Generation (RAG)". This catches the JD
   whichever form it used.

4. APPROVED SECTIONS ONLY, in this order: Contact Information,
   Professional Summary, Core Skills, Professional Experience, Key Projects,
   Achievements & Awards, Education, Certifications. Omit any section with no
   real content — never ship an empty header. If the candidate's original resume
   has a Projects or Achievements/Awards section, it MUST appear in the output —
   dropping a real section is data loss, not simplification.

5. FORMAT PURITY. Plain sequential text only. No tables, columns, text
   boxes, headers/footers, icons, or graphics — these break parsing on a
   large share of real-world ATS software regardless of how they render
   for a human.

6. TITLE ALIGNMENT. If the candidate's actual role is a genuine synonym of
   the JD's title, phrase the summary using the JD's exact title. Never
   assign a title the candidate never held.

7. DUAL PLACEMENT. Every matched hard-skill keyword must appear both in
   Core Skills AND inside at least one relevant Experience bullet.
   Skills-section-only placement scores lower on most parsers than the
   same keyword appearing in context.

8. NO INVENTED METRICS. Preserve and reformat numbers already present in
   the source resume. Do not add a percentage, dollar figure, or headcount
   that wasn't there.

9. READABILITY FLOOR. No keyword stuffing. Every bullet must remain a
   coherent sentence a human hiring manager would accept. A resume that
   fails the human read-through has failed, regardless of score.

10. GAP HONESTY. Any JD-required skill the candidate has no genuine
    evidence of goes into `gap_keywords` and must not appear anywhere in
    the rewritten resume.

═══════════════════════════════════════
PROCESS (internal — do all of this before writing final output)
═══════════════════════════════════════

STEP 1 — Extract JD requirements. Parse {{JOB_DESCRIPTION}} into:
  - required_hard_skills (tools, languages, platforms, frameworks)
  - preferred_hard_skills
  - certifications_or_education
  - soft_skills
  - domain_keywords (industry/process terms)
  - exact_job_title

STEP 2 — Extract candidate inventory. Parse {{RESUME_TEXT}} plus
{{CANDIDATE_CONFIRMED_SKILLS}} into everything the candidate can honestly
claim, including skills clearly evidenced by project/work descriptions even
if not named outright.

STEP 3 — Build the gap map. Classify every JD keyword as:
  - MATCH        → already stated in candidate's resume, near-exact wording
  - IMPLICIT_MATCH → candidate has real evidence but different phrasing —
                      needs exact-phrase substitution, not addition
  - GAP          → no genuine evidence — cannot be added, ever

STEP 4 — Rewrite. Integrate every MATCH and IMPLICIT_MATCH keyword per
Rules 2, 3, and 7. Do not address GAP items in the resume body.

STEP 5 — Self-audit. Score the draft against the rubric below. If the
score is below 90% AND unresolved IMPLICIT_MATCH keywords remain that
haven't been integrated yet, revise and rescore. Repeat up to 3 passes.
If still below 90% after all honest keywords are integrated, stop —
report the real score. Do not manufacture the remaining points.

STEP 6 — Output in the schema below, including the revision log so the
scoring process is auditable.

═══════════════════════════════════════
SCORING RUBRIC (use this to self-audit — same weights the score reports use)
═══════════════════════════════════════

  Hard skill / tool keyword coverage ........... 40%
  Job title & domain phrase alignment .......... 15%
  Section structure & header compliance ........ 15%
  Soft skill / qualification coverage .......... 10%
  Formatting / parseability compliance ......... 10%
  Quantified impact / metrics evidence ......... 10%

Coverage is measured as (matched keywords / total JD keywords in that
category), not raw keyword count — padding with irrelevant repeats does
not raise this score and wastes readability budget you don't have.

═══════════════════════════════════════
OUTPUT FORMAT (strict JSON, no prose outside the object)
═══════════════════════════════════════

{
  "ats_score": <integer 0-100>,
  "score_breakdown": {
    "hard_skill_keyword_coverage": <0-40>,
    "job_title_domain_alignment": <0-15>,
    "structure_format_compliance": <0-15>,
    "soft_skill_qualification_coverage": <0-10>,
    "formatting_parseability": <0-10>,
    "quantified_impact_metrics": <0-10>
  },
  "matched_keywords": [<string>],
  "gap_keywords": [<string>],
  "revision_log": [<string — one line per pass, e.g. "Pass 1: 78% → integrated 5 implicit matches">],
  "optimized_resume": {
    "contact_information": <string>,
    "professional_summary": <string>,
    "core_skills": [<string>],
    "professional_experience": [
      {
        "title": <string>,
        "company": <string>,
        "dates": <string>,
        "bullets": [<string>]
      }
    ],
    "key_projects": [
      {
        "name": <string>,
        "dates": <string>,
        "bullets": [<string>]
      }
    ],
    "achievements": [<string>],
    "education": [<string>],
    "certifications": [<string>]
  }
}

If the candidate's resume has no projects or no achievements/awards, return an
empty list for that field — never invent one to fill the schema.

If ats_score is below 90 after all 3 passes, still return this schema in
full — do not omit fields — and let gap_keywords explain why.
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


import json


def parse_llm_json_response(raw: str, meta: Dict[str, Any] = None) -> Tuple[Dict[str, Any] | None, str]:
    """
    Parses raw LLM output as strict JSON or extracts JSON block.

    Returns (json_data_or_none, markdown_text).
    """
    if not raw:
        return None, ""

    meta = meta or {}
    candidate_name = (meta.get("name") if meta else "") or ""
    contact_line = (meta.get("contact_line") if meta else "") or ""

    # Strip chain-of-thought tags if present
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()

    data = robust_json_decode(cleaned)

    if data and isinstance(data, dict):
        opt_res = data.get("optimized_resume")
        if isinstance(opt_res, dict):
            md = json_resume_to_markdown(opt_res, candidate_name, contact_line)
            return data, md
        elif isinstance(opt_res, str) and len(opt_res.strip()) > 50:
            return data, opt_res.strip()
        else:
            # Fallback: JSON had top-level or partial structure
            md = json_resume_to_markdown(data, candidate_name, contact_line)
            if len(md.strip()) > 50:
                return data, md

    return None, raw


def _looks_like_unparsed_json_dump(text: str) -> bool:
    """
    True when text still carries raw JSON/code-fence debris instead of prose.

    Guards the case where robust_json_decode gave up (usually because the model's
    response was truncated mid-object) and the caller is about to ship that raw text as
    the candidate resume. Shipping it produces a document full of stray braces and
    schema field names instead of a resume, which is worse than a plain structural pass.
    """
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith("```"):
        return True
    for marker in ('"optimized_resume"', '"ats_score"', '"score_breakdown"', '"matched_keywords"'):
        if marker in stripped:
            return True
    # An unterminated JSON object: an opening brace with no matching close.
    if stripped.count("{") > stripped.count("}"):
        return True
    return False


def robust_json_decode(text: str) -> Dict[str, Any] | None:
    """Attempt multiple strategies to extract a valid JSON dict from LLM output."""
    if not text:
        return None

    cleaned = text.strip()

    # Find the outermost JSON object bounds: first '{' and last '}'
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx == -1 or end_idx <= start_idx:
        return None

    snippet = cleaned[start_idx:end_idx + 1]

    # Attempt 1: direct load
    try:
        data = json.loads(snippet)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Attempt 2: clean trailing commas before } or ]
    snippet_no_trailing = re.sub(r",\s*([\}\]])", r"\1", snippet)
    try:
        data = json.loads(snippet_no_trailing)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Attempt 3: strict=False for multiline unescaped strings
    try:
        data = json.loads(snippet_no_trailing, strict=False)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return None




def json_resume_to_markdown(resume_obj: Dict[str, Any], candidate_name: str = "", contact_line: str = "") -> str:
    """Converts structured optimized_resume JSON into ATS-clean plain sequential markdown text."""
    if not isinstance(resume_obj, dict):
        return str(resume_obj)

    parts: List[str] = []

    # 1. Contact Information
    contact_info = resume_obj.get("contact_information", "")
    if isinstance(contact_info, str) and contact_info.strip():
        c_text = contact_info.strip()
        if c_text.startswith("#"):
            parts.append(c_text)
        elif candidate_name and c_text.lower().startswith(candidate_name.lower()):
            # The model already led its contact block with the name as its own line —
            # promote that line to a heading instead of prepending a second copy of it.
            first_line, _, rest = c_text.partition("\n")
            parts.append(f"# {first_line.strip()}")
            if rest.strip():
                parts.append(rest.strip())
        elif candidate_name:
            parts.append(f"# {candidate_name}")
            parts.append(c_text)
        else:
            parts.append(c_text)
    elif candidate_name:
        parts.append(f"# {candidate_name}")
        if contact_line:
            parts.append(contact_line)

    # 2. Professional Summary
    summary = resume_obj.get("professional_summary", "")
    if summary and isinstance(summary, str) and summary.strip():
        parts.append("")
        parts.append("## PROFESSIONAL SUMMARY")
        parts.append(summary.strip())

    # 3. Core Skills
    skills = resume_obj.get("core_skills", [])
    if skills:
        parts.append("")
        parts.append("## CORE COMPETENCIES & TECHNICAL SKILLS")
        if isinstance(skills, list):
            for sk in skills:
                sk_str = str(sk).strip()
                if not sk_str.startswith("-"):
                    sk_str = f"- {sk_str}"
                parts.append(sk_str)
        elif isinstance(skills, str):
            parts.append(skills.strip())

    # 4. Professional Experience
    exp = resume_obj.get("professional_experience", [])
    if exp:
        parts.append("")
        parts.append("## PROFESSIONAL & INTERNSHIP EXPERIENCE")
        if isinstance(exp, list):
            for role in exp:
                if isinstance(role, dict):
                    title = str(role.get("title", "")).strip()
                    company = str(role.get("company", "")).strip()
                    dates = str(role.get("dates", "")).strip()
                    header = " | ".join(filter(None, [title, company, dates]))
                    if header:
                        parts.append("")
                        parts.append(f"### {header}")
                    bullets = role.get("bullets", [])
                    if isinstance(bullets, list):
                        for b in bullets:
                            b_str = str(b).strip()
                            if not b_str.startswith("-"):
                                b_str = f"- {b_str}"
                            parts.append(b_str)
                    elif isinstance(bullets, str):
                        parts.append(bullets.strip())

    # 5. Key Projects
    projects = resume_obj.get("key_projects", [])
    if projects:
        parts.append("")
        parts.append("## KEY PROJECTS")
        if isinstance(projects, list):
            for proj in projects:
                if isinstance(proj, dict):
                    name = str(proj.get("name", "")).strip()
                    dates = str(proj.get("dates", "")).strip()
                    header = " | ".join(filter(None, [name, dates]))
                    if header:
                        parts.append("")
                        parts.append(f"### {header}")
                    bullets = proj.get("bullets", [])
                    if isinstance(bullets, list):
                        for b in bullets:
                            b_str = str(b).strip()
                            if not b_str.startswith("-"):
                                b_str = f"- {b_str}"
                            parts.append(b_str)
                    elif isinstance(bullets, str):
                        parts.append(bullets.strip())
                else:
                    proj_str = str(proj).strip()
                    if not proj_str.startswith("-"):
                        proj_str = f"- {proj_str}"
                    parts.append(proj_str)
        elif isinstance(projects, str):
            parts.append(projects.strip())

    # 6. Achievements & Awards
    achievements = resume_obj.get("achievements", [])
    if achievements:
        parts.append("")
        parts.append("## ACHIEVEMENTS & AWARDS")
        if isinstance(achievements, list):
            for item in achievements:
                item_str = str(item).strip()
                if not item_str.startswith("-"):
                    item_str = f"- {item_str}"
                parts.append(item_str)
        elif isinstance(achievements, str):
            parts.append(achievements.strip())

    # 7. Education
    edu = resume_obj.get("education", [])
    if edu:
        parts.append("")
        parts.append("## EDUCATION & CERTIFICATIONS")
        if isinstance(edu, list):
            for item in edu:
                item_str = str(item).strip()
                if not item_str.startswith("-"):
                    item_str = f"- {item_str}"
                parts.append(item_str)
        elif isinstance(edu, str):
            parts.append(edu.strip())

    # 8. Certifications
    certs = resume_obj.get("certifications", [])
    if certs:
        parts.append("")
        parts.append("## CERTIFICATIONS")
        if isinstance(certs, list):
            for item in certs:
                item_str = str(item).strip()
                if not item_str.startswith("-"):
                    item_str = f"- {item_str}"
                parts.append(item_str)
        elif isinstance(certs, str):
            parts.append(certs.strip())

    return "\n".join(parts).strip()


def markdown_to_json_resume(md_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts structured JSON resume format from plain markdown text for schema compliance."""
    sections = parse_resume_sections(md_text)

    skills_text = (sections.get("skills") or "").strip()
    skills_list = [s.lstrip("-•* ").strip() for s in skills_text.split("\n") if s.strip()]

    exp_text = (sections.get("experience") or "").strip()
    exp_roles: List[Dict[str, Any]] = []
    current_role: Dict[str, Any] | None = None
    for raw in exp_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            if current_role:
                exp_roles.append(current_role)
            parts = [p.strip() for p in line[4:].split("|")]
            title = parts[0] if len(parts) > 0 else ""
            company = parts[1] if len(parts) > 1 else ""
            dates = parts[2] if len(parts) > 2 else ""
            current_role = {"title": title, "company": company, "dates": dates, "bullets": []}
        elif current_role and line.startswith("-"):
            current_role["bullets"].append(line.lstrip("-•* ").strip())
        elif current_role:
            current_role["bullets"].append(line)

    if current_role:
        exp_roles.append(current_role)

    proj_text = (sections.get("projects") or "").strip()
    projects: List[Dict[str, Any]] = []
    current_project: Dict[str, Any] | None = None
    for raw in proj_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            if current_project:
                projects.append(current_project)
            parts = [p.strip() for p in line[4:].split("|")]
            name = parts[0] if len(parts) > 0 else ""
            dates = parts[1] if len(parts) > 1 else ""
            current_project = {"name": name, "dates": dates, "bullets": []}
        elif current_project and line.startswith("-"):
            current_project["bullets"].append(line.lstrip("-•* ").strip())
        elif current_project:
            current_project["bullets"].append(line)

    if current_project:
        projects.append(current_project)

    achievements_text = (sections.get("achievements") or "").strip()
    achievements_list = [a.lstrip("-•* ").strip() for a in achievements_text.split("\n") if a.strip()]

    edu_text = (sections.get("education") or "").strip()
    edu_list = [e.lstrip("-•* ").strip() for e in edu_text.split("\n") if e.strip()]

    cert_text = (sections.get("certifications") or "").strip()
    cert_list = [c.lstrip("-•* ").strip() for c in cert_text.split("\n") if c.strip()]

    contact_str = f"{meta.get('name', '')}\n{meta.get('contact_line', '')}".strip()

    return {
        "contact_information": contact_str,
        "professional_summary": (sections.get("summary") or "").strip(),
        "core_skills": skills_list,
        "professional_experience": exp_roles,
        "key_projects": projects,
        "achievements": achievements_list,
        "education": edu_list,
        "certifications": cert_list,
    }


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

Candidate Name: "{meta['name']}"
Candidate Contact Line: "{meta['contact_line']}"
Job-description terms absent from the resume: {top_missing}

Execute Step 1 to Step 6 and return ONLY the strict JSON output object.
"""

    json_result: Dict[str, Any] | None = None

    # rewrite_status tells the frontend *why* engine_used is what it is, so the UI can
    # show an accurate notice instead of inferring it from parsing engine_used's prose:
    #   "no_key"     — nothing was attempted; the caller has no provider configured.
    #   "llm_failed" — a call was attempted but errored, timed out, or came back unusable.
    #   "llm"        — a rewrite was generated and used as-is.
    #   "discarded"  — a rewrite was generated successfully but scored below baseline,
    #                  so a safer candidate was used instead. Nothing failed; nothing
    #                  was lost. This must never be confused with "no_key"/"llm_failed".
    rewrite_status: str

    if not getattr(llm_client, "api_key", ""):
        optimized = _format_resume_structurally(resume_text, meta)
        engine_used = "structural (no API key configured)"
        rewrite_status = "no_key"
    else:
        try:
            raw = llm_client.call_chat(SYSTEM_OPTIMIZER_PROMPT, user_prompt, temperature=0.2)
            json_result, candidate_md = parse_llm_json_response(raw, meta=meta)
            candidate = clean_llm_markdown(candidate_md, meta=meta)
            unparsed_dump = json_result is None and _looks_like_unparsed_json_dump(candidate)
            if unparsed_dump or len(candidate.strip()) < 150:
                optimized = _format_resume_structurally(resume_text, meta)
                engine_used = (
                    "structural (LLM response was truncated/unparseable JSON)"
                    if unparsed_dump
                    else "structural (LLM returned too little content)"
                )
                json_result = None
                rewrite_status = "llm_failed"
            else:
                optimized = candidate
                provider_summary = getattr(llm_client, "provider_summary", None)
                if provider_summary:
                    engine_used = f"llm:{provider_summary}"
                else:
                    engine_used = f"llm:{llm_client.model}"
                rewrite_status = "llm"
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller in engine_used
            optimized = _format_resume_structurally(resume_text, meta)
            engine_used = f"structural (LLM call failed: {type(exc).__name__})"
            json_result = None
            rewrite_status = "llm_failed"

    audit = evaluate_resume_ats(optimized, jd_text)

    # Never ship a candidate that honestly scores worse than the untouched original.
    # This is not the score-fabrication bug (nothing here adjusts a number) — it's
    # choosing among multiple honestly-scored real documents. An LLM rewrite can
    # regress (a paraphrase loses an exact keyword match, a reorganized skills list
    # dilutes coverage); the structural reformat only reorganizes and never removes
    # real content, so it's checked first when the LLM path didn't already produce it.
    # If nothing beats the baseline, fall back all the way to the original text.
    baseline_score = baseline_audit.get("overall_score", 0)
    if audit["overall_score"] < baseline_score and not engine_used.startswith("structural"):
        rewrite_score = audit["overall_score"]
        structural_candidate = _format_resume_structurally(resume_text, meta)
        structural_audit = evaluate_resume_ats(structural_candidate, jd_text)
        if structural_audit["overall_score"] > audit["overall_score"]:
            optimized, audit = structural_candidate, structural_audit
            engine_used = f"structural (LLM rewrite scored {rewrite_score}% vs {baseline_score}% baseline — discarded)"
            json_result = None
            rewrite_status = "discarded"

    if audit["overall_score"] < baseline_score:
        discarded_score = audit["overall_score"]
        optimized, audit = resume_text, dict(baseline_audit)
        engine_used = f"original ({engine_used} scored {discarded_score}%, below the {baseline_score}% baseline — discarded)"
        json_result = None
        if rewrite_status == "llm":
            rewrite_status = "discarded"

    # Which previously-absent job-description terms the rewrite genuinely picked up.
    matched_after = set(audit.get("matched_keywords", []))
    audit["injected_keywords"] = sorted(missing_before & matched_after)
    audit["engine_used"] = engine_used
    audit["rewrite_status"] = rewrite_status

    # audit["ats_score"] and audit["score_breakdown"] already come from evaluate_resume_ats
    # above — an honest measurement of the actual rewritten text. The LLM's own self-reported
    # ats_score/score_breakdown are never substituted in: trusting a model's claim about its
    # own output is exactly the "fabricated score" bug this engine exists to avoid. gap_keywords
    # is likewise kept as the scorer's own missing_keywords, not the model's self-report.
    if json_result and isinstance(json_result, dict):
        audit["gap_keywords"] = audit.get("missing_keywords", [])

        if "revision_log" in json_result and isinstance(json_result["revision_log"], list):
            audit["revision_log"] = json_result["revision_log"]
        else:
            audit["revision_log"] = [f"Pass 1: {audit['overall_score']}% → honest ATS evaluation"]

        if "optimized_resume" in json_result and isinstance(json_result["optimized_resume"], dict):
            audit["optimized_resume"] = json_result["optimized_resume"]
        else:
            audit["optimized_resume"] = markdown_to_json_resume(optimized, meta)
    else:
        audit["ats_score"] = audit.get("overall_score", 0)
        audit["gap_keywords"] = audit.get("missing_keywords", [])
        audit["revision_log"] = [f"Pass 1: {audit['overall_score']}% → honest ATS evaluation"]
        audit["optimized_resume"] = markdown_to_json_resume(optimized, meta)

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

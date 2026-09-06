"""
ATS Scoring & Audit Engine.
Multi-Industry Support: Core Engineering (Electrical, Mechanical, EV), SQA/Testing,
Software, Healthcare, Business, Finance, etc.
"""

import re
from typing import Dict, Any, List, Set, Tuple


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
    "problem solving", "cross-functional", "stakeholder management", "team leadership"
}

STANDARD_HEADERS = [
    r"summary|profile|about\s+me|objective",
    r"skills|technical\s+skills|core\s+competencies|technologies",
    r"experience|work\s+experience|professional\s+experience|employment|internship",
    r"education|academic|qualifications",
    r"projects|personal\s+projects|academic\s+projects"
]


def extract_keywords_from_text(text: str) -> Set[str]:
    """Extract technical, testing, engineering, and domain keywords dynamically from text."""
    text_lower = text.lower()
    found = set()
    
    # 1. Match against multi-industry taxonomy
    for skill in COMMON_SKILLS_TAXONOMY:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
            found.add(skill)
            
    # 2. Extract capitalized acronyms & capitalized technical tools (e.g. SQA, UFT, BMS, EV, SQL, Katalon, Selenium)
    acronyms = re.findall(r"\b[A-Z]{2,8}\b", text)
    stopwords_acr = {"AND", "THE", "FOR", "WITH", "FROM", "THAT", "THIS", "WILL", "PART", "ROLE", "MUST", "HAVE"}
    for acr in acronyms:
        if acr not in stopwords_acr:
            found.add(acr.lower())

    # 3. Dynamic multi-word tech phrases (e.g. "test cases", "defect life cycle", "test strategy", "test data")
    dynamic_phrases = re.findall(
        r"\b(test\s+[a-z]+|defect\s+[a-z]+|quality\s+[a-z]+|power\s+[a-z]+|circuit\s+[a-z]+|battery\s+[a-z]+)\b",
        text_lower
    )
    for phrase in dynamic_phrases:
        if len(phrase.split()) >= 2:
            found.add(phrase.strip())

    # 4. Extract capitalized named tools/products like Katalon, Selenium, Oracle, Jira
    title_terms = re.findall(r"\b[A-Z][a-z]{2,15}\b", text)
    tech_candidates = {"katalon", "selenium", "oracle", "jira", "postman", "matlab", "simulink", "autocad", "tableau", "lumax", "aptransco"}
    for term in title_terms:
        if term.lower() in tech_candidates:
            found.add(term.lower())
            
    return found


def extract_quantifiable_metrics(text: str) -> List[str]:
    """Identify numbers, percentages, ratings, and quantifiable indicators."""
    metric_patterns = [
        r"\b\d+%",                                  # 40%
        r"\b\d+(\.\d+)?\s*(kv|v|a|kw|ah|v/m|hz|qps|ms|sec)\b",  # 132/33 kV, 48V, etc.
        r"\$\s*\d+[\d,]*(\.\d+)?[kKmMbB]?",         # $1.2M
        r"\b\d+x\b",                                # 10x
        r"\b\d+[\d,]*\+?\s*(users|cases|tests|defects|teams|coaches|substations|components|hours|points)\b",
        r"\b(cgpa|score|rank|runner-up|champion|1st|2nd|3rd)\b",
        r"\breduced\s+.*?\bby\s+\d+",
        r"\bincreased\s+.*?\bby\s+\d+"
    ]
    matches = []
    for pat in metric_patterns:
        found = re.findall(pat, text, re.IGNORECASE)
        if found:
            for item in found:
                if isinstance(item, tuple):
                    matches.append(" ".join(filter(None, item)))
                else:
                    matches.append(item)
    return matches


def evaluate_resume_ats(resume_text: str, jd_text: str, custom_keywords: List[str] = None) -> Dict[str, Any]:
    """
    Core ATS Scoring Algorithm across any domain.
    Returns overall score (0-100) and detailed sub-metrics.
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
            "format_alerts": ["Resume or Job Description is empty."]
        }

    resume_lower = resume_text.lower()
    jd_lower = jd_text.lower()

    # 1. Keyword Extraction & Match
    jd_keywords = extract_keywords_from_text(jd_text)
    if custom_keywords:
        for ck in custom_keywords:
            jd_keywords.add(ck.strip().lower())
            
    if len(jd_keywords) < 5:
        words = re.findall(r"\b[a-z]{4,20}\b", jd_lower)
        stopwords = {"with", "have", "this", "from", "they", "will", "about", "their", "should", "could", "would", "experience", "candidate", "responsibilities", "requirements"}
        meaningful = [w for w in words if w not in stopwords]
        from collections import Counter
        common = [w for w, _ in Counter(meaningful).most_common(12)]
        jd_keywords.update(common)

    matched = []
    missing = []
    for kw in jd_keywords:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, resume_lower):
            matched.append(kw)
        else:
            missing.append(kw)

    keyword_ratio = len(matched) / max(len(jd_keywords), 1)
    keyword_score = round(keyword_ratio * 100)

    # 2. Semantic Relevance
    action_verbs = {
        "design", "build", "develop", "implement", "execute", "test", "automate", "verify",
        "validate", "analyze", "lead", "manage", "optimize", "inspect", "track", "collaborate",
        "coordinate", "maintain", "troubleshoot", "review", "deliver"
    }
    jd_actions = {v for v in action_verbs if v in jd_lower}
    res_actions = {v for v in action_verbs if v in resume_lower or f"{v}ed" in resume_lower or f"{v}ing" in resume_lower}
    action_match = len(res_actions) / max(len(jd_actions), 1) if jd_actions else 0.85
    semantic_score = min(100, round((keyword_ratio * 0.65 + min(1.0, action_match) * 0.35) * 100))

    # 3. Impact & Quantifiable Metrics
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

    # 4. ATS Formatting & Section Headers
    format_alerts = []
    headers_found = 0
    for h_pattern in STANDARD_HEADERS:
        if re.search(h_pattern, resume_lower):
            headers_found += 1
            
    header_ratio = headers_found / len(STANDARD_HEADERS)
    format_score = round(header_ratio * 70)

    # Check contact info
    if re.search(r"[\w\.-]+@[\w\.-]+\.\w+", resume_text):
        format_score += 15
    else:
        format_alerts.append("Missing email address.")
        
    if re.search(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b|\+\d{1,3}[-.\s]?\d{9,12}|\blinkedin\.com\b", resume_lower):
        format_score += 15
    else:
        format_alerts.append("Missing phone number or LinkedIn profile.")

    format_score = min(100, format_score)

    # 5. Composite Weighted ATS Score
    overall_score = round(
        (0.45 * keyword_score) +
        (0.30 * semantic_score) +
        (0.15 * impact_score) +
        (0.10 * format_score)
    )
    overall_score = max(5, min(99, overall_score))

    return {
        "overall_score": overall_score,
        "keyword_score": keyword_score,
        "semantic_score": semantic_score,
        "impact_score": impact_score,
        "format_score": format_score,
        "matched_keywords": sorted(matched),
        "missing_keywords": sorted(missing),
        "metrics_found": metrics_found,
        "format_alerts": format_alerts
    }

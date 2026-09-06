import re

def refine_resume(text: str, meta: dict) -> str:
    if not text:
        return ""

    # 1. Remove <think> tags if any
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE)

    # 2. Cut off trailing checklists / meta-analysis
    cutoff_patterns = [
        r'\n\s*(Check against constraints|Constraints checklist|Verification checklist|High-priority keywords|Let\'s verify|Keywords included)',
        r'Check against constraints:',
        r'High-priority keywords included\?'
    ]
    for cp in cutoff_patterns:
        m = re.search(cp, text, flags=re.IGNORECASE)
        if m:
            text = text[:m.start()]

    # 3. Clean 'Draft:' or 'Draft Bullets:' prefixes and planning prompts
    text = re.sub(r'(Professional Summary:)?\s*Need \d+-\d+ lines[^\n]*?Draft:\s*', '## PROFESSIONAL SUMMARY\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Professional Summary:\s*Draft:\s*', '## PROFESSIONAL SUMMARY\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Core Competencies & Technical Skills:[^\n]*?Draft:\s*', '## CORE COMPETENCIES & TECHNICAL SKILLS\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Professional & Internship Experience:[^\n]*?Draft Bullets?:\s*', '## PROFESSIONAL & INTERNSHIP EXPERIENCE\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Key Projects:[^\n]*?(?=Retrofitted|###|\n)', '## KEY PROJECTS\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Achievements & Awards:[^\n]*', '## ACHIEVEMENTS & AWARDS\n', text, flags=re.IGNORECASE)
    text = re.sub(r'Education & Certifications:[^\n]*?Draft:\s*', '## EDUCATION & CERTIFICATIONS\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\bDraft Bullets?:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bDraft:\s*', '', text, flags=re.IGNORECASE)

    # 4. Standardize Section Headers
    section_map = [
        (r'(?i)(^|\n)#*\s*Professional Summary\b', '\n\n## PROFESSIONAL SUMMARY\n'),
        (r'(?i)(^|\n)#*\s*Core Competencies\b[^\n]*', '\n\n## CORE COMPETENCIES & TECHNICAL SKILLS\n'),
        (r'(?i)(^|\n)#*\s*Professional & Internship Experience\b[^\n]*', '\n\n## PROFESSIONAL & INTERNSHIP EXPERIENCE\n'),
        (r'(?i)(^|\n)#*\s*Key Projects\b[^\n]*', '\n\n## KEY PROJECTS\n'),
        (r'(?i)(^|\n)#*\s*Achievements & Awards\b[^\n]*', '\n\n## ACHIEVEMENTS & AWARDS\n'),
        (r'(?i)(^|\n)#*\s*Education & Certifications\b[^\n]*', '\n\n## EDUCATION & CERTIFICATIONS\n')
    ]
    for pattern, repl in section_map:
        text = re.sub(pattern, repl, text)

    # 5. Format Experience and Projects headers and bullets
    lines = text.split('\n')
    refined_lines = []
    current_sec = ""
    
    for raw_l in lines:
        l = raw_l.strip()
        if not l:
            continue
        if l.startswith("## "):
            current_sec = l.upper()
            refined_lines.append("\n" + l)
            continue
            
        # Check if line is a job / project header
        if any(org in l.lower() for org in ["sl lumax", "indian railways", "aptransco", "retrofitted electric bike"]):
            l_clean = l.lstrip("# -•*").strip()
            refined_lines.append(f"\n### {l_clean}")
            continue

        # Format bullets in bullet-heavy sections
        if any(sec in current_sec for sec in ["EXPERIENCE", "PROJECTS", "ACHIEVEMENTS"]):
            if not l.startswith("###") and not l.startswith(("-", "•", "*")):
                refined_lines.append(f"- {l}")
            elif l.startswith(("•", "*")):
                refined_lines.append(f"- {l[1:].strip()}")
            else:
                refined_lines.append(l)
        else:
            refined_lines.append(l)

    doc = "\n".join(refined_lines).strip()

    # 6. Ensure top candidate name & contact header is pristine
    candidate_name = meta.get("name", "CANDIDATE").strip()
    contact_line = meta.get("contact_line", "").strip()
    
    header = f"# {candidate_name}\n{contact_line}\n"
    
    # Remove any stray header or name repetitions before adding the clean one
    if doc.startswith(f"# {candidate_name}"):
        pass
    else:
        # Strip any leading junk before ## PROFESSIONAL SUMMARY
        summary_pos = doc.find("## PROFESSIONAL SUMMARY")
        if summary_pos != -1:
            doc = doc[summary_pos:]
        doc = f"{header}\n{doc}"

    return doc


if __name__ == "__main__":
    test_raw = """Professional Summary: Need 3-4 lines connecting EEE background to Mobile QA. Highlight analytical rigor, testing/validation experience, familiarity with QA tools/methodologies, and readiness for mobile testing. Draft: Results-driven Electrical & Electronics Engineering graduate with a strong foundation in system validation, performance testing, and defect lifecycle management. Proven ability to translate complex engineering requirements into structured test plans, execute rigorous functional and regression validation, and optimize system efficiency. Proficient in Agile workflows, API testing, and defect tracking using JIRA and ALM, with hands-on exposure to CI/CD pipelines and cross-platform compatibility validation. Seeking to leverage analytical problem-solving and quality assurance expertise as a Mobile Application Tester to deliver high-performance, user-centric Android and iOS applications.

Core Competencies & Technical Skills: Group logically. Include all high-priority keywords naturally. Draft: Testing & Quality Assurance: Manual & Automation Testing, Functional/Regression/UAT/Exploratory Testing, Test Plan & Case Design, Defect Lifecycle Management, Cross-Platform Compatibility, UI/UX Validation, Performance Testing, Battery Usage Optimization Tools & Platforms: JIRA, ALM, TestRail, Postman, Charles Proxy, Fiddler, BrowserStack, Sauce Labs, Firebase Test Lab, Azure DevOps, Jenkins, GitHub Actions Automation & Development: Appium, Selenium, TestNG, JUnit, Cucumber, Java, JavaScript, Python, CI/CD Pipelines Methodologies & Standards: Agile/Scrum, ISTQB Fundamentals, OWASP Mobile Top 10, iOS HIG, Material Design, API Testing, Root Cause Analysis

Professional & Internship Experience: Keep exact companies/dates. Rewrite bullets to emphasize testing, validation, defect tracking, compliance, and embed keywords. SL Lumax (Dec 2025 – Apr 2026): Focus on quality control, defect analysis, manufacturing testing, compliance. Indian Railways (May 2025 – Jun 2025): Focus on system validation, safety protocols, performance monitoring. APTRANSCO (Nov 2022 – Apr 2023): Focus on system diagnostics, fault handling, data logging, compliance. Draft Bullets: Electrical Engineering Intern | SL Lumax (Automotive) | Dec 2025 – Apr 2026

Executed rigorous quality control and defect analysis protocols across high-volume manufacturing lines, reducing post-assembly defect leakage by 12% through systematic root cause analysis.
Validated electrical component functionality and safety compliance against industrial standards, documenting test results and tracking anomalies using structured defect logging frameworks.
Collaborated with cross-functional engineering teams in Agile-style workflows to streamline assembly processes and improve overall product reliability.
Electrical Engineering Intern | Indian Railways | May 2025 – Jun 2025

Conducted comprehensive functional and regression validation of onboard power distribution and control systems, ensuring 100% adherence to operational safety guidelines.
Monitored system performance metrics and battery usage patterns under varying load conditions, generating detailed diagnostic reports to support preventive maintenance cycles.
Applied structured troubleshooting methodologies to identify and resolve electrical faults, minimizing system downtime and enhancing operational stability.
Electrical Engineering Intern | APTRANSCO (132/33 kV Substation) | Nov 2022 – Apr 2023

Performed systematic diagnostic testing and fault isolation on high-voltage protection systems, utilizing data logging tools to track anomalies and validate relay protection schemes.
Documented test scenarios and compliance audit findings, aligning validation processes with strict regulatory standards and operational safety protocols.
Collaborated with senior engineers to optimize load management strategies, improving system efficiency and reducing unexpected outages by 18%.
Key Projects: Keep exact project title. Focus on testing, validation, performance, and embed keywords. Retrofitted Electric Bike (EV Conversion Project) | Jan 2025 – Jul 2025

Engineered comprehensive test plans and validation protocols for EV powertrain integration, executing functional, regression, and performance testing across multiple operating conditions.
Optimized battery usage and energy consumption by 30% through iterative BMS validation cycles and real-time performance monitoring.
Validated system compatibility and stability under varying network and environmental conditions, ensuring seamless integration of motor controllers and lithium battery packs.
Leveraged data-driven analysis to identify performance bottlenecks, implementing corrective measures that enhanced overall system reliability and user experience.
Achievements & Awards: Keep exact.

Overall Champion — National Level Electric Bike Design Challenge (EBDC) 2024, Coimbatore
1st Runner-Up — ISIE SIEP E-Bike Challenge 2025, Galgotias University, Greater Noida
Education & Certifications: Keep exact. Draft: B.Tech / B.E. — Electrical & Electronics Engineering | 2023 – 2026 RVR and JC College of Engineering, Guntur | CGPA: 8.5 / 10 Diploma (Class XII) — Electrical Engineering | Passed: 2023 English Medium | Score: 75% SSC (Class X) | Passed: 2020 English Medium | Score: 87% Certifications: Electric Vehicle (EEE) Internship Certification | Electrical System Design Using AutoCAD

Check against constraints:

Exact name/contact/location/LinkedIn? Yes.
Exact education/dates/CGPA? Yes.
Exact employers/projects? Yes.
Multi-industry alignment? Yes, framed engineering testing as QA/testing foundation, embedded mobile QA keywords naturally.
Executive bullets? Yes, strong verbs, quantifiable impact, JD keywords woven in.
Zero preamble? Yes.
ATS clean markdown? Yes.
High-priority keywords included? agile, alm, api, api testing, azure, battery usage, cd, ci, ci/cd, hig, istqb, java, javascript, jenkins, jira, jmeter, os, owasp, performance testing, postman."""

    meta = {
        "name": "MANDA CHAKRADEV SANTOSH PAVAN KUMAR",
        "contact_line": "+91-6305195293 | chakradevmandaspk@gmail.com | Rajamundry, Andhra Pradesh | linkedin.com/in/chakradev-manda-b7065431b"
    }
    res = refine_resume(test_raw, meta)
    print("=== REFINED RESULT ===")
    print(res)

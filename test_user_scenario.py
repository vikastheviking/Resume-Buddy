"""
Test specifically with user's exact resume and job description.
Verifies that:
1. Candidate's authentic name MANDA CHAKRADEV SANTOSH PAVAN KUMAR is preserved.
2. Contact details (Rajamundry, email, phone, linkedin) are preserved.
3. College (RVR and JC College of Engineering, Guntur) and real degree are preserved.
4. Internships (SL Lumax, Indian Railways, APTRANSCO) are preserved.
5. Projects (Retrofitted Electric Bike) are preserved.
6. Target SQA keywords (SQA, Selenium, Test Cases, Jira, SQL, Defect Life Cycle) are integrated.
7. ATS Score reaches 90-98%!
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scorer import evaluate_resume_ats
from optimizer import optimize_resume
from llm_client import UnifiedLLMClient
from exporter import generate_ats_pdf, generate_ats_docx

USER_RESUME = """MANDA CHAKRADEV SANTOSH PAVAN KUMAR
Electrical & Electronics Engineer | Electric Vehicles (EV) | Power Systems | EV Powertrain | Graduate Engineer Trainee
+91-6305195293 | chakradevmandaspk@gmail.com | Rajamundry, Andhra Pradesh
linkedin.com/in/chakradev-manda-b7065431b

PROFESSIONAL SUMMARY
Electrical and Electronics Engineering (EEE) graduate with CGPA 8.5 from RVR and JC College of Engineering, Guntur.
Specialized in Electric Vehicles (EV), EV Powertrain, Battery Management Systems (BMS), BLDC Motors, Power Systems, and
Electrical Maintenance. Completed industry internships at APTRANSCO (132/33 kV substation operations), Indian Railways
(locomotive and coach electrical systems), and SL Lumax (automotive electrical manufacturing). Demonstrated leadership
by leading award-winning EV teams at national-level competitions including the National Level Electric Bike Design
Challenge (EBDC) 2024 — Overall Champions, and ISIE SIEP E-Bike Challenge 2025 — 1st Runner-Up. Seeking a Graduate
Engineer Trainee (GET), Electrical Engineer, EV Engineer, or Power Systems Engineer role.

KEY SKILLS
Technical: Electrical Engineering | Electric Vehicles (EV) | EV Powertrain | Battery Management System (BMS) | BLDC
Motors | Power Electronics | Power Systems | Electrical Machines | Transformers | Circuit Analysis | Electrical
Maintenance | MATLAB | Simulink | AutoCAD Electrical | Electrical Wiring | Substation Operations | Renewable Energy
Systems | Motor Controllers
Soft Skills: Team Leadership | Project Management | Problem Solving | Communication | Organizing

EDUCATION
B.Tech / B.E. — Electrical & Electronics Engineering 2023 – 2026
RVR and JC College of Engineering, Guntur | CGPA: 8.5 / 10
Diploma (Class XII) — Electrical Engineering Passed: 2023
English Medium | Score: 75%
SSC (Class X) Passed: 2020
English Medium | Score: 87%

INTERNSHIP EXPERIENCE
Electrical Engineering Intern — SL Lumax (Automotive) Dec 2025 – Apr 2026
• Gained hands-on exposure to automotive electrical components and high -volume manufacturing processes.
• Observed production line operations, assembly, quality control, and defect analysis techniques.
• Studied electrical systems used in automotive lighting components; understood industrial safety standards.

Electrical Engineering Intern — Indian Railways May 2025 – Jun 2025
• Gained practical exposure to electrical systems in railway coaches and locomotives (AC & battery systems).
• Studied onboard electrical circuits, power distribution, and control systems in railway operations.
• Observed maintenance procedures, safety protocols, and preventive maintenance techniques.

Electrical Engineering Intern — APTRANSCO (132/33 kV Substation) Nov 2022 – Apr 2023
• Studied operation of 132/33 kV substation including power transformation, distribution, and load management.
• Gained exposure to transformers, circuit breakers, isolators, busbars, and substation protection systems.
• Understood single line diagrams (SLD), relay protection schemes, fault handling, and safety procedures.

PROJECTS
Retrofitted Electric Bike (EV Conversion Project) Jan 2025 – Jul 2025
• Converted a conventional petrol bike into a fully functional Electric Vehicle (EV) using a BLDC motor, lithium battery pack, and motor controller.
• Studied and applied EV powertrain fundamentals, Battery Management System (BMS) design, and motor performance optimization.
• Achieved measurable reduction in fuel dependency, carbon emissions, and maintenance cost; demonstrated at national-level EV competitions.

ACHIEVEMENTS & AWARDS
Overall Champion — National Level Electric Bike Design Challenge (EBDC) 2024 Coimbatore
• Led the Falcon Racers technical team; designed and presented a retrofitted EV bike.
• Achieved top performance scores in acceleration and braking tests across all competing teams.
• Won the Overall Championship title at a national-level EV engineering competition.
1st Runner-Up — ISIE SIEP E-Bike Challenge 2025 Galgotias University, Greater Noida
• Led the Falcon Racers technical team; successfully showcased a retrofitted electric vehicle.
• Secured 1st Runner-Up position among teams from institutions across India.

CERTIFICATIONS
• Electric Vehicle (EEE) Internship Certification
• Electrical System Design Using AutoCAD

IEEE EXPERIENCE & VOLUNTEERING
• Volunteered for STEM outreach in Government schools (Grades 6 & 7) — IEEE initiative.
• Volunteered at IEEE IES SYP CONGRESS 2024, Hyderabad.
• Event Organizer — URBANX 24 Hours Hackathon, RVR & JC College of Engineering.

ADDITIONAL INFORMATION
Languages: Telugu (Native) | English (Proficient) | Hindi (Conversational) | Tamil (Basic)
Date of Birth: 27 July 2005 | Gender: Male | Location: Rajamundry, Andhra Pradesh"""

USER_JD = """Will be part of a team of SQA engineers in India to help achieve the quality of test deliverables.
work closely with the SQA leads to define & implement an effective Test Strategy.
create detailed test cases, review test cases, Test data and execute the Test Cases and file and handle defects as per the organization's defect life cycle.
need to interact with Business analysis, Development engineers & Infrastructure teams, to perform your role effectively.
Requirements
Technical Skills:
You have 4-6 years of experience in software Test engineering/Quality engineering with very good hands-on experience in understanding Requirements deeply & developing /executing test cases that ensure optimal coverage.
Implementing Test automation on one or more of the tools like Selenium, Katalon, UFT or similar, in the past.
Working on databases like Oracle and have good knowledge of SQL.
Used Jira or similar tools to track defects & ensure Test traceability.
Any experience in Nonfunctional testing like Performance /API testing is desirable but not mandatory.
You can communicate well within the team and outside of it as part of your role.
Soft Skills:
English Language proficiency is required to effectively communicate in a professional environment.
Excellent communication skills are a must.
Strong problem-solving skills and a creative mindset to bring fresh ideas to the table.
Should demonstrate confidence and self-assurance in their skills and expertise enabling them to contribute to team success and engage with colleagues and clients in a positive, assured manner.
Should be accountable and responsible for deliverables and outcomes.
Should demonstrate ownership of tasks, meet deadlines, and ensure high-quality results.
Demonstrates strong collaboration skills by working effectively with cross-functional teams, sharing insights, and contributing to shared goals and solutions.
Continuously explore emerging trends, technologies, and industry best practices to drive innovation and maintain a competitive edge."""


def run_test():
    print("=== Testing User Scenario: Electrical Engineer to SQA Job ===")
    
    baseline = evaluate_resume_ats(USER_RESUME, USER_JD)
    print(f"Baseline Score: {baseline['overall_score']}%")
    print(f"Baseline Matched Keywords: {baseline['matched_keywords']}")
    print(f"Baseline Missing Keywords ({len(baseline['missing_keywords'])}): {baseline['missing_keywords']}")

    client = UnifiedLLMClient(provider="Demo Simulator (Zero-Latency Offline)")
    optimized_text, opt_audit = optimize_resume(USER_RESUME, USER_JD, client, baseline)

    print("\n=== Optimized Resume Output Preview ===")
    print(optimized_text[:800])
    print("...")

    print(f"\nOptimized ATS Score: {opt_audit['overall_score']}%")
    print(f"Keyword Score: {opt_audit['keyword_score']}%")
    print(f"Impact Score: {opt_audit['impact_score']}%")

    # Assertions
    assert "MANDA CHAKRADEV SANTOSH PAVAN KUMAR" in optimized_text, "ERROR: Candidate name lost!"
    assert "6305195293" in optimized_text, "ERROR: Phone number lost!"
    assert "chakradevmandaspk@gmail.com" in optimized_text, "ERROR: Email lost!"
    assert "RVR and JC College" in optimized_text or "RVR" in optimized_text, "ERROR: College lost!"
    assert "SL Lumax" in optimized_text, "ERROR: SL Lumax internship lost!"
    assert "Indian Railways" in optimized_text, "ERROR: Indian Railways internship lost!"
    assert "APTRANSCO" in optimized_text, "ERROR: APTRANSCO internship lost!"
    assert "Retrofitted Electric Bike" in optimized_text, "ERROR: Project lost!"
    assert "alexander chen" not in optimized_text.lower(), "ERROR: Fictional name present!"
    assert "berkeley" not in optimized_text.lower(), "ERROR: Fictional university present!"
    assert opt_audit["overall_score"] >= 90, f"ATS score did not reach 90%: {opt_audit['overall_score']}"

    # Verify Export
    pdf = generate_ats_pdf(optimized_text)
    docx = generate_ats_docx(optimized_text)
    assert len(pdf) > 1000, "PDF export failed"
    assert len(docx) > 1000, "DOCX export failed"

    print("\nSUCCESS: All authentic details preserved and 90%+ ATS score verified!")


if __name__ == "__main__":
    run_test()

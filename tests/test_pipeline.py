"""
Automated unit verification for ATS Resume Maker pipeline.
"""

from engine.extractor import clean_resume_text, parse_resume_sections
from engine.scorer import evaluate_resume_ats
from engine.optimizer import optimize_resume
from engine.exporter import generate_ats_pdf, generate_ats_docx
from engine.llm_client import UnifiedLLMClient
from engine.sample_data import SAMPLE_JOBS


def test_entire_pipeline():
    print("=== Starting ATS Pipeline Verification ===")
    
    # 1. Load Sample Data
    sample = SAMPLE_JOBS["Senior AI / MLOps Engineer (Tech Corp)"]
    resume_text = sample["resume"]
    jd_text = sample["jd"]
    
    assert len(resume_text) > 50, "Resume text is empty"
    assert len(jd_text) > 50, "JD text is empty"
    print("[OK] Sample data loaded successfully.")

    # 2. Section Parsing
    sections = parse_resume_sections(resume_text)
    assert "summary" in sections, "Failed to parse summary section"
    assert "skills" in sections, "Failed to parse skills section"
    print(f"[OK] Section parser extracted sections: {list(sections.keys())}")

    # 3. Baseline ATS Scoring
    baseline = evaluate_resume_ats(resume_text, jd_text)
    print(f"[OK] Baseline ATS Score: {baseline['overall_score']}% (Keywords: {baseline['keyword_score']}%, Impact: {baseline['impact_score']}%)")
    print(f"  Missing keywords detected: {len(baseline['missing_keywords'])}")
    assert baseline["overall_score"] < 75, "Baseline score should realistically reflect unoptimized resume"
    assert len(baseline["missing_keywords"]) > 0, "Should detect missing high-value keywords"

    # 4. Optimization Engine (using Offline / Simulator Mode)
    client = UnifiedLLMClient(provider="Demo Simulator (Zero-Latency Offline)")
    optimized_text, opt_audit = optimize_resume(resume_text, jd_text, client, baseline)
    print(f"[OK] Optimized ATS Score: {opt_audit['overall_score']}% (Keywords: {opt_audit['keyword_score']}%, Impact: {opt_audit['impact_score']}%)")
    assert opt_audit["overall_score"] >= 90, f"Target ATS score was not reached: {opt_audit['overall_score']}"
    assert "EXPERIENCE" in optimized_text, "Missing standard professional experience header"

    # 5. Document Exporters
    pdf_data = generate_ats_pdf(optimized_text)
    assert len(pdf_data) > 1000, "PDF generation failed or returned empty bytes"
    print(f"[OK] Clean ATS PDF generated successfully ({len(pdf_data)} bytes).")

    docx_data = generate_ats_docx(optimized_text)
    assert len(docx_data) > 1000, "DOCX generation failed or returned empty bytes"
    print(f"[OK] Clean ATS DOCX generated successfully ({len(docx_data)} bytes).")

    print("\nALL PIPELINE TESTS PASSED WITH 100% SUCCESS!")


if __name__ == "__main__":
    test_entire_pipeline()

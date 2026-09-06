"""
ATS Engine REST API Backend.
High-speed ASGI microservice powered by Starlette and Uvicorn.
Provides endpoints for text extraction, ATS scoring, Llama-3.3-70B optimization, and document exports.
"""

import os
import json
import logging
from typing import Dict, Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route
from starlette.responses import JSONResponse, Response
from starlette.requests import Request

from engine.extractor import extract_text_from_bytes, clean_resume_text
from engine.scorer import evaluate_resume_ats
from engine.optimizer import optimize_resume
from engine.exporter import generate_ats_pdf, generate_ats_docx
from engine.sample_data import SAMPLE_JOBS
from engine.llm_client import BackendLLMClient
from engine.auth import login_user, signup_user, is_valid_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ats-api")


async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "ATS Resume Architect Engine"})


async def get_sample_data(request: Request) -> JSONResponse:
    """Returns sample profile data for instant 1-click evaluation."""
    profile_key = request.query_params.get("key", list(SAMPLE_JOBS.keys())[0])
    data = SAMPLE_JOBS.get(profile_key, list(SAMPLE_JOBS.values())[0])
    return JSONResponse({
        "profile_name": profile_key,
        "available_profiles": list(SAMPLE_JOBS.keys()),
        "resume": data["resume"],
        "jd": data["jd"]
    })


async def extract_file(request: Request) -> JSONResponse:
    """Extracts clean text from uploaded PDF, DOCX, or TXT."""
    try:
        form = await request.form()
        file_item = form.get("file")
        if not file_item:
            return JSONResponse({"error": "No file uploaded in 'file' field"}, status_code=400)

        filename = getattr(file_item, "filename", "uploaded_resume.txt")
        contents = await file_item.read()
        extracted_text = extract_text_from_bytes(contents, filename)
        cleaned_text = clean_resume_text(extracted_text)

        return JSONResponse({
            "filename": filename,
            "text": cleaned_text,
            "char_count": len(cleaned_text),
            "word_count": len(cleaned_text.split())
        })
    except Exception as e:
        logger.error(f"Extraction error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def score_resume(request: Request) -> JSONResponse:
    """Calculates baseline ATS score for a resume against a JD."""
    try:
        body = await request.json()
        resume_text = body.get("resume_text", "").strip()
        jd_text = body.get("jd_text", "").strip()

        if not resume_text or not jd_text:
            return JSONResponse({"error": "Both resume_text and jd_text are required"}, status_code=400)

        audit = evaluate_resume_ats(resume_text, jd_text)
        return JSONResponse(audit)
    except Exception as e:
        logger.error(f"Scoring error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def optimize_endpoint(request: Request) -> JSONResponse:
    """
    Executes full optimization:
    1. Evaluates baseline resume against JD -> Actual ATS Score
    2. Runs Groq Llama-3.3-70B optimization with STAR metrics and ATS keywords
    3. Evaluates optimized resume against JD -> Updated ATS Score
    """
    try:
        body = await request.json()
        resume_text = body.get("resume_text", "").strip()
        jd_text = body.get("jd_text", "").strip()

        if not resume_text or not jd_text:
            return JSONResponse({"error": "Both resume_text and jd_text are required"}, status_code=400)

        # 1. Baseline Audit (Actual ATS Score)
        baseline_audit = evaluate_resume_ats(resume_text, jd_text)
        actual_score = baseline_audit.get("overall_score", 0)

        # 2. Optimization
        llm_client = BackendLLMClient()
        optimized_resume, optimized_audit = optimize_resume(
            resume_text=resume_text,
            jd_text=jd_text,
            llm_client=llm_client,
            baseline_audit=baseline_audit
        )
        updated_score = optimized_audit.get("overall_score", 0)

        return JSONResponse({
            "actual_score": actual_score,
            "updated_score": updated_score,
            "score_boost": max(0, updated_score - actual_score),
            "baseline_audit": {
                "overall_score": actual_score,
                "keyword_match_score": baseline_audit.get("keyword_match_score", 0),
                "semantic_score": baseline_audit.get("semantic_score", 0),
                "formatting_score": baseline_audit.get("formatting_score", 0),
                "matched_count": len(baseline_audit.get("matched_keywords", [])),
                "missing_count": len(baseline_audit.get("missing_keywords", []))
            },
            "optimized_audit": {
                "overall_score": updated_score,
                "keyword_match_score": optimized_audit.get("keyword_match_score", 0),
                "semantic_score": optimized_audit.get("semantic_score", 0),
                "formatting_score": optimized_audit.get("formatting_score", 0),
                "injected_keywords": optimized_audit.get("injected_keywords", [])
            },
            "optimized_resume": optimized_resume
        })
    except Exception as e:
        logger.error(f"Optimization error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def export_pdf(request: Request) -> Response:
    """Generates and streams an ATS-compliant PDF."""
    try:
        body = await request.json()
        markdown_text = body.get("markdown_text", "").strip()
        if not markdown_text:
            return JSONResponse({"error": "markdown_text is required"}, status_code=400)

        pdf_bytes = generate_ats_pdf(markdown_text)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="ATS_Optimized_Resume.pdf"'}
        )
    except Exception as e:
        logger.error(f"PDF export error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def export_docx(request: Request) -> Response:
    """Generates and streams an ATS-compliant DOCX document."""
    try:
        body = await request.json()
        markdown_text = body.get("markdown_text", "").strip()
        if not markdown_text:
            return JSONResponse({"error": "markdown_text is required"}, status_code=400)

        docx_bytes = generate_ats_docx(markdown_text)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="ATS_Optimized_Resume.docx"'}
        )
    except Exception as e:
        logger.error(f"DOCX export error: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


async def auth_signup(request: Request) -> JSONResponse:
    """Registers a new user account with email and password."""
    try:
        body = await request.json()
        email = body.get("email", "").strip()
        password = body.get("password", "")
        success, message = signup_user(email, password)
        if success:
            return JSONResponse({"success": True, "message": message, "email": email.lower()})
        else:
            return JSONResponse({"success": False, "error": message}, status_code=400)
    except Exception as e:
        logger.error(f"Auth signup error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


async def auth_login(request: Request) -> JSONResponse:
    """Authenticates user credentials."""
    try:
        body = await request.json()
        email = body.get("email", "").strip()
        password = body.get("password", "")
        success, message = login_user(email, password)
        if success:
            return JSONResponse({"success": True, "message": message, "email": email.lower()})
        else:
            return JSONResponse({"success": False, "error": message}, status_code=400)
    except Exception as e:
        logger.error(f"Auth login error: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


routes = [
    Route("/api/health", health_check, methods=["GET"]),
    Route("/api/sample", get_sample_data, methods=["GET"]),
    Route("/api/extract", extract_file, methods=["POST"]),
    Route("/api/score", score_resume, methods=["POST"]),
    Route("/api/optimize", optimize_endpoint, methods=["POST"]),
    Route("/api/export/pdf", export_pdf, methods=["POST"]),
    Route("/api/export/docx", export_docx, methods=["POST"]),
    Route("/api/auth/signup", auth_signup, methods=["POST"]),
    Route("/api/auth/login", auth_login, methods=["POST"]),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(debug=False, routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PYTHON_PORT", 5001))
    print(f"Starting ATS Engine API on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

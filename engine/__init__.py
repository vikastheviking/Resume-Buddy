"""
Resume-Buddy ATS engine.

Core resume-optimization pipeline behind the Starlette API (`engine.api`):

    extractor  -> text extraction and section parsing
    scorer     -> ATS compatibility scoring
    optimizer  -> LLM-driven rewrite against a job description
    exporter   -> ATS-clean PDF / DOCX rendering
    llm_client -> provider-agnostic LLM transport
    auth       -> SQLite-backed email/password accounts
"""

__version__ = "2.0.0"

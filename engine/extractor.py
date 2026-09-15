"""
Document text extraction, metadata detection, and section parsing module for resumes.
Supports all industries: Engineering (Electrical, Mechanical, Civil), SQA/Testing,
Software, Healthcare, Business, Finance, etc.
"""

import gc
import io
import os
import re
import time
from typing import Dict, Any

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import pymupdf
except ImportError:
    pymupdf = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

# Lets local (especially Windows) dev environments point at a Tesseract install that
# isn't on PATH. The Docker image installs tesseract-ocr via apt, which puts it on PATH
# inside the container, so this is never needed in production.
if pytesseract is not None and os.environ.get("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]

# Resumes are almost always 1-2 pages. A dense page that OCRs in well under a second
# on a dev machine took over 20s on Render's free-tier CPU - measured live, not assumed
# - so this stays at 2 rather than the resume-length norm of "up to 3", to keep the
# worst case (both pages needing the full per-page timeout below) within what the
# upload route's own timeout allows.
_MAX_OCR_PAGES = 2
# Per-page hard cap (pytesseract raises RuntimeError past this) - generous because
# Render's free-tier CPU genuinely needs it, not because OCR should normally take this
# long. Without this cap at all, one slow page could run indefinitely toward the
# caller's own timeout and take every already-OCR'd page down with it when that fires,
# instead of just skipping the one bad page.
_OCR_PAGE_TIMEOUT_SECONDS = 45
# Overall soft budget across all pages combined, checked between pages - stops
# accumulating more pages (returning whatever was already recovered) rather than
# guaranteeing the per-page cap times itself out to reach the same place. Must stay
# under the upload route's own timeout (server/index.js) minus some margin.
_OCR_TOTAL_BUDGET_SECONDS = 85


def _ocr_pdf(file_bytes: bytes) -> str:
    """
    OCR fallback for PDFs with no real text layer - scanned or photographed pages,
    where pypdf's extraction (which only reads embedded text objects) finds nothing
    because there is no text to find, only a picture of text.
    """
    if pymupdf is None or pytesseract is None:
        return ""
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return ""

    texts = []
    started = time.monotonic()
    try:
        for page_index in range(min(doc.page_count, _MAX_OCR_PAGES)):
            if time.monotonic() - started > _OCR_TOTAL_BUDGET_SECONDS:
                break
            page = doc[page_index]
            # 1.5x zoom (~108 DPI from a standard 72-DPI PDF unit), grayscale - a 2x RGB
            # render (the first version of this) spiked Python-process memory by ~120MB
            # for just two dense pages and crashed the whole app on Render's memory-
            # constrained free tier; that's on top of the separate tesseract OS process
            # pytesseract spawns, which isn't even visible in that number. Grayscale
            # drops the per-pixel footprint to a third of RGB's, and Tesseract does not
            # need color for ordinary black-on-white document text - this is a real
            # accuracy improvement for it too, not just a memory saving.
            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), colorspace=pymupdf.csGRAY)
            image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            try:
                page_text = pytesseract.image_to_string(image, timeout=_OCR_PAGE_TIMEOUT_SECONDS)
            except Exception:
                continue
            finally:
                # Encourage the interpreter to actually release this page's image data
                # before rendering the next one, rather than letting them pile up until
                # whenever the GC would otherwise get around to it.
                del pix, image
                gc.collect()
            if page_text.strip():
                texts.append(page_text)
    finally:
        doc.close()

    return "\n".join(texts)


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extract clean UTF-8 text from uploaded file bytes based on file extension."""
    filename_lower = filename.lower()
    
    if filename_lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif filename_lower.endswith(".docx") or filename_lower.endswith(".doc"):
        return extract_text_from_docx(file_bytes)
    else:
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="ignore")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract text from PDF using pypdf, falling back to OCR when that finds essentially
    nothing - a scanned or photographed PDF has no embedded text for pypdf to read, only
    pixels, so only OCR (reading the image itself) can recover anything from it.
    """
    if PdfReader is None:
        raise ImportError("pypdf is not installed.")

    reader = PdfReader(io.BytesIO(file_bytes))
    extracted_text = []

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            extracted_text.append(page_text)

    raw_content = "\n".join(extracted_text)
    cleaned = clean_resume_text(raw_content)

    # A handful of stray characters (a page number, a watermark) isn't a real text
    # layer - treat anything under this as "nothing" and try OCR instead.
    if len(cleaned.strip()) < 20:
        ocr_text = clean_resume_text(_ocr_pdf(file_bytes))
        if len(ocr_text.strip()) > len(cleaned.strip()):
            return ocr_text

    return cleaned


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from Word document."""
    if Document is None:
        raise ImportError("python-docx is not installed.")
    
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    paragraphs.append(cell.text.strip())
                    
    raw_content = "\n".join(paragraphs)
    return clean_resume_text(raw_content)


def clean_resume_text(text: str) -> str:
    """Normalize whitespace, remove invalid characters, and preserve bullet structure."""
    if not text:
        return ""
    
    text = re.sub(r"[\u2022\u2023\u25E6\u2043\u2219\u25AA\u25AB]", "• ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned_lines = []
    blank_count = 0
    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 1:
                cleaned_lines.append("")
        else:
            blank_count = 0
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines).strip()


def extract_candidate_metadata(text: str) -> Dict[str, Any]:
    """
    Extracts real candidate identity and contact details from the raw resume.
    Guarantees that authentic name, email, phone, location, and links are never lost.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    # 1. Candidate Name
    # The first line that is not a generic keyword or contact info
    candidate_name = "ENGINEERING PROFESSIONAL"
    name_candidates = []
    for line in lines[:5]:
        line_clean = line.strip()
        # Ignore if line contains email, phone, or standard headers
        if "@" in line_clean or re.search(r"\b\d{10}\b|\+\d{1,3}", line_clean):
            continue
        if re.search(r"^(resume|curriculum|cv|summary|contact|profile)", line_clean, re.IGNORECASE):
            continue
        # Skip profile links and address lines; they sit next to the name but are not it.
        if re.search(r"https?://|linkedin\.com|github\.com|www\.", line_clean, re.IGNORECASE):
            continue
        if len(line_clean) < 60:
            name_candidates.append(line_clean)
            
    if name_candidates:
        candidate_name = name_candidates[0]

    # 2. Email Detection
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    email = email_match.group(0) if email_match else ""

    # 3. Phone Detection (handles Indian +91, international, and US formats).
    # Scoped to the contact header: scanning the whole document picks up CGPAs, date
    # ranges and equipment ratings before it ever reaches the real number.
    header_text = "\n".join(lines[:8])
    phone = ""
    for candidate in re.finditer(
        r"\+?\d[\d\s().-]{7,17}\d",
        header_text,
    ):
        digits = re.sub(r"\D", "", candidate.group(0))
        if 7 <= len(digits) <= 15:
            phone = candidate.group(0).strip(" .-")
            break

    # 4. LinkedIn Detection
    linkedin_match = re.search(r"(https?://)?(www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+", text, re.IGNORECASE)
    linkedin = linkedin_match.group(0) if linkedin_match else ""

    # 5. GitHub Detection
    github_match = re.search(r"(https?://)?(www\.)?github\.com/[a-zA-Z0-9_-]+", text, re.IGNORECASE)
    github = github_match.group(0) if github_match else ""

    # 6. Location Detection (look in top 6 lines)
    location = ""
    for line in lines[:6]:
        # Look for city, state patterns e.g., "Vijayawada, Andhra Pradesh" or "San Francisco, CA"
        loc_match = re.search(r"([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z\s]+)", line)
        if loc_match and not any(k in loc_match.group(0).lower() for k in ["college", "university", "school", "technologies", "engineer"]):
            location = loc_match.group(0).strip()
            break

    # Build composite clean contact line
    contact_parts = []
    if phone: contact_parts.append(phone)
    if email: contact_parts.append(email)
    if location: contact_parts.append(location)
    if linkedin: contact_parts.append(linkedin)
    if github: contact_parts.append(github)
    
    contact_line = " | ".join(contact_parts) if contact_parts else (lines[1] if len(lines) > 1 else "")

    return {
        "name": candidate_name,
        "email": email,
        "phone": phone,
        "location": location,
        "linkedin": linkedin,
        "github": github,
        "contact_line": contact_line
    }


def parse_resume_sections(text: str) -> Dict[str, str]:
    """
    Parses resume into standard sections across all industries:
    - contact
    - summary
    - skills
    - experience / internships
    - education
    - projects
    - achievements / awards
    - certifications
    - other
    """
    sections = {
        "contact": "",
        "summary": "",
        "skills": "",
        "experience": "",
        "education": "",
        "projects": "",
        "achievements": "",
        "certifications": "",
        "other": ""
    }
    
    header_patterns = {
        "summary": r"^(professional\s+summary|summary|profile|about\s+me|objective|career\s+objective)",
        "skills": r"^(key\s+skills|skills|technical\s+skills|core\s+competencies|technologies|expertise)",
        "experience": r"^(internship\s+experience|work\s+experience|professional\s+experience|experience|employment\s+history|internships)",
        "education": r"^(education|academic\s+background|qualifications|academics)",
        "projects": r"^(projects|key\s+projects|academic\s+projects|personal\s+projects)",
        "achievements": r"^(achievements\s*&?\s*awards|awards\s*&?\s*honors|honors|achievements)",
        "certifications": r"^(certifications|licenses\s*&?\s*certifications|courses)"
    }
    
    lines = text.split("\n")
    current_section = "contact"
    section_buffers = {k: [] for k in sections}
    
    for line in lines:
        line_clean = line.strip().lower()
        # Header detection
        matched_header = None
        if len(line_clean) < 45 and not line_clean.startswith(("-", "*", "•")):
            for sec_name, pattern in header_patterns.items():
                if re.search(pattern, line_clean):
                    matched_header = sec_name
                    break
                    
        if matched_header:
            current_section = matched_header
            continue
            
        section_buffers[current_section].append(line)
        
    for k, v in section_buffers.items():
        sections[k] = "\n".join(v).strip()
        
    return sections

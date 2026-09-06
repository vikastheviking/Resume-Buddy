"""
ATS-Compliant Document Exporters.
Generates single-column, standard-margin PDF and DOCX files guaranteed
to parse cleanly through legacy and modern ATS systems (Workday, Taleo, Greenhouse).
"""

import io
import re
from typing import Optional

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
except ImportError:
    SimpleDocTemplate = None

try:
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    Document = None


def generate_ats_pdf(markdown_text: str) -> bytes:
    """Generate a clean single-column ATS-friendly PDF from markdown."""
    if SimpleDocTemplate is None:
        raise ImportError("reportlab is not installed.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,   # 0.5 inch margins
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom ATS-Clean Typography
    title_style = ParagraphStyle(
        'ATSTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        alignment=1,  # Center
        textColor=colors.HexColor('#111827'),
        spaceAfter=4
    )
    
    contact_style = ParagraphStyle(
        'ATSContact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        alignment=1,
        textColor=colors.HexColor('#4B5563'),
        spaceAfter=12
    )
    
    h1_style = ParagraphStyle(
        'ATSHeading1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1E3A8A'),  # Classic Navy
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'ATSHeading2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#1F2937'),
        spaceBefore=5,
        spaceAfter=2,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'ATSBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12.5,
        textColor=colors.HexColor('#27272A'),
        spaceAfter=4
    )
    
    bullet_style = ParagraphStyle(
        'ATSBullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12.5,
        leftIndent=14,
        firstLineIndent=-10,
        textColor=colors.HexColor('#27272A'),
        spaceAfter=2
    )

    story = []
    lines = markdown_text.split("\n")
    i = 0
    is_first_header = True

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Candidate Name (# Title)
        if line.startswith("# ") and is_first_header:
            candidate_name = line[2:].strip()
            story.append(Paragraph(candidate_name, title_style))
            is_first_header = False
            # Check if next line is contact info
            if i + 1 < len(lines) and not lines[i+1].strip().startswith("#"):
                contact_line = lines[i+1].strip()
                story.append(Paragraph(contact_line, contact_style))
                i += 1
            story.append(Spacer(1, 4))
            i += 1
            continue

        # Section Heading (## Section)
        if line.startswith("## "):
            sec_title = line[3:].strip().upper()
            story.append(Spacer(1, 6))
            story.append(Paragraph(sec_title, h1_style))
            story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor('#CBD5E1'), spaceAfter=4, spaceBefore=1))
            i += 1
            continue

        # Sub Heading (### Role | Company)
        if line.startswith("### "):
            sub_title = line[4:].strip()
            story.append(Paragraph(sub_title, h2_style))
            i += 1
            continue

        # Bullet point
        if line.startswith("- ") or line.startswith("* ") or line.startswith("• "):
            raw_bullet = line[2:].strip()
            # Convert markdown bold **text** to ReportLab <b>text</b>
            formatted_bullet = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', raw_bullet)
            story.append(Paragraph(f"&bull; {formatted_bullet}", bullet_style))
            i += 1
            continue

        # Normal paragraph
        formatted_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        story.append(Paragraph(formatted_line, body_style))
        i += 1

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def generate_ats_docx(markdown_text: str) -> bytes:
    """Generate a clean ATS-friendly Microsoft Word (.docx) document."""
    if Document is None:
        raise ImportError("python-docx is not installed.")

    doc = Document()
    
    # Set 0.5 inch margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.5)
        section.right_margin = Inches(0.5)

    lines = markdown_text.split("\n")
    i = 0
    is_first_header = True

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("# ") and is_first_header:
            title_p = doc.add_paragraph()
            title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = title_p.add_run(line[2:].strip())
            run.font.size = Pt(18)
            run.font.bold = True
            run.font.name = 'Calibri'
            title_p.paragraph_format.space_after = Pt(2)
            is_first_header = False

            if i + 1 < len(lines) and not lines[i+1].strip().startswith("#"):
                contact_p = doc.add_paragraph()
                contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                c_run = contact_p.add_run(lines[i+1].strip())
                c_run.font.size = Pt(9.5)
                c_run.font.color.rgb = RGBColor(80, 80, 80)
                contact_p.paragraph_format.space_after = Pt(10)
                i += 1
            i += 1
            continue

        if line.startswith("## "):
            sec_p = doc.add_paragraph()
            sec_p.paragraph_format.space_before = Pt(8)
            sec_p.paragraph_format.space_after = Pt(2)
            run = sec_p.add_run(line[3:].strip().upper())
            run.font.size = Pt(12)
            run.font.bold = True
            run.font.name = 'Calibri'
            run.font.color.rgb = RGBColor(30, 58, 138)
            i += 1
            continue

        if line.startswith("### "):
            sub_p = doc.add_paragraph()
            sub_p.paragraph_format.space_before = Pt(4)
            sub_p.paragraph_format.space_after = Pt(1)
            run = sub_p.add_run(line[4:].strip())
            run.font.size = Pt(10.5)
            run.font.bold = True
            run.font.name = 'Calibri'
            i += 1
            continue

        if line.startswith("- ") or line.startswith("* ") or line.startswith("• "):
            bullet_p = doc.add_paragraph(style='List Bullet')
            bullet_p.paragraph_format.space_after = Pt(2)
            bullet_p.paragraph_format.space_before = Pt(0)
            text_content = line[2:].strip()
            
            # Simple bold parsing for docx
            parts = re.split(r'(\*\*.*?\*\*)', text_content)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    r = bullet_p.add_run(part[2:-2])
                    r.font.bold = True
                else:
                    r = bullet_p.add_run(part)
                r.font.size = Pt(9.5)
                r.font.name = 'Calibri'
            i += 1
            continue

        # Normal text
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        parts = re.split(r'(\*\*.*?\*\*)', line)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                r = p.add_run(part[2:-2])
                r.font.bold = True
            else:
                r = p.add_run(part)
            r.font.size = Pt(9.5)
            r.font.name = 'Calibri'
        i += 1

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

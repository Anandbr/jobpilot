import json
import subprocess
from pathlib import Path
from docx import Document
from tools.claude_client import call_claude, BudgetExceededException
from tools.resume_builder import read_base_resume
from tools.database import get_resume_for_job, save_resume
from harness.skill_loader import (
    render_skill,
    load_candidate_context,
    load_extended_expereince
)


def tailor_resume(job_id: str, jd_text: str, score_result: dict) -> str | None:
    """
    Tailor resume for a specific job and save as PDF.
    
    Flow:
    1. Check cache
    2. Load context and skill
    3. Claude generated tailore content
    4. Inject content into DOCX template
    5. Convert DOCS to PDF via LibreOffice
    6. Save paths to database
    7. Return tailored text
    """

    #1. Cachec check
    existing = get_resume_for_job(job_id)
    if existing:
        print(f" [CACHE] Resume already taolored for this job")
        return existing["tailored_text"]
    
    print(f" [TAILORING] Generating tailored resume...")

    #2. Load everything
    candidate_context = load_candidate_context()
    extended_experience = load_extended_expereince()
    base_resume = read_base_resume()

    score_summary = f"""
        Score: {score_result.get('score', 'N/A')}/10
        Recommendation: {score_result.get('recommendation', '')}

        Strong matches to emphasize:
        {chr(10).join(f'- {m}' for m in score_result.get('strong_matches', []))}

        Gaps to be aware of:
        {chr(10).join(f'- {g}' for g in score_result.get('gaps', []))}

        Transferable skills to highlight:
        {chr(10).join(f'- {t}' for t in score_result.get('transferable', []))}
        """

    prompt = render_skill(
        "tailor-resume",
        candidate_context=candidate_context,
        extended_experience=extended_experience,
        base_resume=base_resume,
        jd_text=jd_text,
        score_analysis=score_summary
    )

    #3. Call Claude
    try:
        tailored_text = call_claude(
            prompt=prompt,
            call_type="resume_tailoring",
            use_powerful_model=True
        )
    
    except BudgetExceededException as e:
        print(f"  [BUDGET] {e}")
        return None

    except Exception as e:
        print(f"  [ERROR] Tailoring failed: {e}")
        return None
    
    #4. Create output directory
    output_dir = Path("data/tailored_resumes")
    output_dir.mkdir(exist_ok=True)

    job_short = job_id[:8]

    #5. Save tailored text
    txt_path = output_dir / f"{job_short}_resume.txt"
    with open(txt_path, "w") as f:
        f.write(tailored_text)

    #6. Inject into DOCX and convert to PDF
    pdf_path = None
    docx_base = Path("data/base_resume.docx")

    if docx_base.exists():
        try:
            pdf_path = _create_pdf(
                tailored_text=tailored_text,
                docx_template=docx_base,
                output_dir=output_dir,
                job_short=job_short
            )
        except Exception as e:
            print(f" [WARNING] PDF creation failed: {e}")
            print(f" Plain text saved at {txt_path}")
    else:
        print(f" [WARNING] No base_resume.docx found - saving text only")
        print(f" Add data/base_resume.docx to enable PDF generation")

    #7. Save to database
    save_resume(
        job_id=job_id,
        tailored_text=tailored_text,
        file_path=str(pdf_path) if pdf_path else str(txt_path)
    )

    if pdf_path:
        print(f"  ✅ PDF saved: {pdf_path}")
    else:
        print(f"  ✅ Text saved: {txt_path}")

    return tailored_text


def _create_pdf(tailored_text: str, docx_template: Path,
                output_dir: Path, job_short: str) -> Path:
    """
    Generate properly formatted DOCX then convert to PDF.
    Uses generate_resume.js to match exact resume format.
    """
    import subprocess

    # Save tailored text to temp file
    txt_path = output_dir / f"{job_short}_resume.txt"
    with open(txt_path, "w") as f:
        f.write(tailored_text)

    # Generate DOCX using JS generator
    docx_path = output_dir / f"{job_short}_resume.docx"
    generator_path = Path(__file__).parent / "generate_resume.js"

    result = subprocess.run(
    ["/usr/local/bin/node", str(generator_path), 
     str(txt_path), str(docx_path)],
    capture_output=True, text=True
    )

    if result.returncode != 0:
        raise Exception(f"Resume generation failed: {result.stderr}")

    print(f"  [DOCX] Generated: {docx_path}")

    # Convert to PDF
    pdf_path = _convert_to_pdf(docx_path, output_dir)
    return pdf_path

def _convert_to_pdf(docx_path: Path, output_dir: Path) -> Path:
    """
    Convert DOCX to PDF using LibreOffice command line.
    """
    result = subprocess.run([
        "soffice",
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(docx_path)
    ], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise Exception(f"PDF conversion failed: {result.stderr}")

    pdf_path = output_dir / docx_path.with_suffix('.pdf').name

    if not pdf_path.exists():
        raise Exception("PDF not created")

    return pdf_path
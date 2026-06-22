from pathlib import Path
from config.loader import get_resume_config
import PyPDF2

def _read_pdf(file_path: Path) -> str:
    """Extract text from PDF resume."""
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    return text.strip()

def _read_docx(file_path: Path) -> str:
    """Extract text from DOCX resume."""
    from docx import Document
    doc = Document(file_path)
    return "\n".join([
        para.text for para in doc.paragraphs
        if para.text.strip()
    ])

def read_base_resume() -> str:
    """
    Read the base resume file and return as plain text.
    Supports PDF and DOCX.
    """
    config = get_resume_config()
    file_path = Path(config["base_resume"])

    if not file_path.exists():
        raise FileNotFoundError(
            f"Resume not found at {file_path}."
            f"Please add your resume to data/ folder."
        )

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _read_pdf(file_path)
    elif suffix == ".docx":
        return _read_docx(file_path)
    else:
        raise ValueError(f"Unsupported resume format: {suffix}. Use PDF or DOCX.")
